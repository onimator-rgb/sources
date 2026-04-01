"""
Unit tests for oh.repositories.source_search_repo — in-memory SQLite.
"""
import sqlite3
import time
import unittest
from datetime import datetime, timedelta, timezone

from oh.db.migrations import run_migrations
from oh.models.source_finder import (
    SEARCH_COMPLETED,
    SEARCH_FAILED,
    SEARCH_RUNNING,
    SourceCandidate,
    SourceSearchResult,
)
from oh.repositories.source_search_repo import SourceSearchRepository


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


class TestSearchCRUD(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceSearchRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_create_search_returns_record_with_id(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        self.assertIsNotNone(rec.id)
        self.assertEqual(rec.account_id, self.account_id)
        self.assertEqual(rec.username, "testuser")
        self.assertEqual(rec.status, SEARCH_RUNNING)
        self.assertEqual(rec.step_reached, 0)

    def test_update_search_step(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        self.repo.update_search_step(rec.id, 3)
        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.step_reached, 3)

    def test_update_search_step_increments(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        for step in (1, 2, 3, 4):
            self.repo.update_search_step(rec.id, step)
        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.step_reached, 4)

    def test_complete_search_sets_status_and_completed_at(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        self.repo.complete_search(rec.id, SEARCH_COMPLETED)
        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.status, SEARCH_COMPLETED)
        self.assertIsNotNone(latest.completed_at)
        self.assertIsNone(latest.error_message)

    def test_complete_search_with_error(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        self.repo.complete_search(rec.id, SEARCH_FAILED, "timeout")
        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.status, SEARCH_FAILED)
        self.assertEqual(latest.error_message, "timeout")

    def test_get_latest_search_returns_most_recent(self):
        self.repo.create_search(self.account_id, "testuser")
        self.repo.create_search(self.account_id, "testuser")
        latest = self.repo.get_latest_search(self.account_id)
        # Most recent should have the highest id
        all_rows = self.conn.execute(
            "SELECT id FROM source_searches ORDER BY id"
        ).fetchall()
        self.assertEqual(latest.id, all_rows[-1]["id"])

    def test_get_latest_search_returns_none_when_empty(self):
        result = self.repo.get_latest_search(9999)
        self.assertIsNone(result)


class TestCandidateCRUD(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceSearchRepository(self.conn)
        self.search = self.repo.create_search(self.account_id, "testuser")

    def tearDown(self):
        self.conn.close()

    def _make_candidates(self, n=3):
        return [
            SourceCandidate(
                search_id=self.search.id,
                username=f"cand_{i}",
                full_name=f"Candidate {i}",
                follower_count=1000 * (i + 1),
                bio=f"Bio {i}",
                source_type="suggested" if i % 2 == 0 else "search",
            )
            for i in range(n)
        ]

    def test_save_candidates_bulk_insert(self):
        cands = self._make_candidates(5)
        self.repo.save_candidates(self.search.id, cands)
        loaded = self.repo.get_candidates(self.search.id)
        self.assertEqual(len(loaded), 5)
        # IDs should be assigned
        for c in loaded:
            self.assertIsNotNone(c.id)

    def test_get_candidates_returns_all_for_search(self):
        cands = self._make_candidates(3)
        self.repo.save_candidates(self.search.id, cands)
        loaded = self.repo.get_candidates(self.search.id)
        self.assertEqual(len(loaded), 3)
        usernames = {c.username for c in loaded}
        self.assertEqual(usernames, {"cand_0", "cand_1", "cand_2"})

    def test_get_candidates_empty_for_other_search(self):
        cands = self._make_candidates(2)
        self.repo.save_candidates(self.search.id, cands)
        # Different search
        search2 = self.repo.create_search(self.account_id, "testuser")
        loaded = self.repo.get_candidates(search2.id)
        self.assertEqual(len(loaded), 0)

    def test_update_candidate_enrichment(self):
        cands = self._make_candidates(1)
        self.repo.save_candidates(self.search.id, cands)
        loaded = self.repo.get_candidates(self.search.id)
        cand_id = loaded[0].id

        self.repo.update_candidate_enrichment(
            cand_id, follower_count=5000, bio="Updated bio", avg_er=2.5, is_enriched=True,
        )

        updated = self.repo.get_candidates(self.search.id)
        c = updated[0]
        self.assertEqual(c.follower_count, 5000)
        self.assertEqual(c.bio, "Updated bio")
        self.assertEqual(c.avg_er, 2.5)
        self.assertTrue(c.is_enriched)

    def test_update_candidate_er(self):
        cands = self._make_candidates(1)
        self.repo.save_candidates(self.search.id, cands)
        loaded = self.repo.get_candidates(self.search.id)
        cand_id = loaded[0].id

        self.repo.update_candidate_er(cand_id, 4.321)

        updated = self.repo.get_candidates(self.search.id)
        self.assertEqual(updated[0].avg_er, 4.321)

    def test_update_candidate_ai(self):
        cands = self._make_candidates(1)
        self.repo.save_candidates(self.search.id, cands)
        loaded = self.repo.get_candidates(self.search.id)
        cand_id = loaded[0].id

        self.repo.update_candidate_ai(cand_id, ai_score=7.5, ai_category="Fitness")

        updated = self.repo.get_candidates(self.search.id)
        self.assertEqual(updated[0].ai_score, 7.5)
        self.assertEqual(updated[0].ai_category, "Fitness")


class TestResultsCRUD(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceSearchRepository(self.conn)
        self.search = self.repo.create_search(self.account_id, "testuser")
        # Insert candidates so FK is satisfied
        self.cands = [
            SourceCandidate(
                search_id=self.search.id,
                username=f"result_cand_{i}",
                follower_count=10000 - i * 1000,
            )
            for i in range(3)
        ]
        self.repo.save_candidates(self.search.id, self.cands)
        self.loaded_cands = self.repo.get_candidates(self.search.id)

    def tearDown(self):
        self.conn.close()

    def test_save_results_and_get_results_with_join(self):
        results = [
            SourceSearchResult(
                search_id=self.search.id,
                candidate_id=self.loaded_cands[i].id,
                rank=i + 1,
            )
            for i in range(3)
        ]
        self.repo.save_results(self.search.id, results)
        loaded = self.repo.get_results(self.search.id)

        self.assertEqual(len(loaded), 3)
        # Results should be ordered by rank
        ranks = [r.rank for r in loaded]
        self.assertEqual(ranks, [1, 2, 3])
        # Each result should have a joined candidate
        for r in loaded:
            self.assertIsNotNone(r.candidate)
            self.assertIsNotNone(r.candidate.username)

    def test_mark_added_to_sources(self):
        results = [
            SourceSearchResult(
                search_id=self.search.id,
                candidate_id=self.loaded_cands[0].id,
                rank=1,
            )
        ]
        self.repo.save_results(self.search.id, results)
        loaded = self.repo.get_results(self.search.id)
        result_id = loaded[0].id

        self.assertFalse(loaded[0].added_to_sources)

        self.repo.mark_added_to_sources(result_id)

        after = self.repo.get_results(self.search.id)
        self.assertTrue(after[0].added_to_sources)
        self.assertIsNotNone(after[0].added_at)


class TestRecoverStaleSearches(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceSearchRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_recover_stale_searches_marks_old_as_failed(self):
        # Create a search and manually backdate its started_at
        rec = self.repo.create_search(self.account_id, "testuser")
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.conn.execute(
            "UPDATE source_searches SET started_at=? WHERE id=?",
            (old_time, rec.id),
        )
        self.conn.commit()

        count = self.repo.recover_stale_searches(max_age_hours=24)
        self.assertEqual(count, 1)

        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.status, SEARCH_FAILED)
        self.assertEqual(latest.error_message, "Stale search recovered")

    def test_recover_does_not_touch_recent_running(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        count = self.repo.recover_stale_searches(max_age_hours=24)
        self.assertEqual(count, 0)
        latest = self.repo.get_latest_search(self.account_id)
        self.assertEqual(latest.status, SEARCH_RUNNING)

    def test_recover_does_not_touch_completed(self):
        rec = self.repo.create_search(self.account_id, "testuser")
        self.repo.complete_search(rec.id, SEARCH_COMPLETED)
        # Backdate
        old_time = (datetime.now(timezone.utc) - timedelta(hours=25)).isoformat()
        self.conn.execute(
            "UPDATE source_searches SET started_at=? WHERE id=?",
            (old_time, rec.id),
        )
        self.conn.commit()

        count = self.repo.recover_stale_searches(max_age_hours=24)
        self.assertEqual(count, 0)


if __name__ == "__main__":
    unittest.main()
