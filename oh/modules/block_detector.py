"""
BlockDetector — stateless reader that detects Instagram block/ban signals
from bot files (.stm, data.db patterns, session history).

Detection strategies:
  1. Consecutive zero days — 2+ days of zero activity on running device → action_block
  2. Sudden activity drop — today < 30% of 3-day average → shadow_ban suspect
  3. Effective limit drop — .stm limit file < 50% of configured → rate_limit
  4. Challenge marker — .stm/challenge-* files → challenge
  5. Zero with follow_enabled — zero follows in active slot → action_block (high confidence)

All file access is read-only.  Missing files produce no signal, not errors.
"""
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

from oh.models.block_event import (
    BlockSignal,
    BLOCK_ACTION_BLOCK,
    BLOCK_CHALLENGE,
    BLOCK_SHADOW_BAN,
    BLOCK_RATE_LIMIT,
)
from oh.models.session import AccountSessionRecord

logger = logging.getLogger(__name__)


class BlockDetector:
    """Stateless block/ban signal detector."""

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    def detect_for_account(
        self,
        device_id: str,
        username: str,
        session_history: List[AccountSessionRecord],
        configured_follow_limit: int,
        device_status: Optional[str] = None,
        follow_enabled: bool = True,
    ) -> List[BlockSignal]:
        """
        Analyse an account for block/ban signals.

        Args:
            device_id: Device identifier
            username: Account username
            session_history: Recent session snapshots (newest first), ideally 7+ days
            configured_follow_limit: The base follow limit from settings.db
            device_status: 'running' | 'stop' | None
            follow_enabled: Whether follow is enabled for the account

        Returns:
            List of BlockSignal objects (may be empty).
        """
        if not follow_enabled:
            return []

        signals: List[BlockSignal] = []
        account_path = self._root / device_id / username

        # Strategy 1 & 5: Consecutive zero days / zero on running device
        signals.extend(
            self._check_zero_activity(session_history, device_status)
        )

        # Strategy 2: Sudden activity drop
        signal = self._check_activity_drop(session_history)
        if signal:
            signals.append(signal)

        # Strategy 3: Effective limit drop via .stm files
        signal = self._check_limit_drop(
            account_path, configured_follow_limit
        )
        if signal:
            signals.append(signal)

        # Strategy 4: Challenge marker files
        signal = self._check_challenge_markers(account_path)
        if signal:
            signals.append(signal)

        return signals

    # ------------------------------------------------------------------
    # Detection strategies
    # ------------------------------------------------------------------

    def _check_zero_activity(
        self,
        history: List[AccountSessionRecord],
        device_status: Optional[str],
    ) -> List[BlockSignal]:
        """Detect zero-activity patterns."""
        signals = []
        if not history:
            return signals

        # Count consecutive zero-follow days (from most recent)
        zero_days = 0
        for sess in history:
            if sess.follow_count == 0:
                zero_days += 1
            else:
                break

        # Today has zero follows on a running device
        latest = history[0]
        if (latest.follow_count == 0
                and device_status == "running"
                and latest.snapshot_date == date.today().isoformat()):
            confidence = min(0.5 + zero_days * 0.15, 0.95)
            signals.append(BlockSignal(
                event_type=BLOCK_ACTION_BLOCK,
                confidence=confidence,
                evidence={
                    "reason": "Zero follows on running device",
                    "consecutive_zero_days": zero_days,
                    "date": latest.snapshot_date,
                },
            ))

        # 2+ consecutive zero days (even if device not running today)
        elif zero_days >= 2:
            signals.append(BlockSignal(
                event_type=BLOCK_ACTION_BLOCK,
                confidence=min(0.4 + zero_days * 0.15, 0.9),
                evidence={
                    "reason": "Consecutive zero-activity days",
                    "consecutive_zero_days": zero_days,
                },
            ))

        return signals

    def _check_activity_drop(
        self,
        history: List[AccountSessionRecord],
    ) -> Optional[BlockSignal]:
        """Detect sudden drop in follow activity (shadow ban signal)."""
        if len(history) < 4:
            return None

        today = history[0]
        if today.snapshot_date != date.today().isoformat():
            return None
        if today.follow_count == 0:
            return None  # handled by zero-activity check

        # Average of days 1-3 (yesterday, day before, etc.)
        recent_avg = sum(h.follow_count for h in history[1:4]) / 3.0
        if recent_avg < 10:
            return None  # too little data to judge

        ratio = today.follow_count / recent_avg
        if ratio < 0.3:
            return BlockSignal(
                event_type=BLOCK_SHADOW_BAN,
                confidence=min(0.5 + (1.0 - ratio) * 0.4, 0.85),
                evidence={
                    "reason": "Follow count dropped to <30% of 3-day average",
                    "today_follows": today.follow_count,
                    "three_day_avg": round(recent_avg, 1),
                    "ratio": round(ratio, 3),
                },
            )
        return None

    def _check_limit_drop(
        self,
        account_path: Path,
        configured_limit: int,
    ) -> Optional[BlockSignal]:
        """Check .stm for effective limit drop (rate limiting signal)."""
        if configured_limit <= 0:
            return None

        stm_dir = account_path / ".stm"
        if not stm_dir.is_dir():
            return None

        today_str = date.today().isoformat()
        limit_file = stm_dir / f"follow-action-limit-per-day-{today_str}.txt"
        if not limit_file.exists():
            return None

        try:
            effective = int(limit_file.read_text().strip())
        except (ValueError, OSError):
            return None

        ratio = effective / configured_limit
        if ratio < 0.5:
            return BlockSignal(
                event_type=BLOCK_RATE_LIMIT,
                confidence=min(0.6 + (1.0 - ratio) * 0.3, 0.9),
                evidence={
                    "reason": "Effective limit dropped below 50% of configured",
                    "configured_limit": configured_limit,
                    "effective_limit": effective,
                    "ratio": round(ratio, 3),
                },
            )
        return None

    def _check_challenge_markers(
        self,
        account_path: Path,
    ) -> Optional[BlockSignal]:
        """Check for challenge/checkpoint marker files in .stm."""
        stm_dir = account_path / ".stm"
        if not stm_dir.is_dir():
            return None

        challenge_patterns = [
            "challenge-required*",
            "checkpoint-required*",
            "verification-required*",
        ]

        for pattern in challenge_patterns:
            matches = list(stm_dir.glob(pattern))
            if matches:
                return BlockSignal(
                    event_type=BLOCK_CHALLENGE,
                    confidence=0.9,
                    evidence={
                        "reason": "Challenge/verification marker file found",
                        "files": [m.name for m in matches[:3]],
                    },
                )
        return None
