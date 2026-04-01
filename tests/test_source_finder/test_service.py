"""
Unit tests for oh.services.source_finder_service — add_to_sources and accessors.

Uses in-memory SQLite with real repositories. Mocks are avoided where possible;
filesystem tests use tempdir.
"""
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from oh.db.migrations import run_migrations
from oh.models.source_finder import (
    SEARCH_COMPLETED,
    SourceCandidate,
    SourceSearchResult,
)
from oh.repositories.account_repo import AccountRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_search_repo import SourceSearchRepository
from oh.services.source_finder_service import SourceFinderService


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


def _seed(conn: sqlite3.Connection) -> int:
    """Seed device + account, return account_id."""
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


class TestAddToSources(unittest.TestCase):
    """SourceFinderService.add_to_sources with real filesystem in tempdir."""

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed(self.conn)

        self.search_repo = SourceSearchRepository(self.conn)
        self.account_repo = AccountRepository(self.conn)
        self.settings_repo = SettingsRepository(self.conn)
        self.settings_repo.seed_defaults()

        self.svc = SourceFinderService(
            self.search_repo, self.account_repo, self.settings_repo,
        )

        # Temp dir as bot_root with proper device/username structure
        self.tmpdir = tempfile.mkdtemp()
        self.acct_dir = Path(self.tmpdir) / "dev-001" / "testuser"
        self.acct_dir.mkdir(parents=True)

        # Create a completed search with candidate + result
        self.search = self.search_repo.create_search(self.account_id, "testuser")
        self.search_repo.complete_search(self.search.id, SEARCH_COMPLETED)

        cand = SourceCandidate(
            search_id=self.search.id, username="new_source", follower_count=5000,
        )
        self.search_repo.save_candidates(self.search.id, [cand])
        loaded_cands = self.search_repo.get_candidates(self.search.id)
        self.cand_id = loaded_cands[0].id

        result = SourceSearchResult(
            search_id=self.search.id, candidate_id=self.cand_id, rank=1,
        )
        self.search_repo.save_results(self.search.id, [result])
        self.results = self.search_repo.get_results(self.search.id)
        self.result_id = self.results[0].id

    def tearDown(self):
        self.conn.close()
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_creates_sources_txt_if_not_exists(self):
        sources_path = self.acct_dir / "sources.txt"
        self.assertFalse(sources_path.exists())

        status = self.svc.add_to_sources(self.result_id, self.account_id, self.tmpdir)
        self.assertEqual(status, SourceFinderService.ADD_OK)
        self.assertTrue(sources_path.exists())

        content = sources_path.read_text(encoding="utf-8")
        self.assertIn("new_source", content)

    def test_appends_to_existing_with_backup(self):
        sources_path = self.acct_dir / "sources.txt"
        sources_path.write_text("existing_source\n", encoding="utf-8")

        status = self.svc.add_to_sources(self.result_id, self.account_id, self.tmpdir)
        self.assertEqual(status, SourceFinderService.ADD_OK)

        content = sources_path.read_text(encoding="utf-8")
        self.assertIn("existing_source", content)
        self.assertIn("new_source", content)

        # Backup should exist
        bak_path = self.acct_dir / "sources.txt.bak"
        self.assertTrue(bak_path.exists())
        bak_content = bak_path.read_text(encoding="utf-8")
        self.assertIn("existing_source", bak_content)
        self.assertNotIn("new_source", bak_content)

    def test_returns_already_for_duplicate_case_insensitive(self):
        sources_path = self.acct_dir / "sources.txt"
        sources_path.write_text("New_Source\n", encoding="utf-8")

        status = self.svc.add_to_sources(self.result_id, self.account_id, self.tmpdir)
        self.assertEqual(status, SourceFinderService.ADD_ALREADY)

        # Content should NOT have a second entry
        content = sources_path.read_text(encoding="utf-8")
        lines = [ln.strip() for ln in content.strip().splitlines() if ln.strip()]
        self.assertEqual(len(lines), 1)

    def test_marks_result_in_db(self):
        self.svc.add_to_sources(self.result_id, self.account_id, self.tmpdir)
        results = self.search_repo.get_results(self.search.id)
        self.assertTrue(results[0].added_to_sources)
        self.assertIsNotNone(results[0].added_at)


class TestGetLatestSearchQuery(unittest.TestCase):
    """SourceFinderService.get_latest_search_query."""

    def setUp(self):
        self.conn = _create_db()
        self.account_id = _seed(self.conn)
        self.search_repo = SourceSearchRepository(self.conn)
        self.account_repo = AccountRepository(self.conn)
        self.settings_repo = SettingsRepository(self.conn)
        self.settings_repo.seed_defaults()
        self.svc = SourceFinderService(
            self.search_repo, self.account_repo, self.settings_repo,
        )

    def tearDown(self):
        self.conn.close()

    def test_returns_query_string(self):
        search = self.search_repo.create_search(self.account_id, "testuser")
        self.search_repo.update_search_query(search.id, "trener Gdansk")
        result = self.svc.get_latest_search_query(self.account_id)
        self.assertEqual(result, "trener Gdansk")

    def test_returns_none_when_no_search(self):
        result = self.svc.get_latest_search_query(9999)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
