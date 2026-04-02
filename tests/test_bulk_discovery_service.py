"""
Unit tests for oh.services.bulk_discovery_service — get_qualifying_accounts.

Uses unittest.mock to isolate the service from real repositories.
"""
import unittest
from unittest.mock import MagicMock, patch

from oh.models.account import AccountRecord
from oh.models.bulk_discovery import BULK_RUNNING
from oh.services.bulk_discovery_service import BulkDiscoveryService


def _make_account(account_id: int, username: str, device_id: str = "dev-001") -> AccountRecord:
    """Helper to create a minimal AccountRecord with an id."""
    acct = AccountRecord(
        device_id=device_id,
        username=username,
        discovered_at="2026-04-01T00:00:00+00:00",
        last_seen_at="2026-04-01T00:00:00+00:00",
        data_db_exists=True,
        sources_txt_exists=True,
        id=account_id,
    )
    return acct


class TestGetQualifyingAccounts(unittest.TestCase):
    """Test that get_qualifying_accounts filters and sorts correctly."""

    def setUp(self):
        self.bulk_repo = MagicMock()
        self.source_finder_svc = MagicMock()
        self.account_repo = MagicMock()
        self.assignment_repo = MagicMock()
        self.settings_repo = MagicMock()

        # recover_stale_runs is called in __init__, let it pass
        self.bulk_repo.recover_stale_runs.return_value = 0

        self.svc = BulkDiscoveryService(
            bulk_repo=self.bulk_repo,
            source_finder_service=self.source_finder_svc,
            account_repo=self.account_repo,
            assignment_repo=self.assignment_repo,
            settings_repo=self.settings_repo,
        )

    def test_accounts_below_threshold_are_returned(self):
        acct1 = _make_account(1, "user_a")
        acct2 = _make_account(2, "user_b")
        self.account_repo.get_all_active.return_value = [acct1, acct2]
        self.assignment_repo.get_active_source_counts.return_value = {1: 2, 2: 3}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 2)
        # Both have fewer than 5 sources
        usernames = [acct.username for acct, _ in result]
        self.assertIn("user_a", usernames)
        self.assertIn("user_b", usernames)

    def test_accounts_at_threshold_are_excluded(self):
        acct1 = _make_account(1, "user_at")
        self.account_repo.get_all_active.return_value = [acct1]
        self.assignment_repo.get_active_source_counts.return_value = {1: 5}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 0)

    def test_accounts_above_threshold_are_excluded(self):
        acct1 = _make_account(1, "user_above")
        self.account_repo.get_all_active.return_value = [acct1]
        self.assignment_repo.get_active_source_counts.return_value = {1: 10}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 0)

    def test_sorted_by_source_count_ascending(self):
        acct1 = _make_account(1, "user_3_sources")
        acct2 = _make_account(2, "user_1_source")
        acct3 = _make_account(3, "user_0_sources")
        self.account_repo.get_all_active.return_value = [acct1, acct2, acct3]
        self.assignment_repo.get_active_source_counts.return_value = {1: 3, 2: 1, 3: 0}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 3)
        # Most needy first (0, 1, 3)
        self.assertEqual(result[0][0].username, "user_0_sources")
        self.assertEqual(result[0][1], 0)
        self.assertEqual(result[1][0].username, "user_1_source")
        self.assertEqual(result[1][1], 1)
        self.assertEqual(result[2][0].username, "user_3_sources")
        self.assertEqual(result[2][1], 3)

    def test_accounts_missing_from_source_counts_default_to_zero(self):
        acct1 = _make_account(1, "new_account")
        self.account_repo.get_all_active.return_value = [acct1]
        # account 1 not in source_counts dict at all
        self.assignment_repo.get_active_source_counts.return_value = {}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], 0)

    def test_empty_active_accounts_returns_empty(self):
        self.account_repo.get_all_active.return_value = []
        self.assignment_repo.get_active_source_counts.return_value = {}

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(result, [])

    def test_mixed_above_and_below_threshold(self):
        acct1 = _make_account(1, "below")
        acct2 = _make_account(2, "at")
        acct3 = _make_account(3, "above")
        acct4 = _make_account(4, "also_below")
        self.account_repo.get_all_active.return_value = [acct1, acct2, acct3, acct4]
        self.assignment_repo.get_active_source_counts.return_value = {
            1: 2, 2: 5, 3: 8, 4: 4,
        }

        result = self.svc.get_qualifying_accounts(min_threshold=5)
        self.assertEqual(len(result), 2)
        usernames = [acct.username for acct, _ in result]
        self.assertIn("below", usernames)
        self.assertIn("also_below", usernames)
        self.assertNotIn("at", usernames)
        self.assertNotIn("above", usernames)

    def test_threshold_of_zero_returns_empty(self):
        """With threshold=0, no account can have fewer than 0 sources."""
        acct1 = _make_account(1, "user")
        self.account_repo.get_all_active.return_value = [acct1]
        self.assignment_repo.get_active_source_counts.return_value = {1: 0}

        result = self.svc.get_qualifying_accounts(min_threshold=0)
        self.assertEqual(len(result), 0)


class TestServiceInit(unittest.TestCase):
    """Test that __init__ calls recover_stale_runs."""

    def test_init_calls_recover_stale_runs(self):
        bulk_repo = MagicMock()
        bulk_repo.recover_stale_runs.return_value = 0

        BulkDiscoveryService(
            bulk_repo=bulk_repo,
            source_finder_service=MagicMock(),
            account_repo=MagicMock(),
            assignment_repo=MagicMock(),
            settings_repo=MagicMock(),
        )
        bulk_repo.recover_stale_runs.assert_called_once_with(max_age_hours=24)


if __name__ == "__main__":
    unittest.main()
