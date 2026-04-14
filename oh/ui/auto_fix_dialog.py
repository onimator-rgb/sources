"""
AutoFixProposalDialog — operator review dialog for auto-fix proposals.

Shows detected issues as a table with checkboxes. The operator reviews,
selects which proposals to apply, and confirms execution.

Info-only proposals (e.g. dead device alerts) are shown without a checkbox.
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QWidget, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.auto_fix import (
    AutoFixProposal,
    FIX_DEAD_DEVICE,
    FIX_SEV_HIGH, FIX_SEV_MEDIUM, FIX_SEV_LOW,
)
from oh.services.auto_fix_service import AutoFixResult
from oh.ui.style import sc
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

_HEADERS = ["", "Severity", "Type", "Target", "Description", "Detail"]

_SEV_COLORS = {
    FIX_SEV_HIGH: "high",
    FIX_SEV_MEDIUM: "medium",
    FIX_SEV_LOW: "low",
}


class AutoFixProposalDialog(QDialog):
    """Modal dialog for reviewing and approving auto-fix proposals."""

    def __init__(
        self,
        proposals: List[AutoFixProposal],
        auto_fix_service,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._proposals = proposals
        self._service = auto_fix_service
        self.result = AutoFixResult()  # empty until Apply
        self._checkboxes: List[Optional[QCheckBox]] = []
        self._worker: Optional[WorkerThread] = None

        self.setWindowTitle(f"Auto-Fix Proposals ({len(proposals)} issue{'s' if len(proposals) != 1 else ''})")
        self.setMinimumSize(750, 420)
        self.setModal(True)
        self._build_ui()
        self._populate()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(8)

        # Summary header
        n_actionable = sum(1 for p in self._proposals if p.is_actionable)
        n_info = len(self._proposals) - n_actionable
        parts = []
        if n_actionable:
            parts.append(f"{n_actionable} actionable")
        if n_info:
            parts.append(f"{n_info} info-only")
        summary_text = f"{len(self._proposals)} proposals detected  ({', '.join(parts)})"
        summary = QLabel(summary_text)
        summary.setStyleSheet(f"font-size: 13px; color: {sc('heading').name()};")
        lo.addWidget(summary)

        hint = QLabel("Review the proposals below. Check the ones you want to apply.")
        hint.setStyleSheet(f"font-size: 11px; color: {sc('text_secondary').name()};")
        lo.addWidget(hint)

        # Table
        t = QTableWidget(0, len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setWordWrap(False)
        t.setSortingEnabled(False)

        t.setColumnWidth(0, 32)    # Checkbox
        t.setColumnWidth(1, 68)    # Severity
        t.setColumnWidth(2, 140)   # Type
        t.setColumnWidth(3, 160)   # Target
        t.setColumnWidth(4, 220)   # Description
        t.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)

        self._table = t
        lo.addWidget(t, stretch=1)

        # Buttons
        btn_lo = QHBoxLayout()

        sel_all_btn = QPushButton("Select All")
        sel_all_btn.setFixedHeight(28)
        sel_all_btn.clicked.connect(self._select_all)
        btn_lo.addWidget(sel_all_btn)

        desel_all_btn = QPushButton("Deselect All")
        desel_all_btn.setFixedHeight(28)
        desel_all_btn.clicked.connect(self._deselect_all)
        btn_lo.addWidget(desel_all_btn)

        btn_lo.addStretch()

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
        )
        btn_lo.addWidget(self._status_label)

        skip_btn = QPushButton("Skip All")
        skip_btn.setFixedHeight(28)
        skip_btn.setToolTip("Close without applying any changes")
        skip_btn.clicked.connect(self.reject)
        btn_lo.addWidget(skip_btn)

        self._apply_btn = QPushButton("Apply Selected")
        self._apply_btn.setFixedHeight(28)
        self._apply_btn.setToolTip("Execute the checked proposals")
        _hover_bg = sc('success')
        self._apply_btn.setStyleSheet(
            f"QPushButton {{ color: {sc('success').name()}; font-weight: bold; }}"
            f"QPushButton:hover {{ background: rgba({_hover_bg.red()},{_hover_bg.green()},{_hover_bg.blue()},30); }}"
        )
        self._apply_btn.clicked.connect(self._apply_selected)
        btn_lo.addWidget(self._apply_btn)

        lo.addLayout(btn_lo)

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate(self) -> None:
        """Fill the table with proposal rows."""
        self._table.setRowCount(len(self._proposals))
        self._checkboxes.clear()

        for row_idx, proposal in enumerate(self._proposals):
            # Column 0: Checkbox (or info icon for non-actionable)
            if proposal.is_actionable:
                cb = QCheckBox()
                # HIGH severity checked by default, others unchecked
                cb.setChecked(proposal.severity == FIX_SEV_HIGH)
                cb.stateChanged.connect(lambda _: self._update_selected_count())
                cb_widget = QWidget()
                cb_lo = QHBoxLayout(cb_widget)
                cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
                cb_lo.setContentsMargins(0, 0, 0, 0)
                cb_lo.addWidget(cb)
                self._table.setCellWidget(row_idx, 0, cb_widget)
                self._checkboxes.append(cb)
            else:
                info_item = QTableWidgetItem("\u2139")  # info icon
                info_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                info_item.setToolTip("Info-only — no action available")
                self._table.setItem(row_idx, 0, info_item)
                self._checkboxes.append(None)

            # Column 1: Severity
            sev_item = QTableWidgetItem(proposal.severity)
            sev_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            color_key = _SEV_COLORS.get(proposal.severity, "text")
            sev_item.setForeground(sc(color_key))
            self._table.setItem(row_idx, 1, sev_item)

            # Column 2: Type
            type_item = QTableWidgetItem(proposal.type_label)
            self._table.setItem(row_idx, 2, type_item)

            # Column 3: Target
            target_item = QTableWidgetItem(proposal.target)
            self._table.setItem(row_idx, 3, target_item)

            # Column 4: Description
            desc_item = QTableWidgetItem(proposal.description)
            self._table.setItem(row_idx, 4, desc_item)

            # Column 5: Detail
            detail_item = QTableWidgetItem(proposal.detail)
            detail_item.setForeground(sc("text_secondary"))
            self._table.setItem(row_idx, 5, detail_item)

        self._update_selected_count()

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _apply_selected(self) -> None:
        """Execute checked proposals after confirmation, using WorkerThread."""
        selected = []
        for proposal, cb in zip(self._proposals, self._checkboxes):
            if cb is not None and cb.isChecked():
                selected.append(proposal)

        if not selected:
            self._status_label.setText("No proposals selected")
            self._status_label.setStyleSheet(
                f"color: {sc('warning').name()}; font-size: 11px;"
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirm Auto-Fix",
            f"Apply {len(selected)} selected proposal(s)?\n\n"
            f"This will modify bot files on disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Applying...")

        svc = self._service

        def do_execute():
            return svc.execute_proposals(selected)

        self._worker = WorkerThread(do_execute)
        self._worker.result.connect(self._on_apply_done)
        self._worker.error.connect(self._on_apply_error)
        self._worker.start()

    def _on_apply_done(self, result: AutoFixResult) -> None:
        """Handle successful completion of auto-fix execution."""
        self._worker = None
        self.result = result
        self.accept()

    def _on_apply_error(self, error_msg: str) -> None:
        """Handle error during auto-fix execution."""
        self._worker = None
        logger.error("Auto-fix execution error: %s", error_msg)
        self.result = AutoFixResult()
        self.result.errors.append(error_msg)
        self._apply_btn.setEnabled(True)
        self._apply_btn.setText("Apply Selected")
        self._status_label.setText("Execution failed — see logs")
        self._status_label.setStyleSheet(
            f"color: {sc('error').name()}; font-size: 11px;"
        )

    def _select_all(self) -> None:
        """Check all actionable checkboxes."""
        for cb in self._checkboxes:
            if cb is not None:
                cb.setChecked(True)
        self._update_selected_count()

    def _deselect_all(self) -> None:
        """Uncheck all checkboxes."""
        for cb in self._checkboxes:
            if cb is not None:
                cb.setChecked(False)
        self._update_selected_count()

    def _update_selected_count(self) -> None:
        """Update the status label with the count of selected proposals."""
        count = sum(1 for cb in self._checkboxes if cb is not None and cb.isChecked())
        total = sum(1 for cb in self._checkboxes if cb is not None)
        self._status_label.setText(f"{count}/{total} selected")
        self._status_label.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
        )
