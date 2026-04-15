"""
Comprehensive tests for the Enhanced Settings Copier feature.

Covers:
  - Model layer (settings_copy.py): categories, keys, dataclasses
  - Module layer (settings_copier.py): nested helpers, read/write settings, text files
  - Migration 017: lbr_snapshots, lbr_source_results, like_source_assignments tables
"""
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from oh.models.settings_copy import (
    ALL_COPYABLE_KEYS,
    COPYABLE_SETTINGS,
    COPYABLE_TEXT_FILES,
    SETTINGS_CATEGORIES,
    SettingDef,
    SettingsCategory,
    SettingsCopyBatchResult,
    SettingsCopyResult,
    SettingsDiff,
    SettingsDiffEntry,
    SettingsSnapshot,
)
from oh.modules.settings_copier import (
    SettingsCopierModule,
    _get_nested,
    _set_nested,
)
from oh.db.migrations import run_migrations


# ============================================================================
# 1. Model tests — settings_copy.py
# ============================================================================


class TestSettingsCategories(unittest.TestCase):
    """Tests for SETTINGS_CATEGORIES structure."""

    def test_exactly_9_categories(self):
        self.assertEqual(len(SETTINGS_CATEGORIES), 9)

    def test_category_names(self):
        expected_names = [
            "Follow", "Unfollow", "Like", "Story", "Reels",
            "DM", "Share", "Post", "Human Behavior",
        ]
        actual_names = [cat.name for cat in SETTINGS_CATEGORIES]
        self.assertEqual(actual_names, expected_names)

    def test_category_keys(self):
        expected_keys = [
            "follow", "unfollow", "like", "story", "reels",
            "dm", "share", "post", "human_behavior",
        ]
        actual_keys = [cat.key for cat in SETTINGS_CATEGORIES]
        self.assertEqual(actual_keys, expected_keys)

    def test_all_categories_have_settings(self):
        for cat in SETTINGS_CATEGORIES:
            self.assertGreater(
                len(cat.settings), 0,
                f"Category '{cat.name}' has no settings",
            )

    def test_every_setting_is_setting_def(self):
        for cat in SETTINGS_CATEGORIES:
            for sd in cat.settings:
                self.assertIsInstance(sd, SettingDef, f"{cat.name}/{sd}")


class TestAllCopyableKeys(unittest.TestCase):
    """Tests for ALL_COPYABLE_KEYS aggregated set."""

    def test_is_a_set(self):
        self.assertIsInstance(ALL_COPYABLE_KEYS, set)

    def test_has_over_100_entries(self):
        self.assertGreater(len(ALL_COPYABLE_KEYS), 100)

    def test_all_category_keys_in_all_copyable_keys(self):
        for cat in SETTINGS_CATEGORIES:
            for sd in cat.settings:
                self.assertIn(
                    sd.key, ALL_COPYABLE_KEYS,
                    f"Key '{sd.key}' from category '{cat.name}' not in ALL_COPYABLE_KEYS",
                )

    def test_all_legacy_keys_in_all_copyable_keys(self):
        for key in COPYABLE_SETTINGS:
            self.assertIn(
                key, ALL_COPYABLE_KEYS,
                f"Legacy key '{key}' not in ALL_COPYABLE_KEYS",
            )

    def test_no_empty_keys(self):
        for key in ALL_COPYABLE_KEYS:
            self.assertTrue(len(key) > 0, "Found an empty key in ALL_COPYABLE_KEYS")

    def test_no_trailing_dots(self):
        for key in ALL_COPYABLE_KEYS:
            self.assertFalse(
                key.endswith("."),
                f"Key '{key}' has trailing dot",
            )


class TestCopyableTextFiles(unittest.TestCase):
    """Tests for COPYABLE_TEXT_FILES list."""

    def test_has_4_entries(self):
        self.assertEqual(len(COPYABLE_TEXT_FILES), 4)

    def test_entries_are_tuples(self):
        for entry in COPYABLE_TEXT_FILES:
            self.assertIsInstance(entry, tuple)
            self.assertEqual(len(entry), 2)

    def test_filenames_end_with_txt(self):
        for filename, _display in COPYABLE_TEXT_FILES:
            self.assertTrue(
                filename.endswith(".txt"),
                f"Text file '{filename}' should end with .txt",
            )

    def test_display_names_not_empty(self):
        for _filename, display in COPYABLE_TEXT_FILES:
            self.assertTrue(len(display) > 0)


class TestDataclasses(unittest.TestCase):
    """Tests for dataclass instantiation."""

    def test_setting_def(self):
        sd = SettingDef(key="foo.bar", display_name="Foo Bar")
        self.assertEqual(sd.key, "foo.bar")
        self.assertEqual(sd.display_name, "Foo Bar")

    def test_settings_category(self):
        sd = SettingDef(key="k1", display_name="Key One")
        cat = SettingsCategory(name="Test", key="test", settings=[sd])
        self.assertEqual(cat.name, "Test")
        self.assertEqual(cat.key, "test")
        self.assertEqual(len(cat.settings), 1)

    def test_settings_snapshot_defaults(self):
        snap = SettingsSnapshot(
            account_id=1, username="u", device_id="d",
            device_name=None, values={},
        )
        self.assertIsNone(snap.raw_json)
        self.assertIsNone(snap.error)
        self.assertIsNone(snap.text_files)

    def test_settings_diff_entry(self):
        entry = SettingsDiffEntry(
            key="k", display_name="K",
            source_value=10, target_value=20,
            is_different=True,
        )
        self.assertTrue(entry.is_different)

    def test_settings_diff(self):
        diff = SettingsDiff(
            target_account_id=1, target_username="u",
            target_device_name=None, entries=[], different_count=5,
        )
        self.assertEqual(diff.different_count, 5)

    def test_settings_copy_result(self):
        result = SettingsCopyResult(
            target_account_id=1, target_username="u",
            target_device_name=None, success=True,
            backed_up=True, keys_written=["k1"],
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_settings_copy_batch_result(self):
        batch = SettingsCopyBatchResult(
            source_username="src", total_targets=3,
            success_count=2, fail_count=1, results=[],
        )
        self.assertEqual(batch.total_targets, 3)


# ============================================================================
# 2. Module tests — nested JSON helpers
# ============================================================================


class TestGetNested(unittest.TestCase):
    """Tests for _get_nested helper."""

    def test_flat_key(self):
        self.assertEqual(_get_nested({"foo": 1}, "foo"), 1)

    def test_dot_path(self):
        self.assertEqual(_get_nested({"a": {"b": 3}}, "a.b"), 3)

    def test_missing_key_returns_none(self):
        self.assertIsNone(_get_nested({"a": 1}, "b"))

    def test_missing_nested_key_returns_none(self):
        self.assertIsNone(_get_nested({"a": {"b": 1}}, "a.c"))

    def test_deep_path_3_levels(self):
        data = {"x": {"y": {"z": 42}}}
        self.assertEqual(_get_nested(data, "x.y.z"), 42)

    def test_intermediate_not_dict_returns_none(self):
        data = {"a": "string_not_dict"}
        self.assertIsNone(_get_nested(data, "a.b"))

    def test_empty_dict(self):
        self.assertIsNone(_get_nested({}, "anything"))

    def test_returns_boolean_false(self):
        data = {"flag": False}
        self.assertIs(_get_nested(data, "flag"), False)

    def test_returns_zero(self):
        data = {"count": 0}
        self.assertEqual(_get_nested(data, "count"), 0)

    def test_returns_nested_dict(self):
        data = {"a": {"b": {"c": 1}}}
        result = _get_nested(data, "a.b")
        self.assertEqual(result, {"c": 1})


class TestSetNested(unittest.TestCase):
    """Tests for _set_nested helper."""

    def test_flat_key(self):
        d = {}
        _set_nested(d, "foo", 42)
        self.assertEqual(d, {"foo": 42})

    def test_dot_path_creates_intermediate_dicts(self):
        d = {}
        _set_nested(d, "a.b.c", 99)
        self.assertEqual(d, {"a": {"b": {"c": 99}}})

    def test_preserves_other_keys(self):
        d = {"a": {"existing": 1}}
        _set_nested(d, "a.new_key", 2)
        self.assertEqual(d["a"]["existing"], 1)
        self.assertEqual(d["a"]["new_key"], 2)

    def test_overwrites_existing_value(self):
        d = {"k": "old"}
        _set_nested(d, "k", "new")
        self.assertEqual(d["k"], "new")

    def test_overwrites_nested_value(self):
        d = {"a": {"b": "old"}}
        _set_nested(d, "a.b", "new")
        self.assertEqual(d["a"]["b"], "new")

    def test_replaces_non_dict_intermediate(self):
        d = {"a": "not_a_dict"}
        _set_nested(d, "a.b", 1)
        self.assertEqual(d["a"]["b"], 1)

    def test_set_boolean(self):
        d = {}
        _set_nested(d, "flag", True)
        self.assertTrue(d["flag"])

    def test_set_list_value(self):
        d = {}
        _set_nested(d, "items", [1, 2, 3])
        self.assertEqual(d["items"], [1, 2, 3])


# ============================================================================
# 3. Module tests — read/write settings (requires temp bot structure)
# ============================================================================


class _BotStructureMixin:
    """Mixin to create/tear down a temp bot directory with settings.db."""

    device_id = "test-device-001"
    username = "testuser"

    def _create_bot_structure(self, settings_json: dict):
        """Create temp dir with device_id/username/settings.db."""
        self.tmp_dir = tempfile.mkdtemp()
        acct_dir = Path(self.tmp_dir) / self.device_id / self.username
        acct_dir.mkdir(parents=True)

        db_path = acct_dir / "settings.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE accountsettings (id INTEGER PRIMARY KEY, settings TEXT)"
        )
        conn.execute(
            "INSERT INTO accountsettings (settings) VALUES (?)",
            (json.dumps(settings_json),),
        )
        conn.commit()
        conn.close()

        self.module = SettingsCopierModule(self.tmp_dir)
        return acct_dir

    def _cleanup_bot_structure(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)


class TestReadSettings(unittest.TestCase, _BotStructureMixin):
    """Tests for SettingsCopierModule.read_settings()."""

    def setUp(self):
        self.settings_json = {
            "follow_enabled": True,
            "default_action_limit_perday": 50,
            "filters": {
                "min_posts": 5,
                "max_posts": 500,
            },
            "non_copyable_key": "should_not_appear",
        }
        self._create_bot_structure(self.settings_json)

    def tearDown(self):
        self._cleanup_bot_structure()

    def test_reads_flat_key(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertEqual(snap.values.get("follow_enabled"), True)
        self.assertEqual(snap.values.get("default_action_limit_perday"), 50)

    def test_reads_nested_key(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertEqual(snap.values.get("filters.min_posts"), 5)
        self.assertEqual(snap.values.get("filters.max_posts"), 500)

    def test_missing_key_not_in_values(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertNotIn("non_copyable_key", snap.values)

    def test_no_error_on_valid_db(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertIsNone(snap.error)

    def test_returns_raw_json(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertIsNotNone(snap.raw_json)
        self.assertEqual(snap.raw_json["non_copyable_key"], "should_not_appear")

    def test_missing_db_returns_error(self):
        snap = self.module.read_settings("nonexistent", "nobody")
        self.assertIsNotNone(snap.error)
        self.assertIn("not found", snap.error)
        self.assertEqual(snap.values, {})

    def test_snapshot_metadata(self):
        snap = self.module.read_settings(
            self.device_id, self.username,
            device_name="MyDevice", account_id=42,
        )
        self.assertEqual(snap.device_id, self.device_id)
        self.assertEqual(snap.username, self.username)
        self.assertEqual(snap.device_name, "MyDevice")
        self.assertEqual(snap.account_id, 42)


class TestReadSettingsEmptyDB(unittest.TestCase, _BotStructureMixin):
    """Tests read_settings with an empty accountsettings table."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        acct_dir = Path(self.tmp_dir) / self.device_id / self.username
        acct_dir.mkdir(parents=True)
        db_path = acct_dir / "settings.db"
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE accountsettings (id INTEGER PRIMARY KEY, settings TEXT)"
        )
        conn.commit()
        conn.close()
        self.module = SettingsCopierModule(self.tmp_dir)

    def tearDown(self):
        self._cleanup_bot_structure()

    def test_empty_table_returns_error(self):
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertIsNotNone(snap.error)
        self.assertIn("empty", snap.error)


class TestWriteSettings(unittest.TestCase, _BotStructureMixin):
    """Tests for SettingsCopierModule.write_settings()."""

    def setUp(self):
        self.initial_json = {
            "follow_enabled": False,
            "default_action_limit_perday": 10,
            "some_other_key": "preserve_me",
            "filters": {
                "min_posts": 1,
                "max_posts": 100,
                "other_filter": True,
            },
        }
        self.acct_dir = self._create_bot_structure(self.initial_json)

    def tearDown(self):
        self._cleanup_bot_structure()

    def test_writes_flat_key(self):
        result = self.module.write_settings(
            self.device_id, self.username,
            {"follow_enabled": True},
        )
        self.assertTrue(result.success)
        self.assertIn("follow_enabled", result.keys_written)

        # Verify in DB
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertEqual(snap.values["follow_enabled"], True)

    def test_writes_nested_key(self):
        result = self.module.write_settings(
            self.device_id, self.username,
            {"filters.min_posts": 10},
        )
        self.assertTrue(result.success)

        snap = self.module.read_settings(self.device_id, self.username)
        self.assertEqual(snap.values["filters.min_posts"], 10)

    def test_creates_backup_file(self):
        self.module.write_settings(
            self.device_id, self.username,
            {"follow_enabled": True},
        )
        bak_path = self.acct_dir / "settings.db.bak"
        self.assertTrue(bak_path.exists(), "Backup file should be created")

    def test_backup_flag_set(self):
        result = self.module.write_settings(
            self.device_id, self.username,
            {"follow_enabled": True},
        )
        self.assertTrue(result.backed_up)

    def test_rejects_invalid_keys(self):
        result = self.module.write_settings(
            self.device_id, self.username,
            {"totally_invalid_key": 999},
        )
        self.assertFalse(result.success)
        self.assertIn("Invalid keys", result.error)
        self.assertEqual(result.keys_written, [])

    def test_preserves_other_keys_in_json(self):
        self.module.write_settings(
            self.device_id, self.username,
            {"follow_enabled": True},
        )
        # Read raw JSON to verify non-copyable keys survived
        snap = self.module.read_settings(self.device_id, self.username)
        self.assertEqual(snap.raw_json["some_other_key"], "preserve_me")

    def test_preserves_sibling_nested_keys(self):
        self.module.write_settings(
            self.device_id, self.username,
            {"filters.min_posts": 50},
        )
        snap = self.module.read_settings(self.device_id, self.username)
        # other_filter is not in ALL_COPYABLE_KEYS so won't be in values,
        # but should still be in raw_json
        self.assertTrue(snap.raw_json["filters"]["other_filter"])

    def test_missing_db_returns_error(self):
        result = self.module.write_settings(
            "nonexistent", "nobody",
            {"follow_enabled": True},
        )
        self.assertFalse(result.success)
        self.assertIn("not found", result.error)

    def test_multiple_keys_at_once(self):
        updates = {
            "follow_enabled": True,
            "default_action_limit_perday": 100,
            "filters.min_posts": 20,
        }
        result = self.module.write_settings(
            self.device_id, self.username, updates,
        )
        self.assertTrue(result.success)
        self.assertEqual(len(result.keys_written), 3)

    def test_result_metadata(self):
        result = self.module.write_settings(
            self.device_id, self.username,
            {"follow_enabled": True},
            device_name="Dev1", account_id=7,
        )
        self.assertEqual(result.target_account_id, 7)
        self.assertEqual(result.target_username, self.username)
        self.assertEqual(result.target_device_name, "Dev1")


# ============================================================================
# 4. Module tests — text files
# ============================================================================


class TestReadTextFiles(unittest.TestCase, _BotStructureMixin):
    """Tests for SettingsCopierModule.read_text_files()."""

    def setUp(self):
        self.acct_dir = self._create_bot_structure({"follow_enabled": True})
        # Create some text files
        (self.acct_dir / "name_must_include.txt").write_text(
            "keyword1\nkeyword2", encoding="utf-8"
        )
        (self.acct_dir / "name_must_not_include.txt").write_text(
            "badword", encoding="utf-8"
        )

    def tearDown(self):
        self._cleanup_bot_structure()

    def test_reads_existing_files(self):
        result = self.module.read_text_files(self.device_id, self.username)
        self.assertEqual(result["name_must_include.txt"], "keyword1\nkeyword2")
        self.assertEqual(result["name_must_not_include.txt"], "badword")

    def test_returns_none_for_missing_files(self):
        result = self.module.read_text_files(self.device_id, self.username)
        self.assertIsNone(result["name_must_include_likes.txt"])
        self.assertIsNone(result["name_must_not_include_likes.txt"])

    def test_returns_all_4_keys(self):
        result = self.module.read_text_files(self.device_id, self.username)
        expected_filenames = {fn for fn, _dn in COPYABLE_TEXT_FILES}
        self.assertEqual(set(result.keys()), expected_filenames)


class TestWriteTextFiles(unittest.TestCase, _BotStructureMixin):
    """Tests for SettingsCopierModule.write_text_files()."""

    def setUp(self):
        self.acct_dir = self._create_bot_structure({"follow_enabled": True})
        # Pre-create one file
        (self.acct_dir / "name_must_include.txt").write_text(
            "old_content", encoding="utf-8"
        )

    def tearDown(self):
        self._cleanup_bot_structure()

    def test_writes_new_content(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {"name_must_include.txt": "new_content"},
        )
        self.assertIn("name_must_include.txt", written)
        content = (self.acct_dir / "name_must_include.txt").read_text(encoding="utf-8")
        self.assertEqual(content, "new_content")

    def test_creates_backup(self):
        self.module.write_text_files(
            self.device_id, self.username,
            {"name_must_include.txt": "new_content"},
        )
        bak_path = self.acct_dir / "name_must_include.txt.bak"
        self.assertTrue(bak_path.exists(), "Backup should be created")
        bak_content = bak_path.read_text(encoding="utf-8")
        self.assertEqual(bak_content, "old_content")

    def test_skips_identical_content(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {"name_must_include.txt": "old_content"},
        )
        self.assertNotIn("name_must_include.txt", written)

    def test_skips_none_content(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {"name_must_include.txt": None},
        )
        self.assertEqual(written, [])

    def test_rejects_non_copyable_filename(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {"evil_script.txt": "malicious content"},
        )
        self.assertEqual(written, [])
        self.assertFalse(
            (self.acct_dir / "evil_script.txt").exists(),
            "Non-copyable file should not be created",
        )

    def test_writes_to_new_file_without_backup(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {"name_must_include_likes.txt": "likes_keywords"},
        )
        self.assertIn("name_must_include_likes.txt", written)
        content = (self.acct_dir / "name_must_include_likes.txt").read_text(
            encoding="utf-8"
        )
        self.assertEqual(content, "likes_keywords")
        # No backup for a file that didn't exist before
        self.assertFalse(
            (self.acct_dir / "name_must_include_likes.txt.bak").exists()
        )

    def test_multiple_files_at_once(self):
        written = self.module.write_text_files(
            self.device_id, self.username,
            {
                "name_must_include.txt": "updated",
                "name_must_not_include.txt": "new_exclusion",
            },
        )
        self.assertEqual(len(written), 2)


# ============================================================================
# 5. Migration 017 — LBR tables
# ============================================================================


class TestMigration017(unittest.TestCase):
    """Tests that migration 017 creates the LBR and like_source_assignments tables."""

    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        run_migrations(self.conn)

    def tearDown(self):
        self.conn.close()

    def _table_exists(self, table_name: str) -> bool:
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM sqlite_master "
            "WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row["cnt"] > 0

    def _table_columns(self, table_name: str) -> set:
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {r["name"] for r in rows}

    def test_migration_17_applied(self):
        row = self.conn.execute(
            "SELECT * FROM schema_migrations WHERE version = 17"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "lbr_tables")

    # -- lbr_snapshots --

    def test_lbr_snapshots_table_exists(self):
        self.assertTrue(self._table_exists("lbr_snapshots"))

    def test_lbr_snapshots_columns(self):
        cols = self._table_columns("lbr_snapshots")
        expected = {
            "id", "account_id", "device_id", "username", "analyzed_at",
            "min_likes", "min_lbr_pct", "total_sources", "quality_sources",
            "status", "best_lbr_pct", "best_lbr_source",
            "highest_vol_source", "highest_vol_count",
            "below_volume_count", "anomaly_count",
            "warnings_json", "schema_error",
        }
        self.assertTrue(
            expected.issubset(cols),
            f"Missing columns: {expected - cols}",
        )

    # -- lbr_source_results --

    def test_lbr_source_results_table_exists(self):
        self.assertTrue(self._table_exists("lbr_source_results"))

    def test_lbr_source_results_columns(self):
        cols = self._table_columns("lbr_source_results")
        expected = {
            "id", "snapshot_id", "source_name",
            "like_count", "followback_count", "lbr_percent",
            "is_quality", "anomaly",
        }
        self.assertTrue(
            expected.issubset(cols),
            f"Missing columns: {expected - cols}",
        )

    # -- like_source_assignments --

    def test_like_source_assignments_table_exists(self):
        self.assertTrue(self._table_exists("like_source_assignments"))

    def test_like_source_assignments_columns(self):
        cols = self._table_columns("like_source_assignments")
        expected = {
            "id", "account_id", "source_name", "is_active",
            "snapshot_id", "updated_at", "created_at",
        }
        self.assertTrue(
            expected.issubset(cols),
            f"Missing columns: {expected - cols}",
        )

    def test_like_source_assignments_unique_constraint(self):
        """account_id + source_name should be unique."""
        now = "2026-04-15T00:00:00Z"
        # Create device + account first (FK constraint)
        self.conn.execute(
            "INSERT INTO oh_devices (device_id, device_name, first_discovered_at, last_synced_at) "
            "VALUES (?, ?, ?, ?)",
            ("d1", "Dev1", now, now),
        )
        self.conn.execute(
            "INSERT INTO oh_accounts (device_id, username, discovered_at, last_seen_at) "
            "VALUES (?, ?, ?, ?)",
            ("d1", "u1", now, now),
        )
        acc_id = self.conn.execute(
            "SELECT id FROM oh_accounts WHERE username='u1'"
        ).fetchone()["id"]

        self.conn.execute(
            "INSERT INTO like_source_assignments (account_id, source_name, created_at) "
            "VALUES (?, ?, ?)",
            (acc_id, "source_a", now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO like_source_assignments (account_id, source_name, created_at) "
                "VALUES (?, ?, ?)",
                (acc_id, "source_a", now),
            )

    def test_lbr_source_results_fk(self):
        """snapshot_id should reference lbr_snapshots."""
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO lbr_source_results (snapshot_id, source_name) "
                "VALUES (?, ?)",
                (99999, "src"),
            )
            self.conn.commit()


if __name__ == "__main__":
    unittest.main()
