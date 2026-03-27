"""
Read/write access to source_delete_actions and source_delete_items tables.

Every destructive source operation must be logged here before the UI
reports success to the operator.
"""
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.delete_history import DeleteAction, DeleteItem

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class DeleteHistoryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_action(
        self,
        action: DeleteAction,
        items: list[DeleteItem],
    ) -> int:
        """
        Insert the action header and all item rows atomically.
        Sets action.id and item.action_id.  Returns action.id.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO source_delete_actions (
                deleted_at, delete_type, scope,
                total_sources, total_accounts_affected,
                threshold_pct, machine, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                action.deleted_at or _utcnow(),
                action.delete_type,
                action.scope,
                action.total_sources,
                action.total_accounts_affected,
                action.threshold_pct,
                action.machine,
                action.notes,
            ),
        )
        action_id = cursor.lastrowid
        action.id = action_id

        if items:
            self._conn.executemany(
                """
                INSERT INTO source_delete_items (
                    action_id, source_name, affected_accounts_json,
                    files_removed, files_not_found, files_failed, errors_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        action_id,
                        item.source_name,
                        json.dumps(item.affected_accounts),
                        item.files_removed,
                        item.files_not_found,
                        item.files_failed,
                        json.dumps(item.errors) if item.errors else None,
                    )
                    for item in items
                ],
            )

        self._conn.commit()
        return action_id

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_recent_actions(self, limit: int = 100) -> list[DeleteAction]:
        """Returns recent actions without items (for the history list view)."""
        rows = self._conn.execute(
            """
            SELECT * FROM source_delete_actions
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._action_from_row(r) for r in rows]

    def get_items_for_action(self, action_id: int) -> list[DeleteItem]:
        rows = self._conn.execute(
            """
            SELECT * FROM source_delete_items
            WHERE action_id = ?
            ORDER BY source_name ASC
            """,
            (action_id,),
        ).fetchall()
        return [self._item_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _action_from_row(row: sqlite3.Row) -> DeleteAction:
        return DeleteAction(
            id=row["id"],
            deleted_at=row["deleted_at"],
            delete_type=row["delete_type"],
            scope=row["scope"],
            total_sources=row["total_sources"],
            total_accounts_affected=row["total_accounts_affected"],
            threshold_pct=row["threshold_pct"],
            machine=row["machine"],
            notes=row["notes"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> DeleteItem:
        return DeleteItem(
            id=row["id"],
            action_id=row["action_id"],
            source_name=row["source_name"],
            affected_accounts=json.loads(row["affected_accounts_json"] or "[]"),
            files_removed=row["files_removed"],
            files_not_found=row["files_not_found"],
            files_failed=row["files_failed"],
            errors=json.loads(row["errors_json"]) if row["errors_json"] else [],
        )
