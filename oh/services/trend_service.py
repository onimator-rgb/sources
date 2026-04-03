"""
TrendService — computes performance trend data for accounts.

Reads existing session_snapshots and fbr_snapshots to build time-series
data for sparkline charts and trend analysis.
"""
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Dict, List, Optional

from oh.repositories.session_repo import SessionRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository

logger = logging.getLogger(__name__)

# Trend direction constants (duplicated here to avoid circular UI import)
TREND_UP     = "up"
TREND_DOWN   = "down"
TREND_STABLE = "stable"
TREND_NONE   = "none"

_TREND_THRESHOLD = 0.15


def compute_trend(values: List[float]) -> str:
    """Compute trend direction from a value series."""
    if len(values) < 3:
        return TREND_NONE

    mid = len(values) // 2
    first_half = values[:mid]
    second_half = values[mid:]

    avg_first = sum(first_half) / len(first_half) if first_half else 0
    avg_second = sum(second_half) / len(second_half) if second_half else 0

    if avg_first == 0:
        return TREND_NONE

    change = (avg_second - avg_first) / avg_first
    if change > _TREND_THRESHOLD:
        return TREND_UP
    elif change < -_TREND_THRESHOLD:
        return TREND_DOWN
    return TREND_STABLE


@dataclass
class AccountTrends:
    """Trend data for one account."""
    follow_trend: List[int] = field(default_factory=list)
    health_trend: List[float] = field(default_factory=list)
    fbr_trend: List[float] = field(default_factory=list)
    trend_direction: str = "none"     # up | down | stable | none


class TrendService:
    def __init__(
        self,
        session_repo: SessionRepository,
        fbr_snapshot_repo: FBRSnapshotRepository,
    ) -> None:
        self._sessions = session_repo
        self._fbr = fbr_snapshot_repo

    def get_follow_trend(
        self, account_id: int, days: int = 14
    ) -> List[int]:
        """Return daily follow counts for last N days, oldest first."""
        snapshots = self._sessions.get_recent_for_account(account_id, days)
        # Snapshots come newest first — reverse
        snapshots.reverse()
        return [s.follow_count for s in snapshots]

    def get_fbr_trend(
        self, account_id: int, days: int = 14
    ) -> List[float]:
        """Return FBR% values from snapshots, oldest first."""
        try:
            snapshots = self._fbr.get_for_account(account_id)
        except Exception:
            return []
        # Filter to recent, newest first → reverse
        result = []
        cutoff = (date.today() - timedelta(days=days)).isoformat()
        for snap in snapshots:
            if snap.analyzed_at and snap.analyzed_at[:10] >= cutoff:
                if snap.best_fbr_pct is not None:
                    result.append(snap.best_fbr_pct)
        result.reverse()
        return result

    def get_trends_map(
        self, account_ids: List[int], days: int = 14
    ) -> Dict[int, AccountTrends]:
        """Batch-compute trend data for multiple accounts.

        For efficiency, loads all session data in one query per date.
        """
        result: Dict[int, AccountTrends] = {}
        id_set = set(account_ids)

        # Load session data for last N days
        dates = []
        for i in range(days):
            d = date.today() - timedelta(days=days - 1 - i)
            dates.append(d.isoformat())

        # Build per-account follow trend from session snapshots
        daily_maps: Dict[str, Dict[int, int]] = {}
        for d_str in dates:
            try:
                day_map = self._sessions.get_map_for_date(d_str)
                daily_maps[d_str] = {
                    aid: sess.follow_count
                    for aid, sess in day_map.items()
                    if aid in id_set
                }
            except Exception:
                daily_maps[d_str] = {}

        for aid in account_ids:
            follows = []
            for d_str in dates:
                follows.append(daily_maps.get(d_str, {}).get(aid, 0))
            trends = AccountTrends(follow_trend=follows)

            trends.trend_direction = compute_trend(
                [float(f) for f in follows]
            )

            result[aid] = trends

        return result
