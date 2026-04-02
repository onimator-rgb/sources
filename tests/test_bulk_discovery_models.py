"""
Unit tests for oh.models.bulk_discovery dataclasses and constants.
"""
import unittest

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
    BulkDiscoveryItem,
    BulkDiscoveryRun,
)


class TestRunStatusConstants(unittest.TestCase):
    """Run-level status constants have expected string values."""

    def test_running(self):
        self.assertEqual(BULK_RUNNING, "running")

    def test_completed(self):
        self.assertEqual(BULK_COMPLETED, "completed")

    def test_failed(self):
        self.assertEqual(BULK_FAILED, "failed")

    def test_cancelled(self):
        self.assertEqual(BULK_CANCELLED, "cancelled")


class TestItemStatusConstants(unittest.TestCase):
    """Item-level status constants have expected string values."""

    def test_queued(self):
        self.assertEqual(ITEM_QUEUED, "queued")

    def test_running(self):
        self.assertEqual(ITEM_RUNNING, "running")

    def test_done(self):
        self.assertEqual(ITEM_DONE, "done")

    def test_failed(self):
        self.assertEqual(ITEM_FAILED, "failed")

    def test_skipped(self):
        self.assertEqual(ITEM_SKIPPED, "skipped")


class TestBulkDiscoveryItem(unittest.TestCase):
    """BulkDiscoveryItem creation and default values."""

    def test_creation_with_required_fields(self):
        item = BulkDiscoveryItem(
            run_id=1,
            account_id=10,
            username="testuser",
            device_id="dev-001",
        )
        self.assertEqual(item.run_id, 1)
        self.assertEqual(item.account_id, 10)
        self.assertEqual(item.username, "testuser")
        self.assertEqual(item.device_id, "dev-001")
        # defaults
        self.assertEqual(item.status, ITEM_QUEUED)
        self.assertIsNone(item.search_id)
        self.assertEqual(item.sources_before, 0)
        self.assertEqual(item.sources_added, 0)
        self.assertEqual(item.sources_after, 0)
        self.assertIsNone(item.added_sources_json)
        self.assertIsNone(item.original_sources_json)
        self.assertIsNone(item.error_message)
        self.assertIsNone(item.id)

    def test_creation_with_all_fields(self):
        item = BulkDiscoveryItem(
            run_id=2,
            account_id=20,
            username="user2",
            device_id="dev-002",
            status=ITEM_DONE,
            search_id=99,
            sources_before=3,
            sources_added=5,
            sources_after=8,
            added_sources_json='["a","b"]',
            original_sources_json='["c","d"]',
            error_message=None,
            id=42,
        )
        self.assertEqual(item.id, 42)
        self.assertEqual(item.status, ITEM_DONE)
        self.assertEqual(item.search_id, 99)
        self.assertEqual(item.sources_before, 3)
        self.assertEqual(item.sources_added, 5)
        self.assertEqual(item.sources_after, 8)
        self.assertEqual(item.added_sources_json, '["a","b"]')

    def test_status_default_is_queued(self):
        item = BulkDiscoveryItem(
            run_id=1, account_id=1, username="u", device_id="d",
        )
        self.assertEqual(item.status, ITEM_QUEUED)


class TestBulkDiscoveryRun(unittest.TestCase):
    """BulkDiscoveryRun creation and default values."""

    def test_creation_with_required_fields(self):
        run = BulkDiscoveryRun(
            started_at="2026-04-01T00:00:00+00:00",
            status=BULK_RUNNING,
            min_threshold=5,
            auto_add_top_n=3,
        )
        self.assertEqual(run.started_at, "2026-04-01T00:00:00+00:00")
        self.assertEqual(run.status, BULK_RUNNING)
        self.assertEqual(run.min_threshold, 5)
        self.assertEqual(run.auto_add_top_n, 3)
        # defaults
        self.assertEqual(run.total_accounts, 0)
        self.assertEqual(run.accounts_done, 0)
        self.assertEqual(run.accounts_failed, 0)
        self.assertEqual(run.total_added, 0)
        self.assertIsNone(run.completed_at)
        self.assertIsNone(run.machine)
        self.assertIsNone(run.error_message)
        self.assertIsNone(run.reverted_at)
        self.assertIsNone(run.revert_status)
        self.assertIsNone(run.items)
        self.assertIsNone(run.id)

    def test_creation_with_all_fields(self):
        run = BulkDiscoveryRun(
            started_at="2026-04-01T00:00:00+00:00",
            status=BULK_COMPLETED,
            min_threshold=5,
            auto_add_top_n=3,
            total_accounts=10,
            accounts_done=8,
            accounts_failed=2,
            total_added=15,
            completed_at="2026-04-01T01:00:00+00:00",
            machine="WORKSTATION-1",
            error_message=None,
            reverted_at=None,
            revert_status=None,
            items=[],
            id=7,
        )
        self.assertEqual(run.id, 7)
        self.assertEqual(run.total_accounts, 10)
        self.assertEqual(run.accounts_done, 8)
        self.assertEqual(run.accounts_failed, 2)
        self.assertEqual(run.total_added, 15)
        self.assertEqual(run.machine, "WORKSTATION-1")
        self.assertEqual(run.items, [])

    def test_items_default_is_none(self):
        run = BulkDiscoveryRun(
            started_at="t", status="running",
            min_threshold=1, auto_add_top_n=1,
        )
        self.assertIsNone(run.items)

    def test_items_can_hold_item_list(self):
        item = BulkDiscoveryItem(
            run_id=1, account_id=1, username="u", device_id="d",
        )
        run = BulkDiscoveryRun(
            started_at="t", status="running",
            min_threshold=1, auto_add_top_n=1,
            items=[item],
        )
        self.assertEqual(len(run.items), 1)
        self.assertIs(run.items[0], item)


if __name__ == "__main__":
    unittest.main()
