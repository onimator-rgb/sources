"""
GroupManagementDialog — create, edit, delete account groups and manage members.

Split view:
  Left:  group list (name, color dot, member count)
  Right: editor form + member list with add/remove
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QPushButton, QLabel, QLineEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QMessageBox, QColorDialog,
    QFormLayout, QTextEdit, QCheckBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.account import AccountRecord
from oh.models.account_group import AccountGroup
from oh.services.account_group_service import AccountGroupService
from oh.ui.style import sc

logger = logging.getLogger(__name__)


class GroupManagementDialog(QDialog):
    def __init__(
        self,
        group_service: AccountGroupService,
        accounts: List[AccountRecord],
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = group_service
        self._accounts = [a for a in accounts if a.is_active]
        self._current_group_id: Optional[int] = None
        self._current_color = "#5B8DEF"

        self.setWindowTitle("Group Management")
        self.setMinimumSize(800, 500)
        self._build_ui()
        self._load_groups()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left pane: group list
        left = QWidget()
        left_lo = QVBoxLayout(left)
        left_lo.setContentsMargins(0, 0, 4, 0)

        left_lo.addWidget(QLabel("Groups"))

        self._group_table = QTableWidget(0, 3)
        self._group_table.setHorizontalHeaderLabels(["Name", "Color", "Members"])
        self._group_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._group_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._group_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._group_table.setColumnWidth(1, 50)
        self._group_table.setColumnWidth(2, 60)
        self._group_table.clicked.connect(self._on_group_selected)
        left_lo.addWidget(self._group_table)

        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("New Group")
        self._new_btn.clicked.connect(self._on_new_group)
        self._del_btn = QPushButton("Delete")
        self._del_btn.clicked.connect(self._on_delete_group)
        self._del_btn.setEnabled(False)
        btn_row.addWidget(self._new_btn)
        btn_row.addWidget(self._del_btn)
        left_lo.addLayout(btn_row)

        splitter.addWidget(left)

        # Right pane: editor + members
        right = QWidget()
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(4, 0, 0, 0)

        # Editor form
        form = QFormLayout()
        self._name_edit = QLineEdit()
        form.addRow("Name:", self._name_edit)

        color_row = QHBoxLayout()
        self._color_label = QLabel("  ")
        self._color_label.setFixedSize(24, 24)
        self._color_label.setStyleSheet("background: #5B8DEF; border: 1px solid gray;")
        color_row.addWidget(self._color_label)
        self._color_btn = QPushButton("Pick Color")
        self._color_btn.clicked.connect(self._on_pick_color)
        color_row.addWidget(self._color_btn)
        color_row.addStretch()
        form.addRow("Color:", color_row)

        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Optional description...")
        form.addRow("Description:", self._desc_edit)

        right_lo.addLayout(form)

        save_btn = QPushButton("Save Group")
        save_btn.clicked.connect(self._on_save_group)
        right_lo.addWidget(save_btn)

        # Member list
        right_lo.addWidget(QLabel("Members"))
        self._member_table = QTableWidget(0, 2)
        self._member_table.setHorizontalHeaderLabels(["Username", "Device"])
        self._member_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._member_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._member_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._member_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self._member_table.setColumnWidth(1, 120)
        right_lo.addWidget(self._member_table)

        member_btns = QHBoxLayout()
        self._add_members_btn = QPushButton("Add Accounts")
        self._add_members_btn.clicked.connect(self._on_add_members)
        self._remove_members_btn = QPushButton("Remove Selected")
        self._remove_members_btn.clicked.connect(self._on_remove_members)
        member_btns.addWidget(self._add_members_btn)
        member_btns.addWidget(self._remove_members_btn)
        right_lo.addLayout(member_btns)

        splitter.addWidget(right)
        splitter.setSizes([250, 550])

        lo.addWidget(splitter)

    # ------------------------------------------------------------------
    # Group list
    # ------------------------------------------------------------------

    def _load_groups(self) -> None:
        groups = self._service.get_all_groups()
        self._group_table.setRowCount(0)
        for g in groups:
            row = self._group_table.rowCount()
            self._group_table.insertRow(row)
            name_item = QTableWidgetItem(g.name)
            name_item.setData(Qt.ItemDataRole.UserRole, g.id)
            self._group_table.setItem(row, 0, name_item)

            color_item = QTableWidgetItem("\u25cf")
            color_item.setForeground(QColor(g.color))
            color_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._group_table.setItem(row, 1, color_item)

            count_item = QTableWidgetItem(str(g.member_count))
            count_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            self._group_table.setItem(row, 2, count_item)

    def _on_group_selected(self, index) -> None:
        row = index.row()
        item = self._group_table.item(row, 0)
        if not item:
            return
        group_id = item.data(Qt.ItemDataRole.UserRole)
        self._current_group_id = group_id
        self._del_btn.setEnabled(True)

        group = self._service.get_group(group_id)
        if group:
            self._name_edit.setText(group.name)
            self._desc_edit.setText(group.description or "")
            self._current_color = group.color
            self._color_label.setStyleSheet(
                f"background: {group.color}; border: 1px solid gray;"
            )
        self._load_members(group_id)

    def _load_members(self, group_id: int) -> None:
        member_ids = set(self._service.get_members(group_id))
        members = [a for a in self._accounts if a.id in member_ids]

        self._member_table.setRowCount(0)
        for a in members:
            row = self._member_table.rowCount()
            self._member_table.insertRow(row)
            name_item = QTableWidgetItem(a.username)
            name_item.setData(Qt.ItemDataRole.UserRole, a.id)
            self._member_table.setItem(row, 0, name_item)
            self._member_table.setItem(row, 1, QTableWidgetItem(
                a.device_name or a.device_id
            ))

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new_group(self) -> None:
        self._current_group_id = None
        self._name_edit.clear()
        self._desc_edit.clear()
        self._current_color = "#5B8DEF"
        self._color_label.setStyleSheet("background: #5B8DEF; border: 1px solid gray;")
        self._member_table.setRowCount(0)
        self._del_btn.setEnabled(False)
        self._name_edit.setFocus()

    def _on_delete_group(self) -> None:
        if self._current_group_id is None:
            return
        reply = QMessageBox.question(
            self, "Delete Group",
            "Are you sure you want to delete this group?\n"
            "Accounts will NOT be deleted — only the group assignment.",
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._service.delete_group(self._current_group_id)
        self._current_group_id = None
        self._load_groups()
        self._name_edit.clear()
        self._desc_edit.clear()
        self._member_table.setRowCount(0)
        self._del_btn.setEnabled(False)

    def _on_save_group(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Group name is required.")
            return

        try:
            if self._current_group_id is None:
                group = self._service.create_group(
                    name, self._current_color, self._desc_edit.text().strip() or None
                )
                self._current_group_id = group.id
            else:
                self._service.update_group(
                    self._current_group_id,
                    name, self._current_color,
                    self._desc_edit.text().strip() or None,
                )
            self._load_groups()
        except Exception as exc:
            QMessageBox.critical(self, "Error", f"Failed to save group:\n\n{exc}")

    def _on_pick_color(self) -> None:
        color = QColorDialog.getColor(
            QColor(self._current_color), self, "Pick Group Color"
        )
        if color.isValid():
            self._current_color = color.name()
            self._color_label.setStyleSheet(
                f"background: {self._current_color}; border: 1px solid gray;"
            )

    def _on_add_members(self) -> None:
        if self._current_group_id is None:
            QMessageBox.warning(self, "No Group", "Save or select a group first.")
            return

        existing_ids = set(self._service.get_members(self._current_group_id))
        available = [a for a in self._accounts if a.id not in existing_ids]

        if not available:
            QMessageBox.information(self, "No Accounts", "All accounts are already in this group.")
            return

        # Simple picker dialog
        dlg = _AccountPickerDialog(available, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            selected = dlg.selected_ids()
            if selected:
                self._service.assign_accounts(self._current_group_id, selected)
                self._load_members(self._current_group_id)
                self._load_groups()

    def _on_remove_members(self) -> None:
        if self._current_group_id is None:
            return
        selected_rows = self._member_table.selectionModel().selectedRows()
        if not selected_rows:
            return
        ids = []
        for idx in selected_rows:
            item = self._member_table.item(idx.row(), 0)
            if item:
                ids.append(item.data(Qt.ItemDataRole.UserRole))
        if ids:
            self._service.unassign_accounts(self._current_group_id, ids)
            self._load_members(self._current_group_id)
            self._load_groups()


class _AccountPickerDialog(QDialog):
    """Simple checkbox-based account picker."""

    def __init__(self, accounts: List[AccountRecord], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Select Accounts")
        self.setMinimumSize(400, 400)
        self._accounts = accounts
        self._checkboxes: list = []
        self._build_ui()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)

        # Search
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search accounts...")
        self._search.textChanged.connect(self._filter)
        lo.addWidget(self._search)

        # Table with checkboxes
        self._table = QTableWidget(0, 3)
        self._table.setHorizontalHeaderLabels(["", "Username", "Device"])
        self._table.setColumnWidth(0, 30)
        self._table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._table.setColumnWidth(2, 120)

        for acc in self._accounts:
            row = self._table.rowCount()
            self._table.insertRow(row)
            cb = QCheckBox()
            self._checkboxes.append((cb, acc))
            self._table.setCellWidget(row, 0, cb)
            name_item = QTableWidgetItem(acc.username)
            name_item.setData(Qt.ItemDataRole.UserRole, acc.id)
            self._table.setItem(row, 1, name_item)
            self._table.setItem(row, 2, QTableWidgetItem(acc.device_name or acc.device_id))

        lo.addWidget(self._table)

        # Select all / OK / Cancel
        btn_row = QHBoxLayout()
        sel_all = QPushButton("Select All")
        sel_all.clicked.connect(self._select_all)
        btn_row.addWidget(sel_all)
        btn_row.addStretch()
        ok_btn = QPushButton("Add Selected")
        ok_btn.clicked.connect(self.accept)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(ok_btn)
        btn_row.addWidget(cancel_btn)
        lo.addLayout(btn_row)

    def _filter(self, text: str) -> None:
        query = text.strip().lower()
        for row, (cb, acc) in enumerate(self._checkboxes):
            match = not query or query in acc.username.lower()
            self._table.setRowHidden(row, not match)

    def _select_all(self) -> None:
        for i, (cb, _) in enumerate(self._checkboxes):
            if not self._table.isRowHidden(i):
                cb.setChecked(True)

    def selected_ids(self) -> List[int]:
        return [acc.id for cb, acc in self._checkboxes if cb.isChecked() and acc.id is not None]
