"""
Read/write access to the session_snapshots table.

Each row captures daily action counters for one account: follows, likes,
DMs, unfollows — collected during a scan.  The table uses UPSERT so
re-scanning the same day always reflects the latest data.
"""
import sqlite3
import logging
from typing import Optional

from oh.models.session import AccountSessionRecord
from oh.utils import utcnow

logger = logging.getLogger(__name__)


class SessionRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_snapshot(self, record: AccountSessionRecord) -> None:
        """
        Insert or replace a session snapshot for (account_id, snapshot_date).
        Re-scanning the same day overwrites the previous values.
        """
        self._conn.execute(
            """
            INSERT INTO session_snapshots (
                account_id, device_id, username, snapshot_date, slot,
                follow_count, like_count, dm_count, unfollow_count,
                follow_limit, like_limit, has_activity, collected_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, snapshot_date) DO UPDATE SET
                device_id      = excluded.device_id,
                username       = excluded.username,
                slot           = excluded.slot,
                follow_count   = excluded.follow_count,
                like_count     = excluded.like_count,
                dm_count       = excluded.dm_count,
                unfollow_count = excluded.unfollow_count,
                follow_limit   = excluded.follow_limit,
                like_limit     = excluded.like_limit,
                has_activity   = excluded.has_activity,
                collected_at   = excluded.collected_at
            """,
            (
                record.account_id,
                record.device_id,
                record.username,
                record.snapshot_date,
                record.slot,
                record.follow_count,
                record.like_count,
                record.dm_count,
                record.unfollow_count,
                record.follow_limit,
                record.like_limit,
                1 if record.has_activity else 0,
                record.collected_at or utcnow(),
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_latest_for_account(
        self, account_id: int
    ) -> Optional[AccountSessionRecord]:
        """Return the most recent snapshot for one account, or None."""
        row = self._conn.execute(
            """
            SELECT * FROM session_snapshots
            WHERE account_id = ?
            ORDER BY snapshot_date DESC
            LIMIT 1
            """,
            (account_id,),
        ).fetchone()
        return self._from_row(row) if row else None

    def get_for_date(self, snapshot_date: str) -> list[AccountSessionRecord]:
        """Return all snapshots for a given date, ordered by account_id."""
        rows = self._conn.execute(
            """
            SELECT * FROM session_snapshots
            WHERE snapshot_date = ?
            ORDER BY account_id
            """,
            (snapshot_date,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_map_for_date(
        self, snapshot_date: str
    ) -> dict[int, AccountSessionRecord]:
        """
        Return {account_id: AccountSessionRecord} for a given date.
        One query; O(1) lookup by account_id.
        """
        rows = self._conn.execute(
            """
            SELECT * FROM session_snapshots
            WHERE snapshot_date = ?
            """,
            (snapshot_date,),
        ).fetchall()
        return {row["account_id"]: self._from_row(row) for row in rows}

    def get_recent_for_account(
        self, account_id: int, days: int = 14
    ) -> list:
        """Return session snapshots for last N days for one account."""
        rows = self._conn.execute(
            """
            SELECT * FROM session_snapshots
            WHERE account_id = ?
            ORDER BY snapshot_date DESC
            LIMIT ?
            """,
            (account_id, days),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AccountSessionRecord:
        return AccountSessionRecord(
            id=row["id"],
            account_id=row["account_id"],
            device_id=row["device_id"],
            username=row["username"],
            snapshot_date=row["snapshot_date"],
            slot=row["slot"],
            follow_count=row["follow_count"],
            like_count=row["like_count"],
            dm_count=row["dm_count"],
            unfollow_count=row["unfollow_count"],
            follow_limit=row["follow_limit"],
            like_limit=row["like_limit"],
            has_activity=bool(row["has_activity"]),
            collected_at=row["collected_at"],
        )
