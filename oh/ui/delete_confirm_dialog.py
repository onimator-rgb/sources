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
from PySide6.QtGui import QFont

from oh.models.fbr import SourceFBRRecord
from oh.models.global_source import GlobalSourceRecord
from oh.ui.style import sc


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

    @classmethod
    def for_single_account(
        cls,
        source_name: str,
        username: str,
        device_name: str,
        parent=None,
    ) -> "DeleteConfirmDialog":
        dlg = cls(parent)
        dlg.setWindowTitle("Confirm Source Deletion")
        dlg._build_single_account(source_name, username, device_name)
        return dlg

    @classmethod
    def for_account_cleanup(
        cls,
        username: str,
        device_name: str,
        sources: list,
        total_active: int = 0,
        parent=None,
    ) -> "DeleteConfirmDialog":
        """Preview non-quality sources to remove from one account."""
        dlg = cls(parent)
        dlg.setWindowTitle("Confirm Account Source Cleanup")
        dlg._selected_sources = list(sources)  # mutable; updated by checkboxes
        dlg._build_account_cleanup(username, device_name, sources, total_active)
        return dlg

    @property
    def selected_sources(self) -> list:
        """Return the list of sources the operator chose to delete.
        Only meaningful after for_account_cleanup()."""
        return getattr(self, "_selected_sources", [])

    @classmethod
    def for_revert(
        cls,
        action_id: int,
        source_names: list[str],
        account_count: int,
        parent=None,
    ) -> "DeleteConfirmDialog":
        dlg = cls(parent)
        dlg.setWindowTitle("Confirm Revert")
        dlg._build_revert(action_id, source_names, account_count)
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
            fbr_item.setForeground(sc("error"))
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

    def _build_single_account(
        self,
        source_name: str,
        username: str,
        device_name: str,
    ) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)

        lo.addWidget(self._warning_label(
            f'Delete source:  "{source_name}"'
        ))

        lo.addWidget(QLabel(
            f"This will remove <b>{source_name}</b> from <b>sources.txt</b> "
            f"for account <b>{username}</b> on device <b>{device_name}</b> only."
        ))

        lo.addWidget(self._note(
            "This affects only this one account, not other accounts using the same source.\n"
            "data.db (follow history) is NOT modified.\n"
            "A backup (sources.txt.bak) will be created before the file write.\n"
            "This action can be reverted from the deletion history."
        ))

        lo.addLayout(self._button_row(f"Delete from {username}"))

    def _build_revert(
        self,
        action_id: int,
        source_names: list[str],
        account_count: int,
    ) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)

        lbl = QLabel(f"Revert delete action #{action_id}")
        font = QFont()
        font.setBold(True)
        font.setPointSize(11)
        lbl.setFont(font)
        lbl.setStyleSheet("color: %s;" % sc("success").name())
        lo.addWidget(lbl)

        sources_preview = ", ".join(source_names[:5])
        if len(source_names) > 5:
            sources_preview += f" ... (+{len(source_names) - 5})"

        lo.addWidget(QLabel(
            f"This will restore <b>{len(source_names)} source(s)</b> to "
            f"<b>sources.txt</b> on up to <b>{account_count} account(s)</b>."
            f"<br><br>Sources: {sources_preview}"
        ))

        lo.addWidget(self._note(
            "Sources will be added back to sources.txt for accounts where they were removed.\n"
            "If a source is already present in an account's file, it will be skipped.\n"
            "A backup (sources.txt.bak) will be created before each file write."
        ))

        confirm_btn_text = f"Restore {len(source_names)} source(s)"
        # Use green confirm style for restore
        row_lo = QHBoxLayout()
        row_lo.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(28)
        cancel_btn.setDefault(True)
        cancel_btn.clicked.connect(self.reject)
        row_lo.addWidget(cancel_btn)
        confirm_btn = QPushButton(confirm_btn_text)
        confirm_btn.setFixedHeight(28)
        confirm_btn.setStyleSheet(
            "QPushButton { background: %s; color: white; border-radius: 3px; }"
            "QPushButton:hover { background: %s; }"
            % (sc("success").name(), sc("status_ok").name())
        )
        confirm_btn.clicked.connect(self.accept)
        row_lo.addWidget(confirm_btn)
        lo.addLayout(row_lo)

    def _build_account_cleanup(
        self,
        username: str,
        device_name: str,
        sources: list,
        total_active: int,
    ) -> None:
        from PySide6.QtWidgets import QCheckBox

        lo = QVBoxLayout(self)
        lo.setSpacing(12)

        lo.addWidget(self._warning_label(
            f"Remove non-quality sources: {username}"
        ))

        remaining = total_active - len(sources)
        lo.addWidget(QLabel(
            f"Account: <b>{username}</b> on <b>{device_name}</b><br>"
            f"<b>{len(sources)}</b> non-quality source(s) selected for removal. "
            f"<b>{remaining}</b> source(s) will remain."
        ))

        if remaining < 5 and remaining >= 0:
            warn = QLabel(
                f"Warning: only {remaining} source(s) will remain after cleanup."
            )
            warn.setStyleSheet("color: %s; font-weight: bold;" % sc("warning").name())
            lo.addWidget(warn)

        # Table with checkboxes
        t = QTableWidget(len(sources), 4)
        t.setHorizontalHeaderLabels(["Remove", "Source", "Follows", "FBR %"])
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.verticalHeader().setVisible(False)
        t.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        t.setColumnWidth(0, 55)
        t.setColumnWidth(2, 70)
        t.setColumnWidth(3, 70)
        t.setMaximumHeight(250)
        t.setSortingEnabled(False)

        center = Qt.AlignmentFlag.AlignCenter
        self._checkboxes = []

        for r, src in enumerate(sources):
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(self._on_checkbox_changed)
            self._checkboxes.append((cb, src))
            cb_widget = QFrame()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.addWidget(cb)
            t.setCellWidget(r, 0, cb_widget)

            t.setItem(r, 1, QTableWidgetItem(src.source_name))

            follows_item = QTableWidgetItem(str(src.follow_count))
            follows_item.setTextAlignment(center)
            t.setItem(r, 2, follows_item)

            fbr_item = QTableWidgetItem(f"{src.fbr_percent:.1f}%")
            fbr_item.setTextAlignment(center)
            fbr_item.setForeground(sc("error"))
            t.setItem(r, 3, fbr_item)

        lo.addWidget(t)
        self._cleanup_table = t

        lo.addWidget(self._note(
            "Uncheck sources you want to keep.\n"
            "data.db (follow history) is NOT modified.\n"
            "A backup (sources.txt.bak) will be created before each file write."
        ))

        self._confirm_btn_ref = None
        row_lo = self._button_row(f"Remove {len(sources)} source(s)")
        # Find the confirm button to update its text on checkbox changes
        for i in range(row_lo.count()):
            w = row_lo.itemAt(i).widget()
            if w and isinstance(w, QPushButton) and w is not self.findChild(QPushButton, ""):
                if "Remove" in w.text():
                    self._confirm_btn_ref = w
        lo.addLayout(row_lo)

    def _on_checkbox_changed(self) -> None:
        """Update selected_sources and confirm button text when checkboxes change."""
        selected = [src for cb, src in self._checkboxes if cb.isChecked()]
        self._selected_sources = selected
        if self._confirm_btn_ref:
            self._confirm_btn_ref.setText(f"Remove {len(selected)} source(s)")

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
        lbl.setStyleSheet("color: %s;" % sc("error").name())
        return lbl

    @staticmethod
    def _note(text: str) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet("background: %s; border-radius: 4px; padding: 4px;" % sc("bg_note").name())
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(8, 6, 8, 6)
        lbl = QLabel(text)
        lbl.setStyleSheet("color: %s; font-size: 11px;" % sc("text_secondary").name())
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
            "QPushButton { background: %s; color: white; border-radius: 3px; }"
            "QPushButton:hover { background: %s; }"
            % (sc("error").name(), sc("critical").name())
        )
        confirm_btn.clicked.connect(self.accept)
        lo.addWidget(confirm_btn)

        return lo
