"""
SettingsCopierDialog — 3-step wizard for copying bot settings between accounts.

Step 1: Select source account + choose which settings to copy
Step 2: Select target accounts + preview diff
Step 3: Results summary
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QStackedWidget, QMessageBox,
    QWidget, QSplitter, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from oh.models.account import AccountRecord
from oh.models.settings_copy import (
    COPYABLE_SETTINGS,
    SettingsSnapshot,
    SettingsDiff,
    SettingsDiffEntry,
    SettingsCopyBatchResult,
)
from oh.services.settings_copier_service import SettingsCopierService
from oh.ui.style import sc
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)


class SettingsCopierDialog(QDialog):
    """3-step wizard for copying settings between accounts."""

    def __init__(
        self,
        service: SettingsCopierService,
        accounts: List[AccountRecord],
        pre_selected_source_id: Optional[int] = None,
        pre_selected_target_ids: Optional[List[int]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._accounts = [a for a in accounts if a.is_active]
        self._pre_selected_source_id = pre_selected_source_id
        self._pre_selected_target_ids = pre_selected_target_ids or []

        self._source_snapshot: Optional[SettingsSnapshot] = None
        self._diffs: List[SettingsDiff] = []
        self._worker: Optional[WorkerThread] = None
        self._step1_checkboxes: list = []
        self._target_checkboxes: list = []

        self.setWindowTitle("Copy Settings")
        self.setMinimumSize(700, 550)
        self.setModal(True)

        self._build_ui()

        # Pre-select source if provided
        if pre_selected_source_id is not None:
            self._pre_select_source(pre_selected_source_id)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_lo = QVBoxLayout(self)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(f"font-size: 14px; font-weight: bold; color: {sc('heading').name()};")
        main_lo.addWidget(self._title_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        self._stack.addWidget(self._build_step3())
        main_lo.addWidget(self._stack, 1)

        # Navigation buttons
        nav_lo = QHBoxLayout()
        self._back_btn = QPushButton("<< Back")
        self._back_btn.clicked.connect(self._on_back)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._next_btn = QPushButton("Next >>")
        self._next_btn.clicked.connect(self._on_next)

        nav_lo.addWidget(self._back_btn)
        nav_lo.addStretch()
        nav_lo.addWidget(self._cancel_btn)
        nav_lo.addWidget(self._next_btn)
        main_lo.addLayout(nav_lo)

        self._go_to_step(0)

    def _build_step1(self) -> QWidget:
        """Step 1: Select source account and settings to copy."""
        w = QWidget()
        lo = QVBoxLayout(w)

        # Source account combo
        src_lo = QHBoxLayout()
        src_lo.addWidget(QLabel("Source account:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(300)
        self._source_combo.addItem("— Select account —", None)
        for acc in self._accounts:
            label = f"{acc.username}  ({acc.device_name or acc.device_id[:12]})"
            self._source_combo.addItem(label, acc.id)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        src_lo.addWidget(self._source_combo, 1)
        lo.addLayout(src_lo)

        # Settings table with checkboxes
        lo.addWidget(QLabel("Settings to copy:"))
        self._settings_table = QTableWidget()
        self._settings_table.setColumnCount(3)
        self._settings_table.setHorizontalHeaderLabels(["Copy", "Setting", "Value"])
        self._settings_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._settings_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        self._settings_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._settings_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._settings_table.verticalHeader().setVisible(False)
        lo.addWidget(self._settings_table, 1)

        self._step1_error = QLabel("")
        self._step1_error.setStyleSheet(f"color: {sc('error').name()};")
        lo.addWidget(self._step1_error)

        return w

    def _build_step2(self) -> QWidget:
        """Step 2: Select targets + preview diff."""
        w = QWidget()
        lo = QVBoxLayout(w)

        # Quick-select buttons
        btn_lo = QHBoxLayout()
        btn_lo.addWidget(QLabel("Select target accounts:"))
        btn_lo.addStretch()
        self._sel_all_btn = QPushButton("Select All")
        self._sel_all_btn.clicked.connect(lambda: self._toggle_all_targets(True))
        self._sel_none_btn = QPushButton("Select None")
        self._sel_none_btn.clicked.connect(lambda: self._toggle_all_targets(False))
        self._sel_device_btn = QPushButton("Select Same Device")
        self._sel_device_btn.clicked.connect(self._select_same_device)
        btn_lo.addWidget(self._sel_all_btn)
        btn_lo.addWidget(self._sel_none_btn)
        btn_lo.addWidget(self._sel_device_btn)
        lo.addLayout(btn_lo)

        # Splitter: target list on top, diff preview on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Target account list
        self._target_table = QTableWidget()
        self._target_table.setColumnCount(3)
        self._target_table.setHorizontalHeaderLabels(["Select", "Account", "Changes"])
        self._target_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._target_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._target_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._target_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._target_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._target_table.verticalHeader().setVisible(False)
        self._target_table.currentCellChanged.connect(self._on_target_selected)
        splitter.addWidget(self._target_table)

        # Diff preview
        diff_frame = QFrame()
        diff_lo = QVBoxLayout(diff_frame)
        self._diff_label = QLabel("Preview:")
        diff_lo.addWidget(self._diff_label)
        self._diff_table = QTableWidget()
        self._diff_table.setColumnCount(3)
        self._diff_table.setHorizontalHeaderLabels(["Setting", "Current", "New"])
        self._diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._diff_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._diff_table.verticalHeader().setVisible(False)
        diff_lo.addWidget(self._diff_table)
        splitter.addWidget(diff_frame)

        lo.addWidget(splitter, 1)
        return w

    def _build_step3(self) -> QWidget:
        """Step 3: Results summary."""
        w = QWidget()
        lo = QVBoxLayout(w)

        self._result_summary = QLabel("")
        self._result_summary.setStyleSheet("font-size: 13px;")
        lo.addWidget(self._result_summary)

        self._result_table = QTableWidget()
        self._result_table.setColumnCount(4)
        self._result_table.setHorizontalHeaderLabels(
            ["Account", "Device", "Status", "Keys Changed"]
        )
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._result_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._result_table.verticalHeader().setVisible(False)
        lo.addWidget(self._result_table, 1)

        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_step(self, step: int) -> None:
        self._stack.setCurrentIndex(step)

        if step == 0:
            self._title_label.setText("Copy Settings \u2014 Step 1 of 3")
            self._back_btn.setVisible(False)
            self._next_btn.setText("Next >>")
            self._next_btn.setVisible(True)
            self._cancel_btn.setText("Cancel")
            self._update_step1_next_state()
        elif step == 1:
            self._title_label.setText("Copy Settings \u2014 Step 2 of 3")
            self._back_btn.setVisible(True)
            self._next_btn.setText("Apply")
            self._next_btn.setVisible(True)
            self._cancel_btn.setText("Cancel")
            self._update_apply_state()
        elif step == 2:
            self._title_label.setText("Copy Settings \u2014 Results")
            self._back_btn.setVisible(False)
            self._next_btn.setVisible(False)
            self._cancel_btn.setText("Close")

    def _on_back(self) -> None:
        current = self._stack.currentIndex()
        if current > 0:
            self._go_to_step(current - 1)

    def _on_next(self) -> None:
        current = self._stack.currentIndex()
        if current == 0:
            self._enter_step2()
        elif current == 1:
            self._on_apply()

    # ------------------------------------------------------------------
    # Step 1 logic
    # ------------------------------------------------------------------

    def _pre_select_source(self, account_id: int) -> None:
        for i in range(self._source_combo.count()):
            if self._source_combo.itemData(i) == account_id:
                self._source_combo.setCurrentIndex(i)
                break

    def _on_source_changed(self) -> None:
        account_id = self._source_combo.currentData()
        if account_id is None:
            self._source_snapshot = None
            self._settings_table.setRowCount(0)
            self._step1_error.setText("")
            self._update_step1_next_state()
            return

        snapshot = self._service.read_source_settings(account_id)
        self._source_snapshot = snapshot

        if snapshot.error:
            self._step1_error.setText(f"Error: {snapshot.error}")
            self._settings_table.setRowCount(0)
            self._update_step1_next_state()
            return

        self._step1_error.setText("")
        self._populate_settings_table(snapshot)
        self._update_step1_next_state()

    def _populate_settings_table(self, snapshot: SettingsSnapshot) -> None:
        keys = list(COPYABLE_SETTINGS.keys())
        self._settings_table.setRowCount(len(keys))
        self._step1_checkboxes = []

        for row_idx, key in enumerate(keys):
            # Checkbox
            cb = QCheckBox()
            has_value = key in snapshot.values
            cb.setChecked(has_value)
            cb.setEnabled(has_value)
            cb.stateChanged.connect(lambda _: self._update_step1_next_state())
            self._step1_checkboxes.append((key, cb))

            cb_widget = QWidget()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.addWidget(cb)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            self._settings_table.setCellWidget(row_idx, 0, cb_widget)

            # Setting name
            name_item = QTableWidgetItem(COPYABLE_SETTINGS[key])
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_value:
                name_item.setForeground(sc('muted'))
            self._settings_table.setItem(row_idx, 1, name_item)

            # Value
            val = snapshot.values.get(key, "(not set)")
            val_item = QTableWidgetItem(str(val))
            val_item.setFlags(val_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_value:
                val_item.setForeground(sc('muted'))
            self._settings_table.setItem(row_idx, 2, val_item)

    def _get_selected_keys(self) -> List[str]:
        """Return list of keys that are checked in step 1."""
        return [key for key, cb in self._step1_checkboxes if cb.isChecked()]

    def _update_step1_next_state(self) -> None:
        has_source = (
            self._source_snapshot is not None
            and self._source_snapshot.error is None
        )
        has_keys = len(self._get_selected_keys()) > 0
        self._next_btn.setEnabled(has_source and has_keys)

    # ------------------------------------------------------------------
    # Step 2 logic
    # ------------------------------------------------------------------

    def _enter_step2(self) -> None:
        """Transition from step 1 to step 2: compute diffs."""
        if self._source_snapshot is None:
            return

        selected_keys = self._get_selected_keys()
        source_id = self._source_snapshot.account_id

        # Get target account IDs (all active except source)
        target_ids = [a.id for a in self._accounts if a.id != source_id]

        if not target_ids:
            QMessageBox.information(
                self, "No Targets",
                "No other active accounts found to copy settings to.",
            )
            return

        # Compute diffs
        self._diffs = self._service.preview_diff(
            self._source_snapshot, target_ids, selected_keys,
        )

        self._populate_target_table()
        self._go_to_step(1)

        # Pre-select targets if provided
        if self._pre_selected_target_ids:
            self._apply_pre_selected_targets()

    def _populate_target_table(self) -> None:
        self._target_table.setRowCount(len(self._diffs))
        self._target_checkboxes = []

        for row_idx, diff in enumerate(self._diffs):
            # Checkbox
            cb = QCheckBox()
            has_changes = diff.different_count > 0
            cb.setChecked(has_changes)
            cb.setEnabled(has_changes)
            cb.stateChanged.connect(lambda _: self._update_apply_state())
            self._target_checkboxes.append((diff.target_account_id, cb))

            cb_widget = QWidget()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.addWidget(cb)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            self._target_table.setCellWidget(row_idx, 0, cb_widget)

            # Account name
            dev_label = diff.target_device_name or "?"
            name_item = QTableWidgetItem(f"{diff.target_username} @ {dev_label}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_changes:
                name_item.setForeground(sc('muted'))
            self._target_table.setItem(row_idx, 1, name_item)

            # Changes count
            if has_changes:
                changes_text = f"{diff.different_count} change(s)"
            else:
                changes_text = "0 changes (identical)"
            changes_item = QTableWidgetItem(changes_text)
            changes_item.setFlags(changes_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_changes:
                changes_item.setForeground(sc('muted'))
            self._target_table.setItem(row_idx, 2, changes_item)

    def _apply_pre_selected_targets(self) -> None:
        """Check pre-selected targets from constructor."""
        pre_ids = set(self._pre_selected_target_ids)
        for target_id, cb in self._target_checkboxes:
            if target_id in pre_ids and cb.isEnabled():
                cb.setChecked(True)
        self._update_apply_state()

    def _toggle_all_targets(self, checked: bool) -> None:
        for _, cb in self._target_checkboxes:
            if cb.isEnabled():
                cb.setChecked(checked)
        self._update_apply_state()

    def _select_same_device(self) -> None:
        """Select only targets on the same device as the source."""
        if self._source_snapshot is None:
            return
        source_device = self._source_snapshot.device_id

        for row_idx, (target_id, cb) in enumerate(self._target_checkboxes):
            if not cb.isEnabled():
                continue
            diff = self._diffs[row_idx]
            # Find the account to check device_id
            acc = None
            for a in self._accounts:
                if a.id == target_id:
                    acc = a
                    break
            if acc and acc.device_id == source_device:
                cb.setChecked(True)
            else:
                cb.setChecked(False)
        self._update_apply_state()

    def _on_target_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        """When a target row is clicked, show its diff in the preview table."""
        if row < 0 or row >= len(self._diffs):
            self._diff_table.setRowCount(0)
            self._diff_label.setText("Preview:")
            return

        diff = self._diffs[row]
        dev_label = diff.target_device_name or "?"
        self._diff_label.setText(f"Preview ({diff.target_username} @ {dev_label}):")
        self._populate_diff_table(diff)

    def _populate_diff_table(self, diff: SettingsDiff) -> None:
        self._diff_table.setRowCount(len(diff.entries))

        for row_idx, entry in enumerate(diff.entries):
            # Setting name
            name_item = QTableWidgetItem(entry.display_name)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._diff_table.setItem(row_idx, 0, name_item)

            # Current value
            current_text = str(entry.target_value) if entry.target_value is not None else "(not set)"
            current_item = QTableWidgetItem(current_text)
            current_item.setFlags(current_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._diff_table.setItem(row_idx, 1, current_item)

            # New value
            new_text = str(entry.source_value) if entry.source_value is not None else "(not set)"
            new_item = QTableWidgetItem(new_text)
            new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

            if entry.is_different:
                # Highlight changed values
                bold_font = QFont()
                bold_font.setBold(True)
                new_item.setFont(bold_font)
                new_item.setForeground(sc('warning'))
                name_item.setFont(bold_font)
            else:
                current_item.setForeground(sc('muted'))
                new_item.setForeground(sc('muted'))
                name_item.setForeground(sc('muted'))

            self._diff_table.setItem(row_idx, 2, new_item)

    def _get_checked_target_ids(self) -> List[int]:
        """Return list of target account IDs that are checked."""
        return [tid for tid, cb in self._target_checkboxes if cb.isChecked()]

    def _update_apply_state(self) -> None:
        checked = self._get_checked_target_ids()
        count = len(checked)
        if count > 0:
            self._next_btn.setText(f"Apply to {count} account(s)")
            self._next_btn.setEnabled(True)
        else:
            self._next_btn.setText("Apply")
            self._next_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Apply logic
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Confirm and execute the copy operation."""
        target_ids = self._get_checked_target_ids()
        selected_keys = self._get_selected_keys()

        if not target_ids or not selected_keys:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Copy",
            f"Apply {len(selected_keys)} setting(s) to {len(target_ids)} account(s)?\n\n"
            f"A backup of each settings.db will be created before writing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable controls during execution
        self._next_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

        # Run in background thread
        self._worker = WorkerThread(
            self._service.apply_copy,
            self._source_snapshot,
            target_ids,
            selected_keys,
        )
        self._worker.result.connect(self._on_apply_done)
        self._worker.error.connect(self._on_apply_error)
        self._worker.start()

    def _on_apply_done(self, batch_result: SettingsCopyBatchResult) -> None:
        """Handle successful completion of the apply operation."""
        self._worker = None
        self._cancel_btn.setEnabled(True)
        self._show_results(batch_result)
        self._go_to_step(2)

    def _on_apply_error(self, error_msg: str) -> None:
        """Handle error during apply operation."""
        self._worker = None
        self._next_btn.setEnabled(True)
        self._back_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Error",
            f"Copy operation failed:\n{error_msg}",
        )

    def _show_results(self, batch: SettingsCopyBatchResult) -> None:
        """Populate step 3 with results."""
        summary_parts = [
            f"Copied settings from <b>{batch.source_username}</b>:",
            f"&nbsp;&nbsp;{batch.success_count} / {batch.total_targets} accounts updated successfully",
        ]
        if batch.fail_count > 0:
            summary_parts.append(
                f"&nbsp;&nbsp;<span style='color:{sc('error').name()}'>"
                f"{batch.fail_count} failed</span>"
            )
        self._result_summary.setText("<br>".join(summary_parts))

        self._result_table.setRowCount(len(batch.results))
        for row_idx, result in enumerate(batch.results):
            # Account
            name_item = QTableWidgetItem(result.target_username)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._result_table.setItem(row_idx, 0, name_item)

            # Device
            dev_item = QTableWidgetItem(result.target_device_name or "?")
            dev_item.setFlags(dev_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._result_table.setItem(row_idx, 1, dev_item)

            # Status
            if result.success:
                status_text = "OK"
                status_color = sc('success')
            else:
                status_text = "FAILED"
                status_color = sc('error')
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(status_color)
            self._result_table.setItem(row_idx, 2, status_item)

            # Keys changed / error
            if result.success:
                detail = str(len(result.keys_written))
            else:
                detail = result.error or "Unknown error"
            detail_item = QTableWidgetItem(detail)
            detail_item.setFlags(detail_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not result.success:
                detail_item.setForeground(sc('error'))
            self._result_table.setItem(row_idx, 3, detail_item)
