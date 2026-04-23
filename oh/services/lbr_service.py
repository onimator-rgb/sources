"""
LBRService — orchestrates LBR computation, persistence, and batch analysis.

Responsibilities:
  - Run LBRCalculator for one account and save a snapshot
  - Run LBR analysis for all eligible active accounts (batch)
  - Expose the latest snapshot map for the main table

This service is the single integration point between LBRCalculator
(pure computation) and LBRSnapshotRepository (persistence).
UI layers call this service; they do not call LBRCalculator or the repo directly.
"""
from __future__ import annotations

import json
import logging
from typing import Optional

from oh.models.lbr import LBRAnalysisResult
from oh.models.lbr_snapshot import (
    LBRSnapshotRecord, BatchLBRResult,
    SNAPSHOT_OK, SNAPSHOT_EMPTY, SNAPSHOT_ERROR,
)
from oh.modules.lbr_calculator import LBRCalculator
from oh.repositories.account_repo import AccountRepository
from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.like_source_assignment_repo import LikeSourceAssignmentRepository
from oh.utils import utcnow

logger = logging.getLogger(__name__)

# Default LBR thresholds — used when no settings keys exist
_DEFAULT_MIN_LIKES = 50
_DEFAULT_MIN_LBR_PCT = 5.0


class LBRService:
    def __init__(
        self,
        snapshot_repo: LBRSnapshotRepository,
        account_repo: AccountRepository,
        settings_repo: SettingsRepository,
        like_assignment_repo: LikeSourceAssignmentRepository,
    ) -> None:
        self._snapshot_repo = snapshot_repo
        self._account_repo = account_repo
        self._settings = settings_repo
        self._assignment_repo = like_assignment_repo

    # ------------------------------------------------------------------
    # Single-account analysis + save
    # ------------------------------------------------------------------

    def analyze_and_save(
        self,
        bot_root: str,
        device_id: str,
        username: str,
        account_id: int,
    ) -> tuple[LBRAnalysisResult, LBRSnapshotRecord]:
        """
        Compute LBR for one account and persist the snapshot.

        Always returns a (result, snapshot) pair.
        Errors are captured in result.schema_valid / schema_error.
        """
        min_likes, min_lbr_pct = self._get_lbr_thresholds()

        calc = LBRCalculator(
            bot_root, min_likes=min_likes, min_lbr_pct=min_lbr_pct
        )
        result = calc.calculate(device_id, username)

        snapshot = self._build_snapshot(result, account_id)
        snapshot = self._snapshot_repo.save(snapshot)

        if result.records:
            self._snapshot_repo.save_source_results(snapshot.id, result.records)

        self._update_like_assignments(
            calc, device_id, username, account_id, snapshot.id, result
        )

        logger.info(
            f"LBR snapshot saved: {username}@{device_id[:8]}… "
            f"status={snapshot.status} quality={snapshot.quality_sources}/{snapshot.total_sources}"
        )
        return result, snapshot

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def analyze_all_active(self, bot_root: str) -> BatchLBRResult:
        """
        Analyze all active accounts for LBR.

        - Attempts every active account (LBRCalculator handles missing likes.db).
        - Continues on per-account failures (logs the error, increments errors).
        - Saves a snapshot for every account that is attempted, even errors.
        - Returns a BatchLBRResult summary for UI display.
        """
        accounts = self._account_repo.get_all_active()
        batch = BatchLBRResult(total_accounts=len(accounts))
        min_likes, min_lbr_pct = self._get_lbr_thresholds()

        for acc in accounts:
            try:
                calc = LBRCalculator(
                    bot_root, min_likes=min_likes, min_lbr_pct=min_lbr_pct
                )
                result = calc.calculate(acc.device_id, acc.username)

                snapshot = self._build_snapshot(result, acc.id)
                snapshot = self._snapshot_repo.save(snapshot)

                if result.records:
                    self._snapshot_repo.save_source_results(snapshot.id, result.records)

                self._update_like_assignments(
                    calc, acc.device_id, acc.username, acc.id, snapshot.id, result
                )

                batch.snapshots.append(snapshot)

                if result.schema_valid:
                    batch.analyzed += 1
                else:
                    # Schema invalid = likes.db missing or unreadable — skip
                    batch.skipped += 1

            except Exception as e:
                logger.warning(
                    f"LBR batch: failed for {acc.username}@{acc.device_id}: {e}"
                )
                batch.errors += 1

        logger.info(
            f"LBR batch complete — "
            f"{batch.analyzed} analyzed, {batch.skipped} skipped, "
            f"{batch.errors} errors of {batch.total_accounts} active accounts"
        )
        return batch

    # ------------------------------------------------------------------
    # Read pass-through (for main table refresh)
    # ------------------------------------------------------------------

    def get_latest_map(self) -> dict[int, LBRSnapshotRecord]:
        """Returns {account_id: LBRSnapshotRecord} for the latest snapshot per account."""
        return self._snapshot_repo.get_latest_map()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _get_lbr_thresholds(self) -> tuple[int, float]:
        """
        Read LBR thresholds from settings, falling back to defaults.

        Uses settings keys 'min_likes_threshold' and 'min_lbr_threshold'
        if they exist; otherwise uses _DEFAULT_MIN_LIKES / _DEFAULT_MIN_LBR_PCT.
        """
        try:
            min_likes_raw = self._settings.get("min_likes_threshold")
            min_likes = int(min_likes_raw) if min_likes_raw else _DEFAULT_MIN_LIKES
        except (ValueError, TypeError):
            min_likes = _DEFAULT_MIN_LIKES

        try:
            min_lbr_raw = self._settings.get("min_lbr_threshold")
            min_lbr_pct = float(min_lbr_raw) if min_lbr_raw else _DEFAULT_MIN_LBR_PCT
        except (ValueError, TypeError):
            min_lbr_pct = _DEFAULT_MIN_LBR_PCT

        return min_likes, min_lbr_pct

    def _update_like_assignments(
        self,
        calc: LBRCalculator,
        device_id: str,
        username: str,
        account_id: int,
        snapshot_id: int,
        result: LBRAnalysisResult,
    ) -> None:
        """
        Read like-source-followers.txt and likes.db source names for the
        account and upsert like source assignments.  Errors are logged and
        swallowed — LBR analysis should not fail because source assignment
        update failed.
        """
        try:
            active_names_list = calc.read_active_sources(device_id, username)
            active_names = {n for n in active_names_list if n.strip()}

            # Historical sources = those in likes.db analysis but not in
            # like-source-followers.txt
            analyzed_names = {r.source_name for r in result.records}
            active_lower = {n.strip().lower() for n in active_names}
            historical_names = {
                name for name in analyzed_names
                if name.strip().lower() not in active_lower
            }

            self._assignment_repo.upsert_for_account(
                account_id, snapshot_id, active_names, historical_names
            )

            # Deactivate any assignments no longer in like-source-followers.txt
            self._assignment_repo.deactivate_missing(account_id, active_names)
        except Exception as e:
            logger.warning(
                f"Like source assignment update failed for {username}@{device_id}: {e}"
            )

    def _build_snapshot(
        self, result: LBRAnalysisResult, account_id: int
    ) -> LBRSnapshotRecord:
        """Convert a LBRAnalysisResult into a LBRSnapshotRecord ready for saving."""
        if not result.schema_valid:
            return LBRSnapshotRecord(
                account_id=account_id,
                device_id=result.device_id,
                username=result.username,
                analyzed_at=utcnow(),
                min_likes=result.min_likes,
                min_lbr_pct=result.min_lbr_pct,
                total_sources=0,
                quality_sources=0,
                status=SNAPSHOT_ERROR,
                schema_error=result.schema_error,
            )

        if not result.records:
            return LBRSnapshotRecord(
                account_id=account_id,
                device_id=result.device_id,
                username=result.username,
                analyzed_at=utcnow(),
                min_likes=result.min_likes,
                min_lbr_pct=result.min_lbr_pct,
                total_sources=0,
                quality_sources=0,
                status=SNAPSHOT_EMPTY,
            )

        best = result.best_source_by_lbr
        vol = result.highest_volume_source
        warns = json.dumps(result.warnings) if result.warnings else None

        return LBRSnapshotRecord(
            account_id=account_id,
            device_id=result.device_id,
            username=result.username,
            analyzed_at=utcnow(),
            min_likes=result.min_likes,
            min_lbr_pct=result.min_lbr_pct,
            total_sources=result.total_count,
            quality_sources=result.quality_count,
            best_lbr_pct=best.lbr_percent if best else None,
            best_lbr_source=best.source_name if best else None,
            highest_vol_source=vol.source_name if vol else None,
            highest_vol_count=vol.like_count if vol else None,
            below_volume_count=result.below_volume_count,
            anomaly_count=result.anomaly_count,
            warnings_json=warns,
            status=SNAPSHOT_OK,
        )
