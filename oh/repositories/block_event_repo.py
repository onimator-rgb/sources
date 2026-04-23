"""
Read/write access to the block_events table.

Tracks detected Instagram restrictions (action blocks, challenges,
shadow bans, etc.) per account with evidence and resolution status.
"""
import sqlite3
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from oh.models.block_event import BlockEvent
from oh.utils import utcnow

logger = logging.getLogger(__name__)


class BlockEventRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, event: BlockEvent) -> BlockEvent:
        """Insert a new block event. Returns event with id set."""
        cursor = self._conn.execute(
            """
            INSERT INTO block_events (
                account_id, event_type, detected_at, evidence,
                resolved_at, auto_detected
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.account_id,
                event.event_type,
                event.detected_at or utcnow(),
                event.evidence,
                event.resolved_at,
                1 if event.auto_detected else 0,
            ),
        )
        event.id = cursor.lastrowid
        self._conn.commit()
        return event

    def resolve(self, event_id: int) -> None:
        """Mark a block event as resolved."""
        self._conn.execute(
            "UPDATE block_events SET resolved_at = ? WHERE id = ?",
            (utcnow(), event_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_active_for_account(self, account_id: int) -> List[BlockEvent]:
        """Return all active (unresolved) block events for one account."""
        rows = self._conn.execute(
            """
            SELECT * FROM block_events
            WHERE account_id = ? AND resolved_at IS NULL
            ORDER BY detected_at DESC
            """,
            (account_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_active_all(self) -> List[BlockEvent]:
        """Return all active block events across all accounts."""
        rows = self._conn.execute(
            """
            SELECT * FROM block_events
            WHERE resolved_at IS NULL
            ORDER BY detected_at DESC
            """
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_active_map(self) -> Dict[int, List[BlockEvent]]:
        """Return {account_id: [BlockEvent, ...]} for all active blocks."""
        events = self.get_active_all()
        result: Dict[int, List[BlockEvent]] = defaultdict(list)
        for ev in events:
            result[ev.account_id].append(ev)
        return dict(result)

    def get_recent(self, limit: int = 50) -> List[BlockEvent]:
        """Return recent events (active and resolved), newest first."""
        rows = self._conn.execute(
            """
            SELECT * FROM block_events
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> BlockEvent:
        return BlockEvent(
            id=row["id"],
            account_id=row["account_id"],
            event_type=row["event_type"],
            detected_at=row["detected_at"],
            evidence=row["evidence"],
            resolved_at=row["resolved_at"],
            auto_detected=bool(row["auto_detected"]),
        )
