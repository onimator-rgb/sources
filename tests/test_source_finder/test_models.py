"""
Unit tests for oh.models.source_finder dataclasses and constants.
"""
import unittest

from oh.models.source_finder import (
    SEARCH_COMPLETED,
    SEARCH_FAILED,
    SEARCH_RUNNING,
    SourceCandidate,
    SourceSearchRecord,
    SourceSearchResult,
)


class TestSourceSearchRecord(unittest.TestCase):
    """SourceSearchRecord creation and defaults."""

    def test_creation_with_required_fields(self):
        rec = SourceSearchRecord(
            account_id=1,
            username="testuser",
            started_at="2026-04-01T00:00:00+00:00",
            status=SEARCH_RUNNING,
        )
        self.assertEqual(rec.account_id, 1)
        self.assertEqual(rec.username, "testuser")
        self.assertEqual(rec.status, SEARCH_RUNNING)
        self.assertEqual(rec.step_reached, 0)
        self.assertIsNone(rec.completed_at)
        self.assertIsNone(rec.query_used)
        self.assertIsNone(rec.error_message)
        self.assertIsNone(rec.id)

    def test_creation_with_all_fields(self):
        rec = SourceSearchRecord(
            account_id=2,
            username="user2",
            started_at="2026-04-01T00:00:00+00:00",
            status=SEARCH_COMPLETED,
            step_reached=7,
            completed_at="2026-04-01T01:00:00+00:00",
            query_used="fitness Warszawa",
            error_message=None,
            id=42,
        )
        self.assertEqual(rec.id, 42)
        self.assertEqual(rec.step_reached, 7)
        self.assertEqual(rec.query_used, "fitness Warszawa")

    def test_defaults(self):
        rec = SourceSearchRecord(
            account_id=1, username="u", started_at="t", status="running",
        )
        self.assertEqual(rec.step_reached, 0)
        self.assertIsNone(rec.id)


class TestSourceCandidate(unittest.TestCase):
    """SourceCandidate creation and defaults."""

    def test_creation_with_defaults(self):
        cand = SourceCandidate(search_id=1, username="candidate1")
        self.assertEqual(cand.search_id, 1)
        self.assertEqual(cand.username, "candidate1")
        self.assertIsNone(cand.full_name)
        self.assertEqual(cand.follower_count, 0)
        self.assertIsNone(cand.bio)
        self.assertEqual(cand.source_type, "suggested")
        self.assertFalse(cand.is_private)
        self.assertFalse(cand.is_verified)
        self.assertFalse(cand.is_enriched)
        self.assertIsNone(cand.avg_er)
        self.assertIsNone(cand.ai_score)
        self.assertIsNone(cand.ai_category)
        self.assertIsNone(cand.profile_pic_url)
        self.assertIsNone(cand.id)

    def test_creation_with_all_fields(self):
        cand = SourceCandidate(
            search_id=10,
            username="big_account",
            full_name="Big Account",
            follower_count=50000,
            bio="Fitness coach",
            source_type="search",
            is_private=False,
            is_verified=True,
            is_enriched=True,
            avg_er=3.5,
            ai_score=8.2,
            ai_category="Fitness Coach",
            profile_pic_url="https://example.com/pic.jpg",
            id=99,
        )
        self.assertEqual(cand.id, 99)
        self.assertEqual(cand.follower_count, 50000)
        self.assertTrue(cand.is_verified)
        self.assertEqual(cand.avg_er, 3.5)


class TestSourceSearchResult(unittest.TestCase):
    """SourceSearchResult creation — with and without joined candidate."""

    def test_creation_without_candidate(self):
        result = SourceSearchResult(
            search_id=1, candidate_id=10, rank=1,
        )
        self.assertEqual(result.search_id, 1)
        self.assertEqual(result.candidate_id, 10)
        self.assertEqual(result.rank, 1)
        self.assertFalse(result.added_to_sources)
        self.assertIsNone(result.added_at)
        self.assertIsNone(result.candidate)
        self.assertIsNone(result.id)

    def test_creation_with_candidate(self):
        cand = SourceCandidate(search_id=1, username="joined_user", id=10)
        result = SourceSearchResult(
            search_id=1,
            candidate_id=10,
            rank=3,
            added_to_sources=True,
            added_at="2026-04-01T02:00:00+00:00",
            candidate=cand,
            id=5,
        )
        self.assertTrue(result.added_to_sources)
        self.assertIsNotNone(result.candidate)
        self.assertEqual(result.candidate.username, "joined_user")


class TestStatusConstants(unittest.TestCase):
    """Verify status constant values."""

    def test_constants(self):
        self.assertEqual(SEARCH_RUNNING, "running")
        self.assertEqual(SEARCH_COMPLETED, "completed")
        self.assertEqual(SEARCH_FAILED, "failed")


if __name__ == "__main__":
    unittest.main()
