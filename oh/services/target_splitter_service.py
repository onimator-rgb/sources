"""
TargetSplitterService — distribute sources across accounts.

DISTRIBUTION SEMANTICS:
  compute_plan() is read-only and deterministic. It builds a SplitPlan
  showing exactly which sources will be added to which accounts, with
  skip markers for sources already present.

  execute_plan() writes to disk via SourceRestorer. Only called after
  operator confirms. Per-item errors do not abort the batch.

SAFETY:
  - SourceRestorer creates sources.txt.bak before every file write
  - Sources already present in an account are skipped (not re-added)
  - source_assignments is updated after each successful write
  - Audit trail via OperatorActionRepository
"""
import logging
import re
import socket
from datetime import datetime, timezone
from typing import List, Optional, Tuple

from oh.models.account import AccountRecord
from oh.models.operator_action import OperatorActionRecord, ACTION_DISTRIBUTE_SOURCES
from oh.models.target_splitter import SplitAssignment, SplitPlan, SplitResult
from oh.modules.source_restorer import SourceRestorer
from oh.repositories.account_repo import AccountRepository
from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TargetSplitterService:
    def __init__(
        self,
        assignment_repo: SourceAssignmentRepository,
        operator_action_repo: Optional[OperatorActionRepository],
        account_repo: AccountRepository,
    ) -> None:
        self._assignments = assignment_repo
        self._actions = operator_action_repo
        self._accounts = account_repo

    # ------------------------------------------------------------------
    # Read-only plan computation
    # ------------------------------------------------------------------

    def compute_plan(
        self,
        sources: List[str],
        account_ids: List[int],
        strategy: str,
    ) -> SplitPlan:
        """
        Build a distribution plan without any side effects.

        Args:
            sources: Raw source names (will be deduped and stripped).
            account_ids: IDs of target accounts.
            strategy: "even_split" or "fill_up".

        Returns:
            A SplitPlan with all assignments and skip markers.
        """
        # Dedup, strip, and validate source names, preserving order
        _SOURCE_RE = re.compile(r'^[a-zA-Z0-9_.]+$')
        clean: List[str] = []
        seen_lower: set = set()
        for s in sources:
            stripped = s.strip()
            if not stripped or stripped.lower() in seen_lower:
                continue
            if not _SOURCE_RE.match(stripped):
                logger.warning("Invalid source name rejected: '%s'", stripped)
                continue
            clean.append(stripped)
            seen_lower.add(stripped.lower())

        # Load account records for the selected IDs
        account_map: dict = {}
        for acc in self._accounts.get_all_active():
            if acc.id in account_ids:
                account_map[acc.id] = acc

        # Maintain requested order but only include valid accounts
        ordered_ids = [aid for aid in account_ids if aid in account_map]

        if not clean or not ordered_ids:
            return SplitPlan(
                strategy=strategy,
                sources=clean,
                target_account_ids=ordered_ids,
                assignments=[],
                skipped_count=0,
            )

        # Build active-source set per account for skip checking
        active_counts = self._assignments.get_active_source_counts()
        active_sets = self._get_active_source_sets(ordered_ids)

        if strategy == "fill_up":
            assignments = self._plan_fill_up(
                clean, ordered_ids, account_map, active_counts, active_sets
            )
        else:
            assignments = self._plan_even_split(
                clean, ordered_ids, account_map, active_sets
            )

        skipped = sum(1 for a in assignments if a.skipped)
        return SplitPlan(
            strategy=strategy,
            sources=clean,
            target_account_ids=ordered_ids,
            assignments=assignments,
            skipped_count=skipped,
        )

    # ------------------------------------------------------------------
    # Execution (writes to disk)
    # ------------------------------------------------------------------

    def execute_plan(
        self,
        plan: SplitPlan,
        bot_root: str,
    ) -> SplitResult:
        """
        Execute a confirmed SplitPlan by writing to sources.txt files.

        Only non-skipped assignments are written. Per-item errors do not
        abort the batch. Returns a SplitResult with outcome summary.
        """
        restorer = SourceRestorer(bot_root)
        result = SplitResult()

        # Group assignments by account for audit logging
        account_added: dict = {}  # account_id -> list of source names added

        for assignment in plan.assignments:
            if assignment.skipped:
                result.total_skipped += 1
                continue

            result.total_attempted += 1

            try:
                fr = restorer.restore_source(
                    assignment.device_id,
                    assignment.username,
                    assignment.device_name,
                    assignment.source_name,
                )

                if fr.restored:
                    result.total_added += 1
                    self._assignments.mark_source_active(
                        assignment.account_id, assignment.source_name
                    )
                    account_added.setdefault(assignment.account_id, []).append(
                        assignment.source_name
                    )
                elif fr.already_present:
                    result.total_skipped += 1
                elif fr.error:
                    result.total_failed += 1
                    result.errors.append(
                        f"{assignment.username}/{assignment.source_name}: {fr.error}"
                    )
            except Exception as e:
                result.total_failed += 1
                result.errors.append(
                    f"{assignment.username}/{assignment.source_name}: {e}"
                )
                logger.exception(
                    "Error distributing '%s' to %s: %s",
                    assignment.source_name, assignment.username, e,
                )

        # Audit trail — one action per account that received sources
        self._log_audit(plan, account_added)

        logger.info(
            "[TargetSplitter] strategy=%s sources=%d accounts=%d "
            "added=%d skipped=%d failed=%d",
            plan.strategy,
            len(plan.sources),
            len(plan.target_account_ids),
            result.total_added,
            result.total_skipped,
            result.total_failed,
        )

        return result

    # ------------------------------------------------------------------
    # Helpers for the UI
    # ------------------------------------------------------------------

    def get_accounts_with_source_counts(
        self,
    ) -> List[Tuple[AccountRecord, int]]:
        """
        Return all active accounts with their active source counts.
        Used by the dialog to show the account selection table.
        """
        accounts = self._accounts.get_all_active()
        counts = self._assignments.get_active_source_counts()
        return [(acc, counts.get(acc.id, 0)) for acc in accounts]

    # ------------------------------------------------------------------
    # Internal — distribution algorithms
    # ------------------------------------------------------------------

    def _get_active_source_sets(
        self, account_ids: List[int]
    ) -> dict:
        """
        Return {account_id: set(lowercase source names)} for skip checking.
        Queries source_assignments where is_active=1 for each account.
        """
        result: dict = {}
        for aid in account_ids:
            result[aid] = self._assignments.get_active_source_names_for_account(aid)
        return result

    def _plan_even_split(
        self,
        sources: List[str],
        account_ids: List[int],
        account_map: dict,
        active_sets: dict,
    ) -> List[SplitAssignment]:
        """Round-robin distribution of sources across accounts."""
        assignments: List[SplitAssignment] = []
        num_accounts = len(account_ids)

        for i, source in enumerate(sources):
            aid = account_ids[i % num_accounts]
            acc = account_map[aid]
            source_lower = source.strip().lower()
            already = source_lower in active_sets.get(aid, set())

            assignments.append(SplitAssignment(
                source_name=source,
                account_id=aid,
                username=acc.username,
                device_id=acc.device_id,
                device_name=acc.device_name or "",
                skipped=already,
                skip_reason="Already present" if already else None,
            ))

        return assignments

    def _plan_fill_up(
        self,
        sources: List[str],
        account_ids: List[int],
        account_map: dict,
        active_counts: dict,
        active_sets: dict,
    ) -> List[SplitAssignment]:
        """Assign each source to the account with fewest active sources."""
        assignments: List[SplitAssignment] = []

        # Working copy of counts so we can increment as we assign
        working_counts = {aid: active_counts.get(aid, 0) for aid in account_ids}

        for source in sources:
            # Pick the account with the fewest sources (stable: first in list wins ties)
            aid = min(account_ids, key=lambda a: working_counts.get(a, 0))
            acc = account_map[aid]
            source_lower = source.strip().lower()
            already = source_lower in active_sets.get(aid, set())

            assignments.append(SplitAssignment(
                source_name=source,
                account_id=aid,
                username=acc.username,
                device_id=acc.device_id,
                device_name=acc.device_name or "",
                skipped=already,
                skip_reason="Already present" if already else None,
            ))

            # Increment working count even for skipped (source is present either way)
            working_counts[aid] = working_counts.get(aid, 0) + 1

        return assignments

    # ------------------------------------------------------------------
    # Internal — audit logging
    # ------------------------------------------------------------------

    def _log_audit(
        self,
        plan: SplitPlan,
        account_added: dict,
    ) -> None:
        """Log one operator action per account that received sources."""
        if not self._actions:
            return

        machine = socket.gethostname()
        strategy_label = "Even split" if plan.strategy == "even_split" else "Fill up"
        note = (
            f"{strategy_label}: {len(plan.sources)} sources "
            f"across {len(plan.target_account_ids)} accounts"
        )

        for aid, source_names in account_added.items():
            # Look up account info from the plan assignments
            acc_assignment = None
            for a in plan.assignments:
                if a.account_id == aid:
                    acc_assignment = a
                    break
            if not acc_assignment:
                continue

            record = OperatorActionRecord(
                account_id=aid,
                username=acc_assignment.username,
                device_id=acc_assignment.device_id,
                action_type=ACTION_DISTRIBUTE_SOURCES,
                old_value=None,
                new_value=", ".join(source_names),
                note=note,
                machine=machine,
            )
            try:
                self._actions.log_action(record)
            except Exception as e:
                logger.warning(
                    "Failed to log audit for account %d: %s", aid, e
                )
