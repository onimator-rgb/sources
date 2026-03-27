"""
Read/write access to fbr_snapshots and fbr_source_results tables.

Latest-snapshot rule: the row with the highest id for a given account_id
is always the most recent, regardless of status.  This is honest —
a recent error is surfaced, not hidden behind an older success.
"""
import json
import sqlite3
import logging
from typing import Optional

from oh.models.fbr import SourceFBRRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord

logger = logging.getLogger(__name__)


class FBRSnapshotRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save(self, snapshot: FBRSnapshotRecord) -> FBRSnapshotRecord:
        """Insert a new snapshot row and set snapshot.id. Returns snapshot."""
        cursor = self._conn.execute(
            """
            INSERT INTO fbr_snapshots (
                account_id, device_id, username, analyzed_at,
                min_follows, min_fbr_pct,
                total_sources, quality_sources,
                best_fbr_pct, best_fbr_source,
                highest_vol_source, highest_vol_count,
                below_volume_count, anomaly_count,
                warnings_json, status, schema_error
            ) VALUES (
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?
            )
            """,
            (
                snapshot.account_id, snapshot.device_id, snapshot.username,
                snapshot.analyzed_at,
                snapshot.min_follows, snapshot.min_fbr_pct,
                snapshot.total_sources, snapshot.quality_sources,
                snapshot.best_fbr_pct, snapshot.best_fbr_source,
                snapshot.highest_vol_source, snapshot.highest_vol_count,
                snapshot.below_volume_count, snapshot.anomaly_count,
                snapshot.warnings_json, snapshot.status, snapshot.schema_error,
            ),
        )
        snapshot.id = cursor.lastrowid
        self._conn.commit()
        return snapshot

    def save_source_results(
        self, snapshot_id: int, records: list[SourceFBRRecord]
    ) -> None:
        """Bulk-insert per-source FBR rows for a snapshot."""
        self._conn.executemany(
            """
            INSERT INTO fbr_source_results
                (snapshot_id, source_name, follow_count, followback_count,
                 fbr_percent, is_quality, anomaly)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    snapshot_id,
                    r.source_name,
                    r.follow_count,
                    r.followback_count,
                    r.fbr_percent,
                    1 if r.is_quality else 0,
                    r.anomaly,
                )
                for r in records
            ],
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_latest_map(self) -> dict[int, FBRSnapshotRecord]:
        """
        Returns {account_id: FBRSnapshotRecord} for the most recent snapshot
        of every account that has ever been analyzed.
        One query; no N+1.
        """
        rows = self._conn.execute(
            """
            SELECT s.*
            FROM fbr_snapshots s
            INNER JOIN (
                SELECT account_id, MAX(id) AS max_id
                FROM fbr_snapshots
                GROUP BY account_id
            ) latest ON s.id = latest.max_id
            """
        ).fetchall()
        return {row["account_id"]: self._from_row(row) for row in rows}

    def get_for_account(self, account_id: int) -> list[FBRSnapshotRecord]:
        """Returns all snapshots for one account, newest first."""
        rows = self._conn.execute(
            "SELECT * FROM fbr_snapshots WHERE account_id=? ORDER BY id DESC",
            (account_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_source_results(self, snapshot_id: int) -> list[SourceFBRRecord]:
        """Returns per-source FBR records for a snapshot."""
        rows = self._conn.execute(
            "SELECT * FROM fbr_source_results WHERE snapshot_id=? ORDER BY follow_count DESC",
            (snapshot_id,),
        ).fetchall()
        return [
            SourceFBRRecord(
                source_name=r["source_name"],
                follow_count=r["follow_count"],
                followback_count=r["followback_count"],
                fbr_percent=r["fbr_percent"],
                is_quality=bool(r["is_quality"]),
                anomaly=r["anomaly"],
            )
            for r in rows
        ]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> FBRSnapshotRecord:
        return FBRSnapshotRecord(
            id=row["id"],
            account_id=row["account_id"],
            device_id=row["device_id"],
            username=row["username"],
            analyzed_at=row["analyzed_at"],
            min_follows=row["min_follows"],
            min_fbr_pct=row["min_fbr_pct"],
            total_sources=row["total_sources"],
            quality_sources=row["quality_sources"],
            best_fbr_pct=row["best_fbr_pct"],
            best_fbr_source=row["best_fbr_source"],
            highest_vol_source=row["highest_vol_source"],
            highest_vol_count=row["highest_vol_count"],
            below_volume_count=row["below_volume_count"],
            anomaly_count=row["anomaly_count"],
            warnings_json=row["warnings_json"],
            status=row["status"],
            schema_error=row["schema_error"],
        )
