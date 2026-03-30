"""
Read/write access to the operator_actions audit table.

Every operator-initiated change (review flag, tag, TB/limits increment)
is logged here.  The table is append-only; rows are never modified.
"""
import sqlite3
import logging
from datetime import datetime, timezone

from oh.models.operator_action import OperatorActionRecord

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperatorActionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def log_action(self, record: OperatorActionRecord) -> int:
        """Insert an audit row. Returns the new row id."""
        cursor = self._conn.execute(
            """
            INSERT INTO operator_actions (
                account_id, username, device_id, action_type,
                old_value, new_value, note,
                performed_at, machine
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.account_id,
                record.username,
                record.device_id,
                record.action_type,
                record.old_value,
                record.new_value,
                record.note,
                record.performed_at or _utcnow(),
                record.machine,
            ),
        )
        self._conn.commit()
        return cursor.lastrowid

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_recent(self, limit: int = 100) -> list[OperatorActionRecord]:
        """Return recent actions, newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM operator_actions
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_for_account(
        self, account_id: int
    ) -> list[OperatorActionRecord]:
        """Return all actions for one account, newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM operator_actions
            WHERE account_id = ?
            ORDER BY id DESC
            """,
            (account_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> OperatorActionRecord:
        return OperatorActionRecord(
            id=row["id"],
            account_id=row["account_id"],
            username=row["username"],
            device_id=row["device_id"],
            action_type=row["action_type"],
            old_value=row["old_value"],
            new_value=row["new_value"],
            note=row["note"],
            performed_at=row["performed_at"],
            machine=row["machine"],
        )
