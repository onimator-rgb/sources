"""
GlobalSourcesService — orchestrates source assignment refresh and data reads.

Two paths update source_assignments:
  1. FBRService.analyze_and_save / analyze_all_active — updates assignments as a
     side-effect of FBR analysis (uses SourceInspector, runs on every FBR run).
  2. GlobalSourcesService.refresh_assignments — manual refresh path that only
     reads sources.txt + data.db; does NOT recompute FBR.  Used by the Sources
     tab "Refresh Sources" button to let operators update source assignments
     independently of FBR analysis.

The Sources tab reads all data from the DB (no disk access on open).
"""
import logging
from dataclasses import dataclass, field

from oh.models.global_source import GlobalSourceRecord, SourceAccountDetail
from oh.modules.source_inspector import SourceInspector
from oh.repositories.account_repo import AccountRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository

logger = logging.getLogger(__name__)


@dataclass
class SourceRefreshResult:
    """Summary returned to the UI after a refresh_assignments run."""
    total: int = 0
    refreshed: int = 0
    skipped: int = 0      # account has neither sources.txt nor data.db
    failed: int = 0
    errors: list[str] = field(default_factory=list)

    def status_line(self) -> str:
        parts = [f"✓ {self.refreshed} indexed"]
        if self.skipped:
            parts.append(f"↷ {self.skipped} skipped")
        if self.failed:
            parts.append(f"✗ {self.failed} failed")
        return "  ·  ".join(parts) + f"  (of {self.total} active accounts)"


class GlobalSourcesService:
    def __init__(
        self,
        account_repo: AccountRepository,
        assignment_repo: SourceAssignmentRepository,
    ) -> None:
        self._accounts    = account_repo
        self._assignments = assignment_repo

    # ------------------------------------------------------------------
    # Refresh (hits disk)
    # ------------------------------------------------------------------

    def refresh_assignments(self, bot_root: str) -> SourceRefreshResult:
        """
        Read sources.txt and data.db for every active account and upsert
        source assignments.  Does not recompute FBR.

        Accounts with neither file are skipped (counted as skipped).
        Errors per account are logged and collected; processing continues.
        """
        accounts  = self._accounts.get_all_active()
        result    = SourceRefreshResult(total=len(accounts))
        inspector = SourceInspector(bot_root)

        for acc in accounts:
            try:
                inspection = inspector.inspect(acc.device_id, acc.username)

                if not inspection.has_data:
                    result.skipped += 1
                    continue

                active_names = {
                    s.source_name for s in inspection.sources if s.is_active
                }
                historical_names = {
                    s.source_name
                    for s in inspection.sources
                    if s.is_historical and not s.is_active
                }

                self._assignments.upsert_for_account(
                    acc.id, None, active_names, historical_names
                )
                result.refreshed += 1

            except Exception as e:
                logger.warning(
                    f"Source refresh failed for {acc.username}@{acc.device_id}: {e}"
                )
                result.failed += 1
                result.errors.append(f"{acc.username}: {e}")

        logger.info(
            f"Source refresh — {result.refreshed} refreshed, "
            f"{result.skipped} skipped, {result.failed} failed "
            f"of {result.total} active accounts"
        )
        return result

    # ------------------------------------------------------------------
    # Reads (DB only, no disk)
    # ------------------------------------------------------------------

    def get_global_sources(self) -> list[GlobalSourceRecord]:
        return self._assignments.get_global_sources()

    def get_accounts_for_source(self, source_name: str) -> list[SourceAccountDetail]:
        return self._assignments.get_accounts_for_source(source_name)

    def has_any_data(self) -> bool:
        return self._assignments.has_any_data()

    def get_active_source_counts(self) -> dict[int, int]:
        """Returns {account_id: active_source_count} for source count column."""
        return self._assignments.get_active_source_counts()

    def get_sources_below_threshold(
        self, threshold_pct: float, min_follows: int = 0
    ) -> list[GlobalSourceRecord]:
        """
        Return sources eligible for bulk weak-source deletion.

        Eligibility rules (all must be true):
          - weighted_fbr_pct is not None (has actual follow data — no blind deletes)
          - weighted_fbr_pct <= threshold_pct
          - total_follows >= min_follows (enough data to be confident)
          - active_accounts > 0 (only delete from active assignments)
        """
        return [
            src for src in self._assignments.get_global_sources()
            if src.weighted_fbr_pct is not None
            and src.weighted_fbr_pct <= threshold_pct
            and src.total_follows >= min_follows
            and src.active_accounts > 0
        ]
