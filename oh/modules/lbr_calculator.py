"""
LBRCalculator — computes per-source Like-Back Ratio analytics
for a single account from its likes.db.

All access is READ-ONLY.  Nothing is written to the Onimator folder.

Responsibilities:
  1. Validate that likes.db exists and has the expected schema
  2. Run the aggregation query (like count + followback count per source)
  3. Compute LBR safely (no division by zero)
  4. Detect and flag data anomalies
  5. Apply quality thresholds and return a structured LBRAnalysisResult

This module has no UI dependency and no knowledge of like-source-followers.txt.
LBR is purely about likes.db content.
"""
import contextlib
import sqlite3
import logging
from pathlib import Path
from typing import List, Optional

from oh.models.lbr import SourceLBRRecord, LBRAnalysisResult

logger = logging.getLogger(__name__)

# Columns that must be present in the likes table for analytics to work.
_REQUIRED_COLUMNS = frozenset({"source", "liked", "follow_back"})

# Aggregate query: count all rows per source and count the follow_back = 1 rows.
_AGGREGATION_SQL = """
    SELECT
        TRIM(source)                                             AS source_name,
        COUNT(*)                                                 AS like_count,
        SUM(CASE WHEN follow_back = 1 THEN 1 ELSE 0 END)        AS followback_count
    FROM likes
    WHERE source IS NOT NULL
      AND LOWER(TRIM(source)) NOT IN ('none', 'null', '')
    GROUP BY TRIM(source)
    ORDER BY like_count DESC, source_name ASC
"""


class LBRCalculator:
    """
    Computes LBR analytics for a single account.

    Args:
        bot_root:    Absolute path to the Onimator installation folder.
        min_likes:   Minimum like count for a source to be considered quality.
        min_lbr_pct: Minimum LBR% for a source to be considered quality.
    """

    def __init__(
        self,
        bot_root: str,
        min_likes: int = 50,
        min_lbr_pct: float = 5.0,
    ) -> None:
        self._root = Path(bot_root)
        self._min_likes = min_likes
        self._min_lbr_pct = min_lbr_pct

    def calculate(self, device_id: str, username: str) -> LBRAnalysisResult:
        """
        Run LBR analytics for one account.  Always returns a result object;
        never raises.  Errors are captured in schema_valid / schema_error.
        """
        result = LBRAnalysisResult(
            device_id=device_id,
            username=username,
            min_likes=self._min_likes,
            min_lbr_pct=self._min_lbr_pct,
        )

        db_path = self._root / device_id / username / "likes.db"

        if not db_path.exists():
            result.schema_valid = False
            result.schema_error = "likes.db not found — no LBR data available."
            logger.debug(f"LBRCalculator: likes.db missing at {db_path}")
            return result

        uri = f"file:{db_path.as_posix()}?mode=ro"
        try:
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row

                schema_err = self._validate_schema(conn)
                if schema_err:
                    result.schema_valid = False
                    result.schema_error = schema_err
                    return result

                rows = conn.execute(_AGGREGATION_SQL).fetchall()

        except sqlite3.OperationalError as e:
            result.schema_valid = False
            result.schema_error = f"Cannot read likes.db: {e}"
            logger.warning(f"LBRCalculator: OperationalError for {username}@{device_id}: {e}")
            return result

        for row in rows:
            record = self._build_record(row, result)
            if record is not None:
                result.records.append(record)

        logger.debug(
            f"LBRCalculator: {username}@{device_id[:8]}… — "
            f"{len(result.records)} sources, "
            f"{result.quality_count} quality, "
            f"{result.anomaly_count} anomalies"
        )
        return result

    def read_active_sources(self, device_id: str, username: str) -> List[str]:
        """
        Read the list of currently active like sources from
        like-source-followers.txt.

        Returns an empty list if the file is missing or unreadable.
        """
        path = self._root / device_id / username / "like-source-followers.txt"
        if not path.exists():
            logger.debug(f"LBRCalculator: like-source-followers.txt missing at {path}")
            return []

        try:
            text = path.read_text(encoding="utf-8")
            sources = [
                line.strip()
                for line in text.splitlines()
                if line.strip()
            ]
            logger.debug(
                f"LBRCalculator: {username}@{device_id[:8]}… — "
                f"{len(sources)} active like sources"
            )
            return sources
        except OSError as e:
            logger.warning(
                f"LBRCalculator: cannot read like-source-followers.txt "
                f"for {username}@{device_id}: {e}"
            )
            return []

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _validate_schema(self, conn: sqlite3.Connection) -> Optional[str]:
        """
        Returns a human-readable error string if the schema is invalid,
        or None if everything looks correct.
        """
        # Check table exists
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='likes'"
        ).fetchone()
        if row is None:
            return "Table 'likes' not found in likes.db."

        # Check required columns
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(likes)").fetchall()
        }
        missing = _REQUIRED_COLUMNS - cols
        if missing:
            return (
                f"Schema mismatch in likes.db — "
                f"missing column(s): {', '.join(sorted(missing))}"
            )

        return None

    def _build_record(
        self, row: sqlite3.Row, result: LBRAnalysisResult
    ) -> Optional[SourceLBRRecord]:
        """
        Build a SourceLBRRecord from one aggregation row.
        Detects anomalies and logs warnings onto the result.
        Returns None for rows that cannot be processed.
        """
        source_name    = row["source_name"]
        like_count     = int(row["like_count"] or 0)
        followback_count = int(row["followback_count"] or 0)

        if like_count == 0:
            # Should not happen with COUNT(*) but guard defensively
            return None

        raw_lbr = (followback_count / like_count) * 100
        anomaly: Optional[str] = None

        if followback_count > like_count:
            anomaly = "followback_exceeds_likes"
            result.warnings.append(
                f"'{source_name}': followback_count ({followback_count}) "
                f"> like_count ({like_count}) — data anomaly"
            )
        elif raw_lbr > 100:
            anomaly = "lbr_over_100"
            result.warnings.append(
                f"'{source_name}': LBR {raw_lbr:.1f}% > 100% — data anomaly"
            )

        lbr_percent = min(raw_lbr, 100.0)   # cap for display; anomaly flag carries the truth
        is_quality  = (
            like_count     >= self._min_likes and
            lbr_percent    >= self._min_lbr_pct and
            anomaly is None
        )

        return SourceLBRRecord(
            source_name=source_name,
            like_count=like_count,
            followback_count=followback_count,
            lbr_percent=lbr_percent,
            is_quality=is_quality,
            anomaly=anomaly,
        )
