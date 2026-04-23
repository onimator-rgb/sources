"""
Read/write access to source_searches, source_search_candidates,
and source_search_results tables.
"""
import sqlite3
import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from oh.models.source_finder import (
    SourceCandidate,
    SourceSearchRecord,
    SourceSearchResult,
)
from oh.utils import utcnow

logger = logging.getLogger(__name__)


class SourceSearchRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Search CRUD
    # ------------------------------------------------------------------

    def create_search(self, account_id: int, username: str) -> SourceSearchRecord:
        """Create a new search record and return it with id set."""
        now = utcnow()
        cursor = self._conn.execute(
            """
            INSERT INTO source_searches (account_id, username, started_at, status, step_reached)
            VALUES (?, ?, ?, 'running', 0)
            """,
            (account_id, username, now),
        )
        self._conn.commit()
        return SourceSearchRecord(
            id=cursor.lastrowid,
            account_id=account_id,
            username=username,
            started_at=now,
            status="running",
            step_reached=0,
        )

    def update_search_step(self, search_id: int, step_reached: int) -> None:
        """Update the step checkpoint for resume support."""
        self._conn.execute(
            "UPDATE source_searches SET step_reached=? WHERE id=?",
            (step_reached, search_id),
        )
        self._conn.commit()

    def update_search_query(self, search_id: int, query: str) -> None:
        """Save the search query used for this search."""
        self._conn.execute(
            "UPDATE source_searches SET query_used=? WHERE id=?",
            (query, search_id),
        )
        self._conn.commit()

    def complete_search(
        self,
        search_id: int,
        status: str,
        error_message: Optional[str] = None,
    ) -> None:
        """Mark a search as completed or failed."""
        self._conn.execute(
            """
            UPDATE source_searches
            SET status=?, completed_at=?, error_message=?
            WHERE id=?
            """,
            (status, utcnow(), error_message, search_id),
        )
        self._conn.commit()

    def recover_stale_searches(self, max_age_hours: int = 24) -> int:
        """Mark any 'running' searches older than *max_age_hours* as failed.

        Handles app crash recovery — same pattern as sync_repo.recover_stale_runs().
        Returns the number of rows updated.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cursor = self._conn.execute(
            """
            UPDATE source_searches
            SET status='failed', completed_at=?, error_message='Stale search recovered'
            WHERE status='running' AND started_at < ?
            """,
            (utcnow(), cutoff.isoformat()),
        )
        self._conn.commit()
        count = cursor.rowcount
        if count:
            logger.info("Recovered %d stale source searches (older than %dh)", count, max_age_hours)
        return count

    def get_latest_search(self, account_id: int) -> Optional[SourceSearchRecord]:
        """Return the most recent search for an account, or None."""
        row = self._conn.execute(
            """
            SELECT * FROM source_searches
            WHERE account_id=?
            ORDER BY id DESC
            LIMIT 1
            """,
            (account_id,),
        ).fetchone()
        if row is None:
            return None
        return self._search_from_row(row)

    # ------------------------------------------------------------------
    # Candidate CRUD
    # ------------------------------------------------------------------

    def save_candidates(
        self, search_id: int, candidates: List[SourceCandidate]
    ) -> None:
        """Bulk-insert candidate rows for a search."""
        self._conn.executemany(
            """
            INSERT INTO source_search_candidates (
                search_id, username, full_name, follower_count, bio,
                source_type, is_private, is_verified, is_enriched,
                avg_er, ai_score, ai_category, profile_pic_url
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (
                    search_id,
                    c.username,
                    c.full_name,
                    c.follower_count,
                    c.bio,
                    c.source_type,
                    1 if c.is_private else 0,
                    1 if c.is_verified else 0,
                    1 if c.is_enriched else 0,
                    c.avg_er,
                    c.ai_score,
                    c.ai_category,
                    c.profile_pic_url,
                )
                for c in candidates
            ],
        )
        self._conn.commit()

    def update_candidate_enrichment(
        self,
        candidate_id: int,
        follower_count: int,
        bio: Optional[str],
        avg_er: Optional[float],
        is_enriched: bool = True,
    ) -> None:
        """Update a candidate with enriched profile data."""
        self._conn.execute(
            """
            UPDATE source_search_candidates
            SET follower_count=?, bio=?, avg_er=?, is_enriched=?
            WHERE id=?
            """,
            (follower_count, bio, avg_er, 1 if is_enriched else 0, candidate_id),
        )
        self._conn.commit()

    def update_candidate_er(
        self, candidate_id: int, avg_er: Optional[float]
    ) -> None:
        """Update only the avg_er column for a candidate."""
        self._conn.execute(
            "UPDATE source_search_candidates SET avg_er=? WHERE id=?",
            (avg_er, candidate_id),
        )
        self._conn.commit()

    def update_candidate_ai(
        self, candidate_id: int, ai_score: float, ai_category: Optional[str]
    ) -> None:
        """Update a candidate with AI scoring results."""
        self._conn.execute(
            """
            UPDATE source_search_candidates
            SET ai_score=?, ai_category=?
            WHERE id=?
            """,
            (ai_score, ai_category, candidate_id),
        )
        self._conn.commit()

    def get_candidates(self, search_id: int) -> List[SourceCandidate]:
        """Return all candidates for a search."""
        rows = self._conn.execute(
            "SELECT * FROM source_search_candidates WHERE search_id=? ORDER BY id",
            (search_id,),
        ).fetchall()
        return [self._candidate_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Result CRUD
    # ------------------------------------------------------------------

    def save_results(
        self, search_id: int, results: List[SourceSearchResult]
    ) -> None:
        """Bulk-insert ranked result rows for a search."""
        self._conn.executemany(
            """
            INSERT INTO source_search_results (search_id, candidate_id, rank, added_to_sources, added_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (
                    search_id,
                    r.candidate_id,
                    r.rank,
                    1 if r.added_to_sources else 0,
                    r.added_at,
                )
                for r in results
            ],
        )
        self._conn.commit()

    def mark_added_to_sources(self, result_id: int) -> None:
        """Mark a result as added to sources.txt."""
        self._conn.execute(
            """
            UPDATE source_search_results
            SET added_to_sources=1, added_at=?
            WHERE id=?
            """,
            (utcnow(), result_id),
        )
        self._conn.commit()

    def get_results(self, search_id: int) -> List[SourceSearchResult]:
        """Return ranked results with joined candidate data."""
        rows = self._conn.execute(
            """
            SELECT r.*, c.username AS c_username, c.full_name AS c_full_name,
                   c.follower_count AS c_follower_count, c.bio AS c_bio,
                   c.source_type AS c_source_type, c.is_private AS c_is_private,
                   c.is_verified AS c_is_verified, c.is_enriched AS c_is_enriched,
                   c.avg_er AS c_avg_er, c.ai_score AS c_ai_score,
                   c.ai_category AS c_ai_category, c.profile_pic_url AS c_profile_pic_url
            FROM source_search_results r
            JOIN source_search_candidates c ON c.id = r.candidate_id
            WHERE r.search_id=?
            ORDER BY r.rank
            """,
            (search_id,),
        ).fetchall()
        return [self._result_from_row(r) for r in rows]

    # ------------------------------------------------------------------
    # Target & Niche data
    # ------------------------------------------------------------------

    def update_search_target_data(
        self,
        search_id: int,
        target_category: Optional[str] = None,
        target_niche: Optional[str] = None,
        target_bio: Optional[str] = None,
        target_followers: Optional[int] = None,
        target_location: Optional[str] = None,
        target_language: Optional[str] = None,
        target_profile_json: Optional[str] = None,
    ) -> None:
        """Save target profile data on the search record."""
        self._conn.execute(
            """
            UPDATE source_searches
            SET target_category=?, target_niche=?, target_bio=?,
                target_followers=?, target_location=?, target_language=?,
                target_profile_json=?
            WHERE id=?
            """,
            (target_category, target_niche, target_bio,
             target_followers, target_location, target_language,
             target_profile_json, search_id),
        )
        self._conn.commit()

    def update_candidate_niche(
        self,
        candidate_id: int,
        niche_category_local: Optional[str] = None,
        niche_match_score: Optional[float] = None,
        composite_score: Optional[float] = None,
        search_strategy: Optional[str] = None,
        language: Optional[str] = None,
        location: Optional[str] = None,
    ) -> None:
        """Save niche classification and scoring data on a candidate."""
        self._conn.execute(
            """
            UPDATE source_search_candidates
            SET niche_category_local=?, niche_match_score=?, composite_score=?,
                search_strategy=?, language=?, location=?
            WHERE id=?
            """,
            (niche_category_local, niche_match_score, composite_score,
             search_strategy, language, location, candidate_id),
        )
        self._conn.commit()

    def update_candidate_composite_score(
        self, candidate_id: int, composite_score: float
    ) -> None:
        """Update only the composite_score column for a candidate."""
        self._conn.execute(
            "UPDATE source_search_candidates SET composite_score=? WHERE id=?",
            (composite_score, candidate_id),
        )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _search_from_row(row: sqlite3.Row) -> SourceSearchRecord:
        return SourceSearchRecord(
            id=row["id"],
            account_id=row["account_id"],
            username=row["username"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            status=row["status"],
            step_reached=row["step_reached"],
            query_used=row["query_used"],
            error_message=row["error_message"],
        )

    @staticmethod
    def _candidate_from_row(row: sqlite3.Row) -> SourceCandidate:
        return SourceCandidate(
            id=row["id"],
            search_id=row["search_id"],
            username=row["username"],
            full_name=row["full_name"],
            follower_count=row["follower_count"],
            bio=row["bio"],
            source_type=row["source_type"],
            is_private=bool(row["is_private"]),
            is_verified=bool(row["is_verified"]),
            is_enriched=bool(row["is_enriched"]),
            avg_er=row["avg_er"],
            ai_score=row["ai_score"],
            ai_category=row["ai_category"],
            profile_pic_url=row["profile_pic_url"],
        )

    @staticmethod
    def _result_from_row(row: sqlite3.Row) -> SourceSearchResult:
        candidate = SourceCandidate(
            id=row["candidate_id"],
            search_id=row["search_id"],
            username=row["c_username"],
            full_name=row["c_full_name"],
            follower_count=row["c_follower_count"],
            bio=row["c_bio"],
            source_type=row["c_source_type"],
            is_private=bool(row["c_is_private"]),
            is_verified=bool(row["c_is_verified"]),
            is_enriched=bool(row["c_is_enriched"]),
            avg_er=row["c_avg_er"],
            ai_score=row["c_ai_score"],
            ai_category=row["c_ai_category"],
            profile_pic_url=row["c_profile_pic_url"],
        )
        return SourceSearchResult(
            id=row["id"],
            search_id=row["search_id"],
            candidate_id=row["candidate_id"],
            rank=row["rank"],
            added_to_sources=bool(row["added_to_sources"]),
            added_at=row["added_at"],
            candidate=candidate,
        )
