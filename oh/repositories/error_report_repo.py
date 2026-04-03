"""
Read/write access to the error_reports table.

Error reports capture crashes and user-reported issues for remote
diagnostics.  Reports may be queued locally if the send fails and
retried on next startup.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Optional

from oh.models.error_report import ErrorReport

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class ErrorReportRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, report: ErrorReport) -> ErrorReport:
        """Insert a new error report. Returns report with id set."""
        cursor = self._conn.execute(
            """
            INSERT INTO error_reports (
                report_id, error_type, error_message, traceback,
                oh_version, os_version, python_version,
                db_stats, log_tail, user_note, sent_at, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                report.report_id,
                report.error_type,
                report.error_message,
                report.traceback,
                report.oh_version,
                report.os_version,
                report.python_version,
                report.db_stats,
                report.log_tail,
                report.user_note,
                report.sent_at,
                report.created_at or _utcnow(),
            ),
        )
        report.id = cursor.lastrowid
        self._conn.commit()
        return report

    def mark_sent(self, report_id: str) -> None:
        """Mark a report as successfully sent."""
        self._conn.execute(
            "UPDATE error_reports SET sent_at = ? WHERE report_id = ?",
            (_utcnow(), report_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_unsent(self) -> List[ErrorReport]:
        """Return reports that haven't been sent yet."""
        rows = self._conn.execute(
            """
            SELECT * FROM error_reports
            WHERE sent_at IS NULL
            ORDER BY id ASC
            """
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_recent(self, limit: int = 20) -> List[ErrorReport]:
        """Return recent reports, newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM error_reports
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> ErrorReport:
        return ErrorReport(
            id=row["id"],
            report_id=row["report_id"],
            error_type=row["error_type"],
            error_message=row["error_message"],
            traceback=row["traceback"],
            oh_version=row["oh_version"],
            os_version=row["os_version"],
            python_version=row["python_version"],
            db_stats=row["db_stats"],
            log_tail=row["log_tail"],
            user_note=row["user_note"],
            sent_at=row["sent_at"],
            created_at=row["created_at"],
        )
