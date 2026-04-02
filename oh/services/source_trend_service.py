"""
SourceTrendService — computes FBR trends per source over time.

Analyzes fbr_source_results across snapshots to detect improving,
declining, or stable source performance.  Also provides cross-account
niche performance analysis for source optimisation.
"""
import logging
import sqlite3
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# Trend constants
TREND_UP = "up"         # FBR improving
TREND_DOWN = "down"     # FBR declining
TREND_STABLE = "stable" # No significant change
TREND_NEW = "new"       # Not enough data


class SourceTrendService:
    """Computes source FBR trends from historical snapshot data."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Feature A — Source Performance Trends
    # ------------------------------------------------------------------

    def get_source_trends(self, days: int = 14) -> Dict[str, dict]:
        """
        Compute FBR trends for all sources over the last *days* days.

        Returns:
            dict mapping source_name -> {
                "trend": TREND_UP/DOWN/STABLE/NEW,
                "current_fbr": float,    # latest weighted FBR
                "previous_fbr": float,   # FBR from N days ago
                "change_pct": float,     # percentage change
                "data_points": int,      # number of snapshots
            }
        """
        half = days // 2

        query = """
            SELECT
                r.source_name,
                CASE WHEN julianday('now') - julianday(s.analyzed_at) <= ?
                     THEN 'recent' ELSE 'older' END AS period,
                SUM(r.follow_count)       AS total_follows,
                SUM(r.followback_count)   AS total_followbacks,
                COUNT(DISTINCT s.id)      AS snapshots
            FROM fbr_source_results r
            JOIN fbr_snapshots s ON s.id = r.snapshot_id
            WHERE julianday('now') - julianday(s.analyzed_at) <= ?
            GROUP BY r.source_name, period
        """

        try:
            rows = self._conn.execute(query, (half, days)).fetchall()
        except Exception:
            logger.exception("Failed to query source trends")
            return {}

        # Build per-source data
        source_data: Dict[str, dict] = {}
        for row in rows:
            name = row["source_name"]
            if name not in source_data:
                source_data[name] = {"recent": None, "older": None}

            follows = row["total_follows"] or 0
            followbacks = row["total_followbacks"] or 0
            fbr = (followbacks / follows * 100) if follows > 0 else 0.0

            source_data[name][row["period"]] = {
                "fbr": fbr,
                "follows": follows,
                "followbacks": followbacks,
                "snapshots": row["snapshots"],
            }

        # Compute trends
        results: Dict[str, dict] = {}
        for name, data in source_data.items():
            recent = data.get("recent")
            older = data.get("older")

            if recent is None:
                # Only old data, no recent activity
                if older is not None:
                    results[name] = {
                        "trend": TREND_DOWN,
                        "current_fbr": 0.0,
                        "previous_fbr": older["fbr"],
                        "change_pct": -100.0,
                        "data_points": older["snapshots"],
                    }
                continue

            current_fbr = recent["fbr"]

            if older is None:
                # Only recent data — new source
                results[name] = {
                    "trend": TREND_NEW,
                    "current_fbr": current_fbr,
                    "previous_fbr": 0.0,
                    "change_pct": 0.0,
                    "data_points": recent["snapshots"],
                }
                continue

            previous_fbr = older["fbr"]

            # Calculate change
            if previous_fbr > 0:
                change_pct = ((current_fbr - previous_fbr) / previous_fbr) * 100
            else:
                change_pct = 100.0 if current_fbr > 0 else 0.0

            # Determine trend (>15% change = significant)
            if change_pct > 15:
                trend = TREND_UP
            elif change_pct < -15:
                trend = TREND_DOWN
            else:
                trend = TREND_STABLE

            results[name] = {
                "trend": trend,
                "current_fbr": round(current_fbr, 2),
                "previous_fbr": round(previous_fbr, 2),
                "change_pct": round(change_pct, 1),
                "data_points": recent["snapshots"] + older["snapshots"],
            }

        return results

    # ------------------------------------------------------------------
    # Feature B — Cross-Account Source Optimizer
    # ------------------------------------------------------------------

    def get_niche_performance(self) -> Dict[str, Dict[str, dict]]:
        """
        Analyze source FBR performance grouped by account niche.

        Returns:
            dict mapping source_name -> {
                niche_name -> {
                    "accounts": int,
                    "avg_fbr": float,
                    "total_follows": int,
                }
            }

        Useful for identifying sources that perform well in one niche
        but poorly in another.
        """
        query = """
            SELECT
                r.source_name,
                COALESCE(sp.niche_category, 'unknown') AS niche,
                COUNT(DISTINCT s.account_id) AS accounts,
                AVG(r.fbr_percent)           AS avg_fbr,
                SUM(r.follow_count)          AS total_follows
            FROM fbr_source_results r
            JOIN fbr_snapshots s ON s.id = r.snapshot_id
            LEFT JOIN source_profiles sp
                ON LOWER(r.source_name) = LOWER(sp.source_name)
            WHERE r.follow_count >= 10
            GROUP BY r.source_name, niche
            ORDER BY r.source_name, avg_fbr DESC
        """

        try:
            rows = self._conn.execute(query).fetchall()
        except Exception:
            logger.exception("Failed to query niche performance")
            return {}

        result: Dict[str, Dict[str, dict]] = {}
        for row in rows:
            name = row["source_name"]
            if name not in result:
                result[name] = {}
            result[name][row["niche"]] = {
                "accounts": row["accounts"],
                "avg_fbr": round(row["avg_fbr"] or 0, 2),
                "total_follows": row["total_follows"] or 0,
            }

        return result

    def get_mismatched_sources(
        self, min_variance: float = 50.0
    ) -> List[dict]:
        """
        Find sources with high FBR variance between niches.

        Returns list of dicts:
            {
                "source_name": str,
                "best_niche": str,
                "best_fbr": float,
                "best_accounts": int,
                "worst_niche": str,
                "worst_fbr": float,
                "worst_accounts": int,
                "variance_pct": float,
                "suggestion": str,
            }
        """
        niche_data = self.get_niche_performance()
        mismatched: List[dict] = []

        for source_name, niches in niche_data.items():
            if len(niches) < 2:
                continue

            sorted_niches = sorted(
                niches.items(),
                key=lambda x: x[1]["avg_fbr"],
                reverse=True,
            )

            best_niche, best_data = sorted_niches[0]
            worst_niche, worst_data = sorted_niches[-1]

            if best_data["avg_fbr"] <= 0:
                continue

            variance = (
                (best_data["avg_fbr"] - worst_data["avg_fbr"])
                / best_data["avg_fbr"]
            ) * 100

            if variance >= min_variance:
                mismatched.append({
                    "source_name": source_name,
                    "best_niche": best_niche,
                    "best_fbr": best_data["avg_fbr"],
                    "best_accounts": best_data["accounts"],
                    "worst_niche": worst_niche,
                    "worst_fbr": worst_data["avg_fbr"],
                    "worst_accounts": worst_data["accounts"],
                    "variance_pct": round(variance, 1),
                    "suggestion": (
                        f"Remove @{source_name} from {worst_niche} accounts "
                        f"({worst_data['avg_fbr']:.1f}% FBR), keep on "
                        f"{best_niche} ({best_data['avg_fbr']:.1f}% FBR)"
                    ),
                })

        mismatched.sort(key=lambda x: x["variance_pct"], reverse=True)
        return mismatched
