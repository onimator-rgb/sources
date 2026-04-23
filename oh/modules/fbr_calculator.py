"""
FBRCalculator — computes per-source Follow-Back Ratio analytics
for a single account from its data.db.

All access is READ-ONLY.  Nothing is written to the Onimator folder.

Responsibilities:
  1. Validate that data.db exists and has the expected schema
  2. Run the aggregation query (follow count + followback count per source)
  3. Compute FBR safely (no division by zero)
  4. Detect and flag data anomalies
  5. Apply quality thresholds and return a structured FBRAnalysisResult

This module has no UI dependency and no knowledge of sources.txt.
FBR is purely about data.db content.
"""
import contextlib
import sqlite3
import logging
from pathlib import Path
from typing import Optional

from oh.models.fbr import SourceFBRRecord, FBRAnalysisResult

logger = logging.getLogger(__name__)

# Columns that must be present in the sources table for analytics to work.
_REQUIRED_COLUMNS = frozenset({"source", "followback"})

# Aggregate query: count all rows per source and count the True followbacks.
# Does not filter on the `follow` column — all rows represent a historical
# follow action regardless of current follow/unfollow status.
_AGGREGATION_SQL = """
    SELECT
        TRIM(source)                                             AS source_name,
        COUNT(*)                                                 AS follow_count,
        SUM(CASE WHEN TRIM(followback) = 'True' THEN 1 ELSE 0 END) AS followback_count
    FROM sources
    WHERE source IS NOT NULL
      AND LOWER(TRIM(source)) NOT IN ('none', 'null', '')
    GROUP BY TRIM(source)
    ORDER BY follow_count DESC, source_name ASC
"""


class FBRCalculator:
    """
    Computes FBR analytics for a single account.

    Args:
        bot_root:    Absolute path to the Onimator installation folder.
        min_follows: Minimum follow count for a source to be considered quality.
        min_fbr_pct: Minimum FBR% for a source to be considered quality.
    """

    def __init__(
        self,
        bot_root: str,
        min_follows: int = 100,
        min_fbr_pct: float = 10.0,
    ) -> None:
        self._root = Path(bot_root)
        self._min_follows = min_follows
        self._min_fbr_pct = min_fbr_pct

    def calculate(self, device_id: str, username: str) -> FBRAnalysisResult:
        """
        Run FBR analytics for one account.  Always returns a result object;
        never raises.  Errors are captured in schema_valid / schema_error.
        """
        result = FBRAnalysisResult(
            device_id=device_id,
            username=username,
            min_follows=self._min_follows,
            min_fbr_pct=self._min_fbr_pct,
        )

        db_path = self._root / device_id / username / "data.db"

        if not db_path.exists():
            result.schema_valid = False
            result.schema_error = "data.db not found — no FBR data available."
            logger.debug(f"FBRCalculator: data.db missing at {db_path}")
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

        except sqlite3.DatabaseError as e:
            result.schema_valid = False
            result.schema_error = f"Cannot read data.db: {e}"
            logger.warning(f"FBRCalculator: DatabaseError for {username}@{device_id}: {e}")
            return result

        for row in rows:
            record = self._build_record(row, result)
            if record is not None:
                result.records.append(record)

        logger.debug(
            f"FBRCalculator: {username}@{device_id[:8]}… — "
            f"{len(result.records)} sources, "
            f"{result.quality_count} quality, "
            f"{result.anomaly_count} anomalies"
        )
        return result

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
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sources'"
        ).fetchone()
        if row is None:
            return "Table 'sources' not found in data.db."

        # Check required columns
        cols = {
            r["name"]
            for r in conn.execute("PRAGMA table_info(sources)").fetchall()
        }
        missing = _REQUIRED_COLUMNS - cols
        if missing:
            return (
                f"Schema mismatch in data.db — "
                f"missing column(s): {', '.join(sorted(missing))}"
            )

        return None

    def _build_record(
        self, row: sqlite3.Row, result: FBRAnalysisResult
    ) -> Optional[SourceFBRRecord]:
        """
        Build a SourceFBRRecord from one aggregation row.
        Detects anomalies and logs warnings onto the result.
        Returns None for rows that cannot be processed.
        """
        source_name    = row["source_name"]
        follow_count   = int(row["follow_count"] or 0)
        followback_count = int(row["followback_count"] or 0)

        if follow_count == 0:
            # Should not happen with COUNT(*) but guard defensively
            return None

        raw_fbr = (followback_count / follow_count) * 100
        anomaly: Optional[str] = None

        if followback_count > follow_count:
            anomaly = "followback_exceeds_follows"
            result.warnings.append(
                f"'{source_name}': followback_count ({followback_count}) "
                f"> follow_count ({follow_count}) — data anomaly"
            )
        elif raw_fbr > 100:
            anomaly = "fbr_over_100"
            result.warnings.append(
                f"'{source_name}': FBR {raw_fbr:.1f}% > 100% — data anomaly"
            )

        fbr_percent = min(raw_fbr, 100.0)   # cap for display; anomaly flag carries the truth
        is_quality  = (
            follow_count   >= self._min_follows and
            fbr_percent    >= self._min_fbr_pct and
            anomaly is None
        )

        return SourceFBRRecord(
            source_name=source_name,
            follow_count=follow_count,
            followback_count=followback_count,
            fbr_percent=fbr_percent,
            is_quality=is_quality,
            anomaly=anomaly,
        )


