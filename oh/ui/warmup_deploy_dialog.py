"""
WarmupDeployDialog — 2-step wizard for deploying warmup templates to accounts.

Step 1: Select template + target accounts
Step 2: Results summary
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QStackedWidget, QMessageBox,
    QWidget, QFrame, QLineEdit,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from oh.models.account import AccountRecord
from oh.models.warmup_template import (
    WarmupTemplate,
    WarmupDeployBatchResult,
)
from oh.services.warmup_template_service import WarmupTemplateService
from oh.ui.style import sc
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)


class WarmupDeployDialog(QDialog):
    """2-step wizard for deploying warmup templates to accounts."""

    def __init__(
        self,
        service: WarmupTemplateService,
        accounts: List[AccountRecord],
        pre_selected_account_ids: Optional[List[int]] = None,
        pre_selected_template_name: Optional[str] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._accounts = [a for a in accounts if a.is_active]
        self._pre_selected_ids = set(pre_selected_account_ids or [])
        self._pre_selected_template_name = pre_selected_template_name

        self._templates: List[WarmupTemplate] = []
        self._target_checkboxes: List[QCheckBox] = []
        self._worker: Optional[WorkerThread] = None

        self.setWindowTitle("Apply Warmup Template")
        self.setMinimumSize(750, 550)
        self.setModal(True)

        self._build_ui()
        self._load_templates()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_lo = QVBoxLayout(self)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {sc('heading').name()};"
        )
        main_lo.addWidget(self._title_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        main_lo.addWidget(self._stack, 1)

        # Navigation buttons
        nav_lo = QHBoxLayout()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._apply_btn = QPushButton("Apply")
        self._apply_btn.clicked.connect(self._on_apply)

        nav_lo.addStretch()
        nav_lo.addWidget(self._cancel_btn)
        nav_lo.addWidget(self._apply_btn)
        main_lo.addLayout(nav_lo)

        self._go_to_step(0)

    def _build_step1(self) -> QWidget:
        """Step 1: Select template + target accounts."""
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 8, 0, 0)

        # Template selection
        tpl_lo = QHBoxLayout()
        tpl_lo.addWidget(QLabel("Template:"))
        self._template_combo = QComboBox()
        self._template_combo.setMinimumWidth(200)
        self._template_combo.currentIndexChanged.connect(self._on_template_changed)
        tpl_lo.addWidget(self._template_combo, 1)
        lo.addLayout(tpl_lo)

        # Template preview
        self._preview_label = QLabel()
        self._preview_label.setWordWrap(True)
        self._preview_label.setStyleSheet(
            f"padding: 8px; background: {sc('bg_note').name()}; "
            f"border-radius: 4px; color: {sc('text_secondary').name()}; font-size: 12px;"
        )
        lo.addWidget(self._preview_label)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        lo.addWidget(sep)

        # Quick-select buttons
        sel_lo = QHBoxLayout()
        sel_lo.addWidget(QLabel("Target accounts:"))
        sel_lo.addStretch()

        sel_all_btn = QPushButton("Select All")
        sel_all_btn.setFixedHeight(24)
        sel_all_btn.clicked.connect(self._select_all)
        sel_lo.addWidget(sel_all_btn)

        sel_none_btn = QPushButton("Select None")
        sel_none_btn.setFixedHeight(24)
        sel_none_btn.clicked.connect(self._select_none)
        sel_lo.addWidget(sel_none_btn)

        lo.addLayout(sel_lo)

        # Filters row: device + search
        filter_lo = QHBoxLayout()
        filter_lo.addWidget(QLabel("Device:"))
        self._device_filter = QComboBox()
        self._device_filter.setFixedWidth(160)
        self._device_filter.addItem("All devices")
        devices = sorted(set(a.device_name or a.device_id[:12] for a in self._accounts))
        for d in devices:
            self._device_filter.addItem(d)
        self._device_filter.currentIndexChanged.connect(self._apply_filters)
        filter_lo.addWidget(self._device_filter)

        filter_lo.addSpacing(12)
        filter_lo.addWidget(QLabel("Search:"))
        self._search_input = QLineEdit()
        self._search_input.setPlaceholderText("username...")
        self._search_input.setFixedHeight(24)
        self._search_input.textChanged.connect(self._apply_filters)
        filter_lo.addWidget(self._search_input, 1)
        lo.addLayout(filter_lo)

        # Account table
        self._acct_table = QTableWidget(0, 4)
        self._acct_table.setHorizontalHeaderLabels(
            ["", "Username", "Device", "Current Follow/Like"]
        )
        self._acct_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._acct_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._acct_table.setSortingEnabled(True)
        self._acct_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._acct_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._acct_table.verticalHeader().setVisible(False)
        lo.addWidget(self._acct_table, 1)

        self._step1_status = QLabel("")
        self._step1_status.setStyleSheet(f"color: {sc('text_secondary').name()}; font-size: 11px;")
        lo.addWidget(self._step1_status)

        return w

    def _build_step2(self) -> QWidget:
        """Step 2: Results summary."""
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 8, 0, 0)

        self._result_summary = QLabel()
        self._result_summary.setWordWrap(True)
        self._result_summary.setStyleSheet("font-size: 13px;")
        lo.addWidget(self._result_summary)

        self._result_table = QTableWidget(0, 4)
        self._result_table.setHorizontalHeaderLabels(
            ["Username", "Device", "Status", "Keys Changed"]
        )
        self._result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._result_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._result_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._result_table.verticalHeader().setVisible(False)
        lo.addWidget(self._result_table, 1)

        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_step(self, step: int) -> None:
        self._stack.setCurrentIndex(step)
        if step == 0:
            self._title_label.setText("Step 1: Select Template & Accounts")
            self._apply_btn.setText("Apply")
            self._apply_btn.setEnabled(True)
            self._cancel_btn.setText("Cancel")
            self._cancel_btn.setEnabled(True)
        else:
            self._title_label.setText("Step 2: Results")
            self._apply_btn.setText("Close")
            self._apply_btn.setEnabled(True)
            self._cancel_btn.setEnabled(False)
            try:
                self._apply_btn.clicked.disconnect()
            except RuntimeError:
                pass
            self._apply_btn.clicked.connect(self.accept)

    # ------------------------------------------------------------------
    # Template loading
    # ------------------------------------------------------------------

    def _load_templates(self) -> None:
        """Load templates into the combo box and populate the account table."""
        self._templates = self._service.get_all_templates()
        self._template_combo.clear()
        for t in self._templates:
            self._template_combo.addItem(t.name, t.id)

        # Pre-select template if requested
        if self._pre_selected_template_name:
            for i, t in enumerate(self._templates):
                if t.name == self._pre_selected_template_name:
                    self._template_combo.setCurrentIndex(i)
                    break

        self._populate_account_table()

    def _on_template_changed(self, index: int) -> None:
        """Update preview when template selection changes."""
        if index < 0 or index >= len(self._templates):
            self._preview_label.setText("")
            return
        t = self._templates[index]
        lines = t.to_preview_lines()
        if t.description:
            lines.insert(0, t.description)
        self._preview_label.setText("\n".join(lines))

    # ------------------------------------------------------------------
    # Account table
    # ------------------------------------------------------------------

    def _populate_account_table(self) -> None:
        """Fill the account selection table."""
        self._target_checkboxes.clear()
        self._acct_table.setSortingEnabled(False)  # disable during population
        self._acct_table.setRowCount(len(self._accounts))

        for i, acc in enumerate(self._accounts):
            # Checkbox — store account_id on the checkbox for reliable lookup
            cb = QCheckBox()
            cb.setProperty("account_id", acc.id)
            if acc.id in self._pre_selected_ids:
                cb.setChecked(True)
            self._target_checkboxes.append(cb)

            cb_widget = QWidget()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.setContentsMargins(4, 0, 4, 0)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.addWidget(cb)
            self._acct_table.setCellWidget(i, 0, cb_widget)

            # Username — store account_id in UserRole for sorting safety
            uname_item = QTableWidgetItem(acc.username)
            uname_item.setData(Qt.ItemDataRole.UserRole, acc.id)
            self._acct_table.setItem(i, 1, uname_item)

            # Device
            dev_name = acc.device_name or acc.device_id[:12]
            self._acct_table.setItem(i, 2, QTableWidgetItem(dev_name))

            # Current follow/like limits
            fl = acc.follow_limit_perday or "?"
            ll = acc.like_limit_perday or "?"
            self._acct_table.setItem(i, 3, QTableWidgetItem(f"F:{fl}  L:{ll}"))

        self._acct_table.setSortingEnabled(True)  # re-enable after population
        self._update_status()

    def _select_all(self) -> None:
        for cb in self._target_checkboxes:
            cb.setChecked(True)
        self._update_status()

    def _select_none(self) -> None:
        for cb in self._target_checkboxes:
            cb.setChecked(False)
        self._update_status()

    def _apply_filters(self) -> None:
        """Filter account table rows by device and search text."""
        dev_idx = self._device_filter.currentIndex()
        device = self._device_filter.currentText() if dev_idx > 0 else None
        search = self._search_input.text().strip().lower()

        for i, acc in enumerate(self._accounts):
            dev_name = acc.device_name or acc.device_id[:12]
            device_match = device is None or dev_name == device
            search_match = not search or search in acc.username.lower()
            self._acct_table.setRowHidden(i, not (device_match and search_match))

    def _update_status(self) -> None:
        count = sum(1 for cb in self._target_checkboxes if cb.isChecked())
        self._step1_status.setText(f"{count} account(s) selected")

    def _get_selected_account_ids(self) -> List[int]:
        """Return list of account IDs for checked rows (sort-safe via stored property)."""
        ids: List[int] = []
        for cb in self._target_checkboxes:
            if cb.isChecked():
                aid = cb.property("account_id")
                if aid is not None:
                    ids.append(aid)
        return ids

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Validate selection, confirm, then deploy."""
        # Get selected template
        tpl_idx = self._template_combo.currentIndex()
        if tpl_idx < 0 or tpl_idx >= len(self._templates):
            QMessageBox.warning(self, "No Template", "Select a warmup template first.")
            return

        template = self._templates[tpl_idx]
        account_ids = self._get_selected_account_ids()
        logger.info(
            "Warmup deploy: template=%s, selected_accounts=%d, ids=%s",
            template.name, len(account_ids), account_ids,
        )

        if not account_ids:
            QMessageBox.warning(self, "No Accounts", "Select at least one account.")
            return

        # Confirmation dialog
        preview_lines = template.to_preview_lines()
        confirm_msg = (
            f"Apply warmup template \"{template.name}\" to {len(account_ids)} account(s)?\n\n"
            f"Settings to apply:\n"
            f"  " + "\n  ".join(preview_lines) + "\n\n"
            f"A backup of each settings.db will be created before writing."
        )

        reply = QMessageBox.question(
            self,
            "Confirm Warmup Deploy",
            confirm_msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable UI during apply
        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Applying...")
        self._cancel_btn.setEnabled(False)

        # Run in background thread
        self._worker = WorkerThread(
            self._service.apply_deploy,
            template,
            account_ids,
        )
        self._worker.result.connect(self._on_apply_complete)
        self._worker.error.connect(self._on_apply_error)
        self._worker.start()

    def _on_apply_complete(self, result: WarmupDeployBatchResult) -> None:
        """Handle deploy completion — show results."""
        self._worker = None
        self._show_results(result)
        self._go_to_step(1)

    def _on_apply_error(self, error_msg: str) -> None:
        """Handle deploy error."""
        self._worker = None
        self._apply_btn.setEnabled(True)
        self._apply_btn.setText("Apply")
        self._cancel_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Deploy Failed",
            f"Warmup deploy failed:\n\n{error_msg}",
        )

    # ------------------------------------------------------------------
    # Results
    # ------------------------------------------------------------------

    def _show_results(self, result: WarmupDeployBatchResult) -> None:
        """Populate the results step."""
        success_color = sc("success").name()
        error_color = sc("error").name()

        summary = (
            f"Applied <b>{result.template_name}</b> to "
            f"<span style='color:{success_color}'>{result.success_count}</span>/"
            f"{result.total_targets} accounts"
        )
        if result.fail_count > 0:
            summary += (
                f"  |  <span style='color:{error_color}'>"
                f"{result.fail_count} failed</span>"
            )
        self._result_summary.setText(summary)

        self._result_table.setRowCount(len(result.results))
        for i, r in enumerate(result.results):
            self._result_table.setItem(i, 0, QTableWidgetItem(r.username))
            self._result_table.setItem(i, 1, QTableWidgetItem(r.device_name or ""))

            if r.success:
                status_item = QTableWidgetItem("OK")
                status_item.setForeground(sc("success"))
            else:
                status_item = QTableWidgetItem(r.error or "Failed")
                status_item.setForeground(sc("error"))
            self._result_table.setItem(i, 2, status_item)

            keys_str = str(len(r.keys_written)) if r.success else "0"
            self._result_table.setItem(i, 3, QTableWidgetItem(keys_str))
