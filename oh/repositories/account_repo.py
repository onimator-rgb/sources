"""
CRUD access to the oh_accounts table.
Soft-delete: removed accounts keep their row with removed_at set.
"""
import sqlite3
import logging
from typing import Optional

from oh.models.account import AccountRecord

logger = logging.getLogger(__name__)


class AccountRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_all_active(self) -> list:
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

    def get_all(self) -> list:
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

    def get_active_keyset(self) -> set:
        """Returns set of (device_id, username) for all non-removed accounts."""
        rows = self._conn.execute(
            "SELECT device_id, username FROM oh_accounts WHERE removed_at IS NULL"
        ).fetchall()
        return {(r["device_id"], r["username"]) for r in rows}

    def search(self, query: str) -> list:
        pattern = f"%{query}%"
        rows = self._conn.execute(
            """
            SELECT a.*, d.device_name
            FROM oh_accounts a
            LEFT JOIN oh_devices d ON d.device_id = a.device_id
            WHERE a.removed_at IS NULL
              AND (a.username LIKE ? OR d.device_name LIKE ?)
            ORDER BY d.device_name, a.username
            """,
            (pattern, pattern),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert(self, account: AccountRecord) -> AccountRecord:
        """
        Insert new account or update existing one.
        Clears removed_at/removal_sync_run_id if the account reappears.
        """
        existing = self.get_by_device_and_username(account.device_id, account.username)

        if existing is None:
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
        else:
            self._conn.execute(
                """
                UPDATE oh_accounts SET
                    last_seen_at=?,
                    start_time=?, end_time=?,
                    follow_enabled=?, unfollow_enabled=?,
                    limit_per_day=?,
                    data_db_exists=?, sources_txt_exists=?,
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
                    existing.id,
                ),
            )
            account.id = existing.id

        self._conn.commit()
        return account

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
        )
