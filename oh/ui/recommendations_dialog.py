"""
RecommendationsDialog — shows operational recommendations for the operator.

Features:
  - Severity-sorted table with quick filter chips
  - Apply Selected → sets review flags on account-level recs
  - Open Target → navigates to account or source in MainWindow
  - Copy to Clipboard
  - Refresh
"""
import logging
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication, QMessageBox, QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut

from oh.models.recommendation import (
    Recommendation,
    REC_LOW_FBR_SOURCE, REC_SOURCE_EXHAUSTION, REC_LOW_LIKE,
    REC_LIMITS_MAX, REC_TB_MAX, REC_ZERO_ACTION,
    REC_TYPE_LABELS,
    SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW,
    TARGET_SOURCE, TARGET_ACCOUNT,
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

_HEADERS = ["Severity", "Type", "Target", "Reason", "Action"]

# Filter options
_FILTER_ALL          = "All"
_FILTER_CRITICAL_HIGH = "Critical + High"
_FILTER_ACCOUNTS     = "Accounts only"
_FILTER_SOURCES      = "Sources only"


class RecommendationsDialog(QDialog):
    def __init__(
        self,
        recommendations: list,
        operator_action_service=None,
        on_refresh: Optional[Callable] = None,
        on_navigate_account: Optional[Callable] = None,
        on_navigate_source: Optional[Callable] = None,
        on_delete_source: Optional[Callable] = None,
        on_clean_account: Optional[Callable] = None,
        on_open_history: Optional[Callable] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._all_recs = recommendations
        self._filtered_recs = list(recommendations)
        self._action_svc = operator_action_service
        self._on_refresh = on_refresh
        self._on_navigate_account = on_navigate_account
        self._on_navigate_source = on_navigate_source
        self._on_delete_source = on_delete_source
        self._on_clean_account = on_clean_account
        self._on_open_history = on_open_history

        self.setWindowTitle("Recommendations")
        self.setMinimumSize(1080, 580)
        self.setModal(False)

        self._build_ui()
        self._populate()

        QShortcut(QKeySequence("Ctrl+R"), self, self._on_refresh_clicked)
        QShortcut(QKeySequence("Escape"), self, self.accept)

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        # Summary header
        self._summary = QLabel()
        self._summary.setStyleSheet(f"font-size: 13px; color: {sc('heading').name()};")
        lo.addWidget(self._summary)

        # Filter bar
        filter_lo = QHBoxLayout()
        filter_lo.setContentsMargins(0, 0, 0, 0)
        filter_lo.setSpacing(8)
        filter_lo.addWidget(QLabel("Show:"))
        self._filter_combo = QComboBox()
        self._filter_combo.addItems([
            _FILTER_ALL, _FILTER_CRITICAL_HIGH,
            _FILTER_ACCOUNTS, _FILTER_SOURCES,
        ])
        self._filter_combo.setFixedWidth(140)
        self._filter_combo.currentIndexChanged.connect(self._apply_filter)
        filter_lo.addWidget(self._filter_combo)
        filter_lo.addStretch()
        lo.addLayout(filter_lo)

        # Table
        t = QTableWidget(0, len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setWordWrap(False)
        t.setSortingEnabled(False)

        t.setColumnWidth(0, 72)   # Severity
        t.setColumnWidth(1, 100)  # Type
        t.setColumnWidth(2, 190)  # Target
        t.setColumnWidth(3, 300)  # Reason
        t.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)

        t.doubleClicked.connect(self._on_double_click)
        self._table = t
        lo.addWidget(t, stretch=1)

        # Status + Buttons
        self._status = QLabel("")
        self._status.setStyleSheet(f"color: {sc('status_ok').name()}; font-size: 11px;")

        btn_lo = QHBoxLayout()
        btn_lo.addWidget(self._status, stretch=1)

        open_btn = QPushButton("Open Target")
        open_btn.setFixedHeight(28)
        open_btn.setToolTip("Navigate to the selected account or source in OH")
        open_btn.clicked.connect(self._on_open_target)
        btn_lo.addWidget(open_btn)

        if self._on_delete_source:
            del_src_btn = QPushButton("Delete Source")
            del_src_btn.setFixedHeight(28)
            del_src_btn.setToolTip("Delete the selected weak source globally")
            del_src_btn.setStyleSheet(
                f"QPushButton {{ color: {sc('error').name()}; }}"
                "QPushButton:hover { background: rgba(200,60,60,30); }"
            )
            del_src_btn.clicked.connect(self._on_delete_source_clicked)
            btn_lo.addWidget(del_src_btn)

        if self._on_clean_account:
            clean_btn = QPushButton("Clean Sources")
            clean_btn.setFixedHeight(28)
            clean_btn.setToolTip("Remove non-quality sources from selected account")
            clean_btn.setStyleSheet(
                f"QPushButton {{ color: {sc('warning').name()}; }}"
                "QPushButton:hover { background: rgba(200,160,40,30); }"
            )
            clean_btn.clicked.connect(self._on_clean_account_clicked)
            btn_lo.addWidget(clean_btn)

        apply_btn = QPushButton("Apply Selected")
        apply_btn.setFixedHeight(28)
        apply_btn.setEnabled(self._action_svc is not None)
        apply_btn.setToolTip("Flag selected accounts for review")
        apply_btn.clicked.connect(self._on_apply)
        btn_lo.addWidget(apply_btn)

        if self._on_open_history:
            hist_btn = QPushButton("Delete History")
            hist_btn.setFixedHeight(28)
            hist_btn.setToolTip("Open deletion history (revert operations)")
            hist_btn.clicked.connect(self._on_open_history)
            btn_lo.addWidget(hist_btn)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(self._on_refresh_clicked)
        btn_lo.addWidget(refresh_btn)

        copy_btn = QPushButton("Copy")
        copy_btn.setFixedHeight(28)
        copy_btn.clicked.connect(self._on_copy)
        btn_lo.addWidget(copy_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        btn_lo.addWidget(close_btn)

        lo.addLayout(btn_lo)

    # ------------------------------------------------------------------
    # Filter
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        filt = self._filter_combo.currentText()
        if filt == _FILTER_ALL:
            self._filtered_recs = list(self._all_recs)
        elif filt == _FILTER_CRITICAL_HIGH:
            self._filtered_recs = [
                r for r in self._all_recs
                if r.severity in (SEV_CRITICAL, SEV_HIGH)
            ]
        elif filt == _FILTER_ACCOUNTS:
            self._filtered_recs = [
                r for r in self._all_recs
                if r.target_type == TARGET_ACCOUNT
            ]
        elif filt == _FILTER_SOURCES:
            self._filtered_recs = [
                r for r in self._all_recs
                if r.target_type == TARGET_SOURCE
            ]
        self._populate()

    # ------------------------------------------------------------------
    # Data
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        self._update_summary()
        self._table.setRowCount(0)

        for rec in self._filtered_recs:
            r = self._table.rowCount()
            self._table.insertRow(r)

            cells = [
                (rec.severity, _sev_colors().get(rec.severity)),
                (REC_TYPE_LABELS.get(rec.rec_type, rec.rec_type), None),
                (_fmt_target(rec), None),
                (_fmt_reason(rec), None),
                (_fmt_action(rec), None),
            ]

            for c, (text, color) in enumerate(cells):
                item = QTableWidgetItem(text)
                if color:
                    item.setForeground(color)
                if c == 0:
                    item.setData(Qt.ItemDataRole.UserRole, rec)
                self._table.setItem(r, c, item)

        self._table.resizeRowsToContents()

    def _update_summary(self) -> None:
        total_all = len(self._all_recs)
        shown = len(self._filtered_recs)
        counts = {}
        for r in self._all_recs:
            counts[r.severity] = counts.get(r.severity, 0) + 1

        parts = []
        for sev in (SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW):
            n = counts.get(sev, 0)
            if n:
                parts.append(f"{n} {sev}")
        breakdown = " \u00b7 ".join(parts) if parts else "none"

        shown_note = f" (showing {shown})" if shown != total_all else ""
        self._summary.setText(
            f"<b>{total_all} recommendations{shown_note}:</b> {breakdown}"
        )

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _get_rec_at_row(self, row: int) -> Optional[Recommendation]:
        item = self._table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_double_click(self, index) -> None:
        rec = self._get_rec_at_row(index.row())
        if rec:
            self._navigate_to(rec)

    def _on_open_target(self) -> None:
        selected = self._get_selected_recs()
        if not selected:
            self._status.setText("Select a row first.")
            return
        self._navigate_to(selected[0])

    def _navigate_to(self, rec: Recommendation) -> None:
        if rec.target_type == TARGET_ACCOUNT and rec.account_id and self._on_navigate_account:
            self._on_navigate_account(rec.account_id)
            self._status.setText(f"Navigated to {rec.target_id}")
        elif rec.target_type == TARGET_SOURCE and self._on_navigate_source:
            self._on_navigate_source(rec.target_id)
            self._status.setText(f"Sources tab: {rec.target_id}")
        else:
            self._status.setText(f"Target: {rec.target_label}")

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _get_selected_recs(self) -> list:
        recs = []
        for idx in self._table.selectionModel().selectedRows():
            rec = self._get_rec_at_row(idx.row())
            if rec:
                recs.append(rec)
        return recs

    def _on_delete_source_clicked(self) -> None:
        """Delete a weak source globally via callback."""
        selected = self._get_selected_recs()
        if not selected:
            self._status.setText("Select a Weak Source row first.")
            return

        rec = selected[0]
        if rec.rec_type != REC_LOW_FBR_SOURCE or rec.target_id == "_bulk":
            if rec.target_id == "_bulk":
                QMessageBox.information(
                    self, "Bulk Delete",
                    "For batch deletion use:\n"
                    "Sources tab \u2192 Bulk Delete Weak Sources",
                )
            else:
                self._status.setText("Select a Weak Source recommendation.")
            return

        result = self._on_delete_source(rec.target_id)
        if result is None:
            return  # user cancelled
        if result.accounts_removed > 0:
            self._status.setText(
                f"'{rec.target_id}' removed from {result.accounts_removed} account(s). "
                "Revert available in Delete History."
            )
        else:
            self._status.setText(f"'{rec.target_id}': no changes.")
        self._do_refresh()

    def _on_clean_account_clicked(self) -> None:
        """Clean non-quality sources from selected account via callback."""
        selected = self._get_selected_recs()
        if not selected:
            self._status.setText("Select an account row first.")
            return

        rec = selected[0]
        if rec.account_id is None:
            self._status.setText("Select an account-level recommendation.")
            return

        result = self._on_clean_account(rec.account_id)
        if result is None:
            return  # user cancelled or no candidates
        n = result.accounts_removed
        if n > 0:
            self._status.setText(
                f"{n} source(s) removed from {rec.target_id}. "
                "Revert available in Delete History."
            )
        else:
            self._status.setText(f"{rec.target_id}: no changes.")
        self._do_refresh()

    def _on_apply(self) -> None:
        selected = self._get_selected_recs()
        if not selected:
            self._status.setText("Select rows first.")
            return

        actionable = [r for r in selected if r.account_id is not None]
        info_only = [r for r in selected if r.account_id is None]

        if not actionable and info_only:
            QMessageBox.information(
                self, "Source Recommendations",
                "Selected items are source-level.\n\n"
                "Use Sources tab \u2192 Bulk Delete Weak Sources.",
            )
            return

        names = [_fmt_target(r) for r in actionable]
        preview = "\n".join(f"  \u2022 {n}" for n in names[:8])
        if len(names) > 8:
            preview += f"\n  ... +{len(names) - 8} more"

        reply = QMessageBox.question(
            self, "Apply Recommendations",
            f"Flag {len(actionable)} account(s) for review?\n\n{preview}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        applied = 0
        for rec in actionable:
            note = f"{REC_TYPE_LABELS.get(rec.rec_type, '')}: {_fmt_reason(rec)}"
            if len(note) > 200:
                note = note[:197] + "..."
            result = self._action_svc.set_review(rec.account_id, note)
            if result == "review_set":
                applied += 1

        msg = f"{applied} kont oflagowanych do review"
        if info_only:
            msg += f" + {len(info_only)} source-level (Sources tab)"
        self._status.setText(msg)
        self._do_refresh()

    # ------------------------------------------------------------------
    # Refresh / Copy
    # ------------------------------------------------------------------

    def _on_refresh_clicked(self) -> None:
        self._do_refresh()
        self._status.setText("Refreshed.")

    def _do_refresh(self) -> None:
        if self._on_refresh:
            new_recs = self._on_refresh()
            if new_recs is not None:
                self._all_recs = new_recs
                self._apply_filter()

    def _on_copy(self) -> None:
        recs = self._filtered_recs
        total = len(recs)
        counts = {}
        for r in recs:
            counts[r.severity] = counts.get(r.severity, 0) + 1
        breakdown = ", ".join(
            f"{counts.get(s, 0)} {s}"
            for s in (SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW)
            if counts.get(s, 0)
        )

        lines = [f"=== RECOMMENDATIONS ({total}: {breakdown}) ===", ""]
        for rec in recs:
            label = REC_TYPE_LABELS.get(rec.rec_type, rec.rec_type)
            lines.append(
                f"[{rec.severity}] {label} | "
                f"{_fmt_target(rec)} | {_fmt_reason(rec)} | {_fmt_action(rec)}"
            )
        QApplication.clipboard().setText("\n".join(lines))
        self._status.setText(f"Copied {total} items.")


# ---------------------------------------------------------------------------
# Formatters — keep reason/action short and operationally focused
# ---------------------------------------------------------------------------

def _fmt_target(rec: Recommendation) -> str:
    """Short target label."""
    if rec.target_type == TARGET_SOURCE:
        return rec.target_id
    # account: username@short_device
    return rec.target_label


def _fmt_reason(rec: Recommendation) -> str:
    """Compact reason — strip redundancy, keep numbers."""
    m = rec.metadata or {}
    t = rec.rec_type

    if t == REC_LOW_FBR_SOURCE:
        wfbr = m.get("weighted_fbr_pct", 0)
        total = m.get("total_weak")
        if total:
            return f"{total} sources wFBR<={m.get('threshold', 5)}%"
        return f"wFBR={wfbr:.1f}%, {m.get('total_follows', 0)} follows"

    if t == REC_SOURCE_EXHAUSTION:
        active = m.get("active_sources", 0)
        quality = m.get("quality_sources", 0)
        if active == 0:
            return "0 sources"
        return f"{active} src, {quality} quality"

    if t == REC_LOW_LIKE:
        return f"follow={m.get('follow_count', 0)}, like=0, limit={m.get('like_limit', 0)}"

    if t == REC_LIMITS_MAX:
        return f"limits {m.get('limits_level', 5)}"

    if t == REC_TB_MAX:
        return f"TB{m.get('tb_level', 5)}"

    if t == REC_ZERO_ACTION:
        return f"0 actions, device running, slot {m.get('slot', '?')}"

    return rec.reason


def _fmt_action(rec: Recommendation) -> str:
    """Short suggested action."""
    t = rec.rec_type

    if t == REC_LOW_FBR_SOURCE:
        if rec.target_id == "_bulk":
            return "Bulk Delete in Sources tab"
        return "Delete source"

    if t == REC_SOURCE_EXHAUSTION:
        active = (rec.metadata or {}).get("active_sources", 0)
        if active == 0:
            return "Add sources"
        return "Replace weak sources"

    if t == REC_LOW_LIKE:
        return "Check like sources"

    if t == REC_LIMITS_MAX:
        return "Replace exhausted sources"

    if t == REC_TB_MAX:
        return "Move to another device"

    if t == REC_ZERO_ACTION:
        return "Check: popup / 2FA / block"

    return rec.suggested_action
