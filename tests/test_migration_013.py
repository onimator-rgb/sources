"""
Integration test for Migration 013 — error_reports, block_events, account_groups.

Verifies all new tables exist with correct columns after migration.
"""
import sqlite3
import unittest

from oh.db.migrations import run_migrations


class TestMigration013(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        run_migrations(self.conn)

    def tearDown(self):
        self.conn.close()

    def _table_columns(self, table_name):
        rows = self.conn.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {r["name"] for r in rows}

    def _table_exists(self, table_name):
        row = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM sqlite_master WHERE type='table' AND name=?",
            (table_name,),
        ).fetchone()
        return row["cnt"] > 0

    def test_migration_13_applied(self):
        row = self.conn.execute(
            "SELECT * FROM schema_migrations WHERE version = 13"
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["name"], "error_reports_blocks_groups")

    # -- error_reports --

    def test_error_reports_table_exists(self):
        self.assertTrue(self._table_exists("error_reports"))

    def test_error_reports_columns(self):
        cols = self._table_columns("error_reports")
        expected = {
            "id", "report_id", "error_type", "error_message", "traceback",
            "oh_version", "os_version", "python_version", "db_stats",
            "log_tail", "user_note", "sent_at", "created_at",
        }
        self.assertTrue(expected.issubset(cols), f"Missing: {expected - cols}")

    def test_error_reports_unique_report_id(self):
        self.conn.execute(
            "INSERT INTO error_reports (report_id, error_type, created_at) VALUES (?, ?, ?)",
            ("id-1", "crash", "2026-01-01T00:00:00Z"),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO error_reports (report_id, error_type, created_at) VALUES (?, ?, ?)",
                ("id-1", "manual", "2026-01-01T00:00:00Z"),
            )

    # -- block_events --

    def test_block_events_table_exists(self):
        self.assertTrue(self._table_exists("block_events"))

    def test_block_events_columns(self):
        cols = self._table_columns("block_events")
        expected = {
            "id", "account_id", "event_type", "detected_at",
            "evidence", "resolved_at", "auto_detected",
        }
        self.assertTrue(expected.issubset(cols), f"Missing: {expected - cols}")

    def test_block_events_foreign_key(self):
        # Insert without valid account_id should fail
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO block_events (account_id, event_type, detected_at) VALUES (?, ?, ?)",
                (99999, "action_block", "2026-01-01T00:00:00Z"),
            )
            self.conn.commit()

    # -- account_groups --

    def test_account_groups_table_exists(self):
        self.assertTrue(self._table_exists("account_groups"))

    def test_account_groups_columns(self):
        cols = self._table_columns("account_groups")
        expected = {"id", "name", "color", "description", "created_at", "updated_at"}
        self.assertTrue(expected.issubset(cols))

    def test_account_groups_unique_name(self):
        now = "2026-01-01T00:00:00Z"
        self.conn.execute(
            "INSERT INTO account_groups (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("GroupA", now, now),
        )
        with self.assertRaises(sqlite3.IntegrityError):
            self.conn.execute(
                "INSERT INTO account_groups (name, created_at, updated_at) VALUES (?, ?, ?)",
                ("GroupA", now, now),
            )

    # -- account_group_members --

    def test_account_group_members_table_exists(self):
        self.assertTrue(self._table_exists("account_group_members"))

    def test_account_group_members_columns(self):
        cols = self._table_columns("account_group_members")
        expected = {"id", "group_id", "account_id", "added_at"}
        self.assertTrue(expected.issubset(cols))

    def test_cascade_delete_group_removes_members(self):
        now = "2026-01-01T00:00:00Z"
        # Create device + account
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
        acc_id = self.conn.execute("SELECT id FROM oh_accounts WHERE username='u1'").fetchone()["id"]

        # Create group + member
        self.conn.execute(
            "INSERT INTO account_groups (name, created_at, updated_at) VALUES (?, ?, ?)",
            ("G1", now, now),
        )
        gid = self.conn.execute("SELECT id FROM account_groups WHERE name='G1'").fetchone()["id"]
        self.conn.execute(
            "INSERT INTO account_group_members (group_id, account_id, added_at) VALUES (?, ?, ?)",
            (gid, acc_id, now),
        )
        self.conn.commit()

        # Delete group
        self.conn.execute("DELETE FROM account_groups WHERE id = ?", (gid,))
        self.conn.commit()

        # Members should be gone
        cnt = self.conn.execute(
            "SELECT COUNT(*) as cnt FROM account_group_members WHERE group_id = ?", (gid,)
        ).fetchone()["cnt"]
        self.assertEqual(cnt, 0)

    # -- all 13 migrations applied --

    def test_all_migrations_applied(self):
        rows = self.conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version"
        ).fetchall()
        versions = [r["version"] for r in rows]
        self.assertEqual(versions, list(range(1, 17)))


if __name__ == "__main__":
    unittest.main()
