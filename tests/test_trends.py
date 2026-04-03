"""
Unit tests for Phase 10 Feature E — Performance Trends.

Covers: compute_trend function, TrendService, AccountTrends model.
"""
import sqlite3
import unittest
from datetime import date, datetime, timedelta, timezone

from oh.db.migrations import run_migrations
from oh.services.trend_service import (
    TrendService, AccountTrends, compute_trend,
    TREND_UP, TREND_DOWN, TREND_STABLE, TREND_NONE,
)
from oh.repositories.session_repo import SessionRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
from oh.models.session import AccountSessionRecord


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed_account(conn):
    now = datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO oh_devices (device_id, device_name, first_discovered_at, last_synced_at) "
        "VALUES (?, ?, ?, ?)",
        ("dev-001", "Phone1", now, now),
    )
    cursor = conn.execute(
        "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
        "VALUES (?, ?, ?, ?)",
        ("dev-001", "testuser", now, now),
    )
    conn.commit()
    return cursor.lastrowid


# -----------------------------------------------------------------------
# compute_trend tests
# -----------------------------------------------------------------------

class TestComputeTrend(unittest.TestCase):
    def test_trend_up(self):
        values = [10.0, 12.0, 11.0, 20.0, 25.0, 30.0]
        self.assertEqual(compute_trend(values), TREND_UP)

    def test_trend_down(self):
        values = [30.0, 28.0, 25.0, 10.0, 8.0, 5.0]
        self.assertEqual(compute_trend(values), TREND_DOWN)

    def test_trend_stable(self):
        values = [50.0, 52.0, 48.0, 51.0, 49.0, 50.0]
        self.assertEqual(compute_trend(values), TREND_STABLE)

    def test_too_few_values(self):
        self.assertEqual(compute_trend([10.0, 20.0]), TREND_NONE)
        self.assertEqual(compute_trend([10.0]), TREND_NONE)
        self.assertEqual(compute_trend([]), TREND_NONE)

    def test_all_zeros(self):
        values = [0.0, 0.0, 0.0, 0.0]
        self.assertEqual(compute_trend(values), TREND_NONE)

    def test_from_zero_to_positive(self):
        values = [0.0, 0.0, 5.0, 10.0, 15.0, 20.0]
        # first half [0,0,5] avg=1.67, second [10,15,20] avg=15 → big increase
        self.assertEqual(compute_trend(values), TREND_UP)

    def test_pure_zeros_first_half(self):
        values = [0.0, 0.0, 0.0, 10.0, 15.0, 20.0]
        # first half avg = 0 exactly → TREND_NONE (division guard)
        self.assertEqual(compute_trend(values), TREND_NONE)

    def test_exact_threshold(self):
        # 15% change threshold
        values = [100.0, 100.0, 100.0, 115.0, 115.0, 115.0]
        # change = 15/100 = 0.15, not > 0.15, so STABLE
        self.assertEqual(compute_trend(values), TREND_STABLE)

    def test_just_above_threshold(self):
        values = [100.0, 100.0, 100.0, 116.0, 116.0, 116.0]
        self.assertEqual(compute_trend(values), TREND_UP)


# -----------------------------------------------------------------------
# AccountTrends model
# -----------------------------------------------------------------------

class TestAccountTrends(unittest.TestCase):
    def test_defaults(self):
        t = AccountTrends()
        self.assertEqual(t.follow_trend, [])
        self.assertEqual(t.trend_direction, "none")

    def test_with_data(self):
        t = AccountTrends(
            follow_trend=[10, 20, 30],
            trend_direction=TREND_UP,
        )
        self.assertEqual(len(t.follow_trend), 3)
        self.assertEqual(t.trend_direction, TREND_UP)


# -----------------------------------------------------------------------
# TrendService tests
# -----------------------------------------------------------------------

class TestTrendService(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.session_repo = SessionRepository(self.conn)
        self.fbr_repo = FBRSnapshotRepository(self.conn)
        self.service = TrendService(self.session_repo, self.fbr_repo)
        self.account_id = _seed_account(self.conn)

    def tearDown(self):
        self.conn.close()

    def _insert_sessions(self, daily_follows, start_days_ago=None):
        if start_days_ago is None:
            start_days_ago = len(daily_follows) - 1
        for i, follows in enumerate(daily_follows):
            d = date.today() - timedelta(days=start_days_ago - i)
            self.session_repo.upsert_snapshot(AccountSessionRecord(
                account_id=self.account_id,
                device_id="dev-001",
                username="testuser",
                snapshot_date=d.isoformat(),
                slot="06-12",
                follow_count=follows,
                has_activity=follows > 0,
            ))

    def test_get_follow_trend_empty(self):
        result = self.service.get_follow_trend(self.account_id, 14)
        self.assertEqual(result, [])

    def test_get_follow_trend_with_data(self):
        self._insert_sessions([10, 20, 30, 40, 50], start_days_ago=4)
        result = self.service.get_follow_trend(self.account_id, 14)
        self.assertEqual(len(result), 5)
        # Oldest first
        self.assertEqual(result[0], 10)
        self.assertEqual(result[-1], 50)

    def test_get_trends_map_empty(self):
        result = self.service.get_trends_map([self.account_id], 7)
        self.assertIn(self.account_id, result)
        trends = result[self.account_id]
        self.assertEqual(len(trends.follow_trend), 7)
        # All zeros since no data
        self.assertTrue(all(f == 0 for f in trends.follow_trend))

    def test_get_trends_map_with_data(self):
        self._insert_sessions([10, 20, 30, 40, 50, 60, 70], start_days_ago=6)
        result = self.service.get_trends_map([self.account_id], 7)
        trends = result[self.account_id]
        self.assertEqual(trends.trend_direction, TREND_UP)

    def test_get_trends_map_multiple_accounts(self):
        # Add second account
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
            "VALUES (?, ?, ?, ?)",
            ("dev-001", "user2", now, now),
        )
        self.conn.commit()
        acc2 = cursor.lastrowid

        result = self.service.get_trends_map([self.account_id, acc2], 7)
        self.assertIn(self.account_id, result)
        self.assertIn(acc2, result)

    def test_get_fbr_trend_empty(self):
        result = self.service.get_fbr_trend(self.account_id, 14)
        self.assertEqual(result, [])


# -----------------------------------------------------------------------
# Sparkline re-export test
# -----------------------------------------------------------------------

class TestSparklineReExport(unittest.TestCase):
    def test_compute_trend_reexported(self):
        from oh.ui.sparkline_widget import compute_trend as ct
        from oh.services.trend_service import compute_trend as ct2
        self.assertIs(ct, ct2)

    def test_constants_reexported(self):
        from oh.ui.sparkline_widget import TREND_UP, TREND_DOWN, TREND_STABLE, TREND_NONE
        self.assertEqual(TREND_UP, "up")
        self.assertEqual(TREND_DOWN, "down")


if __name__ == "__main__":
    unittest.main()
