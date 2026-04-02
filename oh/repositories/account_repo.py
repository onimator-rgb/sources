"""
CRUD access to the oh_accounts table.
Soft-delete: removed accounts keep their row with removed_at set.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.account import AccountRecord

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class AccountRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all_active(self) -> list[AccountRecord]:
        rows = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            WHERE a.removed_at IS NULL
            ORDER BY d.device_name, a.username
            """
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_all(self) -> list[AccountRecord]:
        """Returns all accounts including removed ones (for full history view)."""
        rows = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            ORDER BY d.device_name, a.username
            """
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_by_id(self, account_id: int) -> Optional[AccountRecord]:
        row = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            WHERE a.id=?
            """,
            (account_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def get_by_device_and_username(
        self, device_id: str, username: str
    ) -> Optional[AccountRecord]:
        row = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            WHERE a.device_id=? AND a.username=?
            """,
            (device_id, username),
        ).fetchone()
        return self._from_row(row) if row else None

    def get_active_id_map(self) -> dict[tuple, int]:
        """Returns {(device_id, username): id} for all non-removed accounts."""
        rows = self._conn.execute(
            "SELECT id, device_id, username FROM oh_accounts WHERE removed_at IS NULL"
        ).fetchall()
        return {(r["device_id"], r["username"]): r["id"] for r in rows}

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def insert(self, account: AccountRecord) -> AccountRecord:
        """Insert a new account row. Sets account.id from the new row."""
        cursor = self._conn.execute(
            """
            INSERT INTO oh_accounts (
                device_id, username, discovered_at, last_seen_at,
                start_time, end_time, follow_enabled, unfollow_enabled,
                limit_per_day, data_db_exists, sources_txt_exists
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account.device_id, account.username,
                account.discovered_at, account.last_seen_at,
                account.start_time, account.end_time,
                1 if account.follow_enabled else 0,
                1 if account.unfollow_enabled else 0,
                account.limit_per_day,
                1 if account.data_db_exists else 0,
                1 if account.sources_txt_exists else 0,
            ),
        )
        account.id = cursor.lastrowid
        self._conn.commit()
        return account

    def update(self, account_id: int, account: AccountRecord) -> None:
        """
        Update metadata for an existing account row.
        Clears removed_at / removal_sync_run_id if the account reappears.
        """
        self._conn.execute(
            """
            UPDATE oh_accounts SET
                last_seen_at=?,
                start_time=?, end_time=?,
                follow_enabled=?, unfollow_enabled=?,
                limit_per_day=?,
                data_db_exists=?, sources_txt_exists=?,
                bot_tags_raw=?,
                follow_limit_perday=?,
                like_limit_perday=?,
                removed_at=NULL,
                removal_sync_run_id=NULL
            WHERE id=?
            """,
            (
                account.last_seen_at,
                account.start_time, account.end_time,
                1 if account.follow_enabled else 0,
                1 if account.unfollow_enabled else 0,
                account.limit_per_day,
                1 if account.data_db_exists else 0,
                1 if account.sources_txt_exists else 0,
                account.bot_tags_raw,
                account.follow_limit_perday,
                account.like_limit_perday,
                account_id,
            ),
        )
        account.id = account_id
        self._conn.commit()

    def mark_removed(
        self, account_id: int, removed_at: str, sync_run_id: int
    ) -> None:
        """Soft-delete: set removed_at timestamp, keep the row forever."""
        self._conn.execute(
            "UPDATE oh_accounts SET removed_at=?, removal_sync_run_id=? WHERE id=?",
            (removed_at, sync_run_id, account_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Writes — review flag
    # ------------------------------------------------------------------

    def set_review_flag(
        self, account_id: int, note: Optional[str] = None
    ) -> None:
        """Mark an account for operator review."""
        self._conn.execute(
            """
            UPDATE oh_accounts
            SET review_flag = 1, review_note = ?, review_set_at = ?
            WHERE id = ?
            """,
            (note, _utcnow(), account_id),
        )
        self._conn.commit()

    def clear_review_flag(self, account_id: int) -> None:
        """Remove the review flag from an account."""
        self._conn.execute(
            """
            UPDATE oh_accounts
            SET review_flag = 0, review_note = NULL, review_set_at = NULL
            WHERE id = ?
            """,
            (account_id,),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Writes — bot metadata (tags + limits from settings.db)
    # ------------------------------------------------------------------

    def update_bot_metadata(
        self,
        account_id: int,
        bot_tags_raw: Optional[str],
        follow_limit_perday: Optional[str],
        like_limit_perday: Optional[str],
    ) -> None:
        """
        Update tag and limit fields read from the bot's settings.db.
        Does not touch any other account fields.
        """
        self._conn.execute(
            """
            UPDATE oh_accounts
            SET bot_tags_raw = ?, follow_limit_perday = ?, like_limit_perday = ?
            WHERE id = ?
            """,
            (bot_tags_raw, follow_limit_perday, like_limit_perday, account_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Queries — review
    # ------------------------------------------------------------------

    def get_flagged_for_review(self) -> list[AccountRecord]:
        """Return all active accounts with review_flag = 1."""
        rows = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            WHERE a.removed_at IS NULL AND a.review_flag = 1
            ORDER BY a.review_set_at DESC, a.username
            """
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AccountRecord:
        keys = row.keys()
        return AccountRecord(
            id=row["id"],
            device_id=row["device_id"],
            username=row["username"],
            device_name=row["device_name"] if "device_name" in keys else None,
            discovered_at=row["discovered_at"],
            last_seen_at=row["last_seen_at"],
            removed_at=row["removed_at"],
            removal_sync_run_id=row["removal_sync_run_id"],
            start_time=row["start_time"],
            end_time=row["end_time"],
            follow_enabled=(
                bool(row["follow_enabled"])
                if row["follow_enabled"] is not None else None
            ),
            unfollow_enabled=(
                bool(row["unfollow_enabled"])
                if row["unfollow_enabled"] is not None else None
            ),
            limit_per_day=row["limit_per_day"],
            last_metadata_updated_at=row["last_metadata_updated_at"],
            data_db_exists=bool(row["data_db_exists"]),
            sources_txt_exists=bool(row["sources_txt_exists"]),
            # --- Stage 1 fields (migration 006) ---
            review_flag=bool(row["review_flag"]) if "review_flag" in keys else False,
            review_note=row["review_note"] if "review_note" in keys else None,
            review_set_at=row["review_set_at"] if "review_set_at" in keys else None,
            bot_tags_raw=row["bot_tags_raw"] if "bot_tags_raw" in keys else None,
            like_limit_perday=row["like_limit_perday"] if "like_limit_perday" in keys else None,
            follow_limit_perday=row["follow_limit_perday"] if "follow_limit_perday" in keys else None,
            # --- Quick Wins fields (migration 011) ---
            operator_notes=row["operator_notes"] if "operator_notes" in keys else None,
        )
