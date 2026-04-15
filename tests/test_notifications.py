"""
Comprehensive tests for the Notifications feature.

Covers:
  - Model: classify_notification(), NOTIFICATION_TYPES
  - Module: NotificationReader (read_all, get_distinct_*)
  - Service: NotificationService (load, filter options, CSV export)
"""
import csv
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import List


from oh.models.notification import (
    NOTIFICATION_TYPES,
    NotificationRecord,
    classify_notification,
)
from oh.modules.notification_reader import NotificationReader
from oh.services.notification_service import NotificationService


# =========================================================================
# 1. Model tests — classify_notification
# =========================================================================


class TestClassifyNotification(unittest.TestCase):
    """Test keyword-based notification classification."""

    def test_added(self):
        self.assertEqual(classify_notification("Account Added"), "Added")

    def test_deleted(self):
        self.assertEqual(classify_notification("Account Deleted"), "Deleted")

    def test_removed_maps_to_deleted(self):
        self.assertEqual(classify_notification("Account Removed"), "Deleted")

    def test_login_successful(self):
        self.assertEqual(classify_notification("Login successful"), "Login")

    def test_logged_in(self):
        self.assertEqual(classify_notification("Logged in"), "Login")

    def test_action_block(self):
        self.assertEqual(classify_notification("Action Block"), "Block")

    def test_suspended(self):
        self.assertEqual(
            classify_notification("Account Suspended xyz"), "Suspended"
        )

    def test_error_occurred(self):
        self.assertEqual(classify_notification("Error occurred"), "Error")

    def test_exception_in_module(self):
        self.assertEqual(
            classify_notification("Exception in module"), "Error"
        )

    def test_failed_to_connect(self):
        self.assertEqual(
            classify_notification("Failed to connect"), "Error"
        )

    def test_unknown_text_returns_other(self):
        self.assertEqual(
            classify_notification("Random unknown text"), "Other"
        )

    def test_empty_string_returns_other(self):
        self.assertEqual(classify_notification(""), "Other")

    def test_case_insensitivity(self):
        self.assertEqual(classify_notification("account added"), "Added")
        self.assertEqual(classify_notification("ACCOUNT ADDED"), "Added")
        self.assertEqual(classify_notification("aCcOuNt AdDeD"), "Added")
        self.assertEqual(classify_notification("login SUCCESSFUL"), "Login")
        self.assertEqual(classify_notification("ACTION BLOCK"), "Block")
        self.assertEqual(classify_notification("error OCCURRED"), "Error")

    def test_keyword_embedded_in_longer_text(self):
        self.assertEqual(
            classify_notification("Something Added to the list"), "Added"
        )
        self.assertEqual(
            classify_notification("User has been Suspended permanently"),
            "Suspended",
        )

    def test_first_match_wins(self):
        # "Added" should match before "Deleted" even if both present
        self.assertEqual(
            classify_notification("Added and Deleted"), "Added"
        )


# =========================================================================
# 2. Model tests — NOTIFICATION_TYPES
# =========================================================================


class TestNotificationTypes(unittest.TestCase):
    """Validate the NOTIFICATION_TYPES mapping."""

    EXPECTED_TYPES = {"Added", "Deleted", "Login", "Block", "Suspended", "Error", "Other"}

    def test_all_seven_types_present(self):
        self.assertEqual(set(NOTIFICATION_TYPES.keys()), self.EXPECTED_TYPES)

    def test_all_keys_are_strings(self):
        for key in NOTIFICATION_TYPES:
            self.assertIsInstance(key, str)

    def test_all_values_are_strings(self):
        for value in NOTIFICATION_TYPES.values():
            self.assertIsInstance(value, str)

    def test_all_color_keys_are_non_empty(self):
        for key, color in NOTIFICATION_TYPES.items():
            self.assertTrue(len(color) > 0, f"Color for {key} is empty")

    def test_known_color_mappings(self):
        self.assertEqual(NOTIFICATION_TYPES["Added"], "success")
        self.assertEqual(NOTIFICATION_TYPES["Deleted"], "critical")
        self.assertEqual(NOTIFICATION_TYPES["Login"], "link")
        self.assertEqual(NOTIFICATION_TYPES["Block"], "high")
        self.assertEqual(NOTIFICATION_TYPES["Suspended"], "warning")
        self.assertEqual(NOTIFICATION_TYPES["Error"], "error")
        self.assertEqual(NOTIFICATION_TYPES["Other"], "muted")


# =========================================================================
# Helper — create a notificationdatabase.db in a temp directory
# =========================================================================


def _create_notification_db(
    directory: str,
    rows: List[tuple],
) -> str:
    """
    Create a notificationdatabase.db in *directory* with the given rows.

    Each row is (deviceid, account, notification, date, time).
    Returns the path to the database file.
    """
    db_path = os.path.join(directory, "notificationdatabase.db")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE notifications (
            deviceid   TEXT,
            account    TEXT,
            notification TEXT,
            date       TEXT,
            time       TEXT
        )
        """
    )
    conn.executemany(
        "INSERT INTO notifications (deviceid, account, notification, date, time) "
        "VALUES (?, ?, ?, ?, ?)",
        rows,
    )
    conn.commit()
    conn.close()
    return db_path


# =========================================================================
# 3. Module tests — NotificationReader
# =========================================================================


class TestNotificationReaderReadAll(unittest.TestCase):
    """Test NotificationReader.read_all() with real SQLite databases."""

    def test_read_all_returns_correct_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("dev1", "user_a", "Account Added", "2026-04-15", "10:00:00"),
                ("dev1", "user_b", "Action Block", "2026-04-15", "10:05:00"),
                ("dev2", None, "Login successful", "2026-04-14", "09:00:00"),
            ]
            _create_notification_db(tmpdir, rows)

            reader = NotificationReader(tmpdir)
            records = reader.read_all()

            self.assertEqual(len(records), 3)

    def test_read_all_classification(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("d1", "u1", "Account Added", "2026-04-15", "10:00:00"),
                ("d1", "u2", "Account Deleted", "2026-04-15", "10:01:00"),
                ("d1", "u3", "Error occurred", "2026-04-15", "10:02:00"),
            ]
            _create_notification_db(tmpdir, rows)

            reader = NotificationReader(tmpdir)
            records = reader.read_all()

            types = {r.notification: r.notification_type for r in records}
            self.assertEqual(types["Account Added"], "Added")
            self.assertEqual(types["Account Deleted"], "Deleted")
            self.assertEqual(types["Error occurred"], "Error")

    def test_read_all_record_fields(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("dev-abc", "alice", "Login successful", "2026-04-15", "12:30:00"),
            ]
            _create_notification_db(tmpdir, rows)

            reader = NotificationReader(tmpdir)
            records = reader.read_all()

            self.assertEqual(len(records), 1)
            rec = records[0]
            self.assertEqual(rec.device_id, "dev-abc")
            self.assertIsNone(rec.device_name)  # not enriched by reader
            self.assertEqual(rec.account, "alice")
            self.assertEqual(rec.notification, "Login successful")
            self.assertEqual(rec.date, "2026-04-15")
            self.assertEqual(rec.time, "12:30:00")
            self.assertEqual(rec.notification_type, "Login")

    def test_read_all_missing_db_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            reader = NotificationReader(tmpdir)
            records = reader.read_all()
            self.assertEqual(records, [])

    def test_read_all_empty_db_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _create_notification_db(tmpdir, [])
            reader = NotificationReader(tmpdir)
            records = reader.read_all()
            self.assertEqual(records, [])

    def test_read_all_null_account_becomes_none(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("dev1", None, "Some notification", "2026-04-15", "08:00:00"),
            ]
            _create_notification_db(tmpdir, rows)

            reader = NotificationReader(tmpdir)
            records = reader.read_all()
            self.assertEqual(len(records), 1)
            self.assertIsNone(records[0].account)

    def test_read_all_order_newest_first(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("d1", "u1", "Old", "2026-04-10", "08:00:00"),
                ("d1", "u1", "New", "2026-04-15", "12:00:00"),
                ("d1", "u1", "Mid", "2026-04-12", "10:00:00"),
            ]
            _create_notification_db(tmpdir, rows)

            reader = NotificationReader(tmpdir)
            records = reader.read_all()

            dates = [r.date for r in records]
            self.assertEqual(dates, ["2026-04-15", "2026-04-12", "2026-04-10"])


class TestNotificationReaderDistinctHelpers(unittest.TestCase):
    """Test static helper methods on NotificationReader."""

    def _make_records(self) -> List[NotificationRecord]:
        return [
            NotificationRecord("dev1", "Device 1", "alice", "Account Added", "2026-04-15", "10:00", "Added"),
            NotificationRecord("dev1", "Device 1", "bob", "Action Block", "2026-04-15", "10:01", "Block"),
            NotificationRecord("dev2", "Device 2", "alice", "Login successful", "2026-04-15", "10:02", "Login"),
            NotificationRecord("dev2", "Device 2", None, "Error occurred", "2026-04-15", "10:03", "Error"),
            NotificationRecord("dev3", "Device 3", "charlie", "Account Added", "2026-04-15", "10:04", "Added"),
        ]

    def test_get_distinct_types(self):
        records = self._make_records()
        types = NotificationReader.get_distinct_types(records)
        self.assertEqual(types, ["Added", "Block", "Error", "Login"])

    def test_get_distinct_types_empty(self):
        self.assertEqual(NotificationReader.get_distinct_types([]), [])

    def test_get_distinct_devices(self):
        records = self._make_records()
        devices = NotificationReader.get_distinct_devices(records)
        self.assertEqual(devices, ["dev1", "dev2", "dev3"])

    def test_get_distinct_devices_empty(self):
        self.assertEqual(NotificationReader.get_distinct_devices([]), [])

    def test_get_distinct_accounts_excludes_none(self):
        records = self._make_records()
        accounts = NotificationReader.get_distinct_accounts(records)
        self.assertEqual(accounts, ["alice", "bob", "charlie"])
        self.assertNotIn(None, accounts)

    def test_get_distinct_accounts_empty(self):
        self.assertEqual(NotificationReader.get_distinct_accounts([]), [])

    def test_get_distinct_accounts_all_none(self):
        records = [
            NotificationRecord("d1", None, None, "Test", "2026-04-15", "10:00", "Other"),
        ]
        self.assertEqual(NotificationReader.get_distinct_accounts(records), [])


# =========================================================================
# 4. Service tests — NotificationService
# =========================================================================


class TestNotificationService(unittest.TestCase):
    """Test NotificationService orchestration."""

    def _make_conn(self, device_rows=None):
        """Create an in-memory DB with oh_devices table."""
        conn = sqlite3.connect(":memory:")
        conn.execute(
            "CREATE TABLE oh_devices ("
            "  device_id TEXT PRIMARY KEY,"
            "  device_name TEXT,"
            "  first_discovered_at TEXT,"
            "  last_synced_at TEXT"
            ")"
        )
        if device_rows:
            conn.executemany(
                "INSERT INTO oh_devices (device_id, device_name, first_discovered_at, last_synced_at) "
                "VALUES (?, ?, ?, ?)",
                device_rows,
            )
            conn.commit()
        return conn

    def test_load_notifications_returns_records(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("dev1", "alice", "Account Added", "2026-04-15", "10:00:00"),
                ("dev1", "bob", "Error occurred", "2026-04-15", "10:01:00"),
            ]
            _create_notification_db(tmpdir, rows)

            conn = self._make_conn()
            service = NotificationService(conn)
            records = service.load_notifications(tmpdir)

            self.assertEqual(len(records), 2)
            conn.close()

    def test_load_notifications_enriches_device_names(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rows = [
                ("dev1", "alice", "Account Added", "2026-04-15", "10:00:00"),
            ]
            _create_notification_db(tmpdir, rows)

            conn = self._make_conn(
                device_rows=[("dev1", "My Phone", "2026-01-01", "2026-04-15")]
            )
            service = NotificationService(conn)
            records = service.load_notifications(tmpdir)

            self.assertEqual(len(records), 1)
            self.assertEqual(records[0].device_name, "My Phone")
            conn.close()

    def test_load_notifications_missing_db_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            conn = self._make_conn()
            service = NotificationService(conn)
            records = service.load_notifications(tmpdir)
            self.assertEqual(records, [])
            conn.close()

    def test_get_filter_options_structure(self):
        conn = self._make_conn()
        service = NotificationService(conn)

        records = [
            NotificationRecord("dev1", "D1", "alice", "Account Added", "2026-04-15", "10:00", "Added"),
            NotificationRecord("dev2", "D2", "bob", "Error occurred", "2026-04-15", "10:01", "Error"),
            NotificationRecord("dev1", "D1", None, "Login successful", "2026-04-15", "10:02", "Login"),
        ]

        opts = service.get_filter_options(records)

        self.assertIn("devices", opts)
        self.assertIn("types", opts)
        self.assertIn("accounts", opts)

        self.assertEqual(opts["devices"], ["dev1", "dev2"])
        self.assertEqual(opts["types"], ["Added", "Error", "Login"])
        self.assertEqual(opts["accounts"], ["alice", "bob"])
        conn.close()

    def test_get_filter_options_empty_records(self):
        conn = self._make_conn()
        service = NotificationService(conn)
        opts = service.get_filter_options([])

        self.assertEqual(opts["devices"], [])
        self.assertEqual(opts["types"], [])
        self.assertEqual(opts["accounts"], [])
        conn.close()

    def test_export_csv_writes_valid_file(self):
        conn = self._make_conn()
        service = NotificationService(conn)

        records = [
            NotificationRecord("dev1", "My Phone", "alice", "Account Added", "2026-04-15", "10:00:00", "Added"),
            NotificationRecord("dev2", None, "bob", "Error occurred", "2026-04-15", "10:01:00", "Error"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "export.csv")
            service.export_csv(records, csv_path)

            with open(csv_path, "r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                rows = list(reader)

            # Header row
            self.assertEqual(
                rows[0],
                ["Device", "Account", "Notification", "Type", "Date", "Time"],
            )
            # Data rows
            self.assertEqual(len(rows), 3)  # header + 2 data

            # First record: device_name present
            self.assertEqual(rows[1][0], "My Phone")
            self.assertEqual(rows[1][1], "alice")
            self.assertEqual(rows[1][2], "Account Added")
            self.assertEqual(rows[1][3], "Added")
            self.assertEqual(rows[1][4], "2026-04-15")
            self.assertEqual(rows[1][5], "10:00:00")

            # Second record: device_name is None, falls back to device_id
            self.assertEqual(rows[2][0], "dev2")
            self.assertEqual(rows[2][1], "bob")

        conn.close()

    def test_export_csv_empty_records(self):
        conn = self._make_conn()
        service = NotificationService(conn)

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "empty.csv")
            service.export_csv([], csv_path)

            with open(csv_path, "r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                rows = list(reader)

            # Only header, no data rows
            self.assertEqual(len(rows), 1)
            self.assertEqual(
                rows[0],
                ["Device", "Account", "Notification", "Type", "Date", "Time"],
            )

        conn.close()

    def test_export_csv_none_account_becomes_empty_string(self):
        conn = self._make_conn()
        service = NotificationService(conn)

        records = [
            NotificationRecord("dev1", "D1", None, "System event", "2026-04-15", "08:00:00", "Other"),
        ]

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "out.csv")
            service.export_csv(records, csv_path)

            with open(csv_path, "r", encoding="utf-8", newline="") as fh:
                reader = csv.reader(fh)
                rows = list(reader)

            self.assertEqual(rows[1][1], "")  # account column

        conn.close()


if __name__ == "__main__":
    unittest.main()
