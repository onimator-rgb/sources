"""
SessionReportDialog — operational session report for OH operators.

Shows a tabbed summary of accounts needing attention based on
session snapshots, device status, review flags, and tag data.

Built entirely from data already in memory (accounts list, session map,
FBR map, device status map) — no extra DB queries required.

Severity levels:
  CRITICAL — immediate intervention required this session
  HIGH     — must be addressed today
  MEDIUM   — review within 24h
  LOW      — informational, no rush
"""
import logging
import re
from datetime import date, datetime
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTabWidget, QWidget,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.session import slot_for_times

logger = logging.getLogger(__name__)

C_CRITICAL = QColor("#e05555")
C_HIGH     = QColor("#e6a817")
C_MEDIUM   = QColor("#86c5f0")
C_LOW      = QColor("#888888")
C_GREEN    = QColor("#4caf7d")

_SEV_COLORS = {
    "CRITICAL": C_CRITICAL,
    "HIGH":     C_HIGH,
    "MEDIUM":   C_MEDIUM,
    "LOW":      C_LOW,
}
_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

_TB_RE = re.compile(r"TB(\d)", re.IGNORECASE)

# TB warmup recommendations per level
_TB_RECOMMENDATIONS = {
    1: "Warmup od nowa: Follow Limit/day=10, Added Daily Limit=10, Till it Reaches=80, Like Limit/day=10",
    2: "Warmup od nowa: Follow Limit/day=10, Added Daily Limit=10, Till it Reaches=60, Like Limit/day=10",
    3: "Warmup od nowa: Follow Limit/day=10, Added Daily Limit=10, Till it Reaches=40, Like Limit/day=10",
    4: "Warmup od nowa: Follow Limit/day=10, Added Daily Limit=10, Till it Reaches=30, Like Limit/day=10",
    5: "Przenieś konto na inne urządzenie, warmup od zera",
}


class SessionReportDialog(QDialog):
    def __init__(
        self,
        accounts: list,
        session_map: dict,
        fbr_map: dict,
        device_status_map: Optional[dict] = None,
        operator_action_service=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._accounts = [a for a in accounts if a.is_active]
        self._session_map = session_map
        self._fbr_map = fbr_map
        self._device_status_map = device_status_map or {}
        self._action_svc = operator_action_service
        self._today = date.today().isoformat()
        self._current_hour = datetime.now().hour

        # username → account_id lookup for actions
        self._username_to_id = {a.username: a.id for a in self._accounts}

        self.setWindowTitle(f"Session Report \u2014 {self._today}")
        self.setMinimumSize(1060, 640)
        self.setModal(False)

        self._build_ui()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _is_active_slot(self, acc) -> bool:
        """Check if the account's assigned slot covers the current hour."""
        try:
            start = int(acc.start_time or 0)
            end = int(acc.end_time or 0)
        except (ValueError, TypeError):
            return False
        if start == 0 and end == 0:
            return False  # unscheduled
        return start <= self._current_hour < end

    @staticmethod
    def _extract_tb_level(raw_tags: str) -> Optional[int]:
        """Extract TB level (1-5) from raw tags string. Returns None if no TB tag."""
        if not raw_tags:
            return None
        m = _TB_RE.search(raw_tags)
        if m:
            level = int(m.group(1))
            return min(level, 5)
        return None

    @staticmethod
    def _extract_limits_level(raw_tags: str) -> Optional[int]:
        """Extract [N] level from raw tags string."""
        if not raw_tags:
            return None
        m = re.match(r"\[(\d+)\]", raw_tags)
        return int(m.group(1)) if m else None

    def _device_status(self, device_id: str, device_name: str) -> str:
        if "spuch" in device_name.lower():
            return "HARDWARE"
        raw = self._device_status_map.get(device_id)
        return raw if raw else "offline"

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        with_activity = sum(1 for s in self._session_map.values() if s.has_activity)
        header = QLabel(
            f"<b>Session Report</b> \u2014 {self._today} \u2014 "
            f"{len(self._accounts)} active accounts \u2014 "
            f"{with_activity} with activity \u2014 "
            f"current hour: {self._current_hour}:00"
        )
        header.setStyleSheet("font-size: 13px; color: #c0d8f0;")
        lo.addWidget(header)

        self._tabs = QTabWidget()
        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #4caf7d; font-size: 11px;")

        self._rebuild_tabs()

        lo.addWidget(self._tabs, stretch=1)

        # Bottom bar: status + buttons
        btn_lo = QHBoxLayout()
        btn_lo.addWidget(self._status_label, stretch=1)
        copy_btn = QPushButton("Copy Report to Clipboard")
        copy_btn.clicked.connect(self._copy_report)
        btn_lo.addWidget(copy_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.close)
        btn_lo.addWidget(close_btn)
        lo.addLayout(btn_lo)

    def _rebuild_tabs(self) -> None:
        """(Re)build all report sections. Called on init and after actions."""
        self._tabs.clear()

        # Collect all section data
        self._zero_data = self._get_zero_activity()
        self._devices_data = self._get_devices_not_running()
        self._review_data = self._get_review_flagged()
        self._low_follow_data = self._get_low_follow()
        self._low_like_data = self._get_low_like()
        self._tb_data = self._get_tb_accounts()
        self._limits_data = self._get_limits_accounts()
        self._actions_data = self._build_operator_actions()

        has_svc = self._action_svc is not None

        # Tab 0: Actions
        self._tabs.addTab(
            self._make_table_tab(self._actions_data, [
                "Severity", "Action", "Affected", "Recommendation",
            ]),
            f"\u26a0 Actions ({len(self._actions_data)})",
        )

        # Tab 1: 0 Actions + Flag for Review button
        self._tabs.addTab(
            self._make_table_tab(self._zero_data, [
                "Severity", "Username", "Device", "Slot", "Tags", "Reason", "Recommendation",
            ], action_btn=("Flag Selected for Review", self._on_flag_selected_review) if has_svc else None),
            f"0 Actions ({len(self._zero_data)})",
        )

        # Tab 2: Devices
        self._tabs.addTab(
            self._make_table_tab(self._devices_data, [
                "Severity", "Device", "Status", "Accounts", "Recommendation",
            ]),
            f"Devices ({len(self._devices_data)})",
        )

        # Tab 3: Review + Clear Review button
        self._tabs.addTab(
            self._make_table_tab(self._review_data, [
                "Severity", "Username", "Device", "Note", "Flagged At", "Recommendation",
            ], action_btn=("Clear Selected Review", self._on_clear_selected_review) if has_svc else None),
            f"Review ({len(self._review_data)})",
        )

        # Tab 4: Low Follow
        self._tabs.addTab(
            self._make_table_tab(self._low_follow_data, [
                "Severity", "Username", "Device", "Follow", "Limit", "%", "Tags", "Recommendation",
            ]),
            f"Low Follow ({len(self._low_follow_data)})",
        )

        # Tab 5: Low Like
        self._tabs.addTab(
            self._make_table_tab(self._low_like_data, [
                "Severity", "Username", "Device", "Like", "Limit", "%", "Recommendation",
            ]),
            f"Low Like ({len(self._low_like_data)})",
        )

        # Tab 6: TB + TB+1 button
        self._tabs.addTab(
            self._make_table_tab(self._tb_data, [
                "Severity", "Username", "Device", "TB Level", "Follow", "Like", "Recommendation",
            ], action_btn=("TB +1 Selected", self._on_tb_increment_selected) if has_svc else None),
            f"TB ({len(self._tb_data)})",
        )

        # Tab 7: Limits + Limits+1 button
        self._tabs.addTab(
            self._make_table_tab(self._limits_data, [
                "Severity", "Username", "Device", "Limits Level", "Follow", "Like", "Recommendation",
            ], action_btn=("Limits +1 Selected", self._on_limits_increment_selected) if has_svc else None),
            f"Limits ({len(self._limits_data)})",
        )

    # ------------------------------------------------------------------
    # Section A: 0 actions today
    # ------------------------------------------------------------------

    def _get_zero_activity(self) -> list:
        rows = []
        for acc in self._accounts:
            sess = self._session_map.get(acc.id)
            if sess and sess.has_activity:
                continue

            dev_status = self._device_status(acc.device_id, acc.device_name or "")
            in_slot = self._is_active_slot(acc)

            if not acc.follow_enabled:
                sev = "LOW"
                reason = "Follow disabled"
                rec = "Verify if intentional. Re-enable or document reason."
            elif dev_status not in ("running",):
                sev = "CRITICAL" if in_slot else "HIGH"
                reason = f"Device {dev_status}"
                rec = "Check device: connection, WiFi, Onimator Viewer restart."
            elif in_slot:
                sev = "HIGH"
                reason = "0 actions in active slot"
                rec = "Check account: popup, 2FA, logout, action block."
            else:
                sev = "LOW"
                reason = "Not in active slot"
                rec = "Monitor at next slot start."

            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                sess.slot if sess else slot_for_times(acc.start_time, acc.end_time),
                acc.bot_tags_raw or "\u2014",
                reason,
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section B: Devices not running
    # ------------------------------------------------------------------

    def _get_devices_not_running(self) -> list:
        device_info = {}
        for acc in self._accounts:
            did = acc.device_id
            if did not in device_info:
                dname = acc.device_name or did
                device_info[did] = {
                    "name": dname,
                    "accounts": 0,
                    "status": self._device_status(did, dname),
                }
            device_info[did]["accounts"] += 1

        rows = []
        for did, info in device_info.items():
            st = info["status"]
            if st == "running":
                continue
            acct_count = info["accounts"]
            if st == "HARDWARE":
                sev = "CRITICAL"
                rec = "Natychmiast odłącz, przenieś konta na nowe urządzenie."
            elif acct_count > 0:
                sev = "CRITICAL"
                rec = f"Restart Onimator na urządzeniu. Sprawdź kabel/WiFi/zasilanie."
            else:
                sev = "MEDIUM"
                rec = "Brak aktywnych kont. Sprawdź czy urządzenie jest potrzebne."
            rows.append([sev, info["name"], st, str(acct_count), rec])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section C: Review flagged
    # ------------------------------------------------------------------

    def _get_review_flagged(self) -> list:
        rows = []
        for acc in self._accounts:
            if not acc.review_flag:
                continue
            note = (acc.review_note or "").lower()
            if any(kw in note for kw in ("block", "try again", "banned")):
                sev = "HIGH"
                rec = "Sprawdź status blocka. Jeśli minął, clear flag i restart."
            elif "pending" in note:
                sev = "MEDIUM"
                rec = "Operacja oczekująca. Sprawdź postęp."
            else:
                sev = "LOW"
                rec = "Przejrzyj notatkę i podejmij decyzję."
            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                acc.review_note or "\u2014",
                (acc.review_set_at or "\u2014")[:16],
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section D: Low follow
    # ------------------------------------------------------------------

    def _get_low_follow(self) -> list:
        rows = []
        for acc in self._accounts:
            if not acc.follow_enabled:
                continue
            sess = self._session_map.get(acc.id)
            follow = sess.follow_count if sess else 0
            try:
                limit = int(acc.follow_limit_perday or 0)
            except (ValueError, TypeError):
                limit = 0

            limits_lvl = self._extract_limits_level(acc.bot_tags_raw)
            limits_note = f" (limits {limits_lvl})" if limits_lvl else ""

            if follow == 0:
                # Handled in "0 actions" tab already — skip unless follow-only zero
                if sess and (sess.like_count > 0 or sess.dm_count > 0):
                    sev = "HIGH"
                    rec = f"Follow=0 ale inne akcje działają. Sprawdź sources/popup.{limits_note}"
                else:
                    continue  # fully zero → in 0 actions tab
            elif follow < 40:
                sev = "MEDIUM"
                rec = f"Follow<40. Możliwy throttle lub block.{limits_note}"
            elif limit > 0 and follow < limit * 0.5:
                sev = "LOW"
                pct_val = round(follow / limit * 100, 1)
                rec = f"{pct_val}% limitu. Monitor, możliwe slow scraping.{limits_note}"
            else:
                continue

            pct_str = f"{round(follow / limit * 100, 1)}%" if limit > 0 else "\u2014"
            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                str(follow),
                str(limit) if limit > 0 else "\u2014",
                pct_str,
                acc.bot_tags_raw or "\u2014",
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section E: Low like
    # ------------------------------------------------------------------

    def _get_low_like(self) -> list:
        rows = []
        for acc in self._accounts:
            sess = self._session_map.get(acc.id)
            if not sess:
                continue
            like = sess.like_count
            try:
                limit = int(acc.like_limit_perday or 0)
            except (ValueError, TypeError):
                limit = 0

            if limit <= 0:
                continue  # no like limit configured → not a like account

            if like == 0 and (sess.follow_count > 0 or self._is_active_slot(acc)):
                sev = "MEDIUM"
                rec = "Like=0 ale konto aktywne. Sprawdź like sources i ustawienia."
            elif 0 < like < 75:
                sev = "LOW"
                rec = "Like<75. Sprawdź like-source-followers.txt, rozważ nowe źródła."
            elif limit > 0 and like < limit * 0.3:
                sev = "LOW"
                pct_val = round(like / limit * 100, 1)
                rec = f"{pct_val}% limitu. Monitor."
            else:
                continue

            pct_str = f"{round(like / limit * 100, 1)}%" if limit > 0 else "\u2014"
            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                str(like),
                str(limit),
                pct_str,
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section F: TB accounts
    # ------------------------------------------------------------------

    def _get_tb_accounts(self) -> list:
        rows = []
        for acc in self._accounts:
            tb_level = self._extract_tb_level(acc.bot_tags_raw)
            if tb_level is None:
                continue

            sess = self._session_map.get(acc.id)
            if tb_level >= 5:
                sev = "CRITICAL"
            elif tb_level >= 3:
                sev = "HIGH"
            else:
                sev = "MEDIUM"

            rec = _TB_RECOMMENDATIONS.get(tb_level, "Review TB status.")

            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                f"TB{tb_level}",
                str(sess.follow_count) if sess else "\u2014",
                str(sess.like_count) if sess else "\u2014",
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section G: Limits accounts
    # ------------------------------------------------------------------

    def _get_limits_accounts(self) -> list:
        rows = []
        for acc in self._accounts:
            lvl = self._extract_limits_level(acc.bot_tags_raw)
            if lvl is None:
                continue

            sess = self._session_map.get(acc.id)
            if lvl >= 5:
                sev = "HIGH"
                rec = "Limits wysoki. Rozważ usunięcie zużytych źródeł i podmianę na nowe."
            elif lvl >= 3:
                sev = "MEDIUM"
                rec = "Limits średni. Monitoruj performance źródeł."
            else:
                sev = "LOW"
                rec = "Limits niski. Normalna praca."

            rows.append([
                sev,
                acc.username,
                acc.device_name or acc.device_id,
                f"limits {lvl}",
                str(sess.follow_count) if sess else "\u2014",
                str(sess.like_count) if sess else "\u2014",
                rec,
            ])
        rows.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return rows

    # ------------------------------------------------------------------
    # Section H: Operator actions (aggregated checklist)
    # ------------------------------------------------------------------

    def _build_operator_actions(self) -> list:
        actions = []

        # --- CRITICAL ---
        hw = [d for d in self._devices_data if d[0] == "CRITICAL" and "HARDWARE" in d[2]]
        if hw:
            actions.append([
                "CRITICAL",
                f"Wymiana urządzeń z problemem hardware: {', '.join(d[1] for d in hw)}",
                str(len(hw)),
                "Odłącz urządzenia, przenieś konta na zapasowe.",
            ])

        dev_crit = [d for d in self._devices_data
                    if d[0] == "CRITICAL" and "HARDWARE" not in d[2]]
        if dev_crit:
            actions.append([
                "CRITICAL",
                f"Urządzenia offline z aktywnymi kontami: {', '.join(d[1] for d in dev_crit)}",
                str(sum(int(d[3]) for d in dev_crit)),
                "Restart Onimator, sprawdź kabel/WiFi/zasilanie.",
            ])

        zero_crit = [z for z in self._zero_data if z[0] == "CRITICAL"]
        if zero_crit:
            actions.append([
                "CRITICAL",
                "Konta bez akcji na offline device w aktywnym slocie",
                str(len(zero_crit)),
                "Napraw urządzenie najpierw, potem sprawdź konta.",
            ])

        tb_crit = [t for t in self._tb_data if t[0] == "CRITICAL"]
        if tb_crit:
            actions.append([
                "CRITICAL",
                f"TB5 — konta do przeniesienia: {', '.join(t[1] for t in tb_crit)}",
                str(len(tb_crit)),
                "Przenieś na inne urządzenie, warmup od zera.",
            ])

        # --- HIGH ---
        zero_high = [z for z in self._zero_data if z[0] == "HIGH"]
        if zero_high:
            actions.append([
                "HIGH",
                "Konta bez akcji w aktywnym slocie (device ok)",
                str(len(zero_high)),
                "Sprawdź na urządzeniu: popup, 2FA, wylogowanie, action block.",
            ])

        tb_high = [t for t in self._tb_data if t[0] == "HIGH"]
        if tb_high:
            actions.append([
                "HIGH",
                f"TB3/TB4 — konta z action blockiem",
                str(len(tb_high)),
                "Sprawdź czy blokada minęła, zastosuj warmup wg procedury TB.",
            ])

        review_high = [r for r in self._review_data if r[0] == "HIGH"]
        if review_high:
            actions.append([
                "HIGH",
                "Konta review z blockiem/banem",
                str(len(review_high)),
                "Sprawdź status konta, clear flag po rozwiązaniu.",
            ])

        follow_high = [f for f in self._low_follow_data if f[0] == "HIGH"]
        if follow_high:
            actions.append([
                "HIGH",
                "Konta z follow=0 ale innymi aktywnymi akcjami",
                str(len(follow_high)),
                "Sprawdź sources.txt i popup/block specyficzny dla follow.",
            ])

        limits_high = [l for l in self._limits_data if l[0] == "HIGH"]
        if limits_high:
            actions.append([
                "HIGH",
                f"Konta z high limits (>=5)",
                str(len(limits_high)),
                "Rozważ usunięcie zużytych źródeł, podmiana na nowe.",
            ])

        # --- MEDIUM ---
        zero_disabled = [z for z in self._zero_data if z[0] == "LOW" and "disabled" in z[5].lower()]
        if zero_disabled:
            actions.append([
                "MEDIUM",
                "Konta z wyłączonym follow",
                str(len(zero_disabled)),
                "Re-enable lub udokumentuj powód (cooldown, ban).",
            ])

        follow_med = [f for f in self._low_follow_data if f[0] == "MEDIUM"]
        if follow_med:
            actions.append([
                "MEDIUM",
                "Konta z follow < 40",
                str(len(follow_med)),
                "Zwiększ uwagę, możliwy throttle. Sprawdź logi bota.",
            ])

        tb_med = [t for t in self._tb_data if t[0] == "MEDIUM"]
        if tb_med:
            actions.append([
                "MEDIUM",
                f"TB1/TB2 — konta z lekkim action blockiem",
                str(len(tb_med)),
                "Zastosuj warmup wg procedury TB1/TB2.",
            ])

        like_med = [l for l in self._low_like_data if l[0] == "MEDIUM"]
        if like_med:
            actions.append([
                "MEDIUM",
                "Konta z like=0 mimo aktywności",
                str(len(like_med)),
                "Sprawdź like sources i ustawienia likepost.",
            ])

        review_other = [r for r in self._review_data if r[0] != "HIGH"]
        if review_other:
            actions.append([
                "MEDIUM" if any(r[0] == "MEDIUM" for r in review_other) else "LOW",
                "Konta review do przeglądu",
                str(len(review_other)),
                "Przejrzyj notatki, podejmij decyzję.",
            ])

        # --- LOW ---
        follow_low = [f for f in self._low_follow_data if f[0] == "LOW"]
        if follow_low:
            actions.append([
                "LOW",
                "Konta z follow < 50% limitu",
                str(len(follow_low)),
                "Monitor. Sprawdź przy następnym przeglądzie.",
            ])

        actions.sort(key=lambda r: _SEV_RANK.get(r[0], 9))
        return actions

    # ------------------------------------------------------------------
    # Table builder
    # ------------------------------------------------------------------

    def _make_table_tab(self, data, headers, action_btn=None):
        """
        Build a tab widget with a table and optional action button.

        action_btn — tuple of (label, callback) or None.
        """
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(4, 4, 4, 4)

        if not data:
            lbl = QLabel("No items in this section.")
            lbl.setStyleSheet("color: #4caf7d; font-style: italic; padding: 20px;")
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lo.addWidget(lbl)
            return w

        # Action toolbar above the table
        if action_btn:
            toolbar = QHBoxLayout()
            toolbar.setContentsMargins(0, 0, 0, 2)
            btn = QPushButton(action_btn[0])
            btn.setFixedHeight(26)
            btn.clicked.connect(action_btn[1])
            toolbar.addWidget(btn)
            toolbar.addStretch()
            lo.addLayout(toolbar)

        t = QTableWidget(len(data), len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setWordWrap(True)
        t.horizontalHeader().setStretchLastSection(True)

        if headers[0] == "Severity":
            t.setColumnWidth(0, 75)
        if "Recommendation" in headers:
            rec_idx = headers.index("Recommendation")
            for i in range(len(headers)):
                if i != rec_idx and headers[i] != "Severity":
                    t.horizontalHeader().setSectionResizeMode(
                        i, QHeaderView.ResizeMode.ResizeToContents
                    )

        t.setSortingEnabled(False)
        for r, row_data in enumerate(data):
            for c, val in enumerate(row_data):
                item = QTableWidgetItem(str(val))
                if headers[c] == "Severity" and val in _SEV_COLORS:
                    item.setForeground(_SEV_COLORS[val])
                if val == "HARDWARE":
                    item.setForeground(C_CRITICAL)
                if val == "offline":
                    item.setForeground(C_HIGH)
                t.setItem(r, c, item)
        t.setSortingEnabled(True)
        t.resizeRowsToContents()

        # Store table ref on widget so action callbacks can find it
        w._report_table = t
        lo.addWidget(t)
        return w

    # ------------------------------------------------------------------
    # Action callbacks
    # ------------------------------------------------------------------

    def _get_selected_usernames(self) -> list:
        """Get usernames from selected rows in the current tab's table."""
        current = self._tabs.currentWidget()
        table = getattr(current, '_report_table', None)
        if not table:
            return []
        usernames = []
        for idx in table.selectionModel().selectedRows():
            # Username is always column 1 in sections that have actions
            item = table.item(idx.row(), 1)
            if item:
                usernames.append(item.text())
        return usernames

    def _resolve_ids(self, usernames: list) -> list:
        """Map usernames to account_ids. Returns list of (account_id, username)."""
        pairs = []
        for u in usernames:
            aid = self._username_to_id.get(u)
            if aid is not None:
                pairs.append((aid, u))
        return pairs

    def _on_flag_selected_review(self) -> None:
        pairs = self._resolve_ids(self._get_selected_usernames())
        if not pairs:
            self._status_label.setText("Select account rows first.")
            return
        names = ", ".join(u for _, u in pairs)
        reply = QMessageBox.question(
            self, "Flag for Review",
            f"Flag {len(pairs)} account(s) for review?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        for aid, username in pairs:
            self._action_svc.set_review(aid, "Flagged from session report")
        self._status_label.setText(f"Review set: {len(pairs)} account(s)")
        self._rebuild_tabs()

    def _on_clear_selected_review(self) -> None:
        pairs = self._resolve_ids(self._get_selected_usernames())
        if not pairs:
            self._status_label.setText("Select account rows first.")
            return
        for aid, username in pairs:
            self._action_svc.clear_review(aid)
        self._status_label.setText(f"Review cleared: {len(pairs)} account(s)")
        self._rebuild_tabs()

    def _on_tb_increment_selected(self) -> None:
        pairs = self._resolve_ids(self._get_selected_usernames())
        if not pairs:
            self._status_label.setText("Select account rows first.")
            return
        names = ", ".join(u for _, u in pairs)
        reply = QMessageBox.question(
            self, "TB +1",
            f"Increment TB for {len(pairs)} account(s)?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        results = []
        for aid, username in pairs:
            r = self._action_svc.increment_tb(aid)
            results.append(f"{username}: {r}")
        self._status_label.setText(f"TB incremented: {', '.join(results)}")
        self._rebuild_tabs()

    def _on_limits_increment_selected(self) -> None:
        pairs = self._resolve_ids(self._get_selected_usernames())
        if not pairs:
            self._status_label.setText("Select account rows first.")
            return
        names = ", ".join(u for _, u in pairs)
        reply = QMessageBox.question(
            self, "Limits +1",
            f"Increment limits for {len(pairs)} account(s)?\n{names}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        results = []
        for aid, username in pairs:
            r = self._action_svc.increment_limits(aid)
            results.append(f"{username}: {r}")
        self._status_label.setText(f"Limits incremented: {', '.join(results)}")
        self._rebuild_tabs()

    # ------------------------------------------------------------------
    # Copy to clipboard
    # ------------------------------------------------------------------

    def _copy_report(self) -> None:
        lines = []
        lines.append(f"=== SESSION REPORT \u2014 {self._today} ===")
        lines.append(f"Active accounts: {len(self._accounts)}")
        lines.append(f"With activity: {sum(1 for s in self._session_map.values() if s.has_activity)}")
        lines.append(f"Current hour: {self._current_hour}:00")
        lines.append("")

        def _section(title, data, headers):
            lines.append(f"--- {title} ({len(data)}) ---")
            if not data:
                lines.append("  (none)")
            else:
                lines.append("  " + " | ".join(headers))
                for row in data:
                    lines.append("  " + " | ".join(str(v) for v in row))
            lines.append("")

        _section("OPERATOR ACTIONS", self._actions_data,
                 ["Severity", "Action", "Affected", "Recommendation"])
        _section("0 ACTIONS TODAY", self._zero_data,
                 ["Sev", "Username", "Device", "Slot", "Tags", "Reason", "Rec"])
        _section("DEVICES NOT RUNNING", self._devices_data,
                 ["Sev", "Device", "Status", "Accounts", "Rec"])
        _section("REVIEW FLAGGED", self._review_data,
                 ["Sev", "Username", "Device", "Note", "Flagged", "Rec"])
        _section("LOW FOLLOW", self._low_follow_data,
                 ["Sev", "Username", "Device", "Follow", "Limit", "%", "Tags", "Rec"])
        _section("LOW LIKE", self._low_like_data,
                 ["Sev", "Username", "Device", "Like", "Limit", "%", "Rec"])
        _section("TB ACCOUNTS", self._tb_data,
                 ["Sev", "Username", "Device", "TB", "Follow", "Like", "Rec"])
        _section("LIMITS ACCOUNTS", self._limits_data,
                 ["Sev", "Username", "Device", "Limits", "Follow", "Like", "Rec"])

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
        logger.info(f"[Report] Copied session report to clipboard ({len(lines)} lines)")
