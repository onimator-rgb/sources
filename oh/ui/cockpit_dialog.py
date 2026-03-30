"""
CockpitDialog — Daily Operations Cockpit for OH operators.

A single scrollable view with 5 sections showing the operational state
at a glance.  Designed to be opened at the start of a shift.

Sections:
  A. Do zrobienia teraz — CRITICAL/HIGH recommendations
  B. Konta do review — flagged accounts
  C. Top rekomendacje — next 10 recommendations (deduplicated)
  D. Ostatnie source actions — recent delete history
  E. Dzisiaj wykonano — today's operator actions
"""
import logging
from datetime import datetime
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QScrollArea, QWidget,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.recommendation import (
    Recommendation,
    SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW,
    REC_LOW_FBR_SOURCE, REC_SOURCE_EXHAUSTION, REC_LOW_LIKE,
    REC_LIMITS_MAX, REC_TB_MAX, REC_ZERO_ACTION,
    REC_TYPE_LABELS, TARGET_ACCOUNT, TARGET_SOURCE,
)
from oh.ui.style import sc

logger = logging.getLogger(__name__)


def _sev_colors():
    return {
        SEV_CRITICAL: sc("critical"),
        SEV_HIGH:     sc("high"),
        SEV_MEDIUM:   sc("medium"),
        SEV_LOW:      sc("low"),
    }

def _del_status_colors():
    return {
        "completed": sc("success"),
        "reverted":  sc("muted"),
    }

_OP_ACTION_LABELS = {
    "set_review":       "Set Review",
    "clear_review":     "Clear Review",
    "add_tag":          "Add Tag",
    "remove_tag":       "Remove Tag",
    "increment_tb":     "TB +1",
    "increment_limits": "Limits +1",
}


# Short action commands for section A
_SHORT_ACTIONS = {
    REC_LOW_FBR_SOURCE:   "Usun zrodlo",
    REC_SOURCE_EXHAUSTION: "Wymien zrodla",
    REC_LOW_LIKE:         "Sprawdz like sources",
    REC_LIMITS_MAX:       "Wymien zrodla",
    REC_TB_MAX:           "Przenies konto",
    REC_ZERO_ACTION:      "Sprawdz konto",
}


class CockpitDialog(QDialog):
    def __init__(
        self,
        accounts,
        recommendations,
        review_accounts,
        recent_deletions,
        recent_actions,
        operator_action_service=None,
        on_navigate_account: Optional[Callable] = None,
        on_navigate_source: Optional[Callable] = None,
        on_open_session_report: Optional[Callable] = None,
        on_open_recommendations: Optional[Callable] = None,
        on_open_delete_history: Optional[Callable] = None,
        on_open_action_history: Optional[Callable] = None,
        on_refresh: Optional[Callable] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._accounts = accounts
        self._recs = recommendations
        self._review = review_accounts
        self._deletions = recent_deletions
        self._actions = recent_actions
        self._action_svc = operator_action_service
        self._nav_account = on_navigate_account
        self._nav_source = on_navigate_source
        self._open_report = on_open_session_report
        self._open_recs = on_open_recommendations
        self._open_history = on_open_delete_history
        self._open_actions = on_open_action_history
        self._on_refresh = on_refresh

        # Per-section table refs for actions
        self._urgent_table = None
        self._urgent_items = []
        self._review_table = None
        self._recs_table = None
        self._recs_items = []

        self.setWindowTitle("Daily Operations Cockpit")
        self.setMinimumSize(1020, 660)
        self.setModal(False)
        self._build_ui()

    # ------------------------------------------------------------------
    # UI skeleton
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setSpacing(6)

        self._summary = QLabel()
        self._summary.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()}; font-weight: bold;"
        )
        outer.addWidget(self._summary)

        # Status feedback
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {sc('status_ok').name()}; font-size: 11px;")
        outer.addWidget(self._status)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        self._content_lo = QVBoxLayout(container)
        self._content_lo.setSpacing(14)
        self._content_lo.setContentsMargins(0, 0, 8, 0)
        scroll.setWidget(container)
        outer.addWidget(scroll, stretch=1)

        btn_lo = QHBoxLayout()
        btn_lo.addStretch()
        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(self._do_refresh)
        btn_lo.addWidget(refresh_btn)
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(close_btn)
        outer.addLayout(btn_lo)

        self._populate()

    def _populate(self) -> None:
        while self._content_lo.count():
            item = self._content_lo.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        self._update_summary()
        self._content_lo.addWidget(self._make_urgent_section())
        self._content_lo.addWidget(self._make_review_section())
        self._content_lo.addWidget(self._make_recs_section())
        self._content_lo.addWidget(self._make_deletions_section())
        self._content_lo.addWidget(self._make_today_section())
        self._content_lo.addStretch()

    def _update_summary(self) -> None:
        active = sum(1 for a in self._accounts if a.is_active)
        n_crit = sum(1 for r in self._recs if r.severity == SEV_CRITICAL)
        n_high = sum(1 for r in self._recs if r.severity == SEV_HIGH)
        n_rev = len(self._review)
        now = datetime.now().strftime("%H:%M")
        self._summary.setText(
            f"{active} accounts  \u00b7  "
            f"{n_crit} CRITICAL  \u00b7  "
            f"{n_high} HIGH  \u00b7  "
            f"{n_rev} review  \u00b7  "
            f"{now}"
        )

    # ------------------------------------------------------------------
    # A: Do zrobienia teraz
    # ------------------------------------------------------------------

    def _make_urgent_section(self) -> QWidget:
        critical = [r for r in self._recs if r.severity == SEV_CRITICAL]
        if not critical:
            critical = [r for r in self._recs if r.severity == SEV_HIGH]
        self._urgent_items = critical[:10]
        sev_label = "CRITICAL" if any(
            r.severity == SEV_CRITICAL for r in self._urgent_items
        ) else "HIGH"

        rows = []
        for r in self._urgent_items:
            rows.append([
                (r.severity, _sev_colors().get(r.severity)),
                (REC_TYPE_LABELS.get(r.rec_type, r.rec_type), None),
                (_fmt_target(r), None),
                (_SHORT_ACTIONS.get(r.rec_type, r.suggested_action), None),
            ])

        # Action buttons for this section
        btns = [("Open Target", self._urgent_open_target)]
        if self._action_svc:
            btns.append(("Set Review", self._urgent_set_review))
        btns.append(("Open Report", self._open_report))

        frame, table = self._make_section(
            f"\u26a0  Do zrobienia teraz  ({len(self._urgent_items)} {sev_label})",
            ["Sev", "Type", "Target", "Action"],
            rows,
            self._urgent_items,
            buttons=btns,
            highlight=True,
        )
        self._urgent_table = table
        return frame

    def _urgent_open_target(self) -> None:
        rec = self._get_selected_obj(self._urgent_table, self._urgent_items)
        if rec:
            self._navigate(rec)

    def _urgent_set_review(self) -> None:
        rec = self._get_selected_obj(self._urgent_table, self._urgent_items)
        if not rec or not rec.account_id or not self._action_svc:
            self._status.setText("Select an account-level item.")
            return
        note = f"{REC_TYPE_LABELS.get(rec.rec_type, '')}: {_fmt_reason(rec)}"
        if len(note) > 200:
            note = note[:197] + "..."
        self._action_svc.set_review(rec.account_id, note)
        self._status.setText(f"Review set: {rec.target_id}")
        self._do_refresh()

    # ------------------------------------------------------------------
    # B: Konta do review
    # ------------------------------------------------------------------

    def _make_review_section(self) -> QWidget:
        accts = self._review[:20]
        rows = []
        for a in accts:
            rows.append([
                (a.username, None),
                (a.device_name or a.device_id, None),
                (_truncate(a.review_note or "\u2014", 60), None),
                ((a.review_set_at or "\u2014")[:16].replace("T", " "), None),
            ])

        btns = [("Open Account", self._review_open)]
        if self._action_svc:
            btns.append(("Clear Review", self._review_clear))

        frame, table = self._make_section(
            f"Konta do review  ({len(accts)})",
            ["Username", "Device", "Note", "Flagged At"],
            rows,
            accts,
            buttons=btns,
            empty_msg="Brak kont do review.",
        )
        self._review_table = table
        return frame

    def _review_open(self) -> None:
        acc = self._get_selected_obj(self._review_table, self._review[:20])
        if acc and acc.id and self._nav_account:
            self._nav_account(acc.id)
            self._status.setText(f"Otwarto: {acc.username}")

    def _review_clear(self) -> None:
        acc = self._get_selected_obj(self._review_table, self._review[:20])
        if not acc or not self._action_svc:
            return
        self._action_svc.clear_review(acc.id)
        self._status.setText(f"Review cleared: {acc.username}")
        self._do_refresh()

    # ------------------------------------------------------------------
    # C: Top rekomendacje
    # ------------------------------------------------------------------

    def _make_recs_section(self) -> QWidget:
        urgent_ids = set(
            (r.rec_type, r.target_id) for r in self._urgent_items
        )
        self._recs_items = [
            r for r in self._recs
            if (r.rec_type, r.target_id) not in urgent_ids
        ][:10]

        rows = []
        for r in self._recs_items:
            rows.append([
                (r.severity, _sev_colors().get(r.severity)),
                (REC_TYPE_LABELS.get(r.rec_type, r.rec_type), None),
                (_fmt_target(r), None),
                (_fmt_reason(r), None),
            ])

        btns = [
            ("Open Target", self._recs_open_target),
            ("Open Recommendations", self._open_recs),
        ]

        frame, table = self._make_section(
            f"Top rekomendacje  ({len(self._recs_items)})",
            ["Sev", "Type", "Target", "Reason"],
            rows,
            self._recs_items,
            buttons=btns,
            empty_msg="Brak dodatkowych rekomendacji.",
        )
        self._recs_table = table
        return frame

    def _recs_open_target(self) -> None:
        rec = self._get_selected_obj(self._recs_table, self._recs_items)
        if rec:
            self._navigate(rec)

    # ------------------------------------------------------------------
    # D: Ostatnie source actions
    # ------------------------------------------------------------------

    def _make_deletions_section(self) -> QWidget:
        items = self._deletions[:10]
        rows = []
        for d in items:
            dt = (d.deleted_at or "")[:16].replace("T", " ")
            rows.append([
                (dt, None),
                (d.delete_type, None),
                (d.scope, None),
                (str(d.total_sources), None),
                (str(d.total_accounts_affected), None),
                (d.status, _del_status_colors().get(d.status)),
            ])

        frame, _ = self._make_section(
            f"Ostatnie source actions  ({len(items)})",
            ["Date", "Type", "Scope", "Sources", "Accounts", "Status"],
            rows,
            None,
            buttons=[("Open Delete History", self._open_history)],
            empty_msg="Brak operacji na zrodlach.",
        )
        return frame

    # ------------------------------------------------------------------
    # E: Dzisiaj wykonano
    # ------------------------------------------------------------------

    def _make_today_section(self) -> QWidget:
        items = self._actions[:20]
        rows = []
        for a in items:
            time_str = _fmt_time(a.performed_at)
            label = _OP_ACTION_LABELS.get(a.action_type, a.action_type)
            change = _fmt_change(a.old_value, a.new_value)
            rows.append([
                (time_str, None),
                (a.username, None),
                (label, None),
                (change, None),
            ])

        frame, _ = self._make_section(
            f"Dzisiaj wykonano  ({len(items)})",
            ["Time", "Username", "Action", "Change"],
            rows,
            None,
            buttons=[("Open Action History", self._open_actions)],
            empty_msg="Brak akcji dzisiaj.",
        )
        return frame

    # ------------------------------------------------------------------
    # Section builder
    # ------------------------------------------------------------------

    def _make_section(
        self, title, headers, rows, nav_objects=None,
        buttons=None, highlight=False, empty_msg="No items.",
    ):
        """
        Returns (frame, table_or_None).
        buttons: list of (label, callback) tuples for the header row.
        """
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        border_color = sc("border_urgent").name() if highlight else sc("border").name()
        frame.setStyleSheet(
            f"QFrame {{ border: 1px solid {border_color}; border-radius: 4px; }}"
        )

        lo = QVBoxLayout(frame)
        lo.setContentsMargins(10, 8, 10, 8)
        lo.setSpacing(6)

        # Header
        hdr = QHBoxLayout()
        lbl = QLabel(title)
        title_color = sc("heading_urgent").name() if highlight else sc("heading").name()
        lbl.setStyleSheet(
            f"font-size: 12px; font-weight: bold; color: {title_color}; border: none;"
        )
        hdr.addWidget(lbl)
        hdr.addStretch()

        if buttons:
            for btn_label, btn_cb in buttons:
                if btn_cb is None:
                    continue
                btn = QPushButton(btn_label)
                btn.setFixedHeight(22)
                btn.setStyleSheet(
                    f"border: none; color: {sc('link').name()}; font-size: 10px; padding: 0 6px;"
                )
                btn.setCursor(Qt.CursorShape.PointingHandCursor)
                btn.clicked.connect(btn_cb)
                hdr.addWidget(btn)
        lo.addLayout(hdr)

        if not rows:
            e = QLabel(empty_msg)
            e.setStyleSheet(
                f"color: {sc('status_ok').name()}; font-style: italic; padding: 8px; border: none;"
            )
            lo.addWidget(e)
            return frame, None

        # Table
        t = QTableWidget(len(rows), len(headers))
        t.setHorizontalHeaderLabels(headers)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)
        t.setWordWrap(False)
        t.setShowGrid(False)
        t.horizontalHeader().setStretchLastSection(True)
        t.setStyleSheet("border: none;")

        if headers[0] == "Sev":
            t.setColumnWidth(0, 70)

        rh = 28
        t.setMaximumHeight(rh * min(len(rows), 8) + 32)

        for ri, cells in enumerate(rows):
            for ci, (text, color) in enumerate(cells):
                item = QTableWidgetItem(str(text))
                if color:
                    item.setForeground(color)
                t.setItem(ri, ci, item)
            t.setRowHeight(ri, 28)

        if nav_objects:
            def _dbl(index, objs=nav_objects):
                r = index.row()
                if r < len(objs):
                    self._navigate(objs[r])
            t.doubleClicked.connect(_dbl)

        lo.addWidget(t)
        return frame, t

    # ------------------------------------------------------------------
    # Navigation helper
    # ------------------------------------------------------------------

    def _navigate(self, obj) -> None:
        if hasattr(obj, 'target_type'):
            if obj.target_type == TARGET_ACCOUNT and obj.account_id and self._nav_account:
                self._nav_account(obj.account_id)
                self._status.setText(f"Otwarto: {obj.target_id}")
            elif obj.target_type == TARGET_SOURCE and self._nav_source:
                self._nav_source(obj.target_id)
                self._status.setText(f"Sources: {obj.target_id}")
        elif hasattr(obj, 'review_flag') and obj.id and self._nav_account:
            self._nav_account(obj.id)
            self._status.setText(f"Otwarto: {obj.username}")

    def _get_selected_obj(self, table, items):
        if not table or not items:
            return None
        selected = table.selectionModel().selectedRows()
        if not selected:
            self._status.setText("Zaznacz wiersz.")
            return None
        row = selected[0].row()
        return items[row] if row < len(items) else None

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    def _do_refresh(self) -> None:
        if self._on_refresh:
            data = self._on_refresh()
            if data:
                (self._accounts, self._recs, self._review,
                 self._deletions, self._actions) = data
                self._populate()
                self._status.setText("Refreshed.")


# ---------------------------------------------------------------------------
# Formatters
# ---------------------------------------------------------------------------

def _fmt_target(rec: Recommendation) -> str:
    if rec.target_type == TARGET_SOURCE:
        return rec.target_id
    return rec.target_label


def _fmt_reason(rec: Recommendation) -> str:
    m = rec.metadata or {}
    t = rec.rec_type
    if t == REC_LOW_FBR_SOURCE:
        w = m.get("weighted_fbr_pct", 0)
        total = m.get("total_weak")
        if total:
            return f"{total} sources wFBR<={m.get('threshold', 5)}%"
        return f"wFBR={w:.1f}%, {m.get('total_follows', 0)} follows"
    if t == REC_SOURCE_EXHAUSTION:
        a = m.get("active_sources", 0)
        q = m.get("quality_sources", 0)
        return f"{a} src, {q} quality" if a > 0 else "0 sources"
    if t == REC_LOW_LIKE:
        return f"follow={m.get('follow_count', 0)}, like=0"
    if t == REC_LIMITS_MAX:
        return f"limits {m.get('limits_level', 5)}"
    if t == REC_TB_MAX:
        return f"TB{m.get('tb_level', 5)}"
    if t == REC_ZERO_ACTION:
        return f"0 actions, slot {m.get('slot', '?')}"
    return _truncate(rec.reason, 50)


def _fmt_time(performed_at: str) -> str:
    if not performed_at or len(performed_at) < 19:
        return performed_at or "\u2014"
    # ISO format: 2026-03-30T14:23:45.123+00:00 → 14:23
    return performed_at[11:16]


def _fmt_change(old_value, new_value) -> str:
    if old_value and new_value:
        return f"{old_value} \u2192 {new_value}"
    if new_value:
        return f"\u2192 {new_value}"
    if old_value:
        return f"{old_value} \u2192"
    return "\u2014"


def _truncate(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    return text[:max_len - 3] + "..."
