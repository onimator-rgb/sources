"""
Read/write access to the like_source_assignments table.

like_source_assignments records which like sources are associated with which
accounts:
  is_active = 1  → source is currently in like-source-followers.txt for this account
  is_active = 0  → source appeared in likes.db history but not in like-source-followers.txt

Records are updated whenever:
  - LBR analysis runs for an account (LBRService)

  - Operator clicks "Refresh Like Sources" (GlobalLikeSourcesService)

The table uses UPSERT so re-running always reflects the latest known state.
Source names are stored stripped of leading/trailing whitespace.
"""
from __future__ import annotations

import sqlite3
import logging
from typing import Optional

from oh.models.global_like_source import GlobalLikeSourceRecord, LikeSourceAccountDetail
from oh.utils import utcnow

logger = logging.getLogger(__name__)


class LikeSourceAssignmentRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_for_account(
        self,
        account_id: int,
        snapshot_id: Optional[int],
        active_sources: set[str],
        historical_sources: set[str],
    ) -> None:
        """
        Upsert like source assignments for one account.

        active_sources    — from like-source-followers.txt (is_active=1)
        historical_sources— in likes.db but not like-source-followers.txt (is_active=0)

        A source present in both sets is treated as active.
        Empty or whitespace-only names are silently skipped.
        """
        now = utcnow()

        rows = [
            (account_id, name.strip(), 1, snapshot_id, now)
            for name in active_sources
            if name.strip()
        ] + [
            (account_id, name.strip(), 0, snapshot_id, now)
            for name in historical_sources
            if name.strip()
        ]

        if not rows:
            return

        self._conn.executemany(
            """
            INSERT INTO like_source_assignments
                (account_id, source_name, is_active, snapshot_id, updated_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, source_name) DO UPDATE SET
                is_active   = excluded.is_active,
                snapshot_id = COALESCE(excluded.snapshot_id, snapshot_id),
                updated_at  = excluded.updated_at
            """,
            [(a, n, ia, sid, ts, ts) for a, n, ia, sid, ts in rows],
        )
        self._conn.commit()

    def deactivate_missing(
        self, account_id: int, active_names: set[str]
    ) -> None:
        """
        Mark all like source assignments for account_id as inactive
        if their name is NOT in active_names.  Used after re-reading
        like-source-followers.txt to reflect removed sources.
        """
        if not active_names:
            # No active names → deactivate everything for this account
            now = utcnow()
            self._conn.execute(
                """
                UPDATE like_source_assignments
                SET is_active = 0, updated_at = ?
                WHERE account_id = ? AND is_active = 1
                """,
                (now, account_id),
            )
            self._conn.commit()
            return

        now = utcnow()
        # Build a set of lowercase trimmed names for comparison
        lower_active = {n.strip().lower() for n in active_names if n.strip()}

        # Fetch currently active rows for this account
        rows = self._conn.execute(
            """
            SELECT id, source_name
            FROM like_source_assignments
            WHERE account_id = ? AND is_active = 1
            """,
            (account_id,),
        ).fetchall()

        ids_to_deactivate = [
            r["id"] for r in rows
            if r["source_name"].strip().lower() not in lower_active
        ]

        if not ids_to_deactivate:
            return

        placeholders = ",".join("?" for _ in ids_to_deactivate)
        self._conn.execute(
            f"""
            UPDATE like_source_assignments
            SET is_active = 0, updated_at = ?
            WHERE id IN ({placeholders})
            """,
            [now] + ids_to_deactivate,
        )
        self._conn.commit()
        logger.info(
            "Deactivated %d like source assignments for account %d",
            len(ids_to_deactivate), account_id,
        )

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_for_account(self, account_id: int) -> list[dict]:
        """
        Return all like source assignments for one account.
        Returns list of dicts with keys: source_name, is_active, snapshot_id,
        updated_at, created_at.
        """
        rows = self._conn.execute(
            """
            SELECT source_name, is_active, snapshot_id, updated_at, created_at
            FROM like_source_assignments
            WHERE account_id = ?
            ORDER BY is_active DESC, source_name ASC
            """,
            (account_id,),
        ).fetchall()
        return [
            {
                "source_name": r["source_name"],
                "is_active": bool(r["is_active"]),
                "snapshot_id": r["snapshot_id"],
                "updated_at": r["updated_at"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_all_active(self) -> list[dict]:
        """
        Return all active like source assignments across all non-removed accounts.
        Returns list of dicts with keys: account_id, source_name, snapshot_id,
        updated_at.
        """
        rows = self._conn.execute(
            """
            SELECT lsa.account_id, lsa.source_name, lsa.snapshot_id, lsa.updated_at
            FROM like_source_assignments lsa
            JOIN oh_accounts a ON a.id = lsa.account_id
            WHERE lsa.is_active = 1 AND a.removed_at IS NULL
            ORDER BY lsa.source_name ASC, a.username ASC
            """
        ).fetchall()
        return [
            {
                "account_id": r["account_id"],
                "source_name": r["source_name"],
                "snapshot_id": r["snapshot_id"],
                "updated_at": r["updated_at"],
            }
            for r in rows
        ]

    def get_global_like_sources(self) -> list[GlobalLikeSourceRecord]:
        """
        Return one GlobalLikeSourceRecord per distinct like source name,
        aggregated across all accounts.

        LBR metrics come from each account's latest LBR snapshot.
        Accounts with no snapshot still contribute to assignment counts.
        Sources are ordered by total_likes DESC then name ASC.
        """
        rows = self._conn.execute(
            """
            WITH latest_snap AS (
                SELECT account_id, MAX(id) AS snap_id
                FROM lbr_snapshots
                GROUP BY account_id
            ),
            latest_lbr AS (
                SELECT
                    LOWER(TRIM(lsr.source_name)) AS source_key,
                    ls.account_id,
                    lsr.like_count,
                    lsr.followback_count,
                    lsr.lbr_percent,
                    lsr.is_quality
                FROM lbr_source_results lsr
                JOIN lbr_snapshots lbs ON lsr.snapshot_id = lbs.id
                JOIN latest_snap  ls ON lbs.id = ls.snap_id
            )
            SELECT
                lsa.source_name,
                SUM(CASE WHEN lsa.is_active = 1 THEN 1 ELSE 0 END)  AS active_accounts,
                SUM(CASE WHEN lsa.is_active = 0 THEN 1 ELSE 0 END)  AS historical_accounts,
                COALESCE(SUM(ll.like_count),     0)                  AS total_likes,
                COALESCE(SUM(ll.followback_count), 0)                AS total_followbacks,
                AVG(
                    CASE WHEN ll.lbr_percent IS NOT NULL
                         THEN ll.lbr_percent END
                )                                                     AS avg_lbr_pct,
                CASE
                    WHEN COALESCE(SUM(ll.like_count), 0) > 0
                    THEN 100.0 * SUM(ll.followback_count)
                               / SUM(ll.like_count)
                    ELSE NULL
                END                                                   AS weighted_lbr_pct,
                COALESCE(SUM(ll.is_quality), 0)                      AS quality_account_count,
                MAX(lsa.updated_at)                                   AS last_analyzed_at
            FROM like_source_assignments lsa
            JOIN oh_accounts acct
                ON  acct.id = lsa.account_id
                AND acct.removed_at IS NULL
            LEFT JOIN latest_lbr ll
                ON  lsa.account_id               = ll.account_id
                AND LOWER(TRIM(lsa.source_name)) = ll.source_key
            GROUP BY LOWER(TRIM(lsa.source_name))
            ORDER BY total_likes DESC, lsa.source_name ASC
            """
        ).fetchall()

        return [
            GlobalLikeSourceRecord(
                source_name=r["source_name"],
                active_accounts=r["active_accounts"] or 0,
                historical_accounts=r["historical_accounts"] or 0,
                total_likes=r["total_likes"] or 0,
                total_followbacks=r["total_followbacks"] or 0,
                avg_lbr_pct=r["avg_lbr_pct"],
                weighted_lbr_pct=r["weighted_lbr_pct"],
                quality_account_count=r["quality_account_count"] or 0,
                last_analyzed_at=r["last_analyzed_at"],
            )
            for r in rows
        ]

    def get_accounts_for_source(self, source_name: str) -> list[LikeSourceAccountDetail]:
        """
        Return per-account details for one like source name.
        Active accounts first, then historical.  Within each group ordered
        by like_count DESC.
        """
        rows = self._conn.execute(
            """
            WITH latest_snap AS (
                SELECT account_id, MAX(id) AS snap_id
                FROM lbr_snapshots
                GROUP BY account_id
            ),
            latest_lbr AS (
                SELECT
                    LOWER(TRIM(lsr.source_name)) AS source_key,
                    ls.account_id,
                    lsr.like_count,
                    lsr.followback_count,
                    lsr.lbr_percent,
                    lsr.is_quality,
                    lbs.analyzed_at
                FROM lbr_source_results lsr
                JOIN lbr_snapshots lbs ON lsr.snapshot_id = lbs.id
                JOIN latest_snap  ls ON lbs.id = ls.snap_id
            )
            SELECT
                lsa.account_id,
                a.username,
                a.device_id,
                COALESCE(d.device_name, a.device_id) AS device_name,
                lsa.is_active,
                COALESCE(ll.like_count,     0)      AS like_count,
                COALESCE(ll.followback_count, 0)    AS followback_count,
                ll.lbr_percent,
                COALESCE(ll.is_quality, 0)          AS is_quality,
                ll.analyzed_at                      AS last_analyzed_at
            FROM like_source_assignments lsa
            JOIN oh_accounts a  ON lsa.account_id = a.id
                                AND a.removed_at IS NULL
            LEFT JOIN oh_devices d ON a.device_id = d.device_id
            LEFT JOIN latest_lbr ll
                ON  lsa.account_id               = ll.account_id
                AND LOWER(TRIM(lsa.source_name)) = ll.source_key
            WHERE LOWER(TRIM(lsa.source_name)) = LOWER(TRIM(?))
            ORDER BY
                lsa.is_active DESC,
                COALESCE(ll.like_count, -1) DESC,
                a.username ASC
            """,
            (source_name.strip(),),
        ).fetchall()

        return [
            LikeSourceAccountDetail(
                account_id=r["account_id"],
                username=r["username"],
                device_id=r["device_id"] or "",
                device_name=r["device_name"] or "",
                is_active=bool(r["is_active"]),
                like_count=r["like_count"] or 0,
                followback_count=r["followback_count"] or 0,
                lbr_percent=r["lbr_percent"],
                is_quality=bool(r["is_quality"]),
                last_analyzed_at=r["last_analyzed_at"],
            )
            for r in rows
        ]

    def has_any_data(self) -> bool:
        """Return True if any like source assignments have been recorded."""
        return bool(
            self._conn.execute(
                "SELECT 1 FROM like_source_assignments LIMIT 1"
            ).fetchone()
        )

    def get_active_source_counts(self) -> dict[int, int]:
        """
        Return {account_id: active_like_source_count} for every active
        (non-removed) account that has at least one like source with is_active=1.
        Accounts with no active like sources are absent from the dict (count = 0).
        """
        rows = self._conn.execute(
            """
            SELECT lsa.account_id, COUNT(*) AS cnt
            FROM like_source_assignments lsa
            JOIN oh_accounts a ON a.id = lsa.account_id
            WHERE lsa.is_active = 1 AND a.removed_at IS NULL
            GROUP BY lsa.account_id
            """
        ).fetchall()
        return {r["account_id"]: r["cnt"] for r in rows}

    def get_active_source_names_for_account(self, account_id: int) -> set:
        """
        Return a set of lowercase, trimmed like source names that are currently
        active (is_active=1) for the given account.
        """
        rows = self._conn.execute(
            """
            SELECT LOWER(TRIM(source_name)) AS sn
            FROM like_source_assignments
            WHERE account_id = ? AND is_active = 1
            """,
            (account_id,),
        ).fetchall()
        return {r["sn"] for r in rows}

    def deactivate_removed_accounts(self) -> int:
        """Mark all like source assignments as inactive for removed accounts.

        Called after Scan & Sync to clean up stale assignments where
        an account was removed but its like sources are still marked active.

        Returns the number of assignments deactivated.
        """
        cursor = self._conn.execute(
            """
            UPDATE like_source_assignments
            SET is_active = 0, updated_at = ?
            WHERE is_active = 1
              AND account_id IN (
                  SELECT id FROM oh_accounts WHERE removed_at IS NOT NULL
              )
            """,
            (utcnow(),),
        )
        self._conn.commit()
        count = cursor.rowcount
        if count:
            logger.info("Deactivated %d stale like source assignments for removed accounts", count)
        return count

    def get_source_dates_for_account(self, account_id: int) -> dict:
        """Return {lowercase_source_name: created_at_date_str} for the account."""
        rows = self._conn.execute(
            """
            SELECT LOWER(TRIM(source_name)) AS sn, created_at
            FROM like_source_assignments
            WHERE account_id = ?
            """,
            (account_id,),
        ).fetchall()
        result = {}
        for r in rows:
            ca = r["created_at"]
            if ca:
                result[r["sn"]] = ca[:10]  # just the date part
        return result
