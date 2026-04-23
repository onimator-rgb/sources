"""
OperatorActionHistoryDialog — shows recent operator actions from the audit trail.

Modeled after DeleteHistoryDialog: simple table, newest first, optional
per-account filter, copy to clipboard.
"""
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QApplication,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.ui.style import sc

logger = logging.getLogger(__name__)

def _type_colors():
    return {
        "set_review":       sc("warning"),
        "clear_review":     sc("muted"),
        "add_tag":          sc("link"),
        "remove_tag":       sc("muted"),
        "increment_tb":     sc("error"),
        "increment_limits": sc("warning"),
    }

_TYPE_LABELS = {
    "set_review":       "Set Review",
    "clear_review":     "Clear Review",
    "add_tag":          "Add Tag",
    "remove_tag":       "Remove Tag",
    "increment_tb":     "TB +1",
    "increment_limits": "Limits +1",
}

_HEADERS = [
    "Date / Time", "Username", "Device", "Action", "Old", "New", "Note", "Machine",
]


class OperatorActionHistoryDialog(QDialog):
    def __init__(
        self,
        action_repo: OperatorActionRepository,
        account_id: Optional[int] = None,
        account_name: Optional[str] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._repo = action_repo
        self._account_id = account_id

        title = "Operator Action History"
        if account_name:
            title += f" \u2014 {account_name}"
        self.setWindowTitle(title)
        self.setMinimumSize(920, 480)
        self.setModal(False)

        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)

        desc = "Recent operator actions (newest first)."
        if self._account_id:
            desc = f"Actions for this account (newest first)."
        lo.addWidget(QLabel(desc))

        t = QTableWidget(0, len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        t.setColumnWidth(0, 150)  # Date
        t.setColumnWidth(1, 140)  # Username
        t.setColumnWidth(2, 100)  # Device
        t.setColumnWidth(3, 90)   # Action
        t.setColumnWidth(4, 90)   # Old
        t.setColumnWidth(5, 90)   # New
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)  # Note
        t.setColumnWidth(7, 80)   # Machine

        self._table = t
        lo.addWidget(t, stretch=1)

        # Bottom row
        row = QHBoxLayout()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(28)
        refresh_btn.clicked.connect(self._load)
        row.addWidget(refresh_btn)

        copy_btn = QPushButton("Copy to Clipboard")
        copy_btn.setFixedHeight(28)
        copy_btn.clicked.connect(self._copy)
        row.addWidget(copy_btn)

        row.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        row.addWidget(close_btn)

        lo.addLayout(row)

    def _load(self) -> None:
        if self._account_id:
            actions = self._repo.get_for_account(self._account_id)
        else:
            actions = self._repo.get_recent(100)

        self._table.setRowCount(0)
        for action in actions:
            r = self._table.rowCount()
            self._table.insertRow(r)

            dt = (action.performed_at or "")[:19].replace("T", "  ")
            action_label = _TYPE_LABELS.get(action.action_type, action.action_type)
            action_color = _type_colors().get(action.action_type)

            cells = [
                dt,
                action.username,
                action.device_id[:12] if action.device_id else "",
                action_label,
                action.old_value or "\u2014",
                action.new_value or "\u2014",
                action.note or "",
                action.machine or "",
            ]

            for c, val in enumerate(cells):
                item = QTableWidgetItem(val)
                if c == 3 and action_color:
                    item.setForeground(action_color)
                self._table.setItem(r, c, item)

    def _copy(self) -> None:
        lines = ["=== OPERATOR ACTION HISTORY ==="]
        lines.append(" | ".join(_HEADERS))
        for r in range(self._table.rowCount()):
            row_vals = []
            for c in range(self._table.columnCount()):
                item = self._table.item(r, c)
                row_vals.append(item.text() if item else "")
            lines.append(" | ".join(row_vals))
        QApplication.clipboard().setText("\n".join(lines))
        logger.info(f"[ActionHistory] Copied {self._table.rowCount()} rows to clipboard")
