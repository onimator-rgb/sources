"""Tests for oh.services.recommendation_service."""
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock

from oh.db.migrations import run_migrations
from oh.models.account import AccountRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.global_source import GlobalSourceRecord
from oh.models.recommendation import (
    REC_LOW_FBR_SOURCE, REC_SOURCE_EXHAUSTION, REC_LOW_LIKE,
    REC_LIMITS_MAX, REC_TB_MAX, REC_ZERO_ACTION,
    SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW,
    SEV_RANK,
)
from oh.models.session import AccountSessionRecord
from oh.repositories.account_repo import AccountRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.tag_repo import TagRepository
from oh.services.recommendation_service import RecommendationService


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


_NOW = datetime.now(timezone.utc).isoformat()


def _seed_device(conn: sqlite3.Connection, device_id: str = "dev-001",
                 device_name: str = "Phone1") -> None:
    """Insert a device row (idempotent on device_id)."""
    conn.execute(
        "INSERT OR IGNORE INTO oh_devices "
        "(device_id, device_name, first_discovered_at, last_synced_at) "
        "VALUES (?, ?, ?, ?)",
        (device_id, device_name, _NOW, _NOW),
    )
    conn.commit()


def _seed_account(conn: sqlite3.Connection, username: str = "testuser",
                  device_id: str = "dev-001", follow_enabled: bool = True,
                  start_time: str = "6", end_time: str = "12",
                  like_limit_perday: str = "100") -> int:
    """Insert an account and return its id."""
    _seed_device(conn, device_id)
    cursor = conn.execute(
        "INSERT INTO oh_accounts "
        "(device_id, username, discovered_at, last_seen_at, "
        " follow_enabled, start_time, end_time, "
        " data_db_exists, sources_txt_exists, like_limit_perday) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)",
        (device_id, username, _NOW, _NOW,
         1 if follow_enabled else 0, start_time, end_time,
         like_limit_perday),
    )
    conn.commit()
    return cursor.lastrowid


def _make_session(account_id: int, username: str = "testuser",
                  follow_count: int = 0, like_count: int = 0,
                  has_activity: bool = False) -> AccountSessionRecord:
    return AccountSessionRecord(
        account_id=account_id,
        device_id="dev-001",
        username=username,
        snapshot_date="2026-04-23",
        slot="06-12",
        follow_count=follow_count,
        like_count=like_count,
        has_activity=has_activity,
    )


def _make_fbr_snap(account_id: int, total_sources: int = 10,
                   quality_sources: int = 3) -> FBRSnapshotRecord:
    return FBRSnapshotRecord(
        account_id=account_id,
        device_id="dev-001",
        username="testuser",
        analyzed_at=_NOW,
        min_follows=100,
        min_fbr_pct=10.0,
        total_sources=total_sources,
        quality_sources=quality_sources,
        status="ok",
    )


def _build_service(conn: sqlite3.Connection,
                   weak_sources=None,
                   source_counts=None) -> RecommendationService:
    """Build RecommendationService with real repos and a mocked GlobalSourcesService."""
    account_repo = AccountRepository(conn)
    settings_repo = SettingsRepository(conn)
    settings_repo.seed_defaults()
    tag_repo = TagRepository(conn)

    gs = MagicMock()
    gs.get_active_source_counts.return_value = source_counts or {}
    gs.get_sources_below_threshold.return_value = weak_sources or []

    return RecommendationService(
        global_sources_service=gs,
        account_repo=account_repo,
        tag_repo=tag_repo,
        settings_repo=settings_repo,
    )


# ======================================================================
# Test: No accounts -> empty
# ======================================================================

class TestNoAccounts(unittest.TestCase):

    def test_empty_db_returns_no_recs(self):
        conn = _create_db()
        svc = _build_service(conn)
        recs = svc.generate({}, {}, {}, {})
        self.assertEqual(recs, [])
        conn.close()


# ======================================================================
# Test: Weak Source (LOW_FBR_SOURCE)
# ======================================================================

class TestWeakSource(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_weak_source_generates_rec(self):
        weak = [GlobalSourceRecord(
            source_name="bad_source",
            active_accounts=3,
            total_follows=200,
            total_followbacks=2,
            weighted_fbr_pct=1.0,
        )]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        low_fbr = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE]
        self.assertEqual(len(low_fbr), 1)
        self.assertEqual(low_fbr[0].target_id, "bad_source")

    def test_zero_wfbr_is_critical(self):
        weak = [GlobalSourceRecord(
            source_name="dead_source",
            active_accounts=2,
            total_follows=150,
            total_followbacks=0,
            weighted_fbr_pct=0.0,
        )]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        rec = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE][0]
        self.assertEqual(rec.severity, SEV_CRITICAL)

    def test_low_wfbr_below_1_is_high(self):
        weak = [GlobalSourceRecord(
            source_name="almost_dead",
            active_accounts=2,
            total_follows=200,
            total_followbacks=1,
            weighted_fbr_pct=0.5,
        )]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        rec = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE][0]
        self.assertEqual(rec.severity, SEV_HIGH)

    def test_wfbr_above_1_is_medium(self):
        weak = [GlobalSourceRecord(
            source_name="mediocre",
            active_accounts=2,
            total_follows=200,
            total_followbacks=5,
            weighted_fbr_pct=2.5,
        )]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        rec = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE][0]
        self.assertEqual(rec.severity, SEV_MEDIUM)

    def test_noise_control_max_25_plus_summary(self):
        """More than 25 weak sources produces 25 individual + 1 summary rec."""
        weak = [
            GlobalSourceRecord(
                source_name=f"weak_{i:03d}",
                active_accounts=1,
                total_follows=100,
                total_followbacks=0,
                weighted_fbr_pct=0.0,
            )
            for i in range(30)
        ]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        low_fbr = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE]
        # 25 individual + 1 summary = 26
        self.assertEqual(len(low_fbr), 26)

        summary = [r for r in low_fbr if r.target_id == "_bulk"]
        self.assertEqual(len(summary), 1)
        self.assertIn("+5 more", summary[0].target_label)

    def test_exactly_25_weak_no_summary(self):
        weak = [
            GlobalSourceRecord(
                source_name=f"weak_{i:03d}",
                active_accounts=1,
                total_follows=100,
                total_followbacks=0,
                weighted_fbr_pct=0.0,
            )
            for i in range(25)
        ]
        svc = _build_service(self.conn, weak_sources=weak)
        recs = svc.generate({}, {}, {}, {})

        low_fbr = [r for r in recs if r.rec_type == REC_LOW_FBR_SOURCE]
        self.assertEqual(len(low_fbr), 25)
        summary = [r for r in low_fbr if r.target_id == "_bulk"]
        self.assertEqual(len(summary), 0)


# ======================================================================
# Test: Source Exhaustion
# ======================================================================

class TestSourceExhaustion(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_zero_sources_generates_high_rec(self):
        aid = _seed_account(self.conn, "user_no_src")
        svc = _build_service(self.conn, source_counts={aid: 0})

        recs = svc.generate({}, {}, {}, {})
        exh = [r for r in recs if r.rec_type == REC_SOURCE_EXHAUSTION]
        self.assertEqual(len(exh), 1)
        self.assertEqual(exh[0].severity, SEV_HIGH)
        self.assertIn("0 active sources", exh[0].reason)

    def test_below_min_warning_generates_medium_rec(self):
        aid = _seed_account(self.conn, "low_src_user")
        snap = _make_fbr_snap(aid, total_sources=5, quality_sources=2)
        # default min_source_count_warning = 5, so 3 active < 5
        svc = _build_service(self.conn, source_counts={aid: 3})

        recs = svc.generate({}, {aid: snap}, {}, {})
        exh = [r for r in recs if r.rec_type == REC_SOURCE_EXHAUSTION]
        self.assertEqual(len(exh), 1)
        self.assertEqual(exh[0].severity, SEV_MEDIUM)

    def test_many_sources_zero_quality_generates_low_rec(self):
        aid = _seed_account(self.conn, "no_quality")
        snap = _make_fbr_snap(aid, total_sources=10, quality_sources=0)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {aid: snap}, {}, {})
        exh = [r for r in recs if r.rec_type == REC_SOURCE_EXHAUSTION]
        self.assertEqual(len(exh), 1)
        self.assertEqual(exh[0].severity, SEV_LOW)

    def test_enough_sources_with_quality_no_rec(self):
        aid = _seed_account(self.conn, "healthy")
        snap = _make_fbr_snap(aid, total_sources=10, quality_sources=5)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {aid: snap}, {}, {})
        exh = [r for r in recs if r.rec_type == REC_SOURCE_EXHAUSTION]
        self.assertEqual(len(exh), 0)


# ======================================================================
# Test: Low Like
# ======================================================================

class TestLowLike(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_active_account_zero_likes_generates_rec(self):
        aid = _seed_account(self.conn, "liker", like_limit_perday="50")
        sess = _make_session(aid, "liker", follow_count=30, like_count=0,
                             has_activity=True)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({aid: sess}, {}, {}, {})
        low = [r for r in recs if r.rec_type == REC_LOW_LIKE]
        self.assertEqual(len(low), 1)
        self.assertEqual(low[0].severity, SEV_MEDIUM)

    def test_account_with_likes_no_rec(self):
        aid = _seed_account(self.conn, "liker2", like_limit_perday="50")
        sess = _make_session(aid, "liker2", follow_count=30, like_count=10,
                             has_activity=True)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({aid: sess}, {}, {}, {})
        low = [r for r in recs if r.rec_type == REC_LOW_LIKE]
        self.assertEqual(len(low), 0)

    def test_like_limit_zero_no_rec(self):
        """Like not configured (limit=0) should not generate recommendation."""
        aid = _seed_account(self.conn, "no_like", like_limit_perday="0")
        sess = _make_session(aid, "no_like", follow_count=30, like_count=0,
                             has_activity=True)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({aid: sess}, {}, {}, {})
        low = [r for r in recs if r.rec_type == REC_LOW_LIKE]
        self.assertEqual(len(low), 0)

    def test_inactive_account_no_rec(self):
        """Account with 0 follows should not trigger low-like rec."""
        aid = _seed_account(self.conn, "idle", like_limit_perday="50")
        sess = _make_session(aid, "idle", follow_count=0, like_count=0)
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({aid: sess}, {}, {}, {})
        low = [r for r in recs if r.rec_type == REC_LOW_LIKE]
        self.assertEqual(len(low), 0)


# ======================================================================
# Test: Limits Max
# ======================================================================

class TestLimitsMax(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_limits_5_generates_high_rec(self):
        aid = _seed_account(self.conn, "limited")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {aid: "limits 5"})
        lim = [r for r in recs if r.rec_type == REC_LIMITS_MAX]
        self.assertEqual(len(lim), 1)
        self.assertEqual(lim[0].severity, SEV_HIGH)

    def test_limits_4_no_rec(self):
        aid = _seed_account(self.conn, "ok_limits")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {aid: "limits 4"})
        lim = [r for r in recs if r.rec_type == REC_LIMITS_MAX]
        self.assertEqual(len(lim), 0)

    def test_no_tags_no_rec(self):
        aid = _seed_account(self.conn, "no_tags")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {})
        lim = [r for r in recs if r.rec_type == REC_LIMITS_MAX]
        self.assertEqual(len(lim), 0)


# ======================================================================
# Test: TB Max
# ======================================================================

class TestTBMax(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_tb5_generates_critical_rec(self):
        aid = _seed_account(self.conn, "tb_user")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {aid: "TB5"})
        tb = [r for r in recs if r.rec_type == REC_TB_MAX]
        self.assertEqual(len(tb), 1)
        self.assertEqual(tb[0].severity, SEV_CRITICAL)

    def test_tb4_no_rec(self):
        aid = _seed_account(self.conn, "tb_ok")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {aid: "TB4"})
        tb = [r for r in recs if r.rec_type == REC_TB_MAX]
        self.assertEqual(len(tb), 0)

    def test_combined_tags_tb5_and_limits(self):
        """Tags string with multiple pipe-separated parts."""
        aid = _seed_account(self.conn, "combo")
        svc = _build_service(self.conn, source_counts={aid: 10})

        recs = svc.generate({}, {}, {}, {aid: "TB5 | limits 3"})
        tb = [r for r in recs if r.rec_type == REC_TB_MAX]
        self.assertEqual(len(tb), 1)
        # limits 3 should NOT trigger LIMITS_MAX
        lim = [r for r in recs if r.rec_type == REC_LIMITS_MAX]
        self.assertEqual(len(lim), 0)


# ======================================================================
# Test: Zero Action
# ======================================================================

class TestZeroAction(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_zero_action_in_active_slot_generates_rec(self):
        # Account slot 6-12, current_hour=9 -> active
        aid = _seed_account(self.conn, "idle_acc", start_time="6", end_time="12")
        sess = _make_session(aid, "idle_acc", follow_count=0, has_activity=False)
        svc = _build_service(self.conn, source_counts={aid: 10})

        # Patch _is_active_slot via current_hour matching 6<=9<12
        # We need to call generate with device running and right hour
        # But generate uses datetime.now().hour internally, so we monkeypatch
        import oh.services.recommendation_service as mod
        _orig = mod.datetime
        try:
            mock_dt = MagicMock(wraps=datetime)
            mock_dt.now.return_value = datetime(2026, 4, 23, 9, 0, 0)
            mod.datetime = mock_dt

            recs = svc.generate(
                {aid: sess}, {}, {"dev-001": "running"}, {}
            )
        finally:
            mod.datetime = _orig

        zero = [r for r in recs if r.rec_type == REC_ZERO_ACTION]
        self.assertEqual(len(zero), 1)
        self.assertEqual(zero[0].severity, SEV_HIGH)

    def test_not_in_active_slot_no_rec(self):
        # Account slot 6-12, current_hour=15 -> NOT active
        aid = _seed_account(self.conn, "off_slot", start_time="6", end_time="12")
        sess = _make_session(aid, "off_slot", follow_count=0, has_activity=False)
        svc = _build_service(self.conn, source_counts={aid: 10})

        import oh.services.recommendation_service as mod
        _orig = mod.datetime
        try:
            mock_dt = MagicMock(wraps=datetime)
            mock_dt.now.return_value = datetime(2026, 4, 23, 15, 0, 0)
            mod.datetime = mock_dt

            recs = svc.generate(
                {aid: sess}, {}, {"dev-001": "running"}, {}
            )
        finally:
            mod.datetime = _orig

        zero = [r for r in recs if r.rec_type == REC_ZERO_ACTION]
        self.assertEqual(len(zero), 0)

    def test_device_not_running_no_rec(self):
        aid = _seed_account(self.conn, "stopped", start_time="6", end_time="12")
        sess = _make_session(aid, "stopped", follow_count=0, has_activity=False)
        svc = _build_service(self.conn, source_counts={aid: 10})

        import oh.services.recommendation_service as mod
        _orig = mod.datetime
        try:
            mock_dt = MagicMock(wraps=datetime)
            mock_dt.now.return_value = datetime(2026, 4, 23, 9, 0, 0)
            mod.datetime = mock_dt

            recs = svc.generate(
                {aid: sess}, {}, {"dev-001": "stop"}, {}
            )
        finally:
            mod.datetime = _orig

        zero = [r for r in recs if r.rec_type == REC_ZERO_ACTION]
        self.assertEqual(len(zero), 0)

    def test_follow_disabled_no_rec(self):
        aid = _seed_account(self.conn, "disabled", follow_enabled=False,
                            start_time="6", end_time="12")
        sess = _make_session(aid, "disabled", follow_count=0, has_activity=False)
        svc = _build_service(self.conn, source_counts={aid: 10})

        import oh.services.recommendation_service as mod
        _orig = mod.datetime
        try:
            mock_dt = MagicMock(wraps=datetime)
            mock_dt.now.return_value = datetime(2026, 4, 23, 9, 0, 0)
            mod.datetime = mock_dt

            recs = svc.generate(
                {aid: sess}, {}, {"dev-001": "running"}, {}
            )
        finally:
            mod.datetime = _orig

        zero = [r for r in recs if r.rec_type == REC_ZERO_ACTION]
        self.assertEqual(len(zero), 0)

    def test_has_activity_no_rec(self):
        aid = _seed_account(self.conn, "active", start_time="6", end_time="12")
        sess = _make_session(aid, "active", follow_count=5, has_activity=True)
        svc = _build_service(self.conn, source_counts={aid: 10})

        import oh.services.recommendation_service as mod
        _orig = mod.datetime
        try:
            mock_dt = MagicMock(wraps=datetime)
            mock_dt.now.return_value = datetime(2026, 4, 23, 9, 0, 0)
            mod.datetime = mock_dt

            recs = svc.generate(
                {aid: sess}, {}, {"dev-001": "running"}, {}
            )
        finally:
            mod.datetime = _orig

        zero = [r for r in recs if r.rec_type == REC_ZERO_ACTION]
        self.assertEqual(len(zero), 0)


# ======================================================================
# Test: _is_active_slot edge cases
# ======================================================================

class TestIsActiveSlot(unittest.TestCase):

    def test_colon_format_start_time(self):
        """The fixed bug: start_time='08:00' should parse to hour=8."""
        acc = AccountRecord(
            device_id="dev-001", username="colon_user",
            discovered_at=_NOW, last_seen_at=_NOW,
            data_db_exists=True, sources_txt_exists=True,
            start_time="08:00", end_time="14:00",
        )
        result = RecommendationService._is_active_slot(acc, 10)
        self.assertTrue(result)

    def test_colon_format_outside_slot(self):
        acc = AccountRecord(
            device_id="dev-001", username="colon_user2",
            discovered_at=_NOW, last_seen_at=_NOW,
            data_db_exists=True, sources_txt_exists=True,
            start_time="08:00", end_time="14:00",
        )
        result = RecommendationService._is_active_slot(acc, 16)
        self.assertFalse(result)

    def test_simple_hour_format(self):
        acc = AccountRecord(
            device_id="dev-001", username="simple",
            discovered_at=_NOW, last_seen_at=_NOW,
            data_db_exists=True, sources_txt_exists=True,
            start_time="6", end_time="12",
        )
        self.assertTrue(RecommendationService._is_active_slot(acc, 6))
        self.assertTrue(RecommendationService._is_active_slot(acc, 11))
        self.assertFalse(RecommendationService._is_active_slot(acc, 12))
        self.assertFalse(RecommendationService._is_active_slot(acc, 5))

    def test_zero_zero_returns_false(self):
        acc = AccountRecord(
            device_id="dev-001", username="unscheduled",
            discovered_at=_NOW, last_seen_at=_NOW,
            data_db_exists=True, sources_txt_exists=True,
            start_time="0", end_time="0",
        )
        self.assertFalse(RecommendationService._is_active_slot(acc, 0))

    def test_none_times_returns_false(self):
        acc = AccountRecord(
            device_id="dev-001", username="none_times",
            discovered_at=_NOW, last_seen_at=_NOW,
            data_db_exists=True, sources_txt_exists=True,
            start_time=None, end_time=None,
        )
        self.assertFalse(RecommendationService._is_active_slot(acc, 10))


# ======================================================================
# Test: _extract_operator_level
# ======================================================================

class TestExtractOperatorLevel(unittest.TestCase):

    def test_tb_extraction(self):
        self.assertEqual(
            RecommendationService._extract_operator_level("TB3", "TB"), 3
        )

    def test_tb_in_compound_string(self):
        self.assertEqual(
            RecommendationService._extract_operator_level("TB5 | limits 2", "TB"), 5
        )

    def test_limits_extraction(self):
        self.assertEqual(
            RecommendationService._extract_operator_level("limits 4", "limits"), 4
        )

    def test_limits_in_compound_string(self):
        self.assertEqual(
            RecommendationService._extract_operator_level("TB2 | limits 5", "limits"), 5
        )

    def test_empty_string_returns_none(self):
        self.assertIsNone(
            RecommendationService._extract_operator_level("", "TB")
        )

    def test_no_match_returns_none(self):
        self.assertIsNone(
            RecommendationService._extract_operator_level("role: SLAVE", "TB")
        )


# ======================================================================
# Test: Severity ordering
# ======================================================================

class TestSeverityOrdering(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()

    def tearDown(self):
        self.conn.close()

    def test_results_sorted_by_severity(self):
        """CRITICAL recs should appear before HIGH, HIGH before MEDIUM, etc."""
        # Create accounts that will trigger different severity recs
        aid1 = _seed_account(self.conn, "tb5_user")
        aid2 = _seed_account(self.conn, "limited_user")
        aid3 = _seed_account(self.conn, "low_src_user")

        snap3 = _make_fbr_snap(aid3, total_sources=5, quality_sources=2)

        svc = _build_service(self.conn, source_counts={
            aid1: 10, aid2: 10, aid3: 3,
        })

        recs = svc.generate(
            {}, {aid3: snap3}, {},
            {aid1: "TB5", aid2: "limits 5"},
        )

        # Should have: TB_MAX (CRITICAL), LIMITS_MAX (HIGH),
        # SOURCE_EXHAUSTION (MEDIUM)
        self.assertGreaterEqual(len(recs), 3)

        severities = [r.severity for r in recs]
        severity_ranks = [SEV_RANK.get(s, 9) for s in severities]
        self.assertEqual(severity_ranks, sorted(severity_ranks))


if __name__ == "__main__":
    unittest.main()
