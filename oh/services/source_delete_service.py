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
from oh.modules.source_restorer import SourceRestorer
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
        affected_details: list[dict] = []
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
                affected_details.append({
                    "account_id": acc_id,
                    "device_id": device_id,
                    "username": username,
                    "device_name": device_name,
                })
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
        item.affected_details = affected_details

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
            f"[Delete] scope=global source='{source_name}' "
            f"removed={result.accounts_removed} absent={result.accounts_not_found} "
            f"failed={result.accounts_failed} action_id={result.action_id}"
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
            item_details: list[dict] = []

            for acc_id, device_id, username, device_name in assignments:
                result.accounts_attempted += 1
                fr = deleter.remove_source(device_id, username, device_name, src.source_name)

                if fr.removed:
                    result.accounts_removed += 1
                    item.files_removed += 1
                    item.affected_accounts.append(username)
                    all_affected.add(username)
                    self._assignments.mark_source_inactive(acc_id, src.source_name)
                    item_details.append({
                        "account_id": acc_id,
                        "device_id": device_id,
                        "username": username,
                        "device_name": device_name,
                    })
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

            item.affected_details = item_details
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
            f"[Delete] scope=bulk threshold={threshold_pct}% "
            f"sources={len(sources_to_delete)} "
            f"removed={result.accounts_removed} absent={result.accounts_not_found} "
            f"failed={result.accounts_failed} action_id={result.action_id}"
        )
        return result

    # ------------------------------------------------------------------
    # Single account delete
    # ------------------------------------------------------------------

    def delete_source_for_account(
        self,
        source_name: str,
        account_id: int,
        device_id: str,
        username: str,
        device_name: str,
        bot_root: str,
    ) -> SourceDeleteResult:
        """
        Remove source_name from sources.txt for one specific account.
        Updates source_assignments and writes delete history.
        """
        deleter = SourceDeleter(bot_root)
        result = SourceDeleteResult(sources_attempted=[source_name])
        result.accounts_attempted = 1

        fr = deleter.remove_source(device_id, username, device_name, source_name)
        affected_details = []

        if fr.removed:
            result.accounts_removed = 1
            self._assignments.mark_source_inactive(account_id, source_name)
            affected_details.append({
                "account_id": account_id,
                "device_id": device_id,
                "username": username,
                "device_name": device_name,
            })
        elif not fr.found:
            result.accounts_not_found = 1
            self._assignments.mark_source_inactive(account_id, source_name)
        else:
            result.accounts_failed = 1
            result.errors.append(f"{username}: {fr.error}")

        item = DeleteItem(
            source_name=source_name,
            affected_accounts=[username] if fr.removed else [],
            affected_details=affected_details,
            files_removed=1 if fr.removed else 0,
            files_not_found=1 if (not fr.found and not fr.error) else 0,
            files_failed=1 if fr.error else 0,
            errors=[fr.error] if fr.error else [],
        )

        action = DeleteAction(
            deleted_at=_utcnow(),
            delete_type="single",
            scope="account",
            total_sources=1,
            total_accounts_affected=1 if fr.removed else 0,
            machine=socket.gethostname(),
            notes=f"Account: {username}",
        )
        result.action_id = self._history.save_action(action, [item])

        logger.info(
            f"[Delete] scope=account source='{source_name}' account={username} "
            f"removed={fr.removed} found={fr.found} backed_up={fr.backed_up} "
            f"action_id={result.action_id}"
        )
        return result

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def can_revert(self, action_id: int) -> tuple[bool, str]:
        """Check if an action can be reverted. Returns (ok, reason)."""
        action = self._history.get_action_with_items(action_id)
        if action is None:
            return False, "Action not found"
        if action.status == "reverted":
            return False, "Already reverted"
        if action.delete_type == "revert":
            return False, "Cannot revert a revert action"
        has_details = any(item.affected_details for item in action.items)
        if not has_details:
            return False, "No restore data available (old action without account details)"
        return True, ""

    def revert_action(
        self, action_id: int, bot_root: str
    ) -> SourceDeleteResult:
        """
        Revert a completed delete action by restoring sources to sources.txt
        and marking source_assignments back to active.

        Only restores items that were successfully removed (files_removed > 0).
        """
        ok, reason = self.can_revert(action_id)
        if not ok:
            raise ValueError(f"Cannot revert action {action_id}: {reason}")

        action = self._history.get_action_with_items(action_id)
        restorer = SourceRestorer(bot_root)
        result = SourceDeleteResult(
            sources_attempted=[item.source_name for item in action.items]
        )

        revert_items: list[DeleteItem] = []
        all_restored_users: set[str] = set()

        for item in action.items:
            if item.files_removed == 0:
                logger.debug(
                    f"[Revert] Skipping '{item.source_name}' — files_removed=0"
                )
                continue
            if not item.affected_details:
                logger.warning(
                    f"[Revert] Skipping '{item.source_name}' — "
                    f"files_removed={item.files_removed} but no affected_details "
                    f"(pre-migration data)"
                )
                continue

            revert_item = DeleteItem(
                source_name=item.source_name,
                affected_accounts=[],
                affected_details=[],
            )

            for detail in item.affected_details:
                result.accounts_attempted += 1
                fr = restorer.restore_source(
                    detail["device_id"],
                    detail["username"],
                    detail.get("device_name", ""),
                    item.source_name,
                )

                if fr.restored:
                    result.accounts_removed += 1  # "removed" = "processed successfully"
                    revert_item.files_removed += 1
                    revert_item.affected_accounts.append(detail["username"])
                    revert_item.affected_details.append(detail)
                    all_restored_users.add(detail["username"])
                    self._assignments.mark_source_active(
                        detail["account_id"], item.source_name
                    )
                elif fr.already_present:
                    result.accounts_not_found += 1  # "not_found" = "already present"
                    revert_item.files_not_found += 1
                    # Also mark active in OH since the source is in the file
                    self._assignments.mark_source_active(
                        detail["account_id"], item.source_name
                    )
                elif fr.error:
                    result.accounts_failed += 1
                    revert_item.files_failed += 1
                    err = f"{detail['username']}: {fr.error}"
                    result.errors.append(err)
                    revert_item.errors.append(err)

            revert_items.append(revert_item)

        # Mark original action as reverted
        self._history.mark_reverted(action_id)

        # Save the revert action
        revert_action = DeleteAction(
            deleted_at=_utcnow(),
            delete_type="revert",
            scope=action.scope,
            total_sources=len(revert_items),
            total_accounts_affected=len(all_restored_users),
            machine=socket.gethostname(),
            revert_of_action_id=action_id,
            notes=f"Revert of action #{action_id}",
        )
        result.action_id = self._history.save_action(revert_action, revert_items)

        logger.info(
            f"[Revert] original_action=#{action_id} "
            f"restored={result.accounts_removed} already_present={result.accounts_not_found} "
            f"failed={result.accounts_failed} revert_action_id={result.action_id}"
        )
        return result
