"""
DeleteHistoryDialog — shows the source deletion history stored in OH DB.
Supports reverting completed delete actions.

Main view: table of recent actions (newest first) with status.
Detail view: items for the selected action, shown in a bottom pane.
Revert: restores deleted sources back to sources.txt for affected accounts.
"""
import logging
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from oh.models.delete_history import SourceDeleteResult
from oh.repositories.delete_history_repo import DeleteHistoryRepository
from oh.ui.delete_confirm_dialog import DeleteConfirmDialog

logger = logging.getLogger(__name__)

_TYPE_COLORS = {
    "single": QColor("#86c5f0"),
    "bulk":   QColor("#e6a817"),
    "revert": QColor("#4caf7d"),
}

_STATUS_COLORS = {
    "completed": QColor("#4caf7d"),
    "reverted":  QColor("#888888"),
}


class DeleteHistoryDialog(QDialog):
    def __init__(
        self,
        history_repo: DeleteHistoryRepository,
        on_revert: Optional[Callable[[int], SourceDeleteResult]] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = history_repo
        self._on_revert = on_revert
        self.setWindowTitle("Source Deletion History")
        self.setMinimumSize(900, 520)
        self.setModal(False)
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        lo.addWidget(QLabel(
            "Each row is one delete operation. Select a row to see details. "
            "Completed actions can be reverted."
        ))

        splitter = QSplitter(Qt.Orientation.Vertical)

        # -- Actions table --
        at = QTableWidget(0, 7)
        at.setHorizontalHeaderLabels(
            ["Date / Time", "Status", "Type", "Sources", "Accounts", "Threshold", "Machine"]
        )
        at.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        at.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        at.verticalHeader().setVisible(False)
        at.setAlternatingRowColors(True)
        at.setSortingEnabled(False)

        hdr = at.horizontalHeader()
        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        at.setColumnWidth(0, 150)
        at.setColumnWidth(1,  85)
        at.setColumnWidth(2,  70)
        at.setColumnWidth(3,  80)
        at.setColumnWidth(4,  90)
        at.setColumnWidth(5,  90)

        at.selectionModel().selectionChanged.connect(self._on_action_selected)
        self._actions_table = at
        splitter.addWidget(at)

        # -- Items detail pane --
        splitter.addWidget(self._make_items_pane())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        lo.addWidget(splitter, stretch=1)

        # -- Bottom button row --
        row = QHBoxLayout()

        self._revert_btn = QPushButton("Revert Selected")
        self._revert_btn.setFixedHeight(28)
        self._revert_btn.setEnabled(False)
        self._revert_btn.setToolTip("Restore deleted sources back to sources.txt")
        self._revert_btn.setStyleSheet(
            "QPushButton:enabled { color: #4caf7d; }"
            "QPushButton:enabled:hover { background: #1a2e1a; }"
        )
        self._revert_btn.clicked.connect(self._on_revert_clicked)
        row.addWidget(self._revert_btn)

        if self._on_revert is None:
            self._revert_btn.setVisible(False)

        row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)

        lo.addLayout(row)

    def _make_items_pane(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)

        self._items_header = QLabel("Select an action above to see deleted sources.")
        self._items_header.setStyleSheet("color: #777; font-size: 11px;")
        lo.addWidget(self._items_header)

        t = QTableWidget(0, 5)
        t.setHorizontalHeaderLabels(
            ["Source", "Removed", "Not Found", "Failed", "Accounts Affected"]
        )
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.verticalHeader().setVisible(False)
        t.setAlternatingRowColors(True)
        t.setSortingEnabled(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in range(1, 5):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(1, 80)
        t.setColumnWidth(2, 90)
        t.setColumnWidth(3, 70)
        t.setColumnWidth(4, 180)

        self._items_table = t
        lo.addWidget(t, stretch=1)
        return w

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load(self) -> None:
        actions = self._repo.get_recent_actions()
        self._actions = actions

        self._actions_table.setRowCount(0)
        center = Qt.AlignmentFlag.AlignCenter

        if not actions:
            self._actions_table.insertRow(0)
            msg = QTableWidgetItem("No deletion history yet.")
            msg.setTextAlignment(center)
            msg.setForeground(QColor("#777"))
            self._actions_table.setItem(0, 0, msg)
            self._actions_table.setSpan(0, 0, 1, 7)
            return

        for action in actions:
            r = self._actions_table.rowCount()
            self._actions_table.insertRow(r)

            date_str = action.deleted_at[:16].replace("T", "  ") if action.deleted_at else "—"
            date_item = QTableWidgetItem(date_str)
            date_item.setData(Qt.ItemDataRole.UserRole, action.id)
            self._actions_table.setItem(r, 0, date_item)

            # Status
            status_item = QTableWidgetItem(action.status.capitalize())
            status_item.setTextAlignment(center)
            status_item.setForeground(
                _STATUS_COLORS.get(action.status, QColor("#aaa"))
            )
            self._actions_table.setItem(r, 1, status_item)

            # Type — show scope for clarity
            if action.revert_of_action_id:
                type_text = f"Revert #{action.revert_of_action_id}"
            elif action.delete_type == "bulk":
                type_text = "Bulk"
            elif action.scope == "account":
                type_text = "Account"
            else:
                type_text = "Global"
            type_item = QTableWidgetItem(type_text)
            type_item.setTextAlignment(center)
            type_item.setForeground(
                _TYPE_COLORS.get(action.delete_type, QColor("#aaa"))
            )
            self._actions_table.setItem(r, 2, type_item)

            for col, val in [
                (3, str(action.total_sources)),
                (4, str(action.total_accounts_affected)),
            ]:
                item = QTableWidgetItem(val)
                item.setTextAlignment(center)
                self._actions_table.setItem(r, col, item)

            thresh = f"{action.threshold_pct:.1f}%" if action.threshold_pct is not None else "—"
            ti = QTableWidgetItem(thresh)
            ti.setTextAlignment(center)
            self._actions_table.setItem(r, 5, ti)

            self._actions_table.setItem(r, 6, QTableWidgetItem(action.machine or ""))

    # ------------------------------------------------------------------
    # Selection
    # ------------------------------------------------------------------

    def _on_action_selected(self) -> None:
        selected = self._actions_table.selectedItems()
        if not selected:
            self._items_header.setText("Select an action above to see deleted sources.")
            self._items_table.setRowCount(0)
            self._revert_btn.setEnabled(False)
            return

        row = selected[0].row()
        item0 = self._actions_table.item(row, 0)
        if not item0:
            self._revert_btn.setEnabled(False)
            return
        action_id = item0.data(Qt.ItemDataRole.UserRole)
        if action_id is None:
            self._revert_btn.setEnabled(False)
            return

        # Find the action in our cached list
        action = next((a for a in self._actions if a.id == action_id), None)

        items = self._repo.get_items_for_action(action_id)

        # Determine revert eligibility with reason for tooltip
        if self._on_revert is None or action is None:
            can_revert = False
            revert_tip = ""
        elif action.status == "reverted":
            can_revert = False
            revert_tip = "This action has already been reverted"
        elif action.delete_type == "revert":
            can_revert = False
            revert_tip = "Cannot revert a revert — delete again instead"
        elif not any(it.affected_details for it in items):
            can_revert = False
            revert_tip = "No restore data (action was logged before revert support was added)"
        elif not any(it.files_removed > 0 for it in items):
            can_revert = False
            revert_tip = "No files were successfully removed in this action"
        else:
            can_revert = True
            revert_tip = "Restore deleted sources back to sources.txt"

        self._revert_btn.setEnabled(can_revert)
        self._revert_btn.setToolTip(revert_tip)

        is_revert_action = action is not None and action.delete_type == "revert"
        label = "Sources restored" if is_revert_action else "Sources deleted"
        self._items_header.setText(f"{label} in this action ({len(items)}):")

        center = Qt.AlignmentFlag.AlignCenter
        self._items_table.setRowCount(0)

        for item in items:
            r = self._items_table.rowCount()
            self._items_table.insertRow(r)
            self._items_table.setItem(r, 0, QTableWidgetItem(item.source_name))
            for col, val in [
                (1, str(item.files_removed)),
                (2, str(item.files_not_found)),
                (3, str(item.files_failed)),
            ]:
                i = QTableWidgetItem(val)
                i.setTextAlignment(center)
                if col == 3 and item.files_failed > 0:
                    i.setForeground(QColor("#e05555"))
                self._items_table.setItem(r, col, i)
            accs = ", ".join(item.affected_accounts[:8])
            if len(item.affected_accounts) > 8:
                accs += f" ... (+{len(item.affected_accounts) - 8})"
            self._items_table.setItem(r, 4, QTableWidgetItem(accs))

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def _on_revert_clicked(self) -> None:
        if self._on_revert is None:
            return

        selected = self._actions_table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        item0 = self._actions_table.item(row, 0)
        if not item0:
            return
        action_id = item0.data(Qt.ItemDataRole.UserRole)
        if action_id is None:
            return

        # Load full action with items for the confirmation dialog
        action = self._repo.get_action_with_items(action_id)
        if action is None:
            QMessageBox.warning(self, "Revert Error", "Action not found.")
            return

        source_names = [item.source_name for item in action.items if item.files_removed > 0]
        account_count = action.total_accounts_affected

        if not source_names:
            QMessageBox.information(
                self, "Nothing to Revert",
                "This action did not successfully remove any sources."
            )
            return

        # Confirm
        dlg = DeleteConfirmDialog.for_revert(
            action_id, source_names, account_count, parent=self
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return

        # Disable button during execution to prevent double-click
        self._revert_btn.setEnabled(False)
        self._revert_btn.setText("Reverting...")

        # Execute revert
        try:
            result = self._on_revert(action_id)
            QMessageBox.information(
                self, "Revert Complete",
                result.summary_line(is_revert=True),
            )
        except Exception as e:
            logger.exception(f"Revert failed for action #{action_id}")
            QMessageBox.critical(
                self, "Revert Failed",
                f"Error during revert:\n\n{e}",
            )

        # Reload history and reset UI
        self._revert_btn.setText("Revert Selected")
        self._load()
        self._items_table.setRowCount(0)
        self._items_header.setText("Select an action above to see deleted sources.")
        self._revert_btn.setEnabled(False)
