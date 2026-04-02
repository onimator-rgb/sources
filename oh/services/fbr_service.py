"""
FBRService — orchestrates FBR computation, persistence, and batch analysis.

Responsibilities:
  - Run FBRCalculator for one account and save a snapshot
  - Run FBR analysis for all eligible active accounts (batch)
  - Expose the latest snapshot map for the main table

This service is the single integration point between FBRCalculator
(pure computation) and FBRSnapshotRepository (persistence).
UI layers call this service; they do not call FBRCalculator or the repo directly.
"""
import json
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.fbr import FBRAnalysisResult
from oh.models.fbr_snapshot import (
    FBRSnapshotRecord, BatchFBRResult,
    SNAPSHOT_OK, SNAPSHOT_EMPTY, SNAPSHOT_ERROR,
)
from oh.modules.fbr_calculator import FBRCalculator
from oh.modules.source_inspector import SourceInspector
from oh.repositories.account_repo import AccountRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class FBRService:
    def __init__(
        self,
        snapshot_repo: FBRSnapshotRepository,
        account_repo: AccountRepository,
        settings_repo: SettingsRepository,
        assignment_repo: SourceAssignmentRepository,
        source_profile_repo=None,
    ) -> None:
        self._snapshot_repo  = snapshot_repo
        self._account_repo   = account_repo
        self._settings       = settings_repo
        self._assignment_repo = assignment_repo
        self._source_profile_repo = source_profile_repo

    # ------------------------------------------------------------------
    # Single-account analysis + save
    # ------------------------------------------------------------------

    def analyze_and_save(
        self,
        bot_root: str,
        device_id: str,
        username: str,
        account_id: int,
    ) -> tuple[FBRAnalysisResult, FBRSnapshotRecord]:
        """
        Compute FBR for one account and persist the snapshot.

        Always returns a (result, snapshot) pair.
        Errors are captured in result.schema_valid / schema_error.
        """
        min_follows, min_fbr_pct = self._settings.get_fbr_thresholds()

        result = FBRCalculator(
            bot_root, min_follows=min_follows, min_fbr_pct=min_fbr_pct
        ).calculate(device_id, username)

        snapshot = self._build_snapshot(result, account_id)
        snapshot = self._snapshot_repo.save(snapshot)

        if result.records:
            self._snapshot_repo.save_source_results(snapshot.id, result.records)

        self._update_assignments(bot_root, device_id, username, account_id, snapshot.id)

        logger.info(
            f"FBR snapshot saved: {username}@{device_id[:8]}… "
            f"status={snapshot.status} quality={snapshot.quality_sources}/{snapshot.total_sources}"
        )
        return result, snapshot

    # ------------------------------------------------------------------
    # Batch analysis
    # ------------------------------------------------------------------

    def analyze_all_active(self, bot_root: str) -> BatchFBRResult:
        """
        Analyze all active accounts that have data_db_exists=True.

        - Skips accounts without data_db_exists.
        - Continues on per-account failures (logs the error, increments failed).
        - Saves a snapshot for every account that is attempted, even errors.
        - Returns a BatchFBRResult summary for UI display.
        """
        accounts = self._account_repo.get_all_active()
        eligible = [a for a in accounts if a.data_db_exists]
        skipped  = len(accounts) - len(eligible)

        batch = BatchFBRResult(total=len(accounts), skipped=skipped)
        min_follows, min_fbr_pct = self._settings.get_fbr_thresholds()

        for acc in eligible:
            try:
                result = FBRCalculator(
                    bot_root, min_follows=min_follows, min_fbr_pct=min_fbr_pct
                ).calculate(acc.device_id, acc.username)

                snapshot = self._build_snapshot(result, acc.id)
                snapshot = self._snapshot_repo.save(snapshot)

                if result.records:
                    self._snapshot_repo.save_source_results(snapshot.id, result.records)

                self._update_assignments(
                    bot_root, acc.device_id, acc.username, acc.id, snapshot.id
                )

                if result.schema_valid:
                    batch.succeeded += 1
                    if result.warnings:
                        batch.with_warnings += 1
                else:
                    batch.failed += 1
                    batch.errors.append(
                        f"{acc.username}: {result.schema_error}"
                    )

            except Exception as e:
                logger.warning(
                    f"FBR batch: failed for {acc.username}@{acc.device_id}: {e}"
                )
                batch.failed += 1
                batch.errors.append(f"{acc.username}: {e}")

        logger.info(
            f"FBR batch complete — "
            f"{batch.succeeded} succeeded, {batch.failed} failed, "
            f"{batch.skipped} skipped of {batch.total} active accounts"
        )

        # Update aggregated source FBR stats
        if self._source_profile_repo is not None:
            try:
                count = self._source_profile_repo.update_fbr_stats()
                logger.info("Updated FBR stats for %d sources", count)
            except Exception as exc:
                logger.warning("Failed to update source FBR stats: %s", exc)

        return batch

    # ------------------------------------------------------------------
    # Read pass-through (for main table refresh)
    # ------------------------------------------------------------------

    def get_latest_map(self) -> dict[int, FBRSnapshotRecord]:
        """Returns {account_id: FBRSnapshotRecord} for the latest snapshot per account."""
        return self._snapshot_repo.get_latest_map()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _update_assignments(
        self,
        bot_root: str,
        device_id: str,
        username: str,
        account_id: int,
        snapshot_id: int,
    ) -> None:
        """
        Read sources.txt and data.db for the account and upsert source
        assignments.  Errors are logged and swallowed — FBR analysis should
        not fail because source assignment update failed.
        """
        try:
            inspection = SourceInspector(bot_root).inspect(device_id, username)
            active_names = {s.source_name for s in inspection.sources if s.is_active}
            historical_names = {
                s.source_name
                for s in inspection.sources
                if s.is_historical and not s.is_active
            }
            self._assignment_repo.upsert_for_account(
                account_id, snapshot_id, active_names, historical_names
            )
        except Exception as e:
            logger.warning(
                f"Source assignment update failed for {username}@{device_id}: {e}"
            )

    def _build_snapshot(
        self, result: FBRAnalysisResult, account_id: int
    ) -> FBRSnapshotRecord:
        """Convert a FBRAnalysisResult into a FBRSnapshotRecord ready for saving."""
        if not result.schema_valid:
            return FBRSnapshotRecord(
                account_id=account_id,
                device_id=result.device_id,
                username=result.username,
                analyzed_at=_utcnow(),
                min_follows=result.min_follows,
                min_fbr_pct=result.min_fbr_pct,
                total_sources=0,
                quality_sources=0,
                status=SNAPSHOT_ERROR,
                schema_error=result.schema_error,
            )

        if not result.records:
            return FBRSnapshotRecord(
                account_id=account_id,
                device_id=result.device_id,
                username=result.username,
                analyzed_at=_utcnow(),
                min_follows=result.min_follows,
                min_fbr_pct=result.min_fbr_pct,
                total_sources=0,
                quality_sources=0,
                status=SNAPSHOT_EMPTY,
            )

        best  = result.best_source_by_fbr
        vol   = result.highest_volume_source
        warns = json.dumps(result.warnings) if result.warnings else None

        return FBRSnapshotRecord(
            account_id=account_id,
            device_id=result.device_id,
            username=result.username,
            analyzed_at=_utcnow(),
            min_follows=result.min_follows,
            min_fbr_pct=result.min_fbr_pct,
            total_sources=result.total_count,
            quality_sources=result.quality_count,
            best_fbr_pct=best.fbr_percent if best else None,
            best_fbr_source=best.source_name if best else None,
            highest_vol_source=vol.source_name if vol else None,
            highest_vol_count=vol.follow_count if vol else None,
            below_volume_count=result.below_volume_count,
            anomaly_count=result.anomaly_count,
            warnings_json=warns,
            status=SNAPSHOT_OK,
        )
