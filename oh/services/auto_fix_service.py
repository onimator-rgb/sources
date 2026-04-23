"""
AutoFixService — proposal-based self-healing operations that run after Scan & Sync.

Flow:
  1. detect_all()          — analyse data, return AutoFixProposal list (NO side effects)
  2. operator reviews      — AutoFixProposalDialog shows proposals with checkboxes
  3. execute_proposals()   — execute only the approved proposals

Features:
  1. Source Cleanup: detect weak sources (wFBR near 0%, sufficient data)
  2. TB Escalation: detect accounts with 0 actions for 2+ days
  3. Dead Device Detection: flag devices with 0 activity in active slots
  4. Duplicate Source Cleanup: detect duplicate entries in sources.txt
"""
import logging
import shutil
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple

from oh.models.auto_fix import (
    AutoFixProposal,
    FIX_SOURCE_CLEANUP, FIX_TB_ESCALATION, FIX_DEAD_DEVICE, FIX_DUPLICATE_CLEANUP,
    FIX_SEV_HIGH, FIX_SEV_MEDIUM, FIX_SEV_LOW,
)

logger = logging.getLogger(__name__)


@dataclass
class AutoFixResult:
    """Summary of all auto-fix actions performed in a single run."""
    sources_cleaned: int = 0
    sources_cleaned_accounts: int = 0
    tb_escalated: int = 0
    dead_devices: List[str] = field(default_factory=list)
    duplicates_cleaned: int = 0
    duplicates_cleaned_accounts: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def has_actions(self) -> bool:
        return (self.sources_cleaned > 0
                or self.tb_escalated > 0
                or len(self.dead_devices) > 0
                or self.duplicates_cleaned > 0)

    def summary_lines(self) -> List[str]:
        """Human-readable summary lines for Cockpit display."""
        lines = []
        if self.sources_cleaned:
            lines.append(
                f"Cleaned {self.sources_cleaned} weak source(s) "
                f"from {self.sources_cleaned_accounts} account(s)"
            )
        if self.tb_escalated:
            lines.append(f"Escalated TB for {self.tb_escalated} account(s)")
        if self.dead_devices:
            lines.append(
                f"{len(self.dead_devices)} device(s) offline: "
                + ", ".join(self.dead_devices[:5])
                + ("..." if len(self.dead_devices) > 5 else "")
            )
        if self.duplicates_cleaned:
            lines.append(
                f"Removed {self.duplicates_cleaned} duplicate source(s) "
                f"from {self.duplicates_cleaned_accounts} account(s)"
            )
        return lines


class AutoFixService:
    """Proposal-based self-healing operations after Scan & Sync."""

    def __init__(
        self,
        conn,
        settings_repo,
        operator_action_service,
        source_delete_service,
        account_repo,
        tag_repo,
        assignment_repo,
    ) -> None:
        self._conn = conn
        self._settings = settings_repo
        self._operator = operator_action_service
        self._delete_svc = source_delete_service
        self._accounts = account_repo
        self._tags = tag_repo
        self._assignments = assignment_repo

    # ------------------------------------------------------------------
    # Public API — detect + execute
    # ------------------------------------------------------------------

    def detect_all(self, bot_root: str) -> List[AutoFixProposal]:
        """Detect all auto-fix candidates. Returns proposals — does NOT execute."""
        proposals: List[AutoFixProposal] = []

        if self._settings.get("auto_fix_source_cleanup") == "1":
            try:
                proposals.extend(self._detect_weak_sources(bot_root))
            except Exception as exc:
                logger.error("Source cleanup detection failed: %s", exc, exc_info=True)

        if self._settings.get("auto_fix_tb_escalation") == "1":
            try:
                proposals.extend(self._detect_tb_candidates())
            except Exception as exc:
                logger.error("TB escalation detection failed: %s", exc, exc_info=True)

        if self._settings.get("auto_fix_dead_device_alert") == "1":
            try:
                proposals.extend(self._detect_dead_devices_proposals())
            except Exception as exc:
                logger.error("Dead device detection failed: %s", exc, exc_info=True)

        if self._settings.get("auto_fix_duplicate_cleanup") == "1":
            try:
                proposals.extend(self._detect_duplicate_sources(bot_root))
            except Exception as exc:
                logger.error("Duplicate detection failed: %s", exc, exc_info=True)

        # Sort by severity rank (HIGH first)
        proposals.sort(key=lambda p: p.sev_rank)
        return proposals

    def execute_proposals(self, proposals: List[AutoFixProposal]) -> AutoFixResult:
        """Execute a list of operator-approved proposals. Returns summary."""
        result = AutoFixResult()
        for p in proposals:
            if not p.is_actionable:
                # Info-only proposals (dead device) — just log
                if p.fix_type == FIX_DEAD_DEVICE:
                    result.dead_devices.append(p.target)
                    self._log_action("dead_device", None, None, p.description, 0)
                continue
            try:
                count = p.execute()
                self._update_result(result, p, count)
            except Exception as exc:
                logger.error("Auto-fix execution failed for %s: %s", p.target, exc)
                result.errors.append(f"{p.type_label} ({p.target}): {exc}")
        if result.has_actions:
            logger.info("Auto-fix executed (operator-approved): %s",
                        "; ".join(result.summary_lines()))
        return result

    def run_all(self, bot_root: str) -> AutoFixResult:
        """Deprecated: detect + execute all in one step. Kept for backward compat."""
        proposals = self.detect_all(bot_root)
        return self.execute_proposals(proposals)

    # ------------------------------------------------------------------
    # Detection methods — return proposals without side effects
    # ------------------------------------------------------------------

    def _detect_weak_sources(self, bot_root: str) -> List[AutoFixProposal]:
        """Find sources eligible for cleanup. Returns proposals."""
        proposals: List[AutoFixProposal] = []
        threshold = float(self._settings.get("auto_fix_source_threshold") or "0.5")
        min_follows = int(self._settings.get("min_follows_threshold") or "100")
        min_source_warning = int(self._settings.get("min_source_count_warning") or "5")

        rows = self._conn.execute(
            """SELECT sf.source_name, sf.weighted_fbr_pct, sf.total_follows,
                      sf.total_accounts_used
               FROM source_fbr_stats sf
               WHERE sf.weighted_fbr_pct IS NOT NULL
                 AND sf.weighted_fbr_pct <= ?
                 AND sf.total_follows >= ?
                 AND sf.total_accounts_used > 0
               ORDER BY sf.weighted_fbr_pct ASC""",
            (threshold, min_follows),
        ).fetchall()

        for row in rows:
            source_name = row["source_name"]
            assignments = self._assignments.get_active_assignments_for_source(source_name)
            eligible = self._filter_eligible_assignments(assignments, min_source_warning)
            if not eligible:
                continue

            n_accounts = len(eligible)
            wfbr = row["weighted_fbr_pct"]

            # Factory function to capture loop variables correctly
            def make_executor(src=source_name, accs=eligible, br=bot_root, w=wfbr):
                def _execute():
                    return self._execute_source_cleanup(br, src, accs, w)
                return _execute

            proposals.append(AutoFixProposal(
                fix_type=FIX_SOURCE_CLEANUP,
                severity=FIX_SEV_HIGH,
                target=source_name,
                description=f"Remove '{source_name}' from {n_accounts} account(s)",
                detail=f"wFBR={wfbr:.1f}%, {row['total_follows']} follows",
                execute=make_executor(),
                metadata={"source_name": source_name, "wfbr": wfbr, "accounts": n_accounts},
            ))

        return proposals

    def _detect_tb_candidates(self) -> List[AutoFixProposal]:
        """Find accounts eligible for TB escalation. Returns proposals."""
        proposals: List[AutoFixProposal] = []
        active = self._accounts.get_all_active()

        for acc in active:
            rows = self._conn.execute(
                """SELECT snapshot_date,
                          COALESCE(follow_count, 0) + COALESCE(like_count, 0) +
                          COALESCE(dm_count, 0) + COALESCE(unfollow_count, 0) AS total_actions
                   FROM session_snapshots
                   WHERE username = ?
                   ORDER BY snapshot_date DESC
                   LIMIT 3""",
                (acc.username,),
            ).fetchall()

            if len(rows) < 2:
                continue

            zero_days = sum(1 for r in rows[:2] if r["total_actions"] == 0)
            if zero_days < 2:
                continue

            if not self._is_in_active_slot(acc):
                continue

            current_tb = self._get_current_tb(acc.id)
            if current_tb is not None and current_tb >= 5:
                continue

            current_label = f"TB{current_tb}" if current_tb else "none"
            new_level = current_tb + 1 if current_tb else 1
            new_label = f"TB{new_level}"

            def make_executor(account=acc, tb_now=current_tb):
                def _execute():
                    return self._execute_tb_escalation(account, tb_now)
                return _execute

            proposals.append(AutoFixProposal(
                fix_type=FIX_TB_ESCALATION,
                severity=FIX_SEV_MEDIUM,
                target=acc.username,
                description=f"Escalate {acc.username}: {current_label} \u2192 {new_label}",
                detail=f"0 actions for 2+ days, active slot",
                execute=make_executor(),
                metadata={"username": acc.username, "current_tb": current_label,
                          "new_tb": new_label},
            ))

        return proposals

    def _detect_dead_devices_proposals(self) -> List[AutoFixProposal]:
        """Flag devices where all accounts had 0 actions today. Info-only proposals."""
        proposals: List[AutoFixProposal] = []
        today_str = date.today().isoformat()

        rows = self._conn.execute(
            """SELECT d.device_id, d.device_name,
                      COUNT(DISTINCT a.id) AS total_accounts,
                      COUNT(DISTINCT CASE WHEN s.follow_count > 0 OR s.like_count > 0
                            THEN a.id END) AS active_accounts
               FROM oh_devices d
               JOIN oh_accounts a ON a.device_id = d.device_id AND a.removed_at IS NULL
               LEFT JOIN session_snapshots s ON s.username = a.username
                    AND s.snapshot_date = ?
               WHERE d.is_active = 1
               GROUP BY d.device_id
               HAVING total_accounts > 0 AND active_accounts = 0""",
            (today_str,),
        ).fetchall()

        for row in rows:
            device_name = row["device_name"] or row["device_id"]
            proposals.append(AutoFixProposal(
                fix_type=FIX_DEAD_DEVICE,
                severity=FIX_SEV_MEDIUM,
                target=device_name,
                description=f"Device '{device_name}' has 0 active accounts today "
                            f"({row['total_accounts']} total)",
                detail="All accounts inactive — check device connectivity",
                execute=None,  # info-only, no action
                metadata={"device_id": row["device_id"],
                          "total_accounts": row["total_accounts"]},
            ))

        return proposals

    def _detect_duplicate_sources(self, bot_root: str) -> List[AutoFixProposal]:
        """Find accounts with duplicate source entries. Returns proposals."""
        proposals: List[AutoFixProposal] = []
        active = self._accounts.get_all_active()

        for acc in active:
            sources_path = (
                Path(bot_root) / acc.device_id / acc.username / "sources.txt"
            )
            if not sources_path.exists():
                continue

            try:
                lines = sources_path.read_text(encoding="utf-8").splitlines()
                seen = set()
                duplicates_found = 0

                for line in lines:
                    stripped = line.strip()
                    if not stripped:
                        continue
                    key = stripped.lower()
                    if key in seen:
                        duplicates_found += 1
                    else:
                        seen.add(key)

                if duplicates_found > 0:
                    def make_executor(account=acc, br=bot_root, sp=sources_path):
                        def _execute():
                            return self._execute_duplicate_cleanup(account, br, sp)
                        return _execute

                    proposals.append(AutoFixProposal(
                        fix_type=FIX_DUPLICATE_CLEANUP,
                        severity=FIX_SEV_LOW,
                        target=acc.username,
                        description=f"Remove {duplicates_found} duplicate(s) from {acc.username}",
                        detail=f"{len(seen)} unique sources, {duplicates_found} duplicate(s)",
                        execute=make_executor(),
                        metadata={"username": acc.username,
                                  "duplicates": duplicates_found},
                    ))
            except Exception as exc:
                logger.warning("Duplicate detection for %s failed: %s", acc.username, exc)

        return proposals

    # ------------------------------------------------------------------
    # Execution methods — perform the actual fix, return items affected
    # ------------------------------------------------------------------

    def _execute_source_cleanup(self, bot_root: str, source_name: str,
                                eligible: list, wfbr: float) -> int:
        """Execute source removal. Returns number of accounts cleaned."""
        from oh.modules.source_deleter import SourceDeleter
        deleter = SourceDeleter(bot_root)
        removed = 0
        for acc_id, device_id, username, device_name in eligible:
            try:
                fr = deleter.remove_source(device_id, username, device_name, source_name)
                if fr.removed:
                    self._assignments.mark_source_inactive(acc_id, source_name)
                    removed += 1
            except Exception as exc:
                logger.warning("Cleanup %s from %s failed: %s", source_name, username, exc)
        if removed:
            self._log_action("source_cleanup", None, None,
                             f"Removed '{source_name}' (wFBR={wfbr:.1f}%) "
                             f"from {removed} account(s)", removed)
        return removed

    def _execute_tb_escalation(self, acc, current_tb: Optional[int]) -> int:
        """Execute TB escalation for one account. Returns 1 if escalated, 0 otherwise."""
        new_level = self._operator.increment_tb(acc.id)
        if new_level and new_level.startswith("TB"):
            self._log_action("tb_escalation", acc.username, acc.device_id,
                             f"TB escalation: {new_level} (0 actions for 2+ days)", 1)
            # Auto-flag for review if TB >= 4
            new_num = int(new_level[2:])
            if new_num >= 4:
                self._operator.set_review(
                    acc.id,
                    note=f"Auto-flagged: {new_level} after 0 actions for 2+ days",
                )
            return 1
        return 0

    def _execute_duplicate_cleanup(self, acc, bot_root: str,
                                   sources_path: Path) -> int:
        """Execute duplicate removal for one account. Returns duplicates removed."""
        lines = sources_path.read_text(encoding="utf-8").splitlines()
        seen = {}
        clean_lines = []
        duplicates_found = 0

        for line in lines:
            stripped = line.strip()
            if not stripped:
                continue
            key = stripped.lower()
            if key in seen:
                duplicates_found += 1
            else:
                seen[key] = stripped
                clean_lines.append(stripped)

        if duplicates_found > 0:
            # Backup first (copy, so original stays intact if write fails)
            bak_path = sources_path.with_suffix(".txt.bak")
            shutil.copy2(sources_path, bak_path)
            sources_path.write_text(
                "\n".join(clean_lines) + "\n", encoding="utf-8"
            )
            bak_path.unlink(missing_ok=True)
            self._log_action(
                "duplicate_cleanup", acc.username, acc.device_id,
                f"Removed {duplicates_found} duplicate source(s)", duplicates_found,
            )

        return duplicates_found

    # ------------------------------------------------------------------
    # Result helpers
    # ------------------------------------------------------------------

    def _update_result(self, result: AutoFixResult, proposal: AutoFixProposal,
                       count: int) -> None:
        """Update result counters based on proposal type and execution count."""
        if proposal.fix_type == FIX_SOURCE_CLEANUP:
            if count > 0:
                result.sources_cleaned += 1
                result.sources_cleaned_accounts += count
        elif proposal.fix_type == FIX_TB_ESCALATION:
            result.tb_escalated += count
        elif proposal.fix_type == FIX_DUPLICATE_CLEANUP:
            if count > 0:
                result.duplicates_cleaned += count
                result.duplicates_cleaned_accounts += 1

    def _filter_eligible_assignments(self, assignments: list,
                                     min_source_warning: int) -> list:
        """Filter assignments to those eligible for source removal."""
        source_counts = self._assignments.get_active_source_counts()
        eligible = []
        for acc_id, device_id, username, device_name in assignments:
            acc = self._accounts.get_by_id(acc_id)
            if acc is None or not acc.is_active:
                continue
            current_sources = source_counts.get(acc_id, 0)
            if current_sources <= min_source_warning:
                continue
            eligible.append((acc_id, device_id, username, device_name))
        return eligible

    # ------------------------------------------------------------------
    # Shared helpers
    # ------------------------------------------------------------------

    def _is_in_active_slot(self, acc) -> bool:
        """Check if current hour falls in account's working hours."""
        try:
            now_hour = datetime.now().hour
            start = int(acc.start_time.split(":")[0]) if acc.start_time else 0
            end = int(acc.end_time.split(":")[0]) if acc.end_time else 24
            if start < end:
                return start <= now_hour < end
            else:  # overnight slot
                return now_hour >= start or now_hour < end
        except (ValueError, AttributeError):
            return True  # assume active if we can't parse

    def _get_current_tb(self, account_id: int) -> Optional[int]:
        """Get current operator TB level for account."""
        row = self._conn.execute(
            """SELECT tag_level FROM account_tags
               WHERE account_id = ? AND tag_source = 'operator' AND tag_category = 'tb'
               ORDER BY updated_at DESC LIMIT 1""",
            (account_id,),
        ).fetchone()
        return row["tag_level"] if row else None

    def _log_action(self, fix_type: str, username: Optional[str],
                    device_id: Optional[str], details: str, items: int) -> None:
        """Log an auto-fix action to the database."""
        now = datetime.now(timezone.utc).isoformat()
        try:
            self._conn.execute(
                """INSERT INTO auto_fix_actions
                   (fix_type, target_username, target_device, details, items_affected, created_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (fix_type, username, device_id, details, items, now),
            )
            self._conn.commit()
        except Exception as exc:
            logger.warning("Failed to log auto-fix action: %s", exc)

    def get_recent_actions(self, limit: int = 20) -> list:
        """Get recent auto-fix actions for display."""
        return self._conn.execute(
            """SELECT fix_type, target_username, target_device, details,
                      items_affected, created_at
               FROM auto_fix_actions
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        ).fetchall()
