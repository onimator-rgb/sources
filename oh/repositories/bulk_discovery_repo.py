"""
Read/write access to bulk_discovery_runs and bulk_discovery_items tables.
"""
import json
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from oh.models.bulk_discovery import (
    BulkDiscoveryItem,
    BulkDiscoveryRun,
    BULK_FAILED,
)

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class BulkDiscoveryRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Run CRUD
    # ------------------------------------------------------------------

    def create_run(
        self,
        min_threshold: int,
        auto_add_top_n: int,
        total_accounts: int,
        machine: Optional[str] = None,
    ) -> BulkDiscoveryRun:
        """Create a new bulk discovery run and return it with id set."""
        now = _utcnow()
        cursor = self._conn.execute(
            """
            INSERT INTO bulk_discovery_runs
                (started_at, status, min_threshold, auto_add_top_n,
                 total_accounts, machine)
            VALUES (?, 'running', ?, ?, ?, ?)
            """,
            (now, min_threshold, auto_add_top_n, total_accounts, machine),
        )
        self._conn.commit()
        return BulkDiscoveryRun(
            id=cursor.lastrowid,
            started_at=now,
            status="running",
            min_threshold=min_threshold,
            auto_add_top_n=auto_add_top_n,
            total_accounts=total_accounts,
            machine=machine,
        )

    def update_run_progress(
        self,
        run_id: int,
        accounts_done: int,
        accounts_failed: int,
        total_added: int,
    ) -> None:
        """Update progress counters on a running bulk discovery."""
        self._conn.execute(
            """
            UPDATE bulk_discovery_runs
            SET accounts_done=?, accounts_failed=?, total_added=?
            WHERE id=?
            """,
            (accounts_done, accounts_failed, total_added, run_id),
        )
        self._conn.commit()

    def complete_run(
        self,
        run_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Mark a bulk discovery run as completed, failed, or cancelled."""
        self._conn.execute(
            """
            UPDATE bulk_discovery_runs
            SET status=?, completed_at=?, error_message=?
            WHERE id=?
            """,
            (status, _utcnow(), error_message, run_id),
        )
        self._conn.commit()

    def mark_run_reverted(self, run_id: int, revert_status: str) -> None:
        """Mark a run as reverted or partially reverted."""
        self._conn.execute(
            """
            UPDATE bulk_discovery_runs
            SET reverted_at=?, revert_status=?
            WHERE id=?
            """,
            (_utcnow(), revert_status, run_id),
        )
        self._conn.commit()

    def recover_stale_runs(self, max_age_hours: int = 24) -> int:
        """Mark any 'running' bulk runs older than max_age_hours as failed."""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cursor = self._conn.execute(
            """
            UPDATE bulk_discovery_runs
            SET status=?, completed_at=?, error_message='Stale run recovered'
            WHERE status='running' AND started_at < ?
            """,
            (BULK_FAILED, _utcnow(), cutoff.isoformat()),
        )
        self._conn.commit()
        count = cursor.rowcount
        if count:
            logger.info(
                "Recovered %d stale bulk discovery runs (older than %dh)",
                count, max_age_hours,
            )
        return count

    # ------------------------------------------------------------------
    # Item CRUD
    # ------------------------------------------------------------------

    def create_item(
        self,
        run_id: int,
        account_id: int,
        username: str,
        device_id: str,
        sources_before: int,
    ) -> BulkDiscoveryItem:
        """Create a queued item for an account within a bulk run."""
        cursor = self._conn.execute(
            """
            INSERT INTO bulk_discovery_items
                (run_id, account_id, username, device_id,
                 sources_before, status)
            VALUES (?, ?, ?, ?, ?, 'queued')
            """,
            (run_id, account_id, username, device_id, sources_before),
        )
        self._conn.commit()
        return BulkDiscoveryItem(
            id=cursor.lastrowid,
            run_id=run_id,
            account_id=account_id,
            username=username,
            device_id=device_id,
            sources_before=sources_before,
        )

    def update_item(
        self,
        item_id: int,
        status: str,
        search_id: Optional[int] = None,
        sources_added: int = 0,
        sources_after: int = 0,
        added_sources_json: Optional[str] = None,
        original_sources_json: Optional[str] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Update an item after processing or on error."""
        self._conn.execute(
            """
            UPDATE bulk_discovery_items
            SET status=?, search_id=?, sources_added=?, sources_after=?,
                added_sources_json=?, original_sources_json=?, error_message=?
            WHERE id=?
            """,
            (
                status, search_id, sources_added, sources_after,
                added_sources_json, original_sources_json, error_message,
                item_id,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_run(self, run_id: int) -> Optional[BulkDiscoveryRun]:
        """Return a single run without items, or None."""
        row = self._conn.execute(
            "SELECT * FROM bulk_discovery_runs WHERE id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return self._run_from_row(row)

    def get_run_with_items(self, run_id: int) -> Optional[BulkDiscoveryRun]:
        """Load one run with all its items attached."""
        run = self.get_run(run_id)
        if run is None:
            return None
        run.items = self.get_items_for_run(run_id)
        return run

    def get_recent_runs(self, limit: int = 20) -> List[BulkDiscoveryRun]:
        """Return recent runs without items (for the history list view)."""
        rows = self._conn.execute(
            """
            SELECT * FROM bulk_discovery_runs
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._run_from_row(r) for r in rows]

    def get_items_for_run(self, run_id: int) -> List[BulkDiscoveryItem]:
        """Return all items for a run, ordered by id."""
        rows = self._conn.execute(
            """
            SELECT * FROM bulk_discovery_items
            WHERE run_id=?
            ORDER BY id
            """,
            (run_id,),
        ).fetchall()
        return [self._item_from_row(r) for r in rows]

    def get_item(self, item_id: int) -> Optional[BulkDiscoveryItem]:
        """Return a single item by id, or None."""
        row = self._conn.execute(
            "SELECT * FROM bulk_discovery_items WHERE id=?",
            (item_id,),
        ).fetchone()
        if row is None:
            return None
        return self._item_from_row(row)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> BulkDiscoveryRun:
        return BulkDiscoveryRun(
            id=row["id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            min_threshold=row["min_threshold"],
            auto_add_top_n=row["auto_add_top_n"],
            total_accounts=row["total_accounts"],
            accounts_done=row["accounts_done"],
            accounts_failed=row["accounts_failed"],
            total_added=row["total_added"],
            machine=row["machine"],
            error_message=row["error_message"],
            reverted_at=row["reverted_at"],
            revert_status=row["revert_status"],
        )

    @staticmethod
    def _item_from_row(row: sqlite3.Row) -> BulkDiscoveryItem:
        return BulkDiscoveryItem(
            id=row["id"],
            run_id=row["run_id"],
            account_id=row["account_id"],
            username=row["username"],
            device_id=row["device_id"],
            search_id=row["search_id"],
            sources_before=row["sources_before"],
            sources_added=row["sources_added"],
            sources_after=row["sources_after"],
            status=row["status"],
            added_sources_json=row["added_sources_json"],
            original_sources_json=row["original_sources_json"],
            error_message=row["error_message"],
        )
