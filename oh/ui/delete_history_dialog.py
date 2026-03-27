"""
DeleteHistoryDialog — shows the source deletion history stored in OH DB.

Main view: table of recent actions (newest first).
Detail view: items for the selected action, shown in a bottom pane.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.repositories.delete_history_repo import DeleteHistoryRepository

_TYPE_COLORS = {
    "single": QColor("#86c5f0"),
    "bulk":   QColor("#e6a817"),
}


class DeleteHistoryDialog(QDialog):
    def __init__(self, history_repo: DeleteHistoryRepository, parent=None) -> None:
        super().__init__(parent)
        self._repo = history_repo
        self.setWindowTitle("Source Deletion History")
        self.setMinimumSize(820, 520)
        self.setModal(False)   # non-modal — operator can keep it open
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        lo.addWidget(QLabel(
            "Each row is one delete operation. Select a row to see which sources were deleted."
        ))

        splitter = QSplitter(Qt.Orientation.Vertical)

        # -- Actions table --
        at = QTableWidget(0, 6)
        at.setHorizontalHeaderLabels(
            ["Date / Time", "Type", "Sources", "Accounts", "Threshold", "Machine"]
        )
        at.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        at.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        at.verticalHeader().setVisible(False)
        at.setAlternatingRowColors(True)
        at.setSortingEnabled(False)

        hdr = at.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        at.setColumnWidth(0, 150)
        at.setColumnWidth(1,  70)
        at.setColumnWidth(2,  80)
        at.setColumnWidth(3,  90)
        at.setColumnWidth(4,  90)

        at.selectionModel().selectionChanged.connect(self._on_action_selected)
        self._actions_table = at
        splitter.addWidget(at)

        # -- Items detail pane --
        detail_w = QWidget() if False else self._make_items_pane()
        splitter.addWidget(detail_w)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        lo.addWidget(splitter, stretch=1)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        row = QHBoxLayout()
        row.addStretch()
        row.addWidget(close_btn)
        lo.addLayout(row)

    def _make_items_pane(self):
        from PySide6.QtWidgets import QWidget
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
            self._actions_table.setSpan(0, 0, 1, 6)
            return

        for action in actions:
            r = self._actions_table.rowCount()
            self._actions_table.insertRow(r)

            date_str = action.deleted_at[:16].replace("T", "  ") if action.deleted_at else "—"
            self._actions_table.setItem(r, 0, QTableWidgetItem(date_str))

            type_item = QTableWidgetItem(action.delete_type.capitalize())
            type_item.setTextAlignment(center)
            type_item.setForeground(_TYPE_COLORS.get(action.delete_type, QColor("#aaa")))
            self._actions_table.setItem(r, 1, type_item)

            for col, val in [
                (2, str(action.total_sources)),
                (3, str(action.total_accounts_affected)),
            ]:
                item = QTableWidgetItem(val)
                item.setTextAlignment(center)
                self._actions_table.setItem(r, col, item)

            thresh = f"{action.threshold_pct:.1f}%" if action.threshold_pct is not None else "—"
            ti = QTableWidgetItem(thresh)
            ti.setTextAlignment(center)
            self._actions_table.setItem(r, 4, ti)

            self._actions_table.setItem(r, 5, QTableWidgetItem(action.machine or ""))

            # Store action_id on first column
            self._actions_table.item(r, 0).setData(
                Qt.ItemDataRole.UserRole, action.id
            )

    def _on_action_selected(self) -> None:
        selected = self._actions_table.selectedItems()
        if not selected:
            self._items_header.setText("Select an action above to see deleted sources.")
            self._items_table.setRowCount(0)
            return

        row = selected[0].row()
        item0 = self._actions_table.item(row, 0)
        if not item0:
            return
        action_id = item0.data(Qt.ItemDataRole.UserRole)
        if action_id is None:
            return

        items = self._repo.get_items_for_action(action_id)
        self._items_header.setText(
            f"Sources deleted in this action ({len(items)}):"
        )

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
                accs += f" … (+{len(item.affected_accounts) - 8})"
            self._items_table.setItem(r, 4, QTableWidgetItem(accs))


# Avoid referencing QWidget before __init__ — fix the _make_items_pane to not be in __init__
# Already correct as-is since _make_items_pane is a separate method called inside _build_ui.


# Small shim: QWidget import needed inside _make_items_pane
from PySide6.QtWidgets import QWidget  # noqa: E402 — intentional late import
