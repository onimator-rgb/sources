"""
DeleteConfirmDialog — modal confirmation before any destructive source deletion.

Used for both single-source and bulk-delete flows.
The operator must explicitly click the red confirm button; Cancel is the default.
"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from oh.models.global_source import GlobalSourceRecord


class DeleteConfirmDialog(QDialog):
    """
    Modal confirmation dialog.  Returns True if the operator confirmed.

    Use via:
        dlg = DeleteConfirmDialog.for_single(source_name, assignments, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted: ...

        dlg = DeleteConfirmDialog.for_bulk(threshold, sources, parent)
        if dlg.exec() == QDialog.DialogCode.Accepted: ...
    """

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setModal(True)
        self.setMinimumWidth(560)

    # ------------------------------------------------------------------
    # Factory methods
    # ------------------------------------------------------------------

    @classmethod
    def for_single(
        cls,
        source_name: str,
        assignments: list[tuple[int, str, str, str]],  # (acc_id, device_id, username, device_name)
        parent=None,
    ) -> "DeleteConfirmDialog":
        dlg = cls(parent)
        dlg.setWindowTitle("Confirm Source Deletion")
        dlg._build_single(source_name, assignments)
        return dlg

    @classmethod
    def for_bulk(
        cls,
        threshold_pct: float,
        sources: list[GlobalSourceRecord],
        parent=None,
    ) -> "DeleteConfirmDialog":
        dlg = cls(parent)
        dlg.setWindowTitle("Confirm Bulk Source Deletion")
        dlg._build_bulk(threshold_pct, sources)
        return dlg

    # ------------------------------------------------------------------
    # UI builders
    # ------------------------------------------------------------------

    def _build_single(
        self,
        source_name: str,
        assignments: list[tuple],
    ) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)

        lo.addWidget(self._warning_label(
            f'Delete source:  "{source_name}"'
        ))

        count = len(assignments)
        lo.addWidget(QLabel(
            f"This will remove <b>{source_name}</b> from <b>sources.txt</b> "
            f"on <b>{count} account(s)</b>:"
        ))

        # Account list
        if assignments:
            t = QTableWidget(len(assignments), 2)
            t.setHorizontalHeaderLabels(["Username", "Device"])
            t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            t.verticalHeader().setVisible(False)
            t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
            t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
            t.setColumnWidth(1, 130)
            t.setMaximumHeight(200)
            t.setSortingEnabled(False)

            for r, (_, _, username, device_name) in enumerate(assignments):
                t.setItem(r, 0, QTableWidgetItem(username))
                t.setItem(r, 1, QTableWidgetItem(device_name or ""))

            lo.addWidget(t)

        lo.addWidget(self._note(
            "data.db (follow history) is NOT modified.\n"
            "A backup (sources.txt.bak) will be created before each file write."
        ))

        lo.addLayout(self._button_row(f"Delete from {count} account(s)"))

    def _build_bulk(
        self,
        threshold_pct: float,
        sources: list[GlobalSourceRecord],
    ) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)

        total_accounts = sum(s.active_accounts for s in sources)
        lo.addWidget(self._warning_label(
            f"Bulk delete: weighted FBR \u2264 {threshold_pct:.1f}%"
        ))
        lo.addWidget(QLabel(
            f"This will remove <b>{len(sources)} source(s)</b> from "
            f"<b>{total_accounts} active assignment(s)</b>:"
        ))

        # Sources list
        t = QTableWidget(len(sources), 3)
        t.setHorizontalHeaderLabels(["Source", "Wtd FBR %", "Active Accounts"])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        t.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Fixed)
        t.setColumnWidth(1, 90)
        t.setColumnWidth(2, 110)
        t.setMaximumHeight(220)
        t.setSortingEnabled(False)

        center = Qt.AlignmentFlag.AlignCenter
        for r, src in enumerate(sources):
            t.setItem(r, 0, QTableWidgetItem(src.source_name))
            fbr_item = QTableWidgetItem(
                f"{src.weighted_fbr_pct:.1f}%" if src.weighted_fbr_pct is not None else "—"
            )
            fbr_item.setTextAlignment(center)
            fbr_item.setForeground(QColor("#e05555"))
            t.setItem(r, 1, fbr_item)
            acc_item = QTableWidgetItem(str(src.active_accounts))
            acc_item.setTextAlignment(center)
            t.setItem(r, 2, acc_item)

        lo.addWidget(t)

        lo.addWidget(self._note(
            "Only sources with known weighted FBR and sufficient follow data are included.\n"
            "data.db (follow history) is NOT modified.\n"
            "A backup (sources.txt.bak) will be created before each file write."
        ))

        lo.addLayout(self._button_row(f"Delete {len(sources)} Source(s)"))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _warning_label(text: str) -> QLabel:
        lbl = QLabel(text)
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        lbl.setFont(font)
        lbl.setStyleSheet("color: #e05555;")
        return lbl

    @staticmethod
    def _note(text: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("background: #2a2a2e; border-radius: 4px; padding: 4px;")
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(8, 6, 8, 6)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: #aaa; font-size: 11px;")
        lbl.setWordWrap(True)
        lo.addWidget(lbl)
        return frame

    def _button_row(self, confirm_text: str) -> QHBoxLayout:
        lo = QHBoxLayout()
        lo.addStretch()

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(28)
        cancel_btn.setDefault(True)  # Cancel is the default (safe)
        cancel_btn.clicked.connect(self.reject)
        lo.addWidget(cancel_btn)

        confirm_btn = QPushButton(confirm_text)
        confirm_btn.setFixedHeight(28)
        confirm_btn.setStyleSheet(
            "QPushButton { background: #8b1a1a; color: white; border-radius: 3px; }"
            "QPushButton:hover { background: #c02020; }"
        )
        confirm_btn.clicked.connect(self.accept)
        lo.addWidget(confirm_btn)

        return lo
