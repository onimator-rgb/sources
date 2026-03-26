"""CRUD access to sync_runs and sync_events tables."""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.sync import SyncRun, SyncSummary

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create_run(self, triggered_by: str = "manual") -> SyncRun:
        now = _utcnow()
        cursor = self._conn.execute(
            "INSERT INTO sync_runs (started_at, status, triggered_by) VALUES (?, 'running', ?)",
            (now, triggered_by),
        )
        self._conn.commit()
        return SyncRun(id=cursor.lastrowid, started_at=now, triggered_by=triggered_by)

    def complete_run(self, run_id: int, summary: SyncSummary) -> None:
        self._conn.execute(
            """
            UPDATE sync_runs SET
                status='completed', completed_at=?,
                devices_scanned=?, accounts_scanned=?,
                accounts_added=?, accounts_removed=?,
                accounts_updated=?, accounts_unchanged=?
            WHERE id=?
            """,
            (
                _utcnow(),
                summary.devices_scanned, summary.accounts_scanned,
                summary.accounts_added, summary.accounts_removed,
                summary.accounts_updated, summary.accounts_unchanged,
                run_id,
            ),
        )
        self._conn.commit()

    def fail_run(self, run_id: int, error_message: str) -> None:
        self._conn.execute(
            "UPDATE sync_runs SET status='failed', completed_at=?, error_message=? WHERE id=?",
            (_utcnow(), error_message, run_id),
        )
        self._conn.commit()

    def record_event(
        self,
        sync_run_id: int,
        event_type: str,
        device_id: str,
        username: str,
        account_id: Optional[int] = None,
        changed_fields: Optional[str] = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO sync_events
                (sync_run_id, event_type, device_id, username,
                 account_id, changed_fields, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (sync_run_id, event_type, device_id, username,
             account_id, changed_fields, _utcnow()),
        )
        self._conn.commit()

    def get_run_history(self, limit: int = 20) -> list:
        rows = self._conn.execute(
            "SELECT * FROM sync_runs ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [self._run_from_row(r) for r in rows]

    def get_latest_run(self) -> Optional[SyncRun]:
        row = self._conn.execute(
            "SELECT * FROM sync_runs WHERE status='completed' ORDER BY started_at DESC LIMIT 1"
        ).fetchone()
        return self._run_from_row(row) if row else None

    def recover_stale_runs(self) -> int:
        """Mark any 'running' rows as failed — handles app crash recovery."""
        cursor = self._conn.execute(
            """
            UPDATE sync_runs
            SET status='failed', completed_at=?,
                error_message='Recovered: process was interrupted before completion'
            WHERE status='running'
            """,
            (_utcnow(),),
        )
        self._conn.commit()
        return cursor.rowcount

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> SyncRun:
        return SyncRun(
            id=row["id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            triggered_by=row["triggered_by"],
            devices_scanned=row["devices_scanned"],
            accounts_scanned=row["accounts_scanned"],
            accounts_added=row["accounts_added"],
            accounts_removed=row["accounts_removed"],
            accounts_updated=row["accounts_updated"],
            accounts_unchanged=row["accounts_unchanged"],
            error_message=row["error_message"],
        )
