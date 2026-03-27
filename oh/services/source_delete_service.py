"""
SourceDeleteService — orchestrates source deletion from bot data.

DELETE SEMANTICS:
  Global delete (from Sources tab):
    Remove the source line from sources.txt for every account where
    is_active=1 in source_assignments.  Historical data in data.db is
    never touched.  source_assignments.is_active is set to 0 after
    each successful file modification.

  Bulk delete (weak sources):
    Identify sources whose weighted_fbr_pct is known and <= threshold.
    Only sources with total_follows >= min_follows_threshold are included
    (prevents deleting newly-added sources that have no follow history yet).
    Same file-level operation as global delete, applied to each matching source.

SAFETY:
  - SourceDeleter creates sources.txt.bak before every file write
  - Per-account errors are collected and reported but do not abort the run
  - source_assignments is only marked inactive after successful file removal
  - Every operation is logged to DeleteHistoryRepository
  - The caller (UI) must show confirmation before calling any delete method
"""
import logging
import socket
from datetime import datetime, timezone

from oh.models.delete_history import DeleteAction, DeleteItem, SourceDeleteResult
from oh.models.global_source import GlobalSourceRecord
from oh.modules.source_deleter import SourceDeleter
from oh.repositories.delete_history_repo import DeleteHistoryRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.services.global_sources_service import GlobalSourcesService

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SourceDeleteService:
    def __init__(
        self,
        assignment_repo: SourceAssignmentRepository,
        history_repo: DeleteHistoryRepository,
        settings_repo: SettingsRepository,
        global_sources_service: GlobalSourcesService,
    ) -> None:
        self._assignments  = assignment_repo
        self._history      = history_repo
        self._settings     = settings_repo
        self._sources_svc  = global_sources_service

    # ------------------------------------------------------------------
    # Public accessors (used by UI to avoid reaching into internals)
    # ------------------------------------------------------------------

    @property
    def history_repo(self) -> DeleteHistoryRepository:
        """Expose the history repository for the DeleteHistoryDialog."""
        return self._history

    def get_delete_threshold(self) -> float:
        """Return the configured weak-source delete threshold (FBR%)."""
        return self._settings.get_weak_source_threshold()

    # ------------------------------------------------------------------
    # Preview (read-only, no disk access)
    # ------------------------------------------------------------------

    def preview_bulk_delete(self, threshold_pct: float) -> list[GlobalSourceRecord]:
        """
        Return sources that would be deleted by bulk_delete_weak_sources().
        Read-only DB query — no disk access, safe to call repeatedly.
        """
        min_follows = int(self._settings.get("min_follows_threshold") or "100")
        return self._sources_svc.get_sources_below_threshold(threshold_pct, min_follows)

    def get_active_assignments_for_source(
        self, source_name: str
    ) -> list[tuple[int, str, str, str]]:
        """(account_id, device_id, username, device_name) for preview dialog."""
        return self._assignments.get_active_assignments_for_source(source_name)

    # ------------------------------------------------------------------
    # Single source global delete
    # ------------------------------------------------------------------

    def delete_source_globally(
        self, source_name: str, bot_root: str
    ) -> SourceDeleteResult:
        """
        Remove source_name from sources.txt for all accounts where is_active=1.
        Updates source_assignments and writes delete history.

        Returns SourceDeleteResult with per-account outcome summary.
        Never raises — errors are captured in the result.
        """
        assignments = self._assignments.get_active_assignments_for_source(source_name)
        deleter     = SourceDeleter(bot_root)
        result      = SourceDeleteResult(sources_attempted=[source_name])
        affected_usernames: list[str] = []
        item = DeleteItem(source_name=source_name, affected_accounts=[])
        files_results = []

        for acc_id, device_id, username, device_name in assignments:
            result.accounts_attempted += 1
            fr = deleter.remove_source(device_id, username, device_name, source_name)
            files_results.append((acc_id, fr))

            if fr.removed:
                result.accounts_removed += 1
                affected_usernames.append(username)
                self._assignments.mark_source_inactive(acc_id, source_name)
                item.files_removed += 1
            elif not fr.found:
                result.accounts_not_found += 1
                # Treat "already absent" as a soft success — mark inactive in OH too
                self._assignments.mark_source_inactive(acc_id, source_name)
                item.files_not_found += 1
            else:
                result.accounts_failed += 1
                err = f"{username}: {fr.error}"
                result.errors.append(err)
                item.errors.append(err)
                item.files_failed += 1

        item.affected_accounts = affected_usernames

        action = DeleteAction(
            deleted_at=_utcnow(),
            delete_type="single",
            scope="global",
            total_sources=1,
            total_accounts_affected=len(affected_usernames),
            machine=socket.gethostname(),
        )
        result.action_id = self._history.save_action(action, [item])

        logger.info(
            f"Deleted source '{source_name}' globally — "
            f"{result.accounts_removed} removed, "
            f"{result.accounts_not_found} already absent, "
            f"{result.accounts_failed} failed"
        )
        return result

    # ------------------------------------------------------------------
    # Bulk delete weak sources
    # ------------------------------------------------------------------

    def bulk_delete_weak_sources(
        self, threshold_pct: float, bot_root: str
    ) -> SourceDeleteResult:
        """
        Remove all sources whose weighted_fbr_pct is non-null and <= threshold_pct
        from all active assignments.

        Uses the same eligibility rules as preview_bulk_delete().
        Each source is deleted from all its active accounts.
        Returns an aggregate SourceDeleteResult.
        """
        sources_to_delete = self.preview_bulk_delete(threshold_pct)

        result = SourceDeleteResult(sources_attempted=[s.source_name for s in sources_to_delete])

        if not sources_to_delete:
            action = DeleteAction(
                deleted_at=_utcnow(),
                delete_type="bulk",
                scope="global",
                total_sources=0,
                total_accounts_affected=0,
                threshold_pct=threshold_pct,
                machine=socket.gethostname(),
                notes="No sources matched threshold — nothing deleted",
            )
            self._history.save_action(action, [])
            return result

        deleter = SourceDeleter(bot_root)
        items: list[DeleteItem] = []
        all_affected: set[str] = set()

        for src in sources_to_delete:
            assignments = self._assignments.get_active_assignments_for_source(src.source_name)
            item = DeleteItem(source_name=src.source_name, affected_accounts=[])

            for acc_id, device_id, username, device_name in assignments:
                result.accounts_attempted += 1
                fr = deleter.remove_source(device_id, username, device_name, src.source_name)

                if fr.removed:
                    result.accounts_removed += 1
                    item.files_removed += 1
                    item.affected_accounts.append(username)
                    all_affected.add(username)
                    self._assignments.mark_source_inactive(acc_id, src.source_name)
                elif not fr.found:
                    result.accounts_not_found += 1
                    item.files_not_found += 1
                    self._assignments.mark_source_inactive(acc_id, src.source_name)
                else:
                    result.accounts_failed += 1
                    item.files_failed += 1
                    err = f"{username}/{src.source_name}: {fr.error}"
                    result.errors.append(err)
                    item.errors.append(err)

            items.append(item)

        action = DeleteAction(
            deleted_at=_utcnow(),
            delete_type="bulk",
            scope="global",
            total_sources=len(sources_to_delete),
            total_accounts_affected=len(all_affected),
            threshold_pct=threshold_pct,
            machine=socket.gethostname(),
        )
        result.action_id = self._history.save_action(action, items)

        logger.info(
            f"Bulk delete (threshold={threshold_pct}%): "
            f"{len(sources_to_delete)} sources, "
            f"{result.accounts_removed} files removed, "
            f"{result.accounts_failed} failed"
        )
        return result
