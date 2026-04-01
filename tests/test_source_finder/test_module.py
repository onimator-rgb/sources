"""
Unit tests for oh.modules.source_finder — helper functions and class instantiation.
"""
import unittest

from oh.modules.source_finder import (
    HikerAPIError,
    HikerClient,
    GeminiScorer,
    build_manual_query,
    build_query_variations,
    compute_avg_er,
    pre_filter,
    quality_filter,
)


class TestBuildManualQuery(unittest.TestCase):
    """build_manual_query() with various profile shapes."""

    def test_full_profile(self):
        profile = {
            "username": "fit_kate",
            "full_name": "Katarzyna Trener",
            "biography": "Trener personalny | dietetyk | Gdansk",
            "category": "Personal Trainer",
            "city_name": "Gdansk",
        }
        query = build_manual_query(profile)
        self.assertIsInstance(query, str)
        self.assertTrue(len(query) > 0)

    def test_profile_with_bio_only(self):
        profile = {
            "username": "someuser",
            "biography": "Fotograf slubny Krakow, sesje rodzinne, newborn",
        }
        query = build_manual_query(profile)
        self.assertIsInstance(query, str)
        self.assertTrue(len(query) > 0)

    def test_profile_with_category_only(self):
        profile = {
            "username": "biz",
            "category": "Photographer",
        }
        query = build_manual_query(profile)
        self.assertIn("Photographer", query)

    def test_profile_with_city_only(self):
        profile = {
            "username": "cityuser",
            "city_name": "Warszawa",
        }
        query = build_manual_query(profile)
        # City may be added as the only term
        self.assertIn("Warszawa", query)

    def test_empty_profile_returns_empty_or_short(self):
        query = build_manual_query({})
        # With empty profile all fields are missing so query should be empty
        self.assertIsInstance(query, str)
        self.assertEqual(query.strip(), "")

    def test_profile_with_none_values(self):
        profile = {
            "username": None,
            "full_name": None,
            "biography": None,
            "category": None,
            "city_name": None,
        }
        query = build_manual_query(profile)
        self.assertIsInstance(query, str)


class TestBuildQueryVariations(unittest.TestCase):
    """build_query_variations() returns list of strings."""

    def test_multi_word_query(self):
        variations = build_query_variations("trener personalny Gdansk")
        self.assertIsInstance(variations, list)
        self.assertGreater(len(variations), 1)
        self.assertLessEqual(len(variations), 5)
        # Original query should be first
        self.assertEqual(variations[0], "trener personalny Gdansk")
        # All entries should be strings
        for v in variations:
            self.assertIsInstance(v, str)

    def test_single_word_query(self):
        variations = build_query_variations("fitness")
        self.assertGreater(len(variations), 1)
        self.assertEqual(variations[0], "fitness")

    def test_empty_query(self):
        variations = build_query_variations("")
        self.assertEqual(len(variations), 0)

    def test_two_word_query(self):
        variations = build_query_variations("fitness Warszawa")
        self.assertGreater(len(variations), 1)
        self.assertIn("fitness Warszawa", variations)


class TestComputeAvgER(unittest.TestCase):
    """compute_avg_er() with normal and edge cases."""

    def test_normal_posts(self):
        posts = [
            {"like_count": 100, "comment_count": 10},
            {"like_count": 200, "comment_count": 20},
        ]
        er = compute_avg_er(posts, 10000)
        # Post 1: (110/10000)*100 = 1.1, Post 2: (220/10000)*100 = 2.2
        # Average: 1.65
        self.assertAlmostEqual(er, 1.65, places=2)

    def test_zero_followers(self):
        posts = [{"like_count": 100, "comment_count": 10}]
        er = compute_avg_er(posts, 0)
        self.assertEqual(er, 0.0)

    def test_negative_followers(self):
        posts = [{"like_count": 100, "comment_count": 10}]
        er = compute_avg_er(posts, -5)
        self.assertEqual(er, 0.0)

    def test_empty_posts(self):
        er = compute_avg_er([], 10000)
        self.assertEqual(er, 0.0)

    def test_posts_with_missing_fields(self):
        posts = [{"like_count": 50}, {"comment_count": 25}]
        er = compute_avg_er(posts, 5000)
        # Post 1: (50+0)/5000*100 = 1.0, Post 2: (0+25)/5000*100 = 0.5
        # Average: 0.75
        self.assertAlmostEqual(er, 0.75, places=2)

    def test_posts_with_none_values(self):
        posts = [{"like_count": None, "comment_count": None}]
        er = compute_avg_er(posts, 5000)
        self.assertEqual(er, 0.0)


class TestPreFilter(unittest.TestCase):
    """pre_filter() removes private, verified, and no-username candidates."""

    def test_removes_private(self):
        candidates = [
            {"username": "public1", "is_private": False, "is_verified": False},
            {"username": "private1", "is_private": True, "is_verified": False},
        ]
        result = pre_filter(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "public1")

    def test_removes_verified(self):
        candidates = [
            {"username": "normal", "is_private": False, "is_verified": False},
            {"username": "celeb", "is_private": False, "is_verified": True},
        ]
        result = pre_filter(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "normal")

    def test_removes_no_username(self):
        candidates = [
            {"username": "valid", "is_private": False, "is_verified": False},
            {"username": "", "is_private": False, "is_verified": False},
            {"is_private": False, "is_verified": False},
        ]
        result = pre_filter(candidates)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "valid")

    def test_empty_input(self):
        result = pre_filter([])
        self.assertEqual(len(result), 0)

    def test_all_valid(self):
        candidates = [
            {"username": f"user{i}", "is_private": False, "is_verified": False}
            for i in range(5)
        ]
        result = pre_filter(candidates)
        self.assertEqual(len(result), 5)


class TestQualityFilter(unittest.TestCase):
    """quality_filter() removes low-follower accounts."""

    def test_removes_below_threshold(self):
        candidates = [
            {"username": "big", "follower_count": 5000, "is_private": False, "is_verified": False},
            {"username": "small", "follower_count": 500, "is_private": False, "is_verified": False},
        ]
        result = quality_filter(candidates, min_followers=1000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "big")

    def test_custom_threshold(self):
        candidates = [
            {"username": "u1", "follower_count": 200, "is_private": False, "is_verified": False},
            {"username": "u2", "follower_count": 600, "is_private": False, "is_verified": False},
        ]
        result = quality_filter(candidates, min_followers=500)
        self.assertEqual(len(result), 1)

    def test_also_removes_private_and_verified(self):
        candidates = [
            {"username": "priv", "follower_count": 5000, "is_private": True, "is_verified": False},
            {"username": "verif", "follower_count": 5000, "is_private": False, "is_verified": True},
            {"username": "ok", "follower_count": 5000, "is_private": False, "is_verified": False},
        ]
        result = quality_filter(candidates, min_followers=1000)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["username"], "ok")

    def test_empty_input(self):
        result = quality_filter([], min_followers=1000)
        self.assertEqual(len(result), 0)


class TestHikerClientInit(unittest.TestCase):
    """HikerClient raises HikerAPIError on empty key."""

    def test_empty_key_raises(self):
        with self.assertRaises(HikerAPIError):
            HikerClient("")

    def test_whitespace_key_raises(self):
        with self.assertRaises(HikerAPIError):
            HikerClient("   ")

    def test_none_key_raises(self):
        with self.assertRaises(HikerAPIError):
            HikerClient(None)


class TestGeminiScorerAvailability(unittest.TestCase):
    """GeminiScorer.is_available is False with empty key."""

    def test_empty_key_not_available(self):
        scorer = GeminiScorer("")
        self.assertFalse(scorer.is_available)

    def test_none_key_not_available(self):
        scorer = GeminiScorer(None)
        self.assertFalse(scorer.is_available)


if __name__ == "__main__":
    unittest.main()
