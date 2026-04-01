"""
AccountDetailService — aggregation layer for the Account Detail View.

Assembles all data needed for the detail drawer from maps that MainWindow
already holds in memory.  The only DB query is get_review_history() which
fetches operator review actions for the History / Alerts tabs.

Alert computation follows the same patterns as RecommendationService but
produces AccountAlert objects scoped to a single account.
"""
import logging
import re
from datetime import datetime
from typing import Dict, List, Optional

from oh.models.account import AccountRecord
from oh.models.account_detail import AccountAlert, AccountDetailData
from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.operator_action import (
    ACTION_CLEAR_REVIEW,
    ACTION_SET_REVIEW,
    OperatorActionRecord,
)
from oh.models.recommendation import SEV_CRITICAL, SEV_HIGH, SEV_LOW, SEV_MEDIUM, SEV_RANK
from oh.models.session import AccountSessionRecord, slot_for_times
from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.repositories.settings_repo import SettingsRepository

logger = logging.getLogger(__name__)

_TB_RE = re.compile(r"TB(\d)", re.IGNORECASE)
_LIMITS_RE = re.compile(r"limits\s*(\d)", re.IGNORECASE)


class AccountDetailService:
    """
    Aggregation service for the Account Detail View.

    Constructor dependencies are intentionally minimal — only repos needed
    for queries that are NOT already in MainWindow's cached maps.
    """

    def __init__(
        self,
        operator_action_repo: OperatorActionRepository,
        settings_repo: SettingsRepository,
    ) -> None:
        self._actions = operator_action_repo
        self._settings = settings_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_summary_data(
        self,
        account: AccountRecord,
        session_map: Dict[int, AccountSessionRecord],
        fbr_map: Dict[int, FBRSnapshotRecord],
        source_count_map: Dict[int, int],
        op_tags_map: Dict[int, str],
        device_status_map: Dict[str, str],
    ) -> AccountDetailData:
        """
        Build an AccountDetailData from pre-loaded maps.

        Pure aggregation — no DB queries.  The caller (MainWindow) already
        holds all of these maps in memory after a sync/refresh cycle.

        Parameters
        ----------
        account : AccountRecord
            The account to build detail data for.
        session_map : dict
            {account_id: AccountSessionRecord} for today's session.
        fbr_map : dict
            {account_id: FBRSnapshotRecord} for latest FBR snapshot.
        source_count_map : dict
            {account_id: int} active source counts.
        op_tags_map : dict
            {account_id: str} concatenated operator tags (e.g. "TB3 | limits 2").
        device_status_map : dict
            {device_id: str} device statuses (e.g. "running", "stop").

        Returns
        -------
        AccountDetailData
            Fully populated data bundle with alerts computed.
        """
        aid = account.id
        data = AccountDetailData(
            account=account,
            session=session_map.get(aid) if aid is not None else None,
            fbr_snapshot=fbr_map.get(aid) if aid is not None else None,
            source_count=source_count_map.get(aid, 0) if aid is not None else 0,
            bot_tags=account.bot_tags_raw or "",
            operator_tags=op_tags_map.get(aid, "") if aid is not None else "",
            device_status=device_status_map.get(account.device_id),
        )

        data.alerts = self.compute_alerts(data)

        logger.debug(
            "[AccountDetail] Built summary for %s: %d alerts",
            account.username,
            len(data.alerts),
        )
        return data

    def compute_alerts(self, data: AccountDetailData) -> List[AccountAlert]:
        """
        Generate alerts for one account from its detail data.

        Alert conditions (ordered by severity):
          CRITICAL — zero actions in active slot, device offline, TB >= 4
          HIGH     — no sources, review flag with "pending"/"try again",
                     follow=0 but other actions active, limits >= 4
          MEDIUM   — no quality sources, low follow (<40), like=0 despite
                     limit, few active sources (<min threshold)
          LOW      — below 50% follow limit, never analyzed FBR

        Returns a list sorted by severity (most urgent first).
        """
        alerts = []  # type: List[AccountAlert]
        acc = data.account
        sess = data.session
        snap = data.fbr_snapshot

        current_hour = datetime.now().hour

        # --- CRITICAL ---

        # Zero actions in active slot
        if self._is_active_slot(acc, current_hour) and data.device_status == "running":
            if sess is None or not sess.has_activity:
                alerts.append(AccountAlert(
                    severity=SEV_CRITICAL,
                    title="Zero actions in active slot",
                    detail=(
                        "Device is running and the account's time slot is "
                        "active, but no follow/like/DM actions were recorded."
                    ),
                    recommended_action="Check for popup, 2FA, action block, or logout.",
                ))

        # Device offline
        if data.device_status and data.device_status != "running":
            alerts.append(AccountAlert(
                severity=SEV_CRITICAL,
                title="Device offline",
                detail="Device status: %s" % data.device_status,
                recommended_action="Check cable, WiFi, power supply.",
            ))

        # TB >= 4
        tb_level = self._extract_level(data.operator_tags, "TB")
        if tb_level is not None and tb_level >= 4:
            alerts.append(AccountAlert(
                severity=SEV_CRITICAL,
                title="TB%d — needs device transfer" % tb_level,
                detail="Trust/ban level is critically high.",
                recommended_action="Move account to another device and restart warmup.",
                action_type="tb_plus_1" if tb_level < 5 else None,
            ))

        # --- HIGH ---

        # No sources
        if data.source_count == 0:
            alerts.append(AccountAlert(
                severity=SEV_HIGH,
                title="No active sources",
                detail="Account has 0 active sources for automation.",
                recommended_action="Add sources via Sources tab or Find Sources.",
            ))

        # Review flag with specific patterns
        if acc.review_flag and acc.review_note:
            note_lower = (acc.review_note or "").lower()
            if "pending" in note_lower:
                alerts.append(AccountAlert(
                    severity=SEV_HIGH,
                    title="Follow is pending",
                    detail="Review note: %s" % acc.review_note,
                    recommended_action="Disable follow for 48h, then re-enable and monitor.",
                    action_type="clear_review",
                ))
            elif "try again" in note_lower:
                alerts.append(AccountAlert(
                    severity=SEV_HIGH,
                    title="Try again later",
                    detail="Review note: %s" % acc.review_note,
                    recommended_action="Increase TB level and apply warmup procedure.",
                    action_type="tb_plus_1",
                ))

        # Limits >= 4
        limits_level = self._extract_level(data.operator_tags, "limits")
        if limits_level is not None and limits_level >= 4:
            alerts.append(AccountAlert(
                severity=SEV_HIGH,
                title="Limits %d — sources exhausted" % limits_level,
                detail="Source limits level is high; sources need replacement.",
                recommended_action="Replace exhausted sources, remove weak ones.",
            ))

        # Follow = 0 but other actions active
        if sess is not None and sess.follow_count == 0 and (sess.like_count > 0 or sess.dm_count > 0):
            alerts.append(AccountAlert(
                severity=SEV_HIGH,
                title="Follow = 0 but other actions active",
                detail=(
                    "Like=%d, DM=%d but no follows recorded."
                    % (sess.like_count, sess.dm_count)
                ),
                recommended_action="Check sources, popup, or follow configuration.",
            ))

        # --- MEDIUM ---

        # No quality sources (but has sources and FBR data)
        if snap is not None and snap.quality_sources == 0 and snap.total_sources > 0:
            alerts.append(AccountAlert(
                severity=SEV_MEDIUM,
                title="No quality sources",
                detail=(
                    "%d sources analyzed, 0 quality." % snap.total_sources
                ),
                recommended_action="Replace sources, check FBR analysis.",
            ))

        # Low follow (< 40)
        if sess is not None and 0 < sess.follow_count < 40:
            alerts.append(AccountAlert(
                severity=SEV_MEDIUM,
                title="Low follow count (%d)" % sess.follow_count,
                detail="Follow count is below 40 — may indicate throttling.",
                recommended_action="Check for throttle or temporary block.",
            ))

        # Like = 0 despite limit
        if sess is not None and sess.like_count == 0:
            try:
                like_limit = int(acc.like_limit_perday or 0)
            except (ValueError, TypeError):
                like_limit = 0
            if like_limit > 0:
                alerts.append(AccountAlert(
                    severity=SEV_MEDIUM,
                    title="Like = 0 despite limit (%d)" % like_limit,
                    detail="Like limit is configured but zero likes recorded.",
                    recommended_action="Check like sources, add community sources.",
                ))

        # Few active sources
        min_source_warn = self._get_min_source_warning()
        if 0 < data.source_count < min_source_warn:
            alerts.append(AccountAlert(
                severity=SEV_MEDIUM,
                title="Few active sources (%d)" % data.source_count,
                detail=(
                    "Account has fewer than %d active sources."
                    % min_source_warn
                ),
                recommended_action="Add more sources via Find Sources.",
            ))

        # --- LOW ---

        # Below 50% of follow limit
        if sess is not None and sess.follow_limit is not None and sess.follow_limit > 0:
            if 0 < sess.follow_count < sess.follow_limit * 0.5:
                alerts.append(AccountAlert(
                    severity=SEV_LOW,
                    title="Below 50%% follow limit (%d/%d)" % (
                        sess.follow_count, sess.follow_limit,
                    ),
                    detail="Follow count is below half the configured limit.",
                    recommended_action="Monitor — may indicate early throttling.",
                ))

        # Never analyzed FBR
        if snap is None:
            alerts.append(AccountAlert(
                severity=SEV_LOW,
                title="Never analyzed FBR",
                detail="No FBR snapshot exists for this account.",
                recommended_action="Run Analyze FBR to assess source quality.",
            ))

        # Review flag active (generic, if not already caught by specific patterns)
        if acc.review_flag:
            note_lower = (acc.review_note or "").lower()
            if "pending" not in note_lower and "try again" not in note_lower:
                alerts.append(AccountAlert(
                    severity=SEV_MEDIUM,
                    title="Review flag active",
                    detail="Note: %s" % (acc.review_note or "(no note)"),
                    recommended_action="Inspect account and clear review when resolved.",
                    action_type="clear_review",
                ))

        # Sort by severity rank (most urgent first)
        alerts.sort(key=lambda a: SEV_RANK.get(a.severity, 9))
        return alerts

    def get_review_history(
        self, account_id: int
    ) -> List[OperatorActionRecord]:
        """
        Fetch set_review / clear_review actions for one account.

        This is the only method that hits the database — used for the
        Alerts tab review-history section.
        """
        all_actions = self._actions.get_for_account(account_id)
        return [
            a for a in all_actions
            if a.action_type in (ACTION_SET_REVIEW, ACTION_CLEAR_REVIEW)
        ]

    def format_diagnostic(self, data: AccountDetailData) -> str:
        """
        Generate a structured text summary suitable for clipboard copy.

        The output is designed to be pasted into Slack, a ticket, or a
        notes file for quick handoff between operators.
        """
        acc = data.account
        sess = data.session
        snap = data.fbr_snapshot
        lines = []

        # Header
        lines.append("=== Account Diagnostic ===")
        lines.append("Username:    %s" % acc.username)
        lines.append("Device:      %s (%s)" % (
            acc.device_name or acc.device_id,
            data.device_status or "unknown",
        ))
        lines.append("Status:      %s" % ("Active" if acc.is_active else "Removed"))
        lines.append("Account ID:  %s" % acc.id)

        # Slot
        slot = slot_for_times(acc.start_time, acc.end_time)
        lines.append("Slot:        %s (%s - %s)" % (
            slot, acc.start_time or "?", acc.end_time or "?",
        ))

        # Tags
        if data.bot_tags:
            lines.append("Bot tags:    %s" % data.bot_tags)
        if data.operator_tags:
            lines.append("OP tags:     %s" % data.operator_tags)

        # Review
        if acc.review_flag:
            lines.append("Review:      YES — %s" % (acc.review_note or "(no note)"))
            if acc.review_set_at:
                lines.append("Review set:  %s" % acc.review_set_at)

        lines.append("")

        # Session
        lines.append("--- Today's Session ---")
        if sess:
            lines.append("Follow:      %d / %s" % (
                sess.follow_count,
                sess.follow_limit if sess.follow_limit is not None else "?",
            ))
            lines.append("Like:        %d / %s" % (
                sess.like_count,
                sess.like_limit if sess.like_limit is not None else "?",
            ))
            lines.append("DM:          %d" % sess.dm_count)
            lines.append("Unfollow:    %d" % sess.unfollow_count)
            lines.append("Activity:    %s" % ("Yes" if sess.has_activity else "No"))
        else:
            lines.append("(no session data)")

        lines.append("")

        # FBR
        lines.append("--- FBR Snapshot ---")
        if snap:
            lines.append("Quality:     %d / %d sources" % (
                snap.quality_sources, snap.total_sources,
            ))
            if snap.best_fbr_pct is not None:
                lines.append("Best FBR:    %.1f%% (%s)" % (
                    snap.best_fbr_pct, snap.best_fbr_source or "?",
                ))
            if snap.highest_vol_source:
                lines.append("Top volume:  %s (%d)" % (
                    snap.highest_vol_source, snap.highest_vol_count or 0,
                ))
            lines.append("Analyzed:    %s" % snap.analyzed_at)
            if snap.anomaly_count > 0:
                lines.append("Anomalies:   %d" % snap.anomaly_count)
            if snap.schema_error:
                lines.append("Schema err:  %s" % snap.schema_error)
        else:
            lines.append("(never analyzed)")

        lines.append("")

        # Sources
        lines.append("--- Sources ---")
        lines.append("Active:      %d" % data.source_count)

        lines.append("")

        # Configuration
        lines.append("--- Configuration ---")
        lines.append("Follow:      %s" % (
            "enabled" if acc.follow_enabled else "disabled",
        ))
        lines.append("Unfollow:    %s" % (
            "enabled" if acc.unfollow_enabled else "disabled",
        ))
        if acc.follow_limit_perday:
            lines.append("Follow lim:  %s/day" % acc.follow_limit_perday)
        if acc.like_limit_perday:
            lines.append("Like lim:    %s/day" % acc.like_limit_perday)
        if acc.limit_per_day:
            lines.append("Limit/day:   %s" % acc.limit_per_day)
        lines.append("data.db:     %s" % ("yes" if acc.data_db_exists else "no"))
        lines.append("sources.txt: %s" % ("yes" if acc.sources_txt_exists else "no"))

        lines.append("")

        # Alerts
        if data.alerts:
            lines.append("--- Alerts (%d) ---" % len(data.alerts))
            for alert in data.alerts:
                lines.append("[%s] %s" % (alert.severity, alert.title))
                lines.append("         %s" % alert.detail)
                lines.append("         -> %s" % alert.recommended_action)
        else:
            lines.append("--- Alerts ---")
            lines.append("(none)")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _is_active_slot(acc: AccountRecord, current_hour: int) -> bool:
        """Check if the account's scheduled slot covers the current hour."""
        try:
            start = int(acc.start_time or 0)
            end = int(acc.end_time or 0)
        except (ValueError, TypeError):
            return False
        if start == 0 and end == 0:
            return False
        return start <= current_hour < end

    @staticmethod
    def _extract_level(op_tags_str: str, keyword: str) -> Optional[int]:
        """
        Extract numeric level from operator tags string.

        op_tags_str is the concatenated string from get_operator_tags_map(),
        e.g. "TB3 | limits 2".  We look for a tag matching the keyword.
        """
        if not op_tags_str:
            return None
        for part in op_tags_str.split("|"):
            part = part.strip()
            if keyword == "TB":
                m = _TB_RE.match(part)
                if m:
                    return int(m.group(1))
            elif keyword == "limits":
                m = _LIMITS_RE.match(part)
                if m:
                    return int(m.group(1))
        return None

    def _get_min_source_warning(self) -> int:
        """Read the min_source_count_warning setting (default 5)."""
        try:
            val = self._settings.get("min_source_count_warning")
            return int(val) if val is not None else 5
        except (ValueError, TypeError):
            return 5
