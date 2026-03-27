"""
Read/write access to the source_assignments table.

source_assignments records which sources are associated with which accounts:
  is_active = 1  → source is currently in sources.txt for this account
  is_active = 0  → source appeared in data.db history but not in sources.txt

Records are updated whenever:
  - FBR analysis runs for an account (FBRService)
  - Operator clicks "Refresh Sources" (GlobalSourcesService)

The table uses UPSERT so re-running always reflects the latest known state.
Source names are stored stripped of leading/trailing whitespace.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.global_source import GlobalSourceRecord, SourceAccountDetail

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceAssignmentRepository:
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
        Upsert source assignments for one account.

        active_sources    — from sources.txt (is_active=1)
        historical_sources— in data.db but not sources.txt (is_active=0)

        A source present in both sets is treated as active.
        Empty or whitespace-only names are silently skipped.
        """
        now = _utcnow()

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
            INSERT INTO source_assignments
                (account_id, source_name, is_active, snapshot_id, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id, source_name) DO UPDATE SET
                is_active   = excluded.is_active,
                snapshot_id = COALESCE(excluded.snapshot_id, snapshot_id),
                updated_at  = excluded.updated_at
            """,
            rows,
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_global_sources(self) -> list[GlobalSourceRecord]:
        """
        Return one GlobalSourceRecord per distinct source name, aggregated
        across all accounts.

        FBR metrics come from each account's latest FBR snapshot.
        Accounts with no snapshot still contribute to assignment counts.
        Sources are ordered by total_follows DESC then name ASC.
        """
        rows = self._conn.execute(
            """
            WITH latest_snap AS (
                SELECT account_id, MAX(id) AS snap_id
                FROM fbr_snapshots
                GROUP BY account_id
            ),
            latest_fbr AS (
                SELECT
                    LOWER(TRIM(fsr.source_name)) AS source_key,
                    ls.account_id,
                    fsr.follow_count,
                    fsr.followback_count,
                    fsr.fbr_percent,
                    fsr.is_quality
                FROM fbr_source_results fsr
                JOIN fbr_snapshots fs ON fsr.snapshot_id = fs.id
                JOIN latest_snap  ls ON fs.id = ls.snap_id
            )
            SELECT
                sa.source_name,
                SUM(CASE WHEN sa.is_active = 1 THEN 1 ELSE 0 END)  AS active_accounts,
                SUM(CASE WHEN sa.is_active = 0 THEN 1 ELSE 0 END)  AS historical_accounts,
                COALESCE(SUM(lf.follow_count),     0)               AS total_follows,
                COALESCE(SUM(lf.followback_count), 0)               AS total_followbacks,
                AVG(
                    CASE WHEN lf.fbr_percent IS NOT NULL
                         THEN lf.fbr_percent END
                )                                                    AS avg_fbr_pct,
                CASE
                    WHEN COALESCE(SUM(lf.follow_count), 0) > 0
                    THEN 100.0 * SUM(lf.followback_count)
                               / SUM(lf.follow_count)
                    ELSE NULL
                END                                                  AS weighted_fbr_pct,
                COALESCE(SUM(lf.is_quality), 0)                     AS quality_account_count,
                MAX(sa.updated_at)                                   AS last_analyzed_at
            FROM source_assignments sa
            LEFT JOIN latest_fbr lf
                ON  sa.account_id               = lf.account_id
                AND LOWER(TRIM(sa.source_name)) = lf.source_key
            GROUP BY LOWER(TRIM(sa.source_name))
            ORDER BY total_follows DESC, sa.source_name ASC
            """
        ).fetchall()

        return [
            GlobalSourceRecord(
                source_name=r["source_name"],
                active_accounts=r["active_accounts"] or 0,
                historical_accounts=r["historical_accounts"] or 0,
                total_follows=r["total_follows"] or 0,
                total_followbacks=r["total_followbacks"] or 0,
                avg_fbr_pct=r["avg_fbr_pct"],
                weighted_fbr_pct=r["weighted_fbr_pct"],
                quality_account_count=r["quality_account_count"] or 0,
                last_analyzed_at=r["last_analyzed_at"],
            )
            for r in rows
        ]

    def get_accounts_for_source(self, source_name: str) -> list[SourceAccountDetail]:
        """
        Return per-account details for one source name.
        Active accounts first, then historical.  Within each group ordered
        by follow_count DESC.
        """
        rows = self._conn.execute(
            """
            WITH latest_snap AS (
                SELECT account_id, MAX(id) AS snap_id
                FROM fbr_snapshots
                GROUP BY account_id
            ),
            latest_fbr AS (
                SELECT
                    LOWER(TRIM(fsr.source_name)) AS source_key,
                    ls.account_id,
                    fsr.follow_count,
                    fsr.followback_count,
                    fsr.fbr_percent,
                    fsr.is_quality,
                    fs.analyzed_at
                FROM fbr_source_results fsr
                JOIN fbr_snapshots fs ON fsr.snapshot_id = fs.id
                JOIN latest_snap  ls ON fs.id = ls.snap_id
            )
            SELECT
                sa.account_id,
                a.username,
                a.device_id,
                COALESCE(d.device_name, a.device_id) AS device_name,
                sa.is_active,
                COALESCE(lf.follow_count,     0)      AS follow_count,
                COALESCE(lf.followback_count, 0)      AS followback_count,
                lf.fbr_percent,
                COALESCE(lf.is_quality, 0)            AS is_quality,
                lf.analyzed_at                        AS last_analyzed_at
            FROM source_assignments sa
            JOIN oh_accounts a  ON sa.account_id = a.id
            LEFT JOIN oh_devices d ON a.device_id = d.device_id
            LEFT JOIN latest_fbr lf
                ON  sa.account_id               = lf.account_id
                AND LOWER(TRIM(sa.source_name)) = lf.source_key
            WHERE LOWER(TRIM(sa.source_name)) = LOWER(TRIM(?))
            ORDER BY
                sa.is_active DESC,
                COALESCE(lf.follow_count, -1) DESC,
                a.username ASC
            """,
            (source_name.strip(),),
        ).fetchall()

        return [
            SourceAccountDetail(
                account_id=r["account_id"],
                username=r["username"],
                device_id=r["device_id"] or "",
                device_name=r["device_name"] or "",
                is_active=bool(r["is_active"]),
                follow_count=r["follow_count"] or 0,
                followback_count=r["followback_count"] or 0,
                fbr_percent=r["fbr_percent"],
                is_quality=bool(r["is_quality"]),
                last_analyzed_at=r["last_analyzed_at"],
            )
            for r in rows
        ]

    def has_any_data(self) -> bool:
        """Return True if any source assignments have been recorded."""
        return bool(
            self._conn.execute(
                "SELECT 1 FROM source_assignments LIMIT 1"
            ).fetchone()
        )

    def get_active_assignments_for_source(
        self, source_name: str
    ) -> list[tuple[int, str, str, str]]:
        """
        Return (account_id, device_id, username, device_name) for every account
        that currently has this source actively assigned (is_active=1).
        Used by SourceDeleteService to know which files to modify.
        """
        rows = self._conn.execute(
            """
            SELECT sa.account_id, a.device_id, a.username,
                   COALESCE(d.device_name, a.device_id) AS device_name
            FROM source_assignments sa
            JOIN oh_accounts a  ON sa.account_id = a.id
            LEFT JOIN oh_devices d ON a.device_id = d.device_id
            WHERE LOWER(TRIM(sa.source_name)) = LOWER(TRIM(?))
              AND sa.is_active = 1
            ORDER BY a.username ASC
            """,
            (source_name.strip(),),
        ).fetchall()
        return [
            (r["account_id"], r["device_id"], r["username"], r["device_name"])
            for r in rows
        ]

    def get_active_source_counts(self) -> dict[int, int]:
        """
        Return {account_id: active_source_count} for every account that has
        at least one source with is_active=1.
        Accounts with no active sources are absent from the dict (count = 0).
        """
        rows = self._conn.execute(
            """
            SELECT account_id, COUNT(*) AS cnt
            FROM source_assignments
            WHERE is_active = 1
            GROUP BY account_id
            """
        ).fetchall()
        return {r["account_id"]: r["cnt"] for r in rows}

    def mark_source_inactive(self, account_id: int, source_name: str) -> None:
        """
        Mark a single account-source pair as inactive (is_active=0).
        Called after SourceDeleter successfully removes the source from sources.txt.
        Does nothing if the row does not exist.
        """
        now = _utcnow()
        self._conn.execute(
            """
            UPDATE source_assignments
            SET is_active = 0, updated_at = ?
            WHERE account_id = ?
              AND LOWER(TRIM(source_name)) = LOWER(TRIM(?))
            """,
            (now, account_id, source_name.strip()),
        )
        self._conn.commit()
