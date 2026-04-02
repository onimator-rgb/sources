"""
Read/write access to source_profiles and source_fbr_stats tables.

source_profiles stores global metadata for each source username
(niche, language, location, follower_count, etc.)

source_fbr_stats stores aggregated FBR performance across all accounts.
"""
import json
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Optional

from oh.models.source_profile import SourceProfile, SourceFBRStats

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceProfileRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def upsert_profile(
        self,
        source_name: str,
        niche_category: Optional[str] = None,
        niche_confidence: Optional[float] = None,
        language: Optional[str] = None,
        location: Optional[str] = None,
        follower_count: Optional[int] = None,
        bio: Optional[str] = None,
        avg_er: Optional[float] = None,
        profile_json: Optional[str] = None,
    ) -> None:
        """
        Insert or update a source profile.

        On INSERT, first_seen_at is set to now.
        On UPDATE, only non-NULL incoming values overwrite existing ones
        (COALESCE keeps the old value when the new one is NULL).
        updated_at is always refreshed.
        """
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO source_profiles
                (source_name, niche_category, niche_confidence, language,
                 location, follower_count, bio, avg_er,
                 first_seen_at, updated_at, profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(source_name) DO UPDATE SET
                niche_category   = COALESCE(excluded.niche_category, source_profiles.niche_category),
                niche_confidence = COALESCE(excluded.niche_confidence, source_profiles.niche_confidence),
                language         = COALESCE(excluded.language, source_profiles.language),
                location         = COALESCE(excluded.location, source_profiles.location),
                follower_count   = COALESCE(excluded.follower_count, source_profiles.follower_count),
                bio              = COALESCE(excluded.bio, source_profiles.bio),
                avg_er           = COALESCE(excluded.avg_er, source_profiles.avg_er),
                profile_json     = COALESCE(excluded.profile_json, source_profiles.profile_json),
                updated_at       = excluded.updated_at
            """,
            (
                source_name, niche_category, niche_confidence, language,
                location, follower_count, bio, avg_er,
                now, now, profile_json,
            ),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Profile reads
    # ------------------------------------------------------------------

    def get_profile(self, source_name: str) -> Optional[SourceProfile]:
        """Return a single source profile by name, or None."""
        row = self._conn.execute(
            "SELECT * FROM source_profiles WHERE source_name = ?",
            (source_name,),
        ).fetchone()
        if row is None:
            return None
        return self._profile_from_row(row)

    def get_profiles_by_niche(
        self,
        niche_category: str,
        limit: int = 100,
    ) -> List[SourceProfile]:
        """Return profiles matching a niche category."""
        rows = self._conn.execute(
            """
            SELECT * FROM source_profiles
            WHERE niche_category = ?
            ORDER BY source_name
            LIMIT ?
            """,
            (niche_category, limit),
        ).fetchall()
        return [self._profile_from_row(r) for r in rows]

    def get_all_profiles(self, limit: int = 500) -> List[SourceProfile]:
        """Return all source profiles, ordered by source_name."""
        rows = self._conn.execute(
            """
            SELECT * FROM source_profiles
            ORDER BY source_name
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._profile_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # FBR stats
    # ------------------------------------------------------------------

    def update_fbr_stats(self) -> int:
        """
        Aggregate FBR data from fbr_source_results + fbr_snapshots
        into the source_fbr_stats table.

        Returns the number of rows upserted.
        """
        now = _utcnow()
        cursor = self._conn.execute(
            """
            INSERT OR REPLACE INTO source_fbr_stats
                (source_name, total_accounts_used, total_follows,
                 total_followbacks, avg_fbr_pct, weighted_fbr_pct,
                 quality_account_count, last_analyzed_at, updated_at)
            SELECT
                r.source_name,
                COUNT(DISTINCT s.account_id),
                SUM(r.follow_count),
                SUM(r.followback_count),
                AVG(r.fbr_percent),
                CASE WHEN SUM(r.follow_count) > 0
                     THEN CAST(SUM(r.followback_count) AS REAL)
                          / SUM(r.follow_count) * 100
                     ELSE 0.0 END,
                SUM(r.is_quality),
                MAX(s.analyzed_at),
                ?
            FROM fbr_source_results r
            JOIN fbr_snapshots s ON s.id = r.snapshot_id
            GROUP BY r.source_name
            """,
            (now,),
        )
        self._conn.commit()
        count = cursor.rowcount
        logger.info("Updated FBR stats for %d sources", count)
        return count

    def get_fbr_stats(self, source_name: str) -> Optional[SourceFBRStats]:
        """Return FBR stats for a single source, or None."""
        row = self._conn.execute(
            "SELECT * FROM source_fbr_stats WHERE source_name = ?",
            (source_name,),
        ).fetchone()
        if row is None:
            return None
        return self._stats_from_row(row)

    def get_all_fbr_stats(self) -> List[SourceFBRStats]:
        """Return all source FBR stats, ordered by weighted_fbr_pct DESC."""
        rows = self._conn.execute(
            """
            SELECT * FROM source_fbr_stats
            ORDER BY weighted_fbr_pct DESC
            """,
        ).fetchall()
        return [self._stats_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _profile_from_row(row: sqlite3.Row) -> SourceProfile:
        return SourceProfile(
            id=row["id"],
            source_name=row["source_name"],
            niche_category=row["niche_category"],
            niche_confidence=row["niche_confidence"],
            language=row["language"],
            location=row["location"],
            follower_count=row["follower_count"],
            bio=row["bio"],
            avg_er=row["avg_er"],
            is_active_source=row["is_active_source"],
            first_seen_at=row["first_seen_at"],
            updated_at=row["updated_at"],
            profile_json=row["profile_json"],
        )

    @staticmethod
    def _stats_from_row(row: sqlite3.Row) -> SourceFBRStats:
        return SourceFBRStats(
            id=row["id"],
            source_name=row["source_name"],
            total_accounts_used=row["total_accounts_used"],
            total_follows=row["total_follows"],
            total_followbacks=row["total_followbacks"],
            avg_fbr_pct=row["avg_fbr_pct"],
            weighted_fbr_pct=row["weighted_fbr_pct"],
            quality_account_count=row["quality_account_count"],
            last_analyzed_at=row["last_analyzed_at"],
            updated_at=row["updated_at"],
        )
