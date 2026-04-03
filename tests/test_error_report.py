"""
Unit tests for Phase 10 Feature A — Remote Error Reporting.

Covers: ErrorReport model, ErrorReportRepository, ErrorReportService.
"""
import json
import sqlite3
import unittest
from datetime import datetime, timezone
from unittest.mock import patch, MagicMock

from oh.db.migrations import run_migrations
from oh.models.error_report import (
    ErrorReport, ERROR_TYPE_CRASH, ERROR_TYPE_MANUAL, ERROR_TYPE_STARTUP_FAIL,
)
from oh.repositories.error_report_repo import ErrorReportRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.services.error_report_service import ErrorReportService


def _create_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    run_migrations(conn)
    return conn


# -----------------------------------------------------------------------
# Model tests
# -----------------------------------------------------------------------

class TestErrorReportModel(unittest.TestCase):
    def test_create_crash_report(self):
        r = ErrorReport(
            report_id="abc-123",
            error_type=ERROR_TYPE_CRASH,
            oh_version="1.0.1",
            os_version="Windows 11",
            python_version="3.9.13",
            created_at="2026-04-03T12:00:00Z",
            error_message="ZeroDivisionError: division by zero",
        )
        self.assertEqual(r.error_type, "crash")
        self.assertIsNone(r.id)
        self.assertIsNone(r.sent_at)

    def test_create_manual_report(self):
        r = ErrorReport(
            report_id="def-456",
            error_type=ERROR_TYPE_MANUAL,
            oh_version="1.0.1",
            os_version="Windows 10",
            python_version="3.9.13",
            created_at="2026-04-03T12:00:00Z",
            user_note="App freezes when clicking Scan",
        )
        self.assertEqual(r.error_type, "manual")
        self.assertEqual(r.user_note, "App freezes when clicking Scan")

    def test_constants(self):
        self.assertEqual(ERROR_TYPE_CRASH, "crash")
        self.assertEqual(ERROR_TYPE_MANUAL, "manual")
        self.assertEqual(ERROR_TYPE_STARTUP_FAIL, "startup_fail")


# -----------------------------------------------------------------------
# Repository tests
# -----------------------------------------------------------------------

class TestErrorReportRepo(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.repo = ErrorReportRepository(self.conn)

    def tearDown(self):
        self.conn.close()

    def _make_report(self, report_id="test-001", error_type=ERROR_TYPE_CRASH):
        return ErrorReport(
            report_id=report_id,
            error_type=error_type,
            oh_version="1.0.1",
            os_version="Windows 11",
            python_version="3.9.13",
            created_at="2026-04-03T12:00:00Z",
            error_message="Test error",
        )

    def test_save_and_get_recent(self):
        r = self._make_report()
        saved = self.repo.save(r)
        self.assertIsNotNone(saved.id)

        recent = self.repo.get_recent(10)
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].report_id, "test-001")
        self.assertEqual(recent[0].error_type, ERROR_TYPE_CRASH)

    def test_get_unsent(self):
        r1 = self._make_report("unsent-1")
        r2 = self._make_report("unsent-2")
        self.repo.save(r1)
        self.repo.save(r2)

        unsent = self.repo.get_unsent()
        self.assertEqual(len(unsent), 2)

    def test_mark_sent(self):
        r = self._make_report("mark-sent-test")
        self.repo.save(r)

        self.repo.mark_sent("mark-sent-test")

        unsent = self.repo.get_unsent()
        self.assertEqual(len(unsent), 0)

        recent = self.repo.get_recent(10)
        self.assertIsNotNone(recent[0].sent_at)

    def test_save_with_all_fields(self):
        r = ErrorReport(
            report_id="full-fields",
            error_type=ERROR_TYPE_MANUAL,
            oh_version="1.0.1",
            os_version="Win 11",
            python_version="3.9.13",
            created_at="2026-04-03T12:00:00Z",
            error_message="Test",
            traceback="Traceback...",
            db_stats='{"devices": 5}',
            log_tail="Last log line",
            user_note="User description",
        )
        saved = self.repo.save(r)
        recent = self.repo.get_recent(1)
        self.assertEqual(recent[0].db_stats, '{"devices": 5}')
        self.assertEqual(recent[0].user_note, "User description")
        self.assertEqual(recent[0].traceback, "Traceback...")

    def test_unique_report_id(self):
        r1 = self._make_report("dup-id")
        self.repo.save(r1)
        r2 = self._make_report("dup-id")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.save(r2)


# -----------------------------------------------------------------------
# Service tests
# -----------------------------------------------------------------------

class TestErrorReportService(unittest.TestCase):
    def setUp(self):
        self.conn = _create_db()
        self.repo = ErrorReportRepository(self.conn)
        self.settings = SettingsRepository(self.conn)
        self.settings.seed_defaults()
        self.service = ErrorReportService(
            report_repo=self.repo,
            settings_repo=self.settings,
            conn=self.conn,
        )

    def tearDown(self):
        self.conn.close()

    def test_capture_crash(self):
        try:
            1 / 0
        except ZeroDivisionError:
            import sys
            exc_type, exc_value, exc_tb = sys.exc_info()
            report = self.service.capture_crash(exc_type, exc_value, exc_tb)

        self.assertEqual(report.error_type, ERROR_TYPE_CRASH)
        self.assertIn("ZeroDivisionError", report.error_message)
        self.assertIn("ZeroDivisionError", report.traceback)
        self.assertIsNotNone(report.oh_version)
        self.assertIsNotNone(report.os_version)
        self.assertIsNotNone(report.id)

    def test_capture_manual(self):
        report = self.service.capture_manual("Something broke")
        self.assertEqual(report.error_type, ERROR_TYPE_MANUAL)
        self.assertEqual(report.user_note, "Something broke")
        self.assertIsNotNone(report.id)

    def test_send_report_no_endpoint(self):
        report = self.service.capture_manual("test")
        result = self.service.send_report(report)
        self.assertFalse(result)  # no endpoint configured

    def test_retry_unsent_empty(self):
        count = self.service.retry_unsent()
        self.assertEqual(count, 0)

    def test_build_payload_format(self):
        report = self.service.capture_manual("test payload")
        payload = self.service._build_payload(report)

        self.assertIn("content", payload)
        self.assertIn("embeds", payload)
        self.assertEqual(len(payload["embeds"]), 1)

        embed = payload["embeds"][0]
        self.assertIn("title", embed)
        self.assertIn("fields", embed)
        field_names = [f["name"] for f in embed["fields"]]
        self.assertIn("Version", field_names)
        self.assertIn("OS", field_names)

    def test_db_stats_collected(self):
        stats = self.service._get_db_stats()
        self.assertIn("devices", stats)
        self.assertIn("accounts", stats)
        self.assertEqual(stats["devices"], 0)
        self.assertEqual(stats["accounts"], 0)

    def test_auto_send_enabled_default(self):
        self.assertTrue(self.service.auto_send_enabled())

    def test_auto_send_disabled(self):
        self.settings.set("auto_send_crashes", "0")
        self.assertFalse(self.service.auto_send_enabled())


if __name__ == "__main__":
    unittest.main()
