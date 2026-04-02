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
                threshold_pct, machine, notes,
                status, revert_of_action_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                action.status or "completed",
                action.revert_of_action_id,
            ),
        )
        action_id = cursor.lastrowid
        action.id = action_id

        if items:
            self._conn.executemany(
                """
                INSERT INTO source_delete_items (
                    action_id, source_name, affected_accounts_json,
                    files_removed, files_not_found, files_failed, errors_json,
                    affected_details_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
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
                        json.dumps(item.affected_details) if item.affected_details else None,
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

    def get_items_for_account(self, account_id: int, limit: int = 20) -> list:
        """Return delete items where the account was affected.

        Searches across all actions and returns recent items.
        Returns list of DeleteItem instances.
        """
        rows = self._conn.execute(
            """
            SELECT i.*, a.deleted_at, a.delete_type, a.scope
            FROM source_delete_items i
            JOIN source_delete_actions a ON a.id = i.action_id
            ORDER BY a.deleted_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._item_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def get_action_with_items(self, action_id: int) -> Optional[DeleteAction]:
        """Load one action with all its items attached."""
        row = self._conn.execute(
            "SELECT * FROM source_delete_actions WHERE id = ?",
            (action_id,),
        ).fetchone()
        if not row:
            return None
        action = self._action_from_row(row)
        action.items = self.get_items_for_action(action_id)
        return action

    def mark_reverted(self, action_id: int) -> None:
        """Set the status of an action to 'reverted'."""
        self._conn.execute(
            """
            UPDATE source_delete_actions
            SET status = 'reverted', reverted_at = ?
            WHERE id = ?
            """,
            (_utcnow(), action_id),
        )
        self._conn.commit()

    @staticmethod
    def _action_from_row(row: sqlite3.Row) -> DeleteAction:
        keys = row.keys() if hasattr(row, "keys") else []
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
            status=row["status"] if "status" in keys else "completed",
            reverted_at=row["reverted_at"] if "reverted_at" in keys else None,
            revert_of_action_id=row["revert_of_action_id"] if "revert_of_action_id" in keys else None,
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> DeleteItem:
        keys = row.keys() if hasattr(row, "keys") else []
        details_raw = row["affected_details_json"] if "affected_details_json" in keys else None
        return DeleteItem(
            id=row["id"],
            action_id=row["action_id"],
            source_name=row["source_name"],
            affected_accounts=json.loads(row["affected_accounts_json"] or "[]"),
            affected_details=json.loads(details_raw) if details_raw else [],
            files_removed=row["files_removed"],
            files_not_found=row["files_not_found"],
            files_failed=row["files_failed"],
            errors=json.loads(row["errors_json"]) if row["errors_json"] else [],
        )
