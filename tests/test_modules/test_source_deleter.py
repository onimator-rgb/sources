"""
Tests for oh/modules/source_deleter.py — file-level source removal with backup.

Covers:
  - Single source removal from sources.txt
  - Case-insensitive matching
  - Backup (.bak) creation before modification
  - File content correctness after deletion
  - Edge cases: missing file, empty file, source not found, duplicates, whitespace
  - Error handling: permission errors, backup failures
"""
import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from oh.modules.source_deleter import SourceDeleter, SourceDeleteFileResult


class SourceDeleterTestBase(unittest.TestCase):
    """Base class that creates a temp bot directory structure."""

    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.device_id = "device_001"
        self.username = "testuser"
        self.device_name = "Test Device"
        self.account_dir = Path(self.tmp_dir) / self.device_id / self.username
        self.account_dir.mkdir(parents=True, exist_ok=True)
        self.sources_path = self.account_dir / "sources.txt"
        self.deleter = SourceDeleter(self.tmp_dir)

    def tearDown(self):
        # Ensure all files are writable before cleanup (needed after permission tests)
        for root, dirs, files in os.walk(self.tmp_dir):
            for f in files:
                fp = os.path.join(root, f)
                os.chmod(fp, stat.S_IRUSR | stat.S_IWUSR)
        shutil.rmtree(self.tmp_dir)

    def _write_sources(self, lines, trailing_newline=True):
        """Helper to write sources.txt with given lines."""
        content = "\n".join(lines)
        if trailing_newline:
            content += "\n"
        self.sources_path.write_text(content, encoding="utf-8")

    def _read_sources(self):
        """Helper to read sources.txt lines."""
        return self.sources_path.read_text(encoding="utf-8").splitlines()


class TestRemoveSourceBasic(SourceDeleterTestBase):
    """Core functionality: removing a source from sources.txt."""

    def test_remove_single_source(self):
        """Remove one source, others remain."""
        self._write_sources(["alpha", "beta", "gamma"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertTrue(result.backed_up)
        self.assertIsNone(result.error)
        self.assertEqual(self._read_sources(), ["alpha", "gamma"])

    def test_remove_first_source(self):
        """Remove the first source in the file."""
        self._write_sources(["alpha", "beta", "gamma"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["beta", "gamma"])

    def test_remove_last_source(self):
        """Remove the last source in the file."""
        self._write_sources(["alpha", "beta", "gamma"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "gamma"
        )
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["alpha", "beta"])

    def test_result_dataclass_fields(self):
        """Result carries correct username and device_name."""
        self._write_sources(["source1"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "source1"
        )
        self.assertEqual(result.username, self.username)
        self.assertEqual(result.device_name, self.device_name)

    def test_trailing_newline_preserved(self):
        """If the original file ended with newline, so does the new one."""
        self._write_sources(["alpha", "beta", "gamma"], trailing_newline=True)
        self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        content = self.sources_path.read_text(encoding="utf-8")
        self.assertTrue(content.endswith("\n"))

    def test_no_trailing_newline_preserved(self):
        """If the original file had no trailing newline, neither does the new one."""
        self._write_sources(["alpha", "beta", "gamma"], trailing_newline=False)
        self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        content = self.sources_path.read_text(encoding="utf-8")
        self.assertFalse(content.endswith("\n"))


class TestCaseInsensitiveMatching(SourceDeleterTestBase):
    """Source matching must be case-insensitive."""

    def test_lowercase_target_uppercase_file(self):
        self._write_sources(["ALPHA", "beta"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["beta"])

    def test_uppercase_target_lowercase_file(self):
        self._write_sources(["alpha", "beta"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "ALPHA"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["beta"])

    def test_mixed_case(self):
        self._write_sources(["AlPhA", "beta"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "aLpHa"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)


class TestBackupCreation(SourceDeleterTestBase):
    """Backup (.bak) file is created before any modification."""

    def test_backup_file_created(self):
        self._write_sources(["alpha", "beta"])
        self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        bak_path = self.account_dir / "sources.txt.bak"
        self.assertTrue(bak_path.exists())

    def test_backup_contains_original_content(self):
        original_lines = ["alpha", "beta", "gamma"]
        self._write_sources(original_lines)
        self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "beta"
        )
        bak_path = self.account_dir / "sources.txt.bak"
        bak_content = bak_path.read_text(encoding="utf-8")
        self.assertEqual(bak_content.splitlines(), original_lines)

    def test_no_backup_when_source_not_found(self):
        """If source isn't in the file, no backup is created."""
        self._write_sources(["alpha", "beta"])
        self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "nonexistent"
        )
        bak_path = self.account_dir / "sources.txt.bak"
        self.assertFalse(bak_path.exists())


class TestEdgeCases(SourceDeleterTestBase):
    """Edge cases that must not crash."""

    def test_source_not_found(self):
        """Source not in file returns found=False, no error."""
        self._write_sources(["alpha", "beta"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "nonexistent"
        )
        self.assertFalse(result.found)
        self.assertFalse(result.removed)
        self.assertFalse(result.backed_up)
        self.assertIsNone(result.error)
        # File unchanged
        self.assertEqual(self._read_sources(), ["alpha", "beta"])

    def test_empty_sources_file(self):
        """Empty sources.txt — source not found, no crash."""
        self.sources_path.write_text("", encoding="utf-8")
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "anything"
        )
        self.assertFalse(result.found)
        self.assertFalse(result.removed)

    def test_sources_file_does_not_exist(self):
        """sources.txt missing — returns error, no crash."""
        # Don't create sources.txt
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "anything"
        )
        self.assertFalse(result.found)
        self.assertFalse(result.removed)
        self.assertFalse(result.backed_up)
        self.assertIn("not found", result.error)

    def test_only_target_source_in_file(self):
        """File has only the target source — file becomes empty after removal."""
        self._write_sources(["only_source"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "only_source"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        remaining = self.sources_path.read_text(encoding="utf-8").strip()
        self.assertEqual(remaining, "")

    def test_duplicate_entries_all_removed(self):
        """All duplicate entries of the target source are removed."""
        self._write_sources(["alpha", "beta", "alpha", "gamma", "alpha"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["beta", "gamma"])

    def test_whitespace_in_source_lines(self):
        """Lines with leading/trailing whitespace still match."""
        self.sources_path.write_text("  alpha  \nbeta\n  gamma  \n", encoding="utf-8")
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "alpha"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        remaining = self.sources_path.read_text(encoding="utf-8").splitlines()
        # Only beta and gamma should remain
        self.assertEqual(len(remaining), 2)

    def test_whitespace_in_target_name(self):
        """Target name with whitespace is stripped before matching."""
        self._write_sources(["alpha", "beta"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "  alpha  "
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)

    def test_unicode_source_names(self):
        """Unicode source names work correctly."""
        self._write_sources(["caf\u00e9_account", "normal_source", "\u00fc\u00f1\u00ee\u00e7\u00f6d\u00e9"])
        result = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "caf\u00e9_account"
        )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertEqual(self._read_sources(), ["normal_source", "\u00fc\u00f1\u00ee\u00e7\u00f6d\u00e9"])


class TestErrorHandling(SourceDeleterTestBase):
    """Error handling: permission errors, backup failures."""

    def test_permission_error_on_write(self):
        """If sources.txt cannot be written, result has error."""
        self._write_sources(["alpha", "beta"])
        with patch.object(Path, "write_text", side_effect=OSError("Permission denied")):
            result = self.deleter.remove_source(
                self.device_id, self.username, self.device_name, "alpha"
            )
        # The source was found but could not be removed
        self.assertTrue(result.found)
        self.assertFalse(result.removed)
        self.assertIsNotNone(result.error)
        self.assertIn("Cannot write", result.error)

    def test_backup_failure_does_not_abort_removal(self):
        """Backup failure is non-fatal — removal still proceeds."""
        self._write_sources(["alpha", "beta"])

        original_write_text = Path.write_text

        def mock_write(path_self, data, *args, **kwargs):
            if path_self.name == "sources.txt.bak":
                raise OSError("Disk full")
            return original_write_text(path_self, data, *args, **kwargs)

        with patch.object(Path, "write_text", mock_write):
            result = self.deleter.remove_source(
                self.device_id, self.username, self.device_name, "alpha"
            )
        self.assertTrue(result.found)
        self.assertTrue(result.removed)
        self.assertFalse(result.backed_up)

    def test_read_error(self):
        """If sources.txt cannot be read, result has error."""
        self._write_sources(["alpha"])
        with patch.object(Path, "read_text", side_effect=OSError("I/O error")):
            result = self.deleter.remove_source(
                self.device_id, self.username, self.device_name, "alpha"
            )
        self.assertFalse(result.found)
        self.assertFalse(result.removed)
        self.assertIn("Cannot read", result.error)


class TestMultipleAccounts(SourceDeleterTestBase):
    """Same source removed from multiple accounts independently."""

    def test_remove_from_two_accounts(self):
        """Removing a source from one account doesn't affect another."""
        user2 = "user2"
        user2_dir = Path(self.tmp_dir) / self.device_id / user2
        user2_dir.mkdir(parents=True, exist_ok=True)
        sources2 = user2_dir / "sources.txt"

        self._write_sources(["shared_source", "unique_a"])
        sources2.write_text("shared_source\nunique_b\n", encoding="utf-8")

        result1 = self.deleter.remove_source(
            self.device_id, self.username, self.device_name, "shared_source"
        )
        result2 = self.deleter.remove_source(
            self.device_id, user2, "Device 2", "shared_source"
        )

        self.assertTrue(result1.removed)
        self.assertTrue(result2.removed)
        self.assertEqual(self._read_sources(), ["unique_a"])
        self.assertEqual(sources2.read_text(encoding="utf-8").splitlines(), ["unique_b"])


if __name__ == "__main__":
    unittest.main()
