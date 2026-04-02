"""
AccountHealthService — computes composite health score (0-100) per account.

Score formula:
  fbr_quality_ratio * 30    — quality_sources / total_sources (from FBR snapshot)
  activity_ratio * 20       — today_follows / follow_limit (from session)
  source_health * 15        — active_sources / min_source_threshold (from source count)
  stability * 15            — inverse of TB+Limits levels
  session_regularity * 10   — has activity today? 1.0 or 0.0
  review_penalty * 10       — no review flag = 10, flagged = 0
"""
import logging
from typing import Optional

from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.session import AccountSessionRecord
from oh.models.account import AccountRecord

logger = logging.getLogger(__name__)

# Thresholds
_MIN_SOURCE_DEFAULT = 10


class AccountHealthService:

    @staticmethod
    def compute_score(
        account: AccountRecord,
        fbr: Optional[FBRSnapshotRecord],
        session: Optional[AccountSessionRecord],
        source_count: int,
        op_tags: str,
        min_source_threshold: int = _MIN_SOURCE_DEFAULT,
    ) -> float:
        """Compute health score 0-100 for an account."""
        score = 0.0

        # 1. FBR quality ratio (30 pts)
        if fbr is not None and fbr.total_sources > 0:
            ratio = fbr.quality_sources / fbr.total_sources
            score += ratio * 30
        # If no FBR data, 0 pts (needs analysis)

        # 2. Activity ratio (20 pts) — follows today vs limit
        if session is not None:
            follow_today = session.follow_count or 0
            follow_limit = session.follow_limit or 0
            if follow_limit > 0:
                ratio = min(follow_today / follow_limit, 1.0)
                score += ratio * 20
            elif follow_today > 0:
                score += 10  # some activity but no limit data

        # 3. Source health (15 pts) — active sources vs threshold
        if source_count > 0:
            ratio = min(source_count / min_source_threshold, 1.0)
            score += ratio * 15

        # 4. Stability (15 pts) — inverse of TB + Limits
        # Parse TB and limits from op_tags string like "TB3 | limits 2"
        tb_level = 0
        limits_level = 0
        if op_tags:
            for part in op_tags.split("|"):
                part = part.strip().lower()
                if part.startswith("tb"):
                    try:
                        tb_level = int(part.replace("tb", "").strip())
                    except ValueError:
                        pass
                elif part.startswith("limits"):
                    try:
                        limits_level = int(part.replace("limits", "").strip())
                    except ValueError:
                        pass
        # TB1-5 and Limits1-5, higher = worse
        # Max combined = 10 (TB5 + Limits5), we want inverse
        combined = tb_level + limits_level
        stability = max(0, 1.0 - (combined / 10.0))
        score += stability * 15

        # 5. Session regularity (10 pts) — has any activity today
        if session is not None:
            has_activity = (
                (session.follow_count or 0) > 0
                or (session.like_count or 0) > 0
            )
            score += 10 if has_activity else 0

        # 6. Review penalty (10 pts)
        review_flag = getattr(account, "review_flag", 0) or 0
        score += 0 if review_flag else 10

        return round(min(score, 100.0), 1)

    @staticmethod
    def score_color_key(score: float) -> str:
        """Return semantic color key for score."""
        if score >= 70:
            return "success"
        elif score >= 40:
            return "warning"
        return "error"

    @staticmethod
    def score_label(score: float) -> str:
        """Return label for score."""
        if score >= 70:
            return "Good"
        elif score >= 40:
            return "Fair"
        return "Poor"
