"""
Comprehensive tests for the LBR (Like-Back Rate) feature.

Covers:
  1. Model tests — SourceLBRRecord, LBRAnalysisResult, LBRSnapshotRecord,
     BatchLBRResult, GlobalLikeSourceRecord
  2. LBRCalculator tests — real SQLite likes.db in temp directories
  3. Repository tests — LBRSnapshotRepository, LikeSourceAssignmentRepository
"""
import json
import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from oh.db.migrations import run_migrations
from oh.models.lbr import SourceLBRRecord, LBRAnalysisResult
from oh.models.lbr_snapshot import (
    LBRSnapshotRecord,
    BatchLBRResult,
    SNAPSHOT_OK,
    SNAPSHOT_EMPTY,
    SNAPSHOT_ERROR,
)
from oh.models.global_like_source import GlobalLikeSourceRecord
from oh.modules.lbr_calculator import LBRCalculator
from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
from oh.repositories.like_source_assignment_repo import LikeSourceAssignmentRepository


# ======================================================================
# Helpers
# ======================================================================

def _create_db() -> sqlite3.Connection:
    """Create an in-memory DB with all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed_device_and_account(
    conn: sqlite3.Connection,
    device_id: str = "dev-001",
    device_name: str = "Phone1",
    username: str = "testuser",
) -> int:
    """Insert a minimal device + account row and return the account id."""
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT OR IGNORE INTO oh_devices "
        "(device_id, device_name, first_discovered_at, last_synced_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id, device_name, now, now),
    )
    cursor = conn.execute(
        "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id, username, now, now),
    )
    conn.commit()
    return cursor.lastrowid


def _create_likes_db(db_path: Path, rows: list) -> None:
    """
    Create a likes.db at *db_path* with the expected schema and insert rows.

    Each row is a tuple: (username, liked, source, follow_back, date)
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
        CREATE TABLE IF NOT EXISTS likes (
            username    TEXT,
            liked       TEXT,
            source      TEXT,
            follow_back INTEGER DEFAULT 0,
            date        TEXT
        )
    """)
    if rows:
        conn.executemany(
            "INSERT INTO likes (username, liked, source, follow_back, date) "
            "VALUES (?, ?, ?, ?, ?)",
            rows,
        )
    conn.commit()
    conn.close()


# ======================================================================
# 1. Model Tests — SourceLBRRecord
# ======================================================================

class TestSourceLBRRecord(unittest.TestCase):

    def test_creation_quality_true(self):
        rec = SourceLBRRecord(
            source_name="fitness_guru",
            like_count=100,
            followback_count=15,
            lbr_percent=15.0,
            is_quality=True,
            anomaly=None,
        )
        self.assertEqual(rec.source_name, "fitness_guru")
        self.assertEqual(rec.like_count, 100)
        self.assertEqual(rec.followback_count, 15)
        self.assertAlmostEqual(rec.lbr_percent, 15.0)
        self.assertTrue(rec.is_quality)
        self.assertIsNone(rec.anomaly)

    def test_creation_quality_false(self):
        rec = SourceLBRRecord(
            source_name="low_performer",
            like_count=20,
            followback_count=0,
            lbr_percent=0.0,
            is_quality=False,
            anomaly=None,
        )
        self.assertFalse(rec.is_quality)

    def test_creation_with_anomaly(self):
        rec = SourceLBRRecord(
            source_name="broken_src",
            like_count=10,
            followback_count=20,
            lbr_percent=100.0,
            is_quality=False,
            anomaly="followback_exceeds_likes",
        )
        self.assertEqual(rec.anomaly, "followback_exceeds_likes")


# ======================================================================
# 1. Model Tests — LBRAnalysisResult
# ======================================================================

class TestLBRAnalysisResult(unittest.TestCase):

    def _make_result(self, records=None):
        return LBRAnalysisResult(
            device_id="dev1",
            username="user1",
            records=records or [],
            min_likes=50,
            min_lbr_pct=5.0,
        )

    def test_empty_result(self):
        result = self._make_result()
        self.assertFalse(result.has_data)
        self.assertEqual(result.quality_count, 0)
        self.assertEqual(result.total_count, 0)
        self.assertEqual(result.below_volume_count, 0)
        self.assertEqual(result.anomaly_count, 0)
        self.assertIsNone(result.best_source_by_lbr)
        self.assertIsNone(result.highest_volume_source)

    def test_has_data_with_records(self):
        records = [
            SourceLBRRecord("src1", 100, 20, 20.0, True, None),
            SourceLBRRecord("src2", 30, 5, 16.7, False, None),
        ]
        result = self._make_result(records)
        self.assertTrue(result.has_data)
        self.assertEqual(result.total_count, 2)

    def test_quality_count(self):
        records = [
            SourceLBRRecord("src1", 100, 20, 20.0, True, None),
            SourceLBRRecord("src2", 80, 10, 12.5, True, None),
            SourceLBRRecord("src3", 30, 5, 16.7, False, None),
        ]
        result = self._make_result(records)
        self.assertEqual(result.quality_count, 2)

    def test_below_volume_count(self):
        records = [
            SourceLBRRecord("src1", 100, 20, 20.0, True, None),
            SourceLBRRecord("src2", 30, 5, 16.7, False, None),   # below 50
            SourceLBRRecord("src3", 10, 1, 10.0, False, None),   # below 50
        ]
        result = self._make_result(records)
        self.assertEqual(result.below_volume_count, 2)

    def test_anomaly_count(self):
        records = [
            SourceLBRRecord("src1", 100, 20, 20.0, True, None),
            SourceLBRRecord("src2", 10, 20, 100.0, False, "followback_exceeds_likes"),
            SourceLBRRecord("src3", 50, 60, 100.0, False, "lbr_over_100"),
        ]
        result = self._make_result(records)
        self.assertEqual(result.anomaly_count, 2)

    def test_best_source_by_lbr(self):
        records = [
            SourceLBRRecord("low_vol", 30, 10, 33.3, False, None),   # below min_likes
            SourceLBRRecord("medium", 60, 6, 10.0, True, None),
            SourceLBRRecord("best", 80, 20, 25.0, True, None),
        ]
        result = self._make_result(records)
        best = result.best_source_by_lbr
        self.assertIsNotNone(best)
        self.assertEqual(best.source_name, "best")

    def test_best_source_by_lbr_none_when_all_below_volume(self):
        records = [
            SourceLBRRecord("small1", 10, 5, 50.0, False, None),
            SourceLBRRecord("small2", 20, 8, 40.0, False, None),
        ]
        result = self._make_result(records)
        self.assertIsNone(result.best_source_by_lbr)

    def test_highest_volume_source(self):
        records = [
            SourceLBRRecord("src1", 200, 20, 10.0, True, None),
            SourceLBRRecord("src2", 500, 10, 2.0, False, None),
            SourceLBRRecord("src3", 100, 30, 30.0, True, None),
        ]
        result = self._make_result(records)
        highest = result.highest_volume_source
        self.assertIsNotNone(highest)
        self.assertEqual(highest.source_name, "src2")


# ======================================================================
# 1. Model Tests — LBRSnapshotRecord
# ======================================================================

class TestLBRSnapshotRecord(unittest.TestCase):

    def test_status_constants(self):
        self.assertEqual(SNAPSHOT_OK, "ok")
        self.assertEqual(SNAPSHOT_EMPTY, "empty")
        self.assertEqual(SNAPSHOT_ERROR, "error")

    def test_warnings_property_parses_json(self):
        snap = LBRSnapshotRecord(
            account_id=1, device_id="d1", username="u1",
            analyzed_at="2026-01-01T00:00:00Z",
            min_likes=50, min_lbr_pct=5.0,
            total_sources=3, quality_sources=2, status=SNAPSHOT_OK,
            warnings_json=json.dumps(["warning1", "warning2"]),
        )
        self.assertEqual(snap.warnings, ["warning1", "warning2"])

    def test_warnings_property_empty_when_none(self):
        snap = LBRSnapshotRecord(
            account_id=1, device_id="d1", username="u1",
            analyzed_at="2026-01-01T00:00:00Z",
            min_likes=50, min_lbr_pct=5.0,
            total_sources=1, quality_sources=0, status=SNAPSHOT_OK,
            warnings_json=None,
        )
        self.assertEqual(snap.warnings, [])

    def test_has_quality_data_ok_with_sources(self):
        snap = LBRSnapshotRecord(
            account_id=1, device_id="d1", username="u1",
            analyzed_at="2026-01-01T00:00:00Z",
            min_likes=50, min_lbr_pct=5.0,
            total_sources=5, quality_sources=3, status=SNAPSHOT_OK,
        )
        self.assertTrue(snap.has_quality_data)

    def test_has_quality_data_false_on_error(self):
        snap = LBRSnapshotRecord(
            account_id=1, device_id="d1", username="u1",
            analyzed_at="2026-01-01T00:00:00Z",
            min_likes=50, min_lbr_pct=5.0,
            total_sources=5, quality_sources=3, status=SNAPSHOT_ERROR,
        )
        self.assertFalse(snap.has_quality_data)

    def test_has_quality_data_false_on_zero_sources(self):
        snap = LBRSnapshotRecord(
            account_id=1, device_id="d1", username="u1",
            analyzed_at="2026-01-01T00:00:00Z",
            min_likes=50, min_lbr_pct=5.0,
            total_sources=0, quality_sources=0, status=SNAPSHOT_OK,
        )
        self.assertFalse(snap.has_quality_data)


# ======================================================================
# 1. Model Tests — BatchLBRResult
# ======================================================================

class TestBatchLBRResult(unittest.TestCase):

    def test_status_line_analyzed_only(self):
        batch = BatchLBRResult(total_accounts=10, analyzed=10)
        line = batch.status_line()
        self.assertIn("10 analyzed", line)
        self.assertIn("of 10 active accounts", line)
        self.assertNotIn("skipped", line)
        self.assertNotIn("failed", line)

    def test_status_line_with_skipped_and_errors(self):
        batch = BatchLBRResult(
            total_accounts=20, analyzed=15, skipped=3, errors=2,
        )
        line = batch.status_line()
        self.assertIn("15 analyzed", line)
        self.assertIn("3 skipped", line)
        self.assertIn("2 failed", line)
        self.assertIn("of 20 active accounts", line)


# ======================================================================
# 1. Model Tests — GlobalLikeSourceRecord
# ======================================================================

class TestGlobalLikeSourceRecord(unittest.TestCase):

    def test_total_accounts(self):
        rec = GlobalLikeSourceRecord(
            source_name="src1",
            active_accounts=5,
            historical_accounts=3,
        )
        self.assertEqual(rec.total_accounts, 8)

    def test_low_quality_account_count(self):
        rec = GlobalLikeSourceRecord(
            source_name="src1",
            active_accounts=5,
            historical_accounts=3,
            quality_account_count=2,
        )
        # total_accounts = 8, quality = 2 => low_quality = 6
        self.assertEqual(rec.low_quality_account_count, 6)

    def test_low_quality_all_quality(self):
        rec = GlobalLikeSourceRecord(
            source_name="src1",
            active_accounts=4,
            historical_accounts=0,
            quality_account_count=4,
        )
        self.assertEqual(rec.low_quality_account_count, 0)


# ======================================================================
# 2. LBRCalculator Tests
# ======================================================================

class TestLBRCalculator(unittest.TestCase):

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.calculator = LBRCalculator(
            bot_root=self.tmp_dir,
            min_likes=50,
            min_lbr_pct=5.0,
        )
        self.device_id = "device_abc"
        self.username = "testaccount"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def _likes_db_path(self) -> Path:
        return Path(self.tmp_dir) / self.device_id / self.username / "likes.db"

    def _source_file_path(self) -> Path:
        return (
            Path(self.tmp_dir) / self.device_id / self.username
            / "like-source-followers.txt"
        )

    def _insert_likes(self, rows):
        """Convenience: create likes.db and insert rows."""
        _create_likes_db(self._likes_db_path(), rows)

    # ------------------------------------------------------------------
    # calculate() tests
    # ------------------------------------------------------------------

    def test_calculate_missing_likes_db(self):
        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("not found", result.schema_error)
        self.assertFalse(result.has_data)

    def test_calculate_empty_likes_table(self):
        self._insert_likes([])
        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.schema_valid)
        self.assertFalse(result.has_data)
        self.assertEqual(result.total_count, 0)

    def test_calculate_correct_lbr(self):
        # 100 likes from source_a, 20 follow backs => LBR = 20%
        rows = []
        for i in range(100):
            fb = 1 if i < 20 else 0
            rows.append(("testaccount", f"user_{i}", "source_a", fb, "2026-01-01"))
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertTrue(result.schema_valid)
        self.assertTrue(result.has_data)
        self.assertEqual(result.total_count, 1)

        rec = result.records[0]
        self.assertEqual(rec.source_name, "source_a")
        self.assertEqual(rec.like_count, 100)
        self.assertEqual(rec.followback_count, 20)
        self.assertAlmostEqual(rec.lbr_percent, 20.0)

    def test_calculate_multiple_sources(self):
        rows = [
            ("acc", f"u{i}", "src_a", 1 if i < 10 else 0, "2026-01-01")
            for i in range(60)
        ] + [
            ("acc", f"v{i}", "src_b", 1 if i < 5 else 0, "2026-01-01")
            for i in range(80)
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertEqual(result.total_count, 2)
        names = {r.source_name for r in result.records}
        self.assertEqual(names, {"src_a", "src_b"})

    def test_calculate_quality_threshold_met(self):
        # 100 likes, 10 followbacks => LBR 10% >= 5% and likes >= 50
        rows = [
            ("acc", f"u{i}", "quality_src", 1 if i < 10 else 0, "2026-01-01")
            for i in range(100)
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertTrue(rec.is_quality)

    def test_calculate_below_min_likes_not_quality(self):
        # Only 10 likes — below 50 threshold
        rows = [
            ("acc", f"u{i}", "small_src", 1, "2026-01-01")
            for i in range(10)
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertFalse(rec.is_quality)
        self.assertEqual(rec.like_count, 10)

    def test_calculate_below_min_lbr_not_quality(self):
        # 100 likes, 2 followbacks => LBR 2% < 5%
        rows = [
            ("acc", f"u{i}", "low_lbr", 1 if i < 2 else 0, "2026-01-01")
            for i in range(100)
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertFalse(rec.is_quality)
        self.assertAlmostEqual(rec.lbr_percent, 2.0)

    def test_calculate_anomaly_followback_exceeds_likes(self):
        """
        Test anomaly detection via _build_record.

        The standard SQL query uses SUM(CASE WHEN follow_back=1 THEN 1 ELSE 0 END)
        so followback_count can never exceed like_count (COUNT(*)) under normal
        conditions.  The anomaly check is a defensive guard for corrupt data.

        We test it by calling _build_record directly with a crafted row dict.
        """
        result = LBRAnalysisResult(
            device_id=self.device_id,
            username=self.username,
            min_likes=50,
            min_lbr_pct=5.0,
        )
        # Simulate a row where followback > likes (data corruption)
        fake_row = {"source_name": "anomaly_src", "like_count": 5, "followback_count": 10}

        # sqlite3.Row can't be easily faked, so use a dict-like wrapper
        class DictRow:
            def __init__(self, d):
                self._d = d
            def __getitem__(self, key):
                return self._d[key]

        rec = self.calculator._build_record(DictRow(fake_row), result)
        self.assertIsNotNone(rec)
        self.assertEqual(rec.anomaly, "followback_exceeds_likes")
        self.assertFalse(rec.is_quality)
        self.assertEqual(len(result.warnings), 1)

    def test_calculate_all_followbacks_no_anomaly(self):
        """100% follow-back rate is not an anomaly when followback <= likes."""
        rows = [
            ("acc", f"u{i}", "perfect_src", 1, "2026-01-01")
            for i in range(60)
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        rec = result.records[0]
        self.assertIsNone(rec.anomaly)
        self.assertAlmostEqual(rec.lbr_percent, 100.0)
        self.assertTrue(rec.is_quality)

    def test_calculate_filters_null_and_empty_sources(self):
        rows = [
            ("acc", "u1", None, 0, "2026-01-01"),
            ("acc", "u2", "", 0, "2026-01-01"),
            ("acc", "u3", "none", 0, "2026-01-01"),
            ("acc", "u4", "real_source", 0, "2026-01-01"),
        ]
        self._insert_likes(rows)

        result = self.calculator.calculate(self.device_id, self.username)
        # Only "real_source" should appear
        self.assertEqual(result.total_count, 1)
        self.assertEqual(result.records[0].source_name, "real_source")

    def test_calculate_invalid_schema_no_likes_table(self):
        db_path = self._likes_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE other_table (col TEXT)")
        conn.close()

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("likes", result.schema_error)

    def test_calculate_invalid_schema_missing_columns(self):
        db_path = self._likes_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE likes (username TEXT, liked TEXT)")
        conn.close()

        result = self.calculator.calculate(self.device_id, self.username)
        self.assertFalse(result.schema_valid)
        self.assertIn("missing column", result.schema_error)

    # ------------------------------------------------------------------
    # read_active_sources() tests
    # ------------------------------------------------------------------

    def test_read_active_sources(self):
        path = self._source_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source_alpha\nsource_beta\nsource_gamma\n", encoding="utf-8")

        sources = self.calculator.read_active_sources(self.device_id, self.username)
        self.assertEqual(sources, ["source_alpha", "source_beta", "source_gamma"])

    def test_read_active_sources_strips_blanks(self):
        path = self._source_file_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("src1\n\n  \nsrc2\n", encoding="utf-8")

        sources = self.calculator.read_active_sources(self.device_id, self.username)
        self.assertEqual(sources, ["src1", "src2"])

    def test_read_active_sources_missing_file(self):
        sources = self.calculator.read_active_sources(self.device_id, self.username)
        self.assertEqual(sources, [])


# ======================================================================
# 3. Repository Tests — LBRSnapshotRepository
# ======================================================================

class TestLBRSnapshotRepository(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = LBRSnapshotRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _make_snapshot(self, **overrides) -> LBRSnapshotRecord:
        defaults = dict(
            account_id=self.account_id,
            device_id="dev-001",
            username="testuser",
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            min_likes=50,
            min_lbr_pct=5.0,
            total_sources=3,
            quality_sources=2,
            status=SNAPSHOT_OK,
        )
        defaults.update(overrides)
        return LBRSnapshotRecord(**defaults)

    def test_save_and_get_latest_map(self):
        snap = self._make_snapshot()
        saved = self.repo.save(snap)
        self.assertIsNotNone(saved.id)

        latest = self.repo.get_latest_map()
        self.assertIn(self.account_id, latest)
        self.assertEqual(latest[self.account_id].total_sources, 3)

    def test_get_latest_map_returns_newest(self):
        snap1 = self._make_snapshot(
            analyzed_at="2026-01-01T00:00:00Z", total_sources=1,
        )
        snap2 = self._make_snapshot(
            analyzed_at="2026-01-02T00:00:00Z", total_sources=5,
        )
        self.repo.save(snap1)
        self.repo.save(snap2)

        latest = self.repo.get_latest_map()
        self.assertEqual(latest[self.account_id].total_sources, 5)

    def test_save_source_results_and_get(self):
        snap = self._make_snapshot()
        self.repo.save(snap)

        records = [
            SourceLBRRecord("src_a", 100, 20, 20.0, True, None),
            SourceLBRRecord("src_b", 50, 2, 4.0, False, None),
        ]
        self.repo.save_source_results(snap.id, records)

        results = self.repo.get_source_results(snap.id)
        self.assertEqual(len(results), 2)
        # Ordered by like_count DESC
        self.assertEqual(results[0].source_name, "src_a")
        self.assertEqual(results[0].like_count, 100)
        self.assertTrue(results[0].is_quality)
        self.assertEqual(results[1].source_name, "src_b")
        self.assertFalse(results[1].is_quality)

    def test_get_source_results_empty(self):
        snap = self._make_snapshot()
        self.repo.save(snap)
        results = self.repo.get_source_results(snap.id)
        self.assertEqual(results, [])

    def test_get_for_account_sorted_newest_first(self):
        snap1 = self._make_snapshot(
            analyzed_at="2026-01-01T00:00:00Z", total_sources=1,
        )
        snap2 = self._make_snapshot(
            analyzed_at="2026-01-02T00:00:00Z", total_sources=2,
        )
        snap3 = self._make_snapshot(
            analyzed_at="2026-01-03T00:00:00Z", total_sources=3,
        )
        self.repo.save(snap1)
        self.repo.save(snap2)
        self.repo.save(snap3)

        all_snaps = self.repo.get_for_account(self.account_id)
        self.assertEqual(len(all_snaps), 3)
        # Newest first (highest id first)
        self.assertEqual(all_snaps[0].total_sources, 3)
        self.assertEqual(all_snaps[1].total_sources, 2)
        self.assertEqual(all_snaps[2].total_sources, 1)

    def test_get_for_account_empty(self):
        result = self.repo.get_for_account(self.account_id)
        self.assertEqual(result, [])

    def test_save_preserves_all_fields(self):
        snap = self._make_snapshot(
            best_lbr_pct=25.5,
            best_lbr_source="top_src",
            highest_vol_source="big_src",
            highest_vol_count=500,
            below_volume_count=2,
            anomaly_count=1,
            warnings_json=json.dumps(["w1"]),
            schema_error=None,
        )
        self.repo.save(snap)

        loaded = self.repo.get_for_account(self.account_id)[0]
        self.assertAlmostEqual(loaded.best_lbr_pct, 25.5)
        self.assertEqual(loaded.best_lbr_source, "top_src")
        self.assertEqual(loaded.highest_vol_source, "big_src")
        self.assertEqual(loaded.highest_vol_count, 500)
        self.assertEqual(loaded.below_volume_count, 2)
        self.assertEqual(loaded.anomaly_count, 1)
        self.assertEqual(loaded.warnings, ["w1"])

    def test_get_latest_map_multiple_accounts(self):
        acct2_id = _seed_device_and_account(
            self.conn, device_id="dev-001", username="user2",
        )
        snap1 = self._make_snapshot(total_sources=10)
        snap2 = self._make_snapshot(
            account_id=acct2_id, username="user2", total_sources=20,
        )
        self.repo.save(snap1)
        self.repo.save(snap2)

        latest = self.repo.get_latest_map()
        self.assertIn(self.account_id, latest)
        self.assertIn(acct2_id, latest)
        self.assertEqual(latest[self.account_id].total_sources, 10)
        self.assertEqual(latest[acct2_id].total_sources, 20)


# ======================================================================
# 3. Repository Tests — LikeSourceAssignmentRepository
# ======================================================================

class TestLikeSourceAssignmentRepository(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = LikeSourceAssignmentRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_has_any_data_empty(self):
        self.assertFalse(self.repo.has_any_data())

    def test_upsert_and_get_for_account(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a", "src_b"},
            historical_sources={"src_c"},
        )
        rows = self.repo.get_for_account(self.account_id)
        self.assertEqual(len(rows), 3)
        names = {r["source_name"] for r in rows}
        self.assertEqual(names, {"src_a", "src_b", "src_c"})

        # Check active vs historical
        active_names = {r["source_name"] for r in rows if r["is_active"]}
        self.assertEqual(active_names, {"src_a", "src_b"})

    def test_has_any_data_after_upsert(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a"},
            historical_sources=set(),
        )
        self.assertTrue(self.repo.has_any_data())

    def test_upsert_updates_existing(self):
        # First upsert: src_a is active
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a"},
            historical_sources=set(),
        )
        # Second upsert: src_a becomes historical
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources=set(),
            historical_sources={"src_a"},
        )
        rows = self.repo.get_for_account(self.account_id)
        self.assertEqual(len(rows), 1)
        self.assertFalse(rows[0]["is_active"])

    def test_upsert_skips_empty_names(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"", "  ", "valid_src"},
            historical_sources=set(),
        )
        rows = self.repo.get_for_account(self.account_id)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["source_name"], "valid_src")

    def test_get_all_active(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a", "src_b"},
            historical_sources={"src_c"},
        )
        active = self.repo.get_all_active()
        active_names = {r["source_name"] for r in active}
        self.assertIn("src_a", active_names)
        self.assertIn("src_b", active_names)
        self.assertNotIn("src_c", active_names)

    def test_get_all_active_excludes_removed_accounts(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a"},
            historical_sources=set(),
        )
        # Mark account as removed
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE oh_accounts SET removed_at = ? WHERE id = ?",
            (now, self.account_id),
        )
        self.conn.commit()

        active = self.repo.get_all_active()
        self.assertEqual(len(active), 0)

    def test_deactivate_missing(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a", "src_b", "src_c"},
            historical_sources=set(),
        )
        # Now only src_a is still active
        self.repo.deactivate_missing(self.account_id, {"src_a"})

        rows = self.repo.get_for_account(self.account_id)
        active = {r["source_name"] for r in rows if r["is_active"]}
        inactive = {r["source_name"] for r in rows if not r["is_active"]}
        self.assertEqual(active, {"src_a"})
        self.assertEqual(inactive, {"src_b", "src_c"})

    def test_deactivate_missing_empty_set_deactivates_all(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a", "src_b"},
            historical_sources=set(),
        )
        self.repo.deactivate_missing(self.account_id, set())

        rows = self.repo.get_for_account(self.account_id)
        for r in rows:
            self.assertFalse(r["is_active"])

    def test_get_active_source_counts(self):
        acct2_id = _seed_device_and_account(
            self.conn, device_id="dev-001", username="user2",
        )
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"s1", "s2", "s3"},
            historical_sources=set(),
        )
        self.repo.upsert_for_account(
            account_id=acct2_id,
            snapshot_id=None,
            active_sources={"s1"},
            historical_sources={"s2"},
        )
        counts = self.repo.get_active_source_counts()
        self.assertEqual(counts[self.account_id], 3)
        self.assertEqual(counts[acct2_id], 1)

    def test_get_active_source_names_for_account(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"Alpha", "Beta"},
            historical_sources={"Gamma"},
        )
        names = self.repo.get_active_source_names_for_account(self.account_id)
        self.assertEqual(names, {"alpha", "beta"})

    def test_get_source_dates_for_account(self):
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a"},
            historical_sources=set(),
        )
        dates = self.repo.get_source_dates_for_account(self.account_id)
        self.assertIn("src_a", dates)
        # Date part should be YYYY-MM-DD format
        self.assertEqual(len(dates["src_a"]), 10)

    def test_deactivate_removed_accounts(self):
        acct2_id = _seed_device_and_account(
            self.conn, device_id="dev-001", username="user2",
        )
        self.repo.upsert_for_account(
            account_id=self.account_id,
            snapshot_id=None,
            active_sources={"src_a"},
            historical_sources=set(),
        )
        self.repo.upsert_for_account(
            account_id=acct2_id,
            snapshot_id=None,
            active_sources={"src_b"},
            historical_sources=set(),
        )
        # Remove account 2
        now = datetime.now(timezone.utc).isoformat()
        self.conn.execute(
            "UPDATE oh_accounts SET removed_at = ? WHERE id = ?",
            (now, acct2_id),
        )
        self.conn.commit()

        count = self.repo.deactivate_removed_accounts()
        self.assertEqual(count, 1)

        # Account 1's source should still be active
        rows1 = self.repo.get_for_account(self.account_id)
        self.assertTrue(rows1[0]["is_active"])

        # Account 2's source should be inactive
        rows2 = self.repo.get_for_account(acct2_id)
        self.assertFalse(rows2[0]["is_active"])


# ======================================================================
# 3. Repository Tests — GlobalLikeSourceRecord integration
# ======================================================================

class TestGlobalLikeSourcesQuery(unittest.TestCase):
    """Integration test for get_global_like_sources and get_accounts_for_source."""

    def setUp(self):
        self.conn = _create_db()
        self.acct1_id = _seed_device_and_account(self.conn, username="user1")
        self.acct2_id = _seed_device_and_account(self.conn, username="user2")
        self.lsa_repo = LikeSourceAssignmentRepository(self.conn)
        self.snap_repo = LBRSnapshotRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _save_snapshot_with_results(self, account_id, username, source_records):
        snap = LBRSnapshotRecord(
            account_id=account_id,
            device_id="dev-001",
            username=username,
            analyzed_at=datetime.now(timezone.utc).isoformat(),
            min_likes=50,
            min_lbr_pct=5.0,
            total_sources=len(source_records),
            quality_sources=sum(1 for r in source_records if r.is_quality),
            status=SNAPSHOT_OK,
        )
        self.snap_repo.save(snap)
        if source_records:
            self.snap_repo.save_source_results(snap.id, source_records)
        return snap

    def test_get_global_like_sources(self):
        # Set up assignments
        self.lsa_repo.upsert_for_account(
            self.acct1_id, None, {"shared_src", "only_user1"}, set(),
        )
        self.lsa_repo.upsert_for_account(
            self.acct2_id, None, {"shared_src"}, {"old_src"},
        )

        # Save snapshots with LBR data
        self._save_snapshot_with_results(self.acct1_id, "user1", [
            SourceLBRRecord("shared_src", 100, 20, 20.0, True, None),
            SourceLBRRecord("only_user1", 60, 3, 5.0, True, None),
        ])
        self._save_snapshot_with_results(self.acct2_id, "user2", [
            SourceLBRRecord("shared_src", 200, 30, 15.0, True, None),
        ])

        globals_ = self.lsa_repo.get_global_like_sources()
        self.assertGreaterEqual(len(globals_), 2)

        by_name = {g.source_name: g for g in globals_}

        # shared_src: 2 active, 300 likes, 50 followbacks
        shared = by_name.get("shared_src")
        self.assertIsNotNone(shared)
        self.assertEqual(shared.active_accounts, 2)
        self.assertEqual(shared.total_likes, 300)
        self.assertEqual(shared.total_followbacks, 50)

    def test_get_accounts_for_source(self):
        self.lsa_repo.upsert_for_account(
            self.acct1_id, None, {"test_src"}, set(),
        )
        self._save_snapshot_with_results(self.acct1_id, "user1", [
            SourceLBRRecord("test_src", 80, 16, 20.0, True, None),
        ])

        details = self.lsa_repo.get_accounts_for_source("test_src")
        self.assertEqual(len(details), 1)
        self.assertEqual(details[0].username, "user1")
        self.assertEqual(details[0].like_count, 80)
        self.assertTrue(details[0].is_active)


if __name__ == "__main__":
    unittest.main()
