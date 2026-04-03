"""
Unit tests for Phase 10 Feature B — Block/Ban Detection.

Covers: BlockEvent model, BlockEventRepository, BlockDetector module,
        BlockDetectionService.
"""
import json
import shutil
import sqlite3
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from oh.db.migrations import run_migrations
from oh.models.block_event import (
    BlockEvent, BlockSignal, BlockScanResult,
    BLOCK_ACTION_BLOCK, BLOCK_CHALLENGE, BLOCK_SHADOW_BAN,
    BLOCK_RATE_LIMIT, BLOCK_TEMP_BAN,
    BLOCK_SEVERITY, BLOCK_LABELS,
)
from oh.models.session import AccountSessionRecord
from oh.repositories.block_event_repo import BlockEventRepository
from oh.modules.block_detector import BlockDetector


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed_account(conn, username="testuser", device_id="dev-001"):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO oh_devices (device_id, device_name, first_discovered_at, last_synced_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id, "Phone1", now, now),
    )
    cursor = conn.execute(
        "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id, username, now, now),
    )
    conn.commit()
    return cursor.lastrowid


# -----------------------------------------------------------------------
# Model tests
# -----------------------------------------------------------------------

class TestBlockEventModel(unittest.TestCase):
    def test_create_event(self):
        ev = BlockEvent(
            account_id=1,
            event_type=BLOCK_ACTION_BLOCK,
            detected_at="2026-04-03T12:00:00Z",
        )
        self.assertTrue(ev.is_active)
        self.assertEqual(ev.severity, "CRITICAL")
        self.assertEqual(ev.label, "Action Block")

    def test_resolved_event(self):
        ev = BlockEvent(
            account_id=1,
            event_type=BLOCK_RATE_LIMIT,
            detected_at="2026-04-03T12:00:00Z",
            resolved_at="2026-04-03T18:00:00Z",
        )
        self.assertFalse(ev.is_active)
        self.assertEqual(ev.severity, "MEDIUM")

    def test_all_severities(self):
        self.assertEqual(BLOCK_SEVERITY[BLOCK_ACTION_BLOCK], "CRITICAL")
        self.assertEqual(BLOCK_SEVERITY[BLOCK_CHALLENGE], "CRITICAL")
        self.assertEqual(BLOCK_SEVERITY[BLOCK_SHADOW_BAN], "HIGH")
        self.assertEqual(BLOCK_SEVERITY[BLOCK_TEMP_BAN], "HIGH")
        self.assertEqual(BLOCK_SEVERITY[BLOCK_RATE_LIMIT], "MEDIUM")

    def test_block_signal(self):
        sig = BlockSignal(
            event_type=BLOCK_ACTION_BLOCK,
            confidence=0.85,
            evidence={"reason": "test"},
        )
        self.assertEqual(sig.event_type, BLOCK_ACTION_BLOCK)
        self.assertEqual(sig.confidence, 0.85)

    def test_scan_result(self):
        result = BlockScanResult()
        self.assertEqual(result.total_scanned, 0)
        self.assertEqual(result.new_blocks, 0)
        self.assertEqual(result.resolved, 0)


# -----------------------------------------------------------------------
# Repository tests
# -----------------------------------------------------------------------

class TestBlockEventRepo(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.repo = BlockEventRepository(self.conn)
        self.account_id = _seed_account(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_save_and_get_active(self):
        ev = BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_ACTION_BLOCK,
            detected_at="2026-04-03T12:00:00Z",
            evidence='{"reason": "test"}',
        )
        saved = self.repo.save(ev)
        self.assertIsNotNone(saved.id)

        active = self.repo.get_active_for_account(self.account_id)
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].event_type, BLOCK_ACTION_BLOCK)

    def test_resolve(self):
        ev = BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_CHALLENGE,
            detected_at="2026-04-03T12:00:00Z",
        )
        saved = self.repo.save(ev)

        self.repo.resolve(saved.id)

        active = self.repo.get_active_for_account(self.account_id)
        self.assertEqual(len(active), 0)

    def test_get_active_map(self):
        acc2 = _seed_account(self.conn, "user2")

        self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_ACTION_BLOCK,
            detected_at="2026-04-03T12:00:00Z",
        ))
        self.repo.save(BlockEvent(
            account_id=acc2,
            event_type=BLOCK_RATE_LIMIT,
            detected_at="2026-04-03T12:00:00Z",
        ))

        active_map = self.repo.get_active_map()
        self.assertIn(self.account_id, active_map)
        self.assertIn(acc2, active_map)
        self.assertEqual(len(active_map[self.account_id]), 1)
        self.assertEqual(len(active_map[acc2]), 1)

    def test_get_active_all(self):
        self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_ACTION_BLOCK,
            detected_at="2026-04-03T12:00:00Z",
        ))
        self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_SHADOW_BAN,
            detected_at="2026-04-03T12:00:00Z",
        ))

        all_active = self.repo.get_active_all()
        self.assertEqual(len(all_active), 2)

    def test_resolved_not_in_active(self):
        ev = self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_CHALLENGE,
            detected_at="2026-04-03T12:00:00Z",
        ))
        self.repo.resolve(ev.id)

        self.assertEqual(len(self.repo.get_active_all()), 0)
        self.assertEqual(len(self.repo.get_recent(10)), 1)

    def test_multiple_events_same_account(self):
        self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_ACTION_BLOCK,
            detected_at="2026-04-03T12:00:00Z",
        ))
        self.repo.save(BlockEvent(
            account_id=self.account_id,
            event_type=BLOCK_RATE_LIMIT,
            detected_at="2026-04-03T12:00:00Z",
        ))

        active = self.repo.get_active_for_account(self.account_id)
        self.assertEqual(len(active), 2)


# -----------------------------------------------------------------------
# Module tests — BlockDetector
# -----------------------------------------------------------------------

class TestBlockDetector(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.detector = BlockDetector(self.tmp)
        self.today = date.today().isoformat()

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def _make_session(self, follow_count, days_ago=0):
        d = date.today() - timedelta(days=days_ago)
        return AccountSessionRecord(
            account_id=1,
            device_id="dev-001",
            username="test",
            snapshot_date=d.isoformat(),
            slot="06-12",
            follow_count=follow_count,
            has_activity=follow_count > 0,
        )

    def test_no_signals_healthy_account(self):
        history = [
            self._make_session(100, 0),
            self._make_session(95, 1),
            self._make_session(110, 2),
        ]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        self.assertEqual(len(signals), 0)

    def test_zero_follows_running_device(self):
        history = [
            self._make_session(0, 0),
            self._make_session(100, 1),
        ]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        block_types = [s.event_type for s in signals]
        self.assertIn(BLOCK_ACTION_BLOCK, block_types)

    def test_consecutive_zero_days(self):
        history = [
            self._make_session(0, 0),
            self._make_session(0, 1),
            self._make_session(0, 2),
            self._make_session(100, 3),
        ]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        self.assertTrue(len(signals) > 0)
        confidence = max(s.confidence for s in signals)
        self.assertGreater(confidence, 0.5)

    def test_sudden_activity_drop_shadow_ban(self):
        history = [
            self._make_session(10, 0),   # today: 10 follows
            self._make_session(100, 1),  # yesterday: 100
            self._make_session(90, 2),   # day before: 90
            self._make_session(110, 3),  # 3 days ago: 110
        ]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        shadow_signals = [s for s in signals if s.event_type == BLOCK_SHADOW_BAN]
        self.assertEqual(len(shadow_signals), 1)

    def test_no_shadow_ban_above_threshold(self):
        history = [
            self._make_session(80, 0),
            self._make_session(100, 1),
            self._make_session(90, 2),
            self._make_session(110, 3),
        ]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        shadow_signals = [s for s in signals if s.event_type == BLOCK_SHADOW_BAN]
        self.assertEqual(len(shadow_signals), 0)

    def test_follow_disabled_no_signals(self):
        history = [self._make_session(0, 0)]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=False,
        )
        self.assertEqual(len(signals), 0)

    def test_limit_drop_rate_limit(self):
        # Create .stm directory with effective limit file
        account_path = Path(self.tmp) / "dev-001" / "test"
        stm_dir = account_path / ".stm"
        stm_dir.mkdir(parents=True)

        limit_file = stm_dir / f"follow-action-limit-per-day-{self.today}.txt"
        limit_file.write_text("30")  # 30 vs configured 200 = 15%

        history = [self._make_session(30, 0)]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        rate_signals = [s for s in signals if s.event_type == BLOCK_RATE_LIMIT]
        self.assertEqual(len(rate_signals), 1)
        self.assertGreater(rate_signals[0].confidence, 0.5)

    def test_challenge_marker_detection(self):
        account_path = Path(self.tmp) / "dev-001" / "test"
        stm_dir = account_path / ".stm"
        stm_dir.mkdir(parents=True)

        marker = stm_dir / "challenge-required.txt"
        marker.write_text("1")

        history = [self._make_session(0, 0)]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        challenge_signals = [s for s in signals if s.event_type == BLOCK_CHALLENGE]
        self.assertEqual(len(challenge_signals), 1)
        self.assertGreaterEqual(challenge_signals[0].confidence, 0.9)

    def test_empty_history(self):
        signals = self.detector.detect_for_account(
            "dev-001", "test", [], 200,
            device_status="running", follow_enabled=True,
        )
        self.assertEqual(len(signals), 0)

    def test_no_stm_dir_graceful(self):
        history = [self._make_session(50, 0)]
        signals = self.detector.detect_for_account(
            "dev-001", "test", history, 200,
            device_status="running", follow_enabled=True,
        )
        # Should not crash even without .stm directory
        self.assertIsInstance(signals, list)


if __name__ == "__main__":
    unittest.main()
