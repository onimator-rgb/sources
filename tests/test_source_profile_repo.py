"""Tests for oh.repositories.source_profile_repo."""
import sqlite3
import unittest
from datetime import datetime, timezone

from oh.db.migrations import run_migrations
from oh.repositories.source_profile_repo import SourceProfileRepository


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


# ======================================================================
# Upsert + Get Profile
# ======================================================================


class TestUpsertProfile(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = SourceProfileRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_insert_new_profile(self):
        self.repo.upsert_profile(
            source_name="fitness_guru",
            niche_category="fitness",
            niche_confidence=0.85,
            language="en",
            bio="Personal trainer",
        )
        profile = self.repo.get_profile("fitness_guru")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.source_name, "fitness_guru")
        self.assertEqual(profile.niche_category, "fitness")
        self.assertAlmostEqual(profile.niche_confidence, 0.85)
        self.assertEqual(profile.language, "en")
        self.assertEqual(profile.bio, "Personal trainer")
        self.assertIsNotNone(profile.first_seen_at)
        self.assertIsNotNone(profile.updated_at)

    def test_update_existing_coalesce_preserves_non_null(self):
        # First insert with full data
        self.repo.upsert_profile(
            source_name="fitness_guru",
            niche_category="fitness",
            niche_confidence=0.85,
            language="en",
            location="NYC",
            bio="Personal trainer",
        )
        # Update with only niche_confidence changed, other fields NULL
        self.repo.upsert_profile(
            source_name="fitness_guru",
            niche_confidence=0.92,
        )
        profile = self.repo.get_profile("fitness_guru")
        # Updated field should change
        self.assertAlmostEqual(profile.niche_confidence, 0.92)
        # Existing non-NULL fields should be preserved via COALESCE
        self.assertEqual(profile.niche_category, "fitness")
        self.assertEqual(profile.language, "en")
        self.assertEqual(profile.location, "NYC")
        self.assertEqual(profile.bio, "Personal trainer")

    def test_get_profile_returns_none_for_missing(self):
        result = self.repo.get_profile("nonexistent")
        self.assertIsNone(result)

    def test_upsert_with_all_fields(self):
        self.repo.upsert_profile(
            source_name="full_profile",
            niche_category="beauty",
            niche_confidence=0.75,
            language="pl",
            location="Warsaw",
            follower_count=15000,
            bio="Kosmetyczka",
            avg_er=3.5,
            profile_json='{"key": "value"}',
        )
        profile = self.repo.get_profile("full_profile")
        self.assertEqual(profile.follower_count, 15000)
        self.assertAlmostEqual(profile.avg_er, 3.5)
        self.assertEqual(profile.profile_json, '{"key": "value"}')


# ======================================================================
# Get Profiles By Niche
# ======================================================================


class TestGetProfilesByNiche(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = SourceProfileRepository(self.conn)
        # Insert profiles in different niches
        self.repo.upsert_profile(source_name="fit1", niche_category="fitness")
        self.repo.upsert_profile(source_name="fit2", niche_category="fitness")
        self.repo.upsert_profile(source_name="beauty1", niche_category="beauty")

    def tearDown(self):
        self.conn.close()

    def test_filters_by_niche(self):
        profiles = self.repo.get_profiles_by_niche("fitness")
        self.assertEqual(len(profiles), 2)
        names = {p.source_name for p in profiles}
        self.assertEqual(names, {"fit1", "fit2"})

    def test_returns_empty_for_unknown_niche(self):
        profiles = self.repo.get_profiles_by_niche("nonexistent")
        self.assertEqual(profiles, [])

    def test_respects_limit(self):
        profiles = self.repo.get_profiles_by_niche("fitness", limit=1)
        self.assertEqual(len(profiles), 1)


# ======================================================================
# Get All Profiles
# ======================================================================


class TestGetAllProfiles(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.repo = SourceProfileRepository(self.conn)
        self.repo.upsert_profile(source_name="alpha", niche_category="fitness")
        self.repo.upsert_profile(source_name="beta", niche_category="beauty")
        self.repo.upsert_profile(source_name="gamma", niche_category="food")

    def tearDown(self):
        self.conn.close()

    def test_returns_all(self):
        profiles = self.repo.get_all_profiles()
        self.assertEqual(len(profiles), 3)

    def test_respects_limit(self):
        profiles = self.repo.get_all_profiles(limit=2)
        self.assertEqual(len(profiles), 2)

    def test_ordered_by_source_name(self):
        profiles = self.repo.get_all_profiles()
        names = [p.source_name for p in profiles]
        self.assertEqual(names, ["alpha", "beta", "gamma"])


# ======================================================================
# Update FBR Stats
# ======================================================================


class TestUpdateFbrStats(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceProfileRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _insert_fbr_data(self, source_name: str, follow_count: int,
                         followback_count: int, fbr_percent: float,
                         is_quality: int = 0):
        """Insert an fbr_snapshot + fbr_source_results row."""
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO fbr_snapshots "
            "(account_id, device_id, username, analyzed_at, total_sources) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.account_id, "dev-001", "testuser", now, 1),
        )
        snapshot_id = cursor.lastrowid
        self.conn.execute(
            "INSERT INTO fbr_source_results "
            "(snapshot_id, source_name, follow_count, followback_count, fbr_percent, is_quality) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, source_name, follow_count, followback_count, fbr_percent, is_quality),
        )
        self.conn.commit()

    def test_aggregates_from_fbr_source_results(self):
        self._insert_fbr_data("source_a", 100, 20, 20.0, is_quality=1)
        self._insert_fbr_data("source_a", 50, 15, 30.0, is_quality=0)

        count = self.repo.update_fbr_stats()
        self.assertGreaterEqual(count, 1)

        stats = self.repo.get_fbr_stats("source_a")
        self.assertIsNotNone(stats)
        self.assertEqual(stats.source_name, "source_a")
        self.assertEqual(stats.total_follows, 150)       # 100 + 50
        self.assertEqual(stats.total_followbacks, 35)     # 20 + 15
        self.assertEqual(stats.quality_account_count, 1)  # 1 + 0
        # weighted_fbr_pct = 35/150 * 100 ≈ 23.33
        self.assertAlmostEqual(stats.weighted_fbr_pct, 35 / 150 * 100, places=1)

    def test_multiple_sources(self):
        self._insert_fbr_data("src_x", 200, 40, 20.0)
        self._insert_fbr_data("src_y", 100, 50, 50.0)

        count = self.repo.update_fbr_stats()
        self.assertEqual(count, 2)

        stats_x = self.repo.get_fbr_stats("src_x")
        stats_y = self.repo.get_fbr_stats("src_y")
        self.assertIsNotNone(stats_x)
        self.assertIsNotNone(stats_y)
        self.assertEqual(stats_x.total_follows, 200)
        self.assertEqual(stats_y.total_follows, 100)

    def test_no_data_returns_zero(self):
        count = self.repo.update_fbr_stats()
        # No fbr_source_results rows, so nothing upserted
        self.assertEqual(count, 0)


# ======================================================================
# Get FBR Stats
# ======================================================================


class TestGetFbrStats(unittest.TestCase):

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed_device_and_account(self.conn)
        self.repo = SourceProfileRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def test_returns_stats(self):
        now = datetime.now(timezone.utc).isoformat()
        cursor = self.conn.execute(
            "INSERT INTO fbr_snapshots "
            "(account_id, device_id, username, analyzed_at, total_sources) "
            "VALUES (?, ?, ?, ?, ?)",
            (self.account_id, "dev-001", "testuser", now, 1),
        )
        snapshot_id = cursor.lastrowid
        self.conn.execute(
            "INSERT INTO fbr_source_results "
            "(snapshot_id, source_name, follow_count, followback_count, fbr_percent, is_quality) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (snapshot_id, "tested_source", 80, 24, 30.0, 1),
        )
        self.conn.commit()

        self.repo.update_fbr_stats()
        stats = self.repo.get_fbr_stats("tested_source")
        self.assertIsNotNone(stats)
        self.assertEqual(stats.source_name, "tested_source")
        self.assertEqual(stats.total_follows, 80)
        self.assertEqual(stats.total_followbacks, 24)
        self.assertIsNotNone(stats.updated_at)

    def test_returns_none_for_missing(self):
        result = self.repo.get_fbr_stats("no_such_source")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
