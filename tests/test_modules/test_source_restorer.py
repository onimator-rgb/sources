"""
Tests for oh/modules/source_restorer.py — file-level source restoration.

Covers:
  - Adding a source back to sources.txt
  - Duplicate detection (don't add if already present)
  - File creation when sources.txt doesn't exist
  - Backup creation before modification
  - Invalid source name rejection
  - Error handling
"""
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oh.modules.source_restorer import SourceRestorer, SourceRestoreFileResult


class SourceRestorerTestBase(unittest.TestCase):
    """Base class that creates a temp bot directory structure."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.device_id = "device_001"
        self.username = "testuser"
        self.device_name = "Test Device"
        self.account_dir = Path(self.tmp_dir) / self.device_id / self.username
        self.account_dir.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.account_dir / "sources.txt"
        self.restorer = SourceRestorer(self.tmp_dir)

    def tearDown(self):
        for root, dirs, files in os.walk(self.tmp_dir):
            for f in files:
                fp = os.path.join(root, f)
                os.chmod(fp, stat.S_IRUSR | stat.S_IWUSR)
        shutil.rmtree(self.tmp_dir)

    def _write_sources(self, lines, trailing_newline=True):
        content = "\n".join(lines)
        if trailing_newline:
            content += "\n"
        self.sources_path.write_text(content, encoding="utf-8")

    def _read_sources(self):
        return self.sources_path.read_text(encoding="utf-8").splitlines()


class TestRestoreBasic(SourceRestorerTestBase):
    """Core functionality: restoring a source to sources.txt."""

    def test_restore_adds_source(self):
        """Restoring a source adds it to the end of the file."""
        self._write_sources(["alpha", "beta"])
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "gamma"
        )
        self.assertTrue(result.restored)
        self.assertFalse(result.already_present)
        self.assertIsNone(result.error)
        self.assertIn("gamma", self._read_sources())

    def test_restore_result_fields(self):
        """Result carries correct username and device_name."""
        self._write_sources(["alpha"])
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        self.assertEqual(result.username, self.username)
        self.assertEqual(result.device_name, self.device_name)

    def test_restored_source_appended_at_end(self):
        """New source appears after existing ones."""
        self._write_sources(["alpha", "beta"])
        self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "gamma"
        )
        lines = self._read_sources()
        self.assertEqual(lines[-1], "gamma")


class TestDuplicateDetection(SourceRestorerTestBase):
    """Don't add source if already present (case-insensitive)."""

    def test_already_present_exact_match(self):
        self._write_sources(["alpha", "beta"])
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertFalse(result.restored)
        self.assertTrue(result.already_present)
        # File unchanged
        self.assertEqual(self._read_sources(), ["alpha", "beta"])

    def test_already_present_case_insensitive(self):
        self._write_sources(["Alpha", "beta"])
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertFalse(result.restored)
        self.assertTrue(result.already_present)

    def test_already_present_whitespace_stripped(self):
        self.sources_path.write_text("  alpha  \nbeta\n", encoding="utf-8")
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertFalse(result.restored)
        self.assertTrue(result.already_present)


class TestFileCreation(SourceRestorerTestBase):
    """sources.txt is created if it doesn't exist."""

    def test_creates_file_if_missing(self):
        """Restoring to a nonexistent file creates it."""
        # Don't create sources.txt
        self.assertFalse(self.sources_path.exists())
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "new_source"
        )
        self.assertTrue(result.restored)
        self.assertTrue(self.sources_path.exists())
        self.assertEqual(self._read_sources(), ["new_source"])

    def test_creates_parent_dirs_if_missing(self):
        """If account directory doesn't exist, it's created too."""
        new_user = "brand_new_user"
        new_path = Path(self.tmp_dir) / self.device_id / new_user / "sources.txt"
        self.assertFalse(new_path.exists())
        result = self.restorer.restore_source(
            self.device_id, new_user, self.device_name, "new_source"
        )
        self.assertTrue(result.restored)
        self.assertTrue(new_path.exists())

    def test_no_backup_when_file_is_new(self):
        """No backup is created when the file didn't exist before."""
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "new_source"
        )
        self.assertTrue(result.restored)
        self.assertFalse(result.backed_up)
        bak_path = self.account_dir / "sources.txt.bak"
        self.assertFalse(bak_path.exists())


class TestBackup(SourceRestorerTestBase):
    """Backup is created before modifying an existing file."""

    def test_backup_created_on_existing_file(self):
        self._write_sources(["alpha"])
        self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        bak_path = self.account_dir / "sources.txt.bak"
        self.assertTrue(bak_path.exists())

    def test_backup_contains_pre_modification_content(self):
        self._write_sources(["alpha"])
        self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        bak_path = self.account_dir / "sources.txt.bak"
        bak_lines = bak_path.read_text(encoding="utf-8").splitlines()
        self.assertEqual(bak_lines, ["alpha"])

    def test_backed_up_flag_set(self):
        self._write_sources(["alpha"])
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        self.assertTrue(result.backed_up)


class TestInvalidSourceNames(SourceRestorerTestBase):
    """Invalid source names are rejected."""

    def test_reject_source_with_spaces(self):
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "has space"
        )
        self.assertFalse(result.restored)
        self.assertIn("Invalid", result.error)

    def test_reject_source_with_special_chars(self):
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "user@name"
        )
        self.assertFalse(result.restored)
        self.assertIn("Invalid", result.error)

    def test_accept_dots_underscores_alphanumeric(self):
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "user_name.123"
        )
        self.assertTrue(result.restored)


class TestRestoreErrorHandling(SourceRestorerTestBase):
    """Error conditions."""

    def test_read_error(self):
        self._write_sources(["alpha"])
        with patch.object(Path, "read_text", side_effect=OSError("I/O error")):
            result = self.restorer.restore_source(
                self.device_id, self.username, self.device_name, "beta"
            )
        self.assertFalse(result.restored)
        self.assertIn("Cannot read", result.error)

    def test_write_error(self):
        self._write_sources(["alpha"])

        original_write_text = Path.write_text

        def mock_write(path_self, data, *args, **kwargs):
            if path_self.name == "sources.txt":
                raise OSError("Disk full")
            return original_write_text(path_self, data, *args, **kwargs)

        with patch.object(Path, "write_text", mock_write):
            result = self.restorer.restore_source(
                self.device_id, self.username, self.device_name, "beta"
            )
        self.assertFalse(result.restored)
        self.assertIn("Cannot write", result.error)

    def test_restore_to_empty_file(self):
        """Restoring to an empty file works."""
        self.sources_path.write_text("", encoding="utf-8")
        result = self.restorer.restore_source(
            self.device_id, self.username, self.device_name, "new_source"
        )
        self.assertTrue(result.restored)
        self.assertIn("new_source", self._read_sources())


if __name__ == "__main__":
    unittest.main()
