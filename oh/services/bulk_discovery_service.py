"""
BulkDiscoveryService — orchestrates bulk source discovery across multiple accounts.

Pipeline:
  1. Identify accounts below source threshold
  2. For each: snapshot sources.txt, run search, auto-add top N, record results
  3. Support full revert (remove added, restore originals)
"""
import json
import logging
import socket
import time
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from oh.models.account import AccountRecord
from oh.models.bulk_discovery import (
    BulkDiscoveryItem, BulkDiscoveryRun,
    BULK_COMPLETED, BULK_CANCELLED, BULK_FAILED, BULK_RUNNING,
    ITEM_DONE, ITEM_FAILED, ITEM_RUNNING, ITEM_SKIPPED,
)
from oh.models.source_finder import SourceSearchResult
from oh.modules.source_deleter import SourceDeleter
from oh.modules.source_restorer import SourceRestorer
from oh.modules.source_finder import HikerAPIError
from oh.repositories.account_repo import AccountRepository
from oh.repositories.bulk_discovery_repo import BulkDiscoveryRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.services.source_finder_service import SourceFinderService

logger = logging.getLogger(__name__)

_INTER_ACCOUNT_DELAY = 2.0   # seconds between accounts
_RATE_LIMIT_PAUSE = 60       # seconds to wait on rate limit
_MAX_RETRIES = 3             # per-account retry on rate limit


class BulkDiscoveryService:
    """
    Coordinates bulk source discovery: identifies under-sourced accounts,
    runs searches for each, auto-adds top results, and supports full revert.
    """

    def __init__(
        self,
        bulk_repo: BulkDiscoveryRepository,
        source_finder_service: SourceFinderService,
        account_repo: AccountRepository,
        assignment_repo: SourceAssignmentRepository,
        settings_repo: SettingsRepository,
    ) -> None:
        self._bulk_repo = bulk_repo
        self._finder_svc = source_finder_service
        self._account_repo = account_repo
        self._assignments = assignment_repo
        self._settings = settings_repo

        # Recover any stale runs from previous crash / interrupted sessions
        self._bulk_repo.recover_stale_runs(max_age_hours=24)

    # ------------------------------------------------------------------
    # Qualifying accounts
    # ------------------------------------------------------------------

    def get_qualifying_accounts(
        self, min_threshold: int
    ) -> List[Tuple[AccountRecord, int]]:
        """
        Return accounts with fewer active sources than *min_threshold*.

        Results are sorted by source count ascending (most needy first).
        Each element is (account, current_source_count).
        """
        accounts = self._account_repo.get_all_active()
        source_counts = self._assignments.get_active_source_counts()

        qualifying: List[Tuple[AccountRecord, int]] = []
        for acct in accounts:
            count = source_counts.get(acct.id, 0)
            if count < min_threshold:
                qualifying.append((acct, count))

        qualifying.sort(key=lambda pair: pair[1])
        return qualifying

    # ------------------------------------------------------------------
    # Bulk discovery run
    # ------------------------------------------------------------------

    def run_bulk_discovery(
        self,
        account_ids: List[int],
        min_threshold: int,
        auto_add_top_n: int,
        bot_root: str,
        progress_callback: Optional[Callable[[int, str, str, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> BulkDiscoveryRun:
        """
        Execute bulk source discovery for a list of accounts.

        Args:
            account_ids:       OH account ids to process.
            min_threshold:     minimum source count target.
            auto_add_top_n:    how many top results to auto-add per account.
            bot_root:          path to the bot directory root.
            progress_callback: optional (account_index, username, status,
                               step_pct, step_msg) callback for UI.
            cancel_check:      optional callable returning True if cancelled.

        Returns the completed BulkDiscoveryRun with items attached.
        Per-item errors do not abort the batch.
        """

        def _progress(idx: int, uname: str, status: str, pct: int, msg: str) -> None:
            if progress_callback is not None:
                progress_callback(idx, uname, status, pct, msg)

        def _cancelled() -> bool:
            return cancel_check is not None and cancel_check()

        # ── Create run ──────────────────────────────────────────────
        run = self._bulk_repo.create_run(
            min_threshold=min_threshold,
            auto_add_top_n=auto_add_top_n,
            total_accounts=len(account_ids),
            machine=socket.gethostname(),
        )

        # ── Load accounts and create items ──────────────────────────
        accounts_by_id = {}
        items: List[BulkDiscoveryItem] = []
        source_counts = self._assignments.get_active_source_counts()

        for acc_id in account_ids:
            acct = self._account_repo.get_by_id(acc_id)
            if acct is None:
                logger.warning(
                    "Bulk discovery: account_id=%d not found, skipping", acc_id,
                )
                continue
            accounts_by_id[acc_id] = acct
            sources_before = source_counts.get(acc_id, 0)
            item = self._bulk_repo.create_item(
                run_id=run.id,
                account_id=acc_id,
                username=acct.username,
                device_id=acct.device_id,
                sources_before=sources_before,
            )
            items.append(item)

        # ── Process each account ────────────────────────────────────
        accounts_done = 0
        accounts_failed = 0
        total_added = 0

        for idx, item in enumerate(items):
            # Check cancel
            if _cancelled():
                logger.info("Bulk discovery run %d cancelled by user", run.id)
                # Mark remaining items as skipped
                for remaining in items[idx:]:
                    self._bulk_repo.update_item(
                        remaining.id, status=ITEM_SKIPPED,
                    )
                self._bulk_repo.complete_run(run.id, BULK_CANCELLED)
                run = self._bulk_repo.get_run_with_items(run.id)
                return run

            acct = accounts_by_id.get(item.account_id)
            if acct is None:
                continue

            username = acct.username
            _progress(idx, username, ITEM_RUNNING, 0, "Starting...")

            # Mark item as running
            self._bulk_repo.update_item(item.id, status=ITEM_RUNNING)

            try:
                # Snapshot original sources.txt
                original_sources = self._read_sources_file(
                    bot_root, acct.device_id, username,
                )
                original_sources_json = json.dumps(original_sources)

                # Run search with retry on rate limit
                search_results: List[SourceSearchResult] = []
                retries = 0
                while True:
                    try:
                        def _inner_progress(pct: int, msg: str) -> None:
                            _progress(idx, username, ITEM_RUNNING, pct, msg)

                        search_results = self._finder_svc.run_search(
                            account_id=item.account_id,
                            progress_callback=_inner_progress,
                            cancel_check=cancel_check,
                        )
                        break
                    except HikerAPIError as exc:
                        if "rate limit" in str(exc).lower() and retries < _MAX_RETRIES:
                            retries += 1
                            logger.warning(
                                "Rate limit hit for @%s (attempt %d/%d), "
                                "pausing %ds...",
                                username, retries, _MAX_RETRIES,
                                _RATE_LIMIT_PAUSE,
                            )
                            _progress(
                                idx, username, ITEM_RUNNING, 0,
                                f"Rate limited, waiting {_RATE_LIMIT_PAUSE}s "
                                f"(retry {retries}/{_MAX_RETRIES})...",
                            )
                            for _ in range(_RATE_LIMIT_PAUSE * 10):  # 10 checks per second
                                if _cancelled():
                                    break
                                time.sleep(0.1)
                        else:
                            raise

                # Take top N results
                top_results = search_results[:auto_add_top_n]

                # Auto-add each result to sources.txt
                added_sources: List[str] = []
                search_id = None
                for result in top_results:
                    if result.candidate is not None:
                        source_username = result.candidate.username
                        add_status = self._finder_svc.add_to_sources(
                            result.id, item.account_id, bot_root,
                        )
                        if add_status == SourceFinderService.ADD_OK:
                            added_sources.append(source_username)
                    if search_id is None:
                        search_id = result.search_id

                # Calculate sources after
                sources_after = item.sources_before + len(added_sources)

                # Update item with success
                self._bulk_repo.update_item(
                    item.id,
                    status=ITEM_DONE,
                    search_id=search_id,
                    sources_added=len(added_sources),
                    sources_after=sources_after,
                    added_sources_json=json.dumps(added_sources),
                    original_sources_json=original_sources_json,
                )

                accounts_done += 1
                total_added += len(added_sources)

                _progress(
                    idx, username, ITEM_DONE, 100,
                    f"Done — added {len(added_sources)} sources",
                )
                logger.info(
                    "Bulk discovery: @%s done — added %d sources "
                    "(before=%d, after=%d)",
                    username, len(added_sources),
                    item.sources_before, sources_after,
                )

            except Exception as exc:
                accounts_failed += 1
                error_msg = str(exc)
                self._bulk_repo.update_item(
                    item.id,
                    status=ITEM_FAILED,
                    error_message=error_msg,
                )

                _progress(idx, username, ITEM_FAILED, 0, f"Error: {error_msg}")
                logger.error(
                    "Bulk discovery: @%s failed: %s", username, exc,
                )

            # Update run progress
            self._bulk_repo.update_run_progress(
                run.id,
                accounts_done=accounts_done,
                accounts_failed=accounts_failed,
                total_added=total_added,
            )

            # Delay between accounts (skip after last)
            if idx < len(items) - 1:
                time.sleep(_INTER_ACCOUNT_DELAY)

        # ── Complete run ────────────────────────────────────────────
        if accounts_done == 0 and accounts_failed > 0:
            final_status = BULK_FAILED
        else:
            final_status = BULK_COMPLETED

        self._bulk_repo.complete_run(run.id, final_status)

        run = self._bulk_repo.get_run_with_items(run.id)
        logger.info(
            "Bulk discovery run %d completed: done=%d, failed=%d, added=%d",
            run.id, accounts_done, accounts_failed, total_added,
        )
        return run

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def revert_run(
        self, run_id: int, bot_root: Optional[str] = None
    ) -> Tuple[int, int, List[str]]:
        """
        Revert an entire bulk discovery run.

        For each successfully processed item, removes added sources and
        restores any missing original sources.

        Returns:
            (reverted_count, failed_count, errors)
        """
        if not bot_root:
            bot_root = self._settings.get("bot_root_path") or ""
        if not bot_root:
            return 0, 0, ["Bot root path not configured"]

        run = self._bulk_repo.get_run_with_items(run_id)
        if run is None:
            return 0, 0, ["Run not found"]

        reverted_count = 0
        failed_count = 0
        errors: List[str] = []

        deleter = SourceDeleter(bot_root)
        restorer = SourceRestorer(bot_root)

        for item in (run.items or []):
            if item.status != ITEM_DONE:
                continue

            try:
                self._revert_single_item(
                    item, bot_root, deleter, restorer,
                )
                reverted_count += 1
            except Exception as exc:
                failed_count += 1
                err = f"@{item.username}: {exc}"
                errors.append(err)
                logger.error(
                    "Revert failed for item %d (@%s): %s",
                    item.id, item.username, exc,
                )

        # Determine revert status
        if failed_count == 0:
            revert_status = "reverted"
        elif reverted_count > 0:
            revert_status = "partially_reverted"
        else:
            revert_status = "revert_failed"

        self._bulk_repo.mark_run_reverted(run_id, revert_status)

        logger.info(
            "Revert run %d: reverted=%d, failed=%d",
            run_id, reverted_count, failed_count,
        )
        return reverted_count, failed_count, errors

    def revert_item(self, item_id: int, bot_root: Optional[str] = None) -> bool:
        """
        Revert a single bulk discovery item.

        Removes added sources and restores missing originals.
        Returns True on success, False on failure.
        """
        if not bot_root:
            bot_root = self._settings.get("bot_root_path") or ""
        if not bot_root:
            logger.error("revert_item: bot root path not configured")
            return False

        item = self._bulk_repo.get_item(item_id)
        if item is None:
            logger.error("revert_item: item %d not found", item_id)
            return False

        if item.status != ITEM_DONE:
            logger.warning(
                "revert_item: item %d has status '%s', skipping",
                item_id, item.status,
            )
            return False

        deleter = SourceDeleter(bot_root)
        restorer = SourceRestorer(bot_root)

        try:
            self._revert_single_item(item, bot_root, deleter, restorer)
            return True
        except Exception as exc:
            logger.error(
                "revert_item: item %d (@%s) failed: %s",
                item_id, item.username, exc,
            )
            return False

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    def get_run_details(self, run_id: int) -> Optional[BulkDiscoveryRun]:
        """Load a run with all its items."""
        return self._bulk_repo.get_run_with_items(run_id)

    def get_all_runs(self, limit: int = 20) -> List[BulkDiscoveryRun]:
        """Return recent bulk discovery runs (for history dialog)."""
        return self._bulk_repo.get_recent_runs(limit=limit)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _read_sources_file(
        self, bot_root: str, device_id: str, username: str
    ) -> List[str]:
        """Read sources.txt for an account, returning a list of source names."""
        path = Path(bot_root) / device_id / username / "sources.txt"
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            return [ln.strip() for ln in content.splitlines() if ln.strip()]
        except OSError:
            return []

    def _revert_single_item(
        self,
        item: BulkDiscoveryItem,
        bot_root: str,
        deleter: SourceDeleter,
        restorer: SourceRestorer,
    ) -> None:
        """
        Revert one item: remove added sources, restore missing originals.

        Raises on fatal errors; per-source errors are logged but do not
        prevent processing the remaining sources.
        """
        device_id = item.device_id
        username = item.username
        device_name = device_id  # display name — same as device_id

        # Remove added sources
        added_sources: List[str] = []
        if item.added_sources_json:
            try:
                added_sources = json.loads(item.added_sources_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Cannot parse added_sources_json for item %d", item.id,
                )

        for source_name in added_sources:
            fr = deleter.remove_source(device_id, username, device_name, source_name)
            if fr.removed:
                logger.debug(
                    "Revert: removed added source @%s from @%s",
                    source_name, username,
                )
            elif not fr.found:
                logger.debug(
                    "Revert: added source @%s already absent from @%s",
                    source_name, username,
                )
            elif fr.error:
                logger.warning(
                    "Revert: failed to remove @%s from @%s: %s",
                    source_name, username, fr.error,
                )

        # Restore missing original sources
        original_sources: List[str] = []
        if item.original_sources_json:
            try:
                original_sources = json.loads(item.original_sources_json)
            except (json.JSONDecodeError, TypeError):
                logger.warning(
                    "Cannot parse original_sources_json for item %d", item.id,
                )

        # Read current state to find what's missing
        current_sources = self._read_sources_file(bot_root, device_id, username)
        current_lower = {s.lower() for s in current_sources}

        for source_name in original_sources:
            if source_name.lower() not in current_lower:
                fr = restorer.restore_source(
                    device_id, username, device_name, source_name,
                )
                if fr.restored:
                    logger.debug(
                        "Revert: restored original source @%s for @%s",
                        source_name, username,
                    )
                elif fr.error:
                    logger.warning(
                        "Revert: failed to restore @%s for @%s: %s",
                        source_name, username, fr.error,
                    )
