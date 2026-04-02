"""
Unit tests for oh.repositories.bulk_discovery_repo — in-memory SQLite.
"""
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone

from oh.db.migrations import run_migrations
from oh.models.bulk_discovery import (
    BULK_CANCELLED,
    BULK_COMPLETED,
    BULK_FAILED,
    BULK_RUNNING,
    ITEM_DONE,
    ITEM_FAILED,
    ITEM_QUEUED,
    ITEM_RUNNING,
    ITEM_SKIPPED,
)
from oh.repositories.bulk_discovery_repo import BulkDiscoveryRepository


def _create_db() -> sqlite3.Connection:
    """Create an in-memory DB with all migrations applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed_device_and_account(conn: sqlite3.Connection) -> int:
    """Insert a minimal device + account row and return the account id."""
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


def _seed_second_account(conn: sqlite3.Connection) -> int:
    """Insert a second account on the same device, return its id."""
    now = datetime.now(timezone.utc).isoformat()
    cursor = conn.execute(
        "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
        "VALUES (?, ?, ?, ?)",
        ("dev-001", "testuser2", now, now),
    )
    conn.commit()
    return cursor.lastrowid


# ======================================================================
# Run CRUD
# ======================================================================


class TestCreateRun(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_run_returns_run_with_id(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=10,
        )
        self.assertIsNotNone(run.id)
        self.assertEqual(run.status, BULK_RUNNING)
        self.assertEqual(run.min_threshold, 5)
        self.assertEqual(run.auto_add_top_n, 3)
        self.assertEqual(run.total_accounts, 10)
        self.assertIsNotNone(run.started_at)
        self.assertIsNone(run.machine)

    def test_create_run_with_machine(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3,
            total_accounts=2, machine="WS-01",
        )
        self.assertEqual(run.machine, "WS-01")

    def test_create_run_persists_to_db(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=10,
        )
        row = self.conn.execute(
            "SELECT * FROM bulk_discovery_runs WHERE id=?", (run.id,)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["status"], "running")


class TestUpdateRunProgress(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)
        self.run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=10,
        )

    def tearDown(self):
        self.conn.close()

    def test_update_run_progress(self):
        self.repo.update_run_progress(
            self.run.id, accounts_done=4, accounts_failed=1, total_added=12,
        )
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.accounts_done, 4)
        self.assertEqual(updated.accounts_failed, 1)
        self.assertEqual(updated.total_added, 12)

    def test_update_run_progress_multiple_times(self):
        self.repo.update_run_progress(self.run.id, 1, 0, 3)
        self.repo.update_run_progress(self.run.id, 2, 1, 6)
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.accounts_done, 2)
        self.assertEqual(updated.accounts_failed, 1)
        self.assertEqual(updated.total_added, 6)


class TestCompleteRun(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)
        self.run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=10,
        )

    def tearDown(self):
        self.conn.close()

    def test_complete_run_sets_status_and_completed_at(self):
        self.repo.complete_run(self.run.id, BULK_COMPLETED)
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.status, BULK_COMPLETED)
        self.assertIsNotNone(updated.completed_at)
        self.assertIsNone(updated.error_message)

    def test_complete_run_with_error(self):
        self.repo.complete_run(self.run.id, BULK_FAILED, "All accounts failed")
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.status, BULK_FAILED)
        self.assertEqual(updated.error_message, "All accounts failed")

    def test_complete_run_cancelled(self):
        self.repo.complete_run(self.run.id, BULK_CANCELLED)
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.status, BULK_CANCELLED)


class TestMarkRunReverted(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)
        self.run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=5,
        )
        self.repo.complete_run(self.run.id, BULK_COMPLETED)

    def tearDown(self):
        self.conn.close()

    def test_mark_run_reverted(self):
        self.repo.mark_run_reverted(self.run.id, "reverted")
        updated = self.repo.get_run(self.run.id)
        self.assertIsNotNone(updated.reverted_at)
        self.assertEqual(updated.revert_status, "reverted")

    def test_mark_run_partially_reverted(self):
        self.repo.mark_run_reverted(self.run.id, "partially_reverted")
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.revert_status, "partially_reverted")

    def test_mark_run_revert_failed(self):
        self.repo.mark_run_reverted(self.run.id, "revert_failed")
        updated = self.repo.get_run(self.run.id)
        self.assertEqual(updated.revert_status, "revert_failed")


class TestRecoverStaleRuns(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_recover_stale_runs_marks_old_running_as_failed(self):
        # Insert a run with started_at 48 hours ago
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.conn.execute(
            "INSERT INTO bulk_discovery_runs "
            "(started_at, status, min_threshold, auto_add_top_n, total_accounts) "
            "VALUES (?, 'running', 5, 3, 10)",
            (old_time,),
        )
        self.conn.commit()

        count = self.repo.recover_stale_runs(max_age_hours=24)
        self.assertEqual(count, 1)

        row = self.conn.execute(
            "SELECT status, error_message FROM bulk_discovery_runs"
        ).fetchone()
        self.assertEqual(row["status"], BULK_FAILED)
        self.assertEqual(row["error_message"], "Stale run recovered")

    def test_recover_stale_runs_ignores_recent(self):
        # A run created now should not be recovered
        self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=5)
        count = self.repo.recover_stale_runs(max_age_hours=24)
        self.assertEqual(count, 0)

    def test_recover_stale_runs_ignores_completed(self):
        # A completed run (even if old) should not be touched
        old_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
        self.conn.execute(
            "INSERT INTO bulk_discovery_runs "
            "(started_at, status, min_threshold, auto_add_top_n, total_accounts) "
            "VALUES (?, 'completed', 5, 3, 10)",
            (old_time,),
        )
        self.conn.commit()

        count = self.repo.recover_stale_runs(max_age_hours=24)
        self.assertEqual(count, 0)


# ======================================================================
# Item CRUD
# ======================================================================


class TestItemCRUD(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = BulkDiscoveryRepository(self.conn)
        self.run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=2,
        )

    def tearDown(self):
        self.conn.close()

    def test_create_item_returns_item_with_id(self):
        item = self.repo.create_item(
            run_id=self.run.id,
            account_id=self.account_id,
            username="testuser",
            device_id="dev-001",
            sources_before=3,
        )
        self.assertIsNotNone(item.id)
        self.assertEqual(item.run_id, self.run.id)
        self.assertEqual(item.account_id, self.account_id)
        self.assertEqual(item.username, "testuser")
        self.assertEqual(item.device_id, "dev-001")
        self.assertEqual(item.sources_before, 3)
        self.assertEqual(item.status, ITEM_QUEUED)

    def test_update_item_status_and_results(self):
        item = self.repo.create_item(
            run_id=self.run.id,
            account_id=self.account_id,
            username="testuser",
            device_id="dev-001",
            sources_before=3,
        )
        # Insert a source_searches row to satisfy FK constraint
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO source_searches (account_id, username, started_at, status) "
            "VALUES (?, ?, ?, ?)",
            (self.account_id, "testuser", now, "completed"),
        )
        self.conn.commit()
        search_id = cursor.lastrowid

        self.repo.update_item(
            item.id,
            status=ITEM_DONE,
            search_id=search_id,
            sources_added=5,
            sources_after=8,
            added_sources_json='["src1","src2","src3","src4","src5"]',
            original_sources_json='["old1","old2","old3"]',
        )
        updated = self.repo.get_item(item.id)
        self.assertEqual(updated.status, ITEM_DONE)
        self.assertEqual(updated.search_id, search_id)
        self.assertEqual(updated.sources_added, 5)
        self.assertEqual(updated.sources_after, 8)
        self.assertEqual(updated.added_sources_json, '["src1","src2","src3","src4","src5"]')
        self.assertEqual(updated.original_sources_json, '["old1","old2","old3"]')
        self.assertIsNone(updated.error_message)

    def test_update_item_with_error(self):
        item = self.repo.create_item(
            run_id=self.run.id,
            account_id=self.account_id,
            username="testuser",
            device_id="dev-001",
            sources_before=0,
        )
        self.repo.update_item(
            item.id, status=ITEM_FAILED, error_message="API timeout",
        )
        updated = self.repo.get_item(item.id)
        self.assertEqual(updated.status, ITEM_FAILED)
        self.assertEqual(updated.error_message, "API timeout")

    def test_get_item_returns_none_for_missing_id(self):
        result = self.repo.get_item(9999)
        self.assertIsNone(result)


# ======================================================================
# Read operations
# ======================================================================


class TestGetRun(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_run_returns_run(self):
        created = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=10,
        )
        fetched = self.repo.get_run(created.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.id, created.id)
        self.assertEqual(fetched.min_threshold, 5)

    def test_get_run_returns_none_for_missing_id(self):
        result = self.repo.get_run(9999)
        self.assertIsNone(result)


class TestGetRunWithItems(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_run_with_items_returns_items(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=2,
        )
        self.repo.create_item(
            run.id, self.account_id, "testuser", "dev-001", 3,
        )
        result = self.repo.get_run_with_items(run.id)
        self.assertIsNotNone(result)
        self.assertIsNotNone(result.items)
        self.assertEqual(len(result.items), 1)
        self.assertEqual(result.items[0].username, "testuser")

    def test_get_run_with_items_empty(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=0,
        )
        result = self.repo.get_run_with_items(run.id)
        self.assertIsNotNone(result)
        self.assertEqual(result.items, [])

    def test_get_run_with_items_returns_none_for_missing(self):
        result = self.repo.get_run_with_items(9999)
        self.assertIsNone(result)


class TestGetRecentRuns(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_recent_runs_returns_newest_first(self):
        r1 = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=1)
        r2 = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=2)
        r3 = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=3)

        recent = self.repo.get_recent_runs(limit=10)
        self.assertEqual(len(recent), 3)
        self.assertEqual(recent[0].id, r3.id)
        self.assertEqual(recent[1].id, r2.id)
        self.assertEqual(recent[2].id, r1.id)

    def test_get_recent_runs_respects_limit(self):
        for _ in range(5):
            self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=1)
        recent = self.repo.get_recent_runs(limit=3)
        self.assertEqual(len(recent), 3)

    def test_get_recent_runs_empty_db(self):
        recent = self.repo.get_recent_runs()
        self.assertEqual(recent, [])


class TestGetItemsForRun(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.account_id2 = _seed_second_account(self.conn)
        self.repo = BulkDiscoveryRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_get_items_for_run_returns_ordered_by_id(self):
        run = self.repo.create_run(
            min_threshold=5, auto_add_top_n=3, total_accounts=2,
        )
        i1 = self.repo.create_item(run.id, self.account_id, "testuser", "dev-001", 2)
        i2 = self.repo.create_item(run.id, self.account_id2, "testuser2", "dev-001", 4)

        items = self.repo.get_items_for_run(run.id)
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].id, i1.id)
        self.assertEqual(items[1].id, i2.id)

    def test_get_items_for_run_does_not_cross_runs(self):
        run_a = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=1)
        run_b = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=1)
        self.repo.create_item(run_a.id, self.account_id, "testuser", "dev-001", 2)
        self.repo.create_item(run_b.id, self.account_id2, "testuser2", "dev-001", 4)

        items_a = self.repo.get_items_for_run(run_a.id)
        items_b = self.repo.get_items_for_run(run_b.id)
        self.assertEqual(len(items_a), 1)
        self.assertEqual(items_a[0].username, "testuser")
        self.assertEqual(len(items_b), 1)
        self.assertEqual(items_b[0].username, "testuser2")

    def test_get_items_for_run_empty(self):
        run = self.repo.create_run(min_threshold=5, auto_add_top_n=3, total_accounts=0)
        items = self.repo.get_items_for_run(run.id)
        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
