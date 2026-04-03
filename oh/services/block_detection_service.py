"""
BlockDetectionService — orchestrates block/ban detection across accounts.

Called after Scan & Sync (session collection).  Runs BlockDetector for
each active account, persists new events, and auto-resolves events
when block signals disappear.
"""
import json
import logging
from typing import Dict, List, Optional

from oh.models.account import AccountRecord
from oh.models.block_event import (
    BlockEvent,
    BlockSignal,
    BlockScanResult,
    BLOCK_SEVERITY,
)
from oh.models.session import AccountSessionRecord
from oh.modules.block_detector import BlockDetector
from oh.repositories.block_event_repo import BlockEventRepository
from oh.repositories.session_repo import SessionRepository

logger = logging.getLogger(__name__)

# Minimum confidence to create a block event
_MIN_CONFIDENCE = 0.5


class BlockDetectionService:
    def __init__(
        self,
        block_repo: BlockEventRepository,
        session_repo: SessionRepository,
    ) -> None:
        self._blocks = block_repo
        self._sessions = session_repo

    # ------------------------------------------------------------------
    # Scanning
    # ------------------------------------------------------------------

    def scan_all_accounts(
        self,
        bot_root: str,
        accounts: List[AccountRecord],
        session_map: Dict[int, AccountSessionRecord],
        device_status_map: Dict[str, str],
    ) -> BlockScanResult:
        """
        Run block detection for all active accounts.

        Creates new block events for new detections,
        auto-resolves events when signals disappear.
        """
        result = BlockScanResult()
        detector = BlockDetector(bot_root)
        active_blocks = self._blocks.get_active_map()

        for acc in accounts:
            if not acc.is_active or acc.id is None:
                continue

            result.total_scanned += 1
            try:
                # Get session history for this account
                history = self._sessions.get_recent_for_account(
                    acc.id, days=7
                )

                # Get configured follow limit
                try:
                    configured_limit = int(acc.follow_limit_perday or 0)
                except (ValueError, TypeError):
                    configured_limit = 0

                device_status = device_status_map.get(acc.device_id)

                # Detect signals
                signals = detector.detect_for_account(
                    device_id=acc.device_id,
                    username=acc.username,
                    session_history=history,
                    configured_follow_limit=configured_limit,
                    device_status=device_status,
                    follow_enabled=bool(acc.follow_enabled),
                )

                # Filter by confidence
                strong_signals = [
                    s for s in signals if s.confidence >= _MIN_CONFIDENCE
                ]

                # Get existing active blocks for this account
                existing = active_blocks.get(acc.id, [])
                existing_types = {e.event_type for e in existing}
                signal_types = {s.event_type for s in strong_signals}

                # Create new events for new signal types
                for signal in strong_signals:
                    if signal.event_type not in existing_types:
                        event = BlockEvent(
                            account_id=acc.id,
                            event_type=signal.event_type,
                            detected_at="",  # repo sets timestamp
                            evidence=json.dumps(signal.evidence),
                            auto_detected=True,
                        )
                        self._blocks.save(event)
                        result.new_blocks += 1
                        logger.info(
                            f"[Block] New {signal.event_type} detected: "
                            f"{acc.username} (confidence={signal.confidence:.2f})"
                        )

                # Auto-resolve events whose signals disappeared
                for existing_event in existing:
                    if existing_event.event_type not in signal_types:
                        self._blocks.resolve(existing_event.id)
                        result.resolved += 1
                        logger.info(
                            f"[Block] Auto-resolved {existing_event.event_type}: "
                            f"{acc.username}"
                        )

                # Count still-active
                still = len(signal_types & existing_types)
                result.still_active += still

            except Exception as exc:
                result.errors += 1
                logger.warning(
                    f"Block detection failed for {acc.username}: {exc}",
                    exc_info=True,
                )

        logger.info(
            f"Block scan complete: {result.total_scanned} scanned, "
            f"{result.new_blocks} new, {result.resolved} resolved, "
            f"{result.still_active} active, {result.errors} errors"
        )
        return result

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_blocks(self) -> Dict[int, List[BlockEvent]]:
        """Return {account_id: [BlockEvent]} for all active blocks."""
        return self._blocks.get_active_map()

    def get_active_count(self) -> int:
        """Return total number of active block events."""
        return len(self._blocks.get_active_all())

    def resolve_manually(self, event_id: int) -> None:
        """Mark a block event as manually resolved by operator."""
        self._blocks.resolve(event_id)
        logger.info(f"[Block] Manually resolved event {event_id}")

    def get_block_summary(self) -> Dict[str, int]:
        """Return {event_type: count} for active blocks."""
        events = self._blocks.get_active_all()
        summary: Dict[str, int] = {}
        for ev in events:
            summary[ev.event_type] = summary.get(ev.event_type, 0) + 1
        return summary
