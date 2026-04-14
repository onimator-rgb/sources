"""
TargetSplitterDialog — 3-step wizard for distributing sources across accounts.

Pages:
  0 — Select Sources: paste/type source names
  1 — Select Target Accounts: table with checkboxes, filters
  2 — Preview + Apply: strategy selector, assignment preview, execute
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QPlainTextEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QWidget, QStackedWidget,
    QComboBox, QLineEdit, QCheckBox, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut

from oh.models.target_splitter import SplitPlan, SplitResult
from oh.services.target_splitter_service import TargetSplitterService
from oh.ui.style import sc, BTN_HEIGHT_MD
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Page indices
# ---------------------------------------------------------------------------

_PAGE_SOURCES  = 0
_PAGE_ACCOUNTS = 1
_PAGE_PREVIEW  = 2

# ---------------------------------------------------------------------------
# Account table column indices
# ---------------------------------------------------------------------------

_ACC_COL_CHECK    = 0
_ACC_COL_USERNAME = 1
_ACC_COL_DEVICE   = 2
_ACC_COL_GROUP    = 3
_ACC_COL_SOURCES  = 4

_ACC_HEADERS = ["", "Username", "Device", "Group", "Active Sources"]

# ---------------------------------------------------------------------------
# Preview table column indices
# ---------------------------------------------------------------------------

_PRV_COL_SOURCE  = 0
_PRV_COL_ACCOUNT = 1
_PRV_COL_DEVICE  = 2
_PRV_COL_STATUS  = 3

_PRV_HEADERS = ["Source", "Account", "Device", "Status"]


class TargetSplitterDialog(QDialog):
    """
    3-step wizard for distributing sources across accounts.

    Pages:
      0 — Select Sources
      1 — Select Target Accounts
      2 — Preview + Apply
    """

    def __init__(
        self,
        parent: Optional[QWidget],
        service: TargetSplitterService,
        bot_root: str,
        pre_selected_sources: Optional[List[str]] = None,
        account_group_repo=None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._bot_root = bot_root
        self._account_group_repo = account_group_repo
        self._checkboxes: List[QCheckBox] = []
        self._account_data: list = []   # [(AccountRecord, source_count)]
        self._group_map: dict = {}      # account_id -> group_name
        self._current_plan: Optional[SplitPlan] = None
        self._worker: Optional[WorkerThread] = None
        self._executed = False

        self.setWindowTitle("Distribute Sources")
        self.setMinimumSize(700, 500)
        self.setModal(True)

        self._build_ui()

        # Pre-fill sources if provided
        if pre_selected_sources:
            self._source_edit.setPlainText("\n".join(pre_selected_sources))

        QShortcut(QKeySequence("Escape"), self, self.close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(0)
        lo.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_sources_page())
        self._stack.addWidget(self._build_accounts_page())
        self._stack.addWidget(self._build_preview_page())
        lo.addWidget(self._stack)

    # ---- Page 0: Select Sources ------------------------------------------

    def _build_sources_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Step 1: Select Sources")
        header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        desc = QLabel(
            "Paste or type source names below, one per line. "
            "Duplicates and empty lines are automatically removed."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()}; padding: 2px 0;"
        )
        lo.addWidget(desc)

        self._source_edit = QPlainTextEdit()
        self._source_edit.setPlaceholderText(
            "source_account_1\nsource_account_2\nsource_account_3\n..."
        )
        self._source_edit.textChanged.connect(self._on_source_text_changed)
        lo.addWidget(self._source_edit, stretch=1)

        self._source_count_label = QLabel("0 valid sources")
        self._source_count_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(self._source_count_label)

        # Navigation
        nav = QHBoxLayout()
        nav.addStretch()
        self._sources_next_btn = QPushButton("Next >")
        self._sources_next_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._sources_next_btn.setEnabled(False)
        self._sources_next_btn.clicked.connect(self._go_to_accounts)
        nav.addWidget(self._sources_next_btn)
        lo.addLayout(nav)

        return page

    # ---- Page 1: Select Target Accounts ----------------------------------

    def _build_accounts_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Step 2: Select Target Accounts")
        header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        # Filter row
        filter_row = QHBoxLayout()
        filter_row.setSpacing(8)

        filter_row.addWidget(QLabel("Device:"))
        self._device_filter = QComboBox()
        self._device_filter.setFixedWidth(160)
        self._device_filter.currentIndexChanged.connect(self._apply_account_filter)
        filter_row.addWidget(self._device_filter)

        filter_row.addWidget(QLabel("Group:"))
        self._group_filter = QComboBox()
        self._group_filter.setFixedWidth(160)
        self._group_filter.currentIndexChanged.connect(self._apply_account_filter)
        filter_row.addWidget(self._group_filter)

        filter_row.addWidget(QLabel("Search:"))
        self._account_search = QLineEdit()
        self._account_search.setPlaceholderText("username...")
        self._account_search.setFixedWidth(150)
        self._account_search.textChanged.connect(self._apply_account_filter)
        filter_row.addWidget(self._account_search)

        filter_row.addStretch()
        lo.addLayout(filter_row)

        # Select All / Deselect All
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        select_all_btn = QPushButton("Select All")
        select_all_btn.setFixedHeight(BTN_HEIGHT_MD)
        select_all_btn.clicked.connect(lambda: self._toggle_all_accounts(True))
        btn_row.addWidget(select_all_btn)

        deselect_all_btn = QPushButton("Deselect All")
        deselect_all_btn.setFixedHeight(BTN_HEIGHT_MD)
        deselect_all_btn.clicked.connect(lambda: self._toggle_all_accounts(False))
        btn_row.addWidget(deselect_all_btn)

        btn_row.addStretch()

        self._accounts_count_label = QLabel("0 accounts selected")
        self._accounts_count_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        btn_row.addWidget(self._accounts_count_label)
        lo.addLayout(btn_row)

        # Account table
        self._account_table = QTableWidget()
        self._account_table.setColumnCount(len(_ACC_HEADERS))
        self._account_table.setHorizontalHeaderLabels(_ACC_HEADERS)
        self._account_table.horizontalHeader().setSectionResizeMode(
            _ACC_COL_USERNAME, QHeaderView.ResizeMode.Stretch
        )
        self._account_table.horizontalHeader().setSectionResizeMode(
            _ACC_COL_CHECK, QHeaderView.ResizeMode.Fixed
        )
        self._account_table.setColumnWidth(_ACC_COL_CHECK, 30)
        self._account_table.setColumnWidth(_ACC_COL_DEVICE, 140)
        self._account_table.setColumnWidth(_ACC_COL_GROUP, 120)
        self._account_table.setColumnWidth(_ACC_COL_SOURCES, 100)
        self._account_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._account_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._account_table.verticalHeader().setVisible(False)
        lo.addWidget(self._account_table, stretch=1)

        # Navigation
        nav = QHBoxLayout()
        back_btn = QPushButton("< Back")
        back_btn.setFixedHeight(BTN_HEIGHT_MD)
        back_btn.clicked.connect(self._go_to_sources)
        nav.addWidget(back_btn)
        nav.addStretch()
        self._accounts_next_btn = QPushButton("Next >")
        self._accounts_next_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._accounts_next_btn.setEnabled(False)
        self._accounts_next_btn.clicked.connect(self._go_to_preview)
        nav.addWidget(self._accounts_next_btn)
        lo.addLayout(nav)

        return page

    # ---- Page 2: Preview + Apply -----------------------------------------

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        header = QLabel("Step 3: Preview & Apply")
        header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        # Strategy selector
        strategy_row = QHBoxLayout()
        strategy_row.setSpacing(8)
        strategy_row.addWidget(QLabel("Strategy:"))
        self._strategy_combo = QComboBox()
        self._strategy_combo.addItem("Even split", "even_split")
        self._strategy_combo.addItem("Fill up (fewest sources first)", "fill_up")
        self._strategy_combo.setFixedWidth(250)
        self._strategy_combo.currentIndexChanged.connect(self._on_strategy_changed)
        strategy_row.addWidget(self._strategy_combo)
        strategy_row.addStretch()
        lo.addLayout(strategy_row)

        # Summary
        self._preview_summary = QLabel("")
        self._preview_summary.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()}; padding: 4px 0;"
        )
        self._preview_summary.setWordWrap(True)
        lo.addWidget(self._preview_summary)

        # Preview table
        self._preview_table = QTableWidget()
        self._preview_table.setColumnCount(len(_PRV_HEADERS))
        self._preview_table.setHorizontalHeaderLabels(_PRV_HEADERS)
        self._preview_table.horizontalHeader().setSectionResizeMode(
            _PRV_COL_SOURCE, QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.horizontalHeader().setSectionResizeMode(
            _PRV_COL_ACCOUNT, QHeaderView.ResizeMode.Stretch
        )
        self._preview_table.setColumnWidth(_PRV_COL_DEVICE, 140)
        self._preview_table.setColumnWidth(_PRV_COL_STATUS, 120)
        self._preview_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self._preview_table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self._preview_table.verticalHeader().setVisible(False)
        lo.addWidget(self._preview_table, stretch=1)

        # Navigation
        nav = QHBoxLayout()
        self._preview_back_btn = QPushButton("< Back")
        self._preview_back_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._preview_back_btn.clicked.connect(self._go_to_accounts_from_preview)
        nav.addWidget(self._preview_back_btn)
        nav.addStretch()

        self._apply_btn = QPushButton("Apply")
        self._apply_btn.setFixedHeight(BTN_HEIGHT_MD)
        _hover_bg = sc('success')
        self._apply_btn.setStyleSheet(
            f"QPushButton:enabled {{ color: {sc('success').name()}; font-weight: bold; }}"
            f"QPushButton:enabled:hover {{ background: rgba({_hover_bg.red()},{_hover_bg.green()},{_hover_bg.blue()},30); }}"
        )
        self._apply_btn.clicked.connect(self._on_apply)
        nav.addWidget(self._apply_btn)

        self._close_btn = QPushButton("Close")
        self._close_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._close_btn.setVisible(False)
        self._close_btn.clicked.connect(self.accept)
        nav.addWidget(self._close_btn)

        lo.addLayout(nav)

        return page

    # ------------------------------------------------------------------
    # Page navigation
    # ------------------------------------------------------------------

    def _go_to_sources(self) -> None:
        self._stack.setCurrentIndex(_PAGE_SOURCES)

    def _go_to_accounts(self) -> None:
        self._load_accounts()
        self._stack.setCurrentIndex(_PAGE_ACCOUNTS)

    def _go_to_preview(self) -> None:
        self._recompute_plan()
        self._stack.setCurrentIndex(_PAGE_PREVIEW)

    def _go_to_accounts_from_preview(self) -> None:
        self._stack.setCurrentIndex(_PAGE_ACCOUNTS)

    # ------------------------------------------------------------------
    # Page 0 logic — source text
    # ------------------------------------------------------------------

    def _get_clean_sources(self) -> List[str]:
        """Parse, deduplicate, and strip the source text area."""
        text = self._source_edit.toPlainText()
        seen: set = set()
        result: List[str] = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped and stripped.lower() not in seen:
                result.append(stripped)
                seen.add(stripped.lower())
        return result

    def _on_source_text_changed(self) -> None:
        sources = self._get_clean_sources()
        count = len(sources)
        self._source_count_label.setText(
            f"{count} valid source{'s' if count != 1 else ''}"
        )
        self._sources_next_btn.setEnabled(count > 0)

    # ------------------------------------------------------------------
    # Page 1 logic — account selection
    # ------------------------------------------------------------------

    def _load_accounts(self) -> None:
        """Load accounts with source counts and populate the table."""
        self._account_data = self._service.get_accounts_with_source_counts()

        # Build group map if repo is available
        self._group_map = {}
        if self._account_group_repo is not None:
            try:
                for acc, _ in self._account_data:
                    groups = self._account_group_repo.get_groups_for_account(acc.id)
                    if groups:
                        self._group_map[acc.id] = ", ".join(
                            g.name for g in groups
                        )
            except Exception as e:
                logger.warning("Could not load account groups: %s", e)

        # Populate filter combos
        devices = sorted({
            acc.device_name or acc.device_id
            for acc, _ in self._account_data
        })
        groups = sorted({v for v in self._group_map.values()})

        self._device_filter.blockSignals(True)
        self._device_filter.clear()
        self._device_filter.addItem("All devices", "")
        for d in devices:
            self._device_filter.addItem(d, d)
        self._device_filter.blockSignals(False)

        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem("All groups", "")
        for g in groups:
            self._group_filter.addItem(g, g)
        self._group_filter.blockSignals(False)

        self._populate_account_table()

    def _populate_account_table(self) -> None:
        """Fill the account table with all accounts (filter applied separately)."""
        self._account_table.setRowCount(0)
        self._checkboxes.clear()

        for acc, src_count in self._account_data:
            r = self._account_table.rowCount()
            self._account_table.insertRow(r)

            cb = QCheckBox()
            cb.stateChanged.connect(self._on_account_check_changed)
            self._checkboxes.append(cb)

            cb_widget = QWidget()
            cb_layout = QHBoxLayout(cb_widget)
            cb_layout.addWidget(cb)
            cb_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_layout.setContentsMargins(0, 0, 0, 0)
            self._account_table.setCellWidget(r, _ACC_COL_CHECK, cb_widget)

            username_item = QTableWidgetItem(acc.username)
            username_item.setData(Qt.ItemDataRole.UserRole, acc.id)
            self._account_table.setItem(r, _ACC_COL_USERNAME, username_item)

            device_name = acc.device_name or acc.device_id
            self._account_table.setItem(
                r, _ACC_COL_DEVICE, QTableWidgetItem(device_name)
            )

            group_name = self._group_map.get(acc.id, "")
            self._account_table.setItem(
                r, _ACC_COL_GROUP, QTableWidgetItem(group_name)
            )

            count_item = QTableWidgetItem(str(src_count))
            count_item.setTextAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )
            self._account_table.setItem(r, _ACC_COL_SOURCES, count_item)

        self._apply_account_filter()

    def _apply_account_filter(self) -> None:
        """Show/hide rows based on device, group, and search filters."""
        device_val = self._device_filter.currentData() or ""
        group_val = self._group_filter.currentData() or ""
        search_val = self._account_search.text().strip().lower()

        for r in range(self._account_table.rowCount()):
            username_item = self._account_table.item(r, _ACC_COL_USERNAME)
            device_item = self._account_table.item(r, _ACC_COL_DEVICE)
            group_item = self._account_table.item(r, _ACC_COL_GROUP)
            if not username_item:
                continue

            show = True
            if device_val and device_item and device_item.text() != device_val:
                show = False
            if group_val and group_item and group_val not in group_item.text():
                show = False
            if search_val and search_val not in username_item.text().lower():
                show = False

            self._account_table.setRowHidden(r, not show)

        self._update_account_count()

    def _toggle_all_accounts(self, checked: bool) -> None:
        """Select or deselect all visible accounts."""
        for r in range(self._account_table.rowCount()):
            if not self._account_table.isRowHidden(r):
                if r < len(self._checkboxes):
                    self._checkboxes[r].setChecked(checked)
        self._update_account_count()

    def _on_account_check_changed(self) -> None:
        self._update_account_count()

    def _update_account_count(self) -> None:
        count = self._get_selected_account_count()
        self._accounts_count_label.setText(
            f"{count} account{'s' if count != 1 else ''} selected"
        )
        self._accounts_next_btn.setEnabled(count > 0)

    def _get_selected_account_ids(self) -> List[int]:
        """Return account IDs for all checked rows."""
        ids: List[int] = []
        for r in range(self._account_table.rowCount()):
            if r < len(self._checkboxes) and self._checkboxes[r].isChecked():
                item = self._account_table.item(r, _ACC_COL_USERNAME)
                if item:
                    aid = item.data(Qt.ItemDataRole.UserRole)
                    if aid is not None:
                        ids.append(aid)
        return ids

    def _get_selected_account_count(self) -> int:
        return len(self._get_selected_account_ids())

    # ------------------------------------------------------------------
    # Page 2 logic — preview + apply
    # ------------------------------------------------------------------

    def _on_strategy_changed(self) -> None:
        if self._stack.currentIndex() == _PAGE_PREVIEW and not self._executed:
            self._recompute_plan()

    def _recompute_plan(self) -> None:
        """Compute the distribution plan and populate the preview table."""
        sources = self._get_clean_sources()
        account_ids = self._get_selected_account_ids()
        strategy = self._strategy_combo.currentData()

        self._current_plan = self._service.compute_plan(
            sources, account_ids, strategy
        )
        self._populate_preview_table()
        self._update_preview_summary()

    def _populate_preview_table(self) -> None:
        plan = self._current_plan
        self._preview_table.setRowCount(0)

        if plan is None:
            return

        for assignment in plan.assignments:
            r = self._preview_table.rowCount()
            self._preview_table.insertRow(r)

            self._preview_table.setItem(
                r, _PRV_COL_SOURCE, QTableWidgetItem(assignment.source_name)
            )
            self._preview_table.setItem(
                r, _PRV_COL_ACCOUNT, QTableWidgetItem(assignment.username)
            )
            self._preview_table.setItem(
                r, _PRV_COL_DEVICE, QTableWidgetItem(assignment.device_name)
            )

            if assignment.skipped:
                status_item = QTableWidgetItem("Already present")
                status_item.setForeground(sc("muted"))
            else:
                status_item = QTableWidgetItem("Will add")
                status_item.setForeground(sc("success"))
            self._preview_table.setItem(r, _PRV_COL_STATUS, status_item)

    def _update_preview_summary(self) -> None:
        plan = self._current_plan
        if plan is None:
            self._preview_summary.setText("")
            self._apply_btn.setEnabled(False)
            return

        effective = plan.effective_count
        total = len(plan.assignments)
        accounts = len(plan.target_account_ids)
        skipped = plan.skipped_count

        if accounts > 0 and effective > 0:
            avg = effective / accounts
            text = (
                f"{len(plan.sources)} sources -> {accounts} accounts  |  "
                f"{effective} will be added, {skipped} already present  |  "
                f"~{avg:.1f} sources per account"
            )
        elif accounts > 0:
            text = (
                f"{len(plan.sources)} sources -> {accounts} accounts  |  "
                f"All {total} assignments already present — nothing to apply"
            )
        else:
            text = "No assignments"

        self._preview_summary.setText(text)

        # Enable/disable apply
        if effective > 0 and not self._executed:
            self._apply_btn.setEnabled(True)
            self._apply_btn.setText(f"Apply ({effective} additions)")
        elif not self._executed:
            self._apply_btn.setEnabled(False)
            self._apply_btn.setText("Nothing to apply")

        # Warn about accounts getting 0 new sources
        accounts_with_adds = {
            a.account_id for a in plan.assignments if not a.skipped
        }
        accounts_with_none = set(plan.target_account_ids) - accounts_with_adds
        if accounts_with_none and effective > 0:
            self._preview_summary.setText(
                self._preview_summary.text()
                + f"\nNote: {len(accounts_with_none)} account(s) will receive 0 new sources"
            )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        if self._current_plan is None or self._executed:
            return

        effective = self._current_plan.effective_count
        if effective == 0:
            return

        reply = QMessageBox.question(
            self,
            "Confirm Distribution",
            f"Add {effective} source(s) to {len(self._current_plan.target_account_ids)} account(s)?\n\n"
            f"Strategy: {self._strategy_combo.currentText()}\n"
            f"This will write to sources.txt files on disk.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._apply_btn.setEnabled(False)
        self._apply_btn.setText("Applying...")
        self._preview_back_btn.setEnabled(False)
        self._strategy_combo.setEnabled(False)

        plan = self._current_plan
        bot_root = self._bot_root
        svc = self._service

        def do_execute():
            return svc.execute_plan(plan, bot_root)

        self._worker = WorkerThread(do_execute)
        self._worker.result.connect(self._on_execute_done)
        self._worker.error.connect(self._on_execute_error)
        self._worker.start()

    def _on_execute_done(self, result: SplitResult) -> None:
        self._executed = True
        self._worker = None

        # Update summary to show results
        self._preview_summary.setText(
            f"Distribution complete: {result.summary_line()}"
        )
        if result.errors:
            error_text = "\n".join(result.errors[:10])
            if len(result.errors) > 10:
                error_text += f"\n... and {len(result.errors) - 10} more"
            self._preview_summary.setText(
                self._preview_summary.text() + f"\n\nErrors:\n{error_text}"
            )

        # Switch buttons: hide Apply, show Close
        self._apply_btn.setVisible(False)
        self._close_btn.setVisible(True)
        self._preview_back_btn.setEnabled(False)

    def _on_execute_error(self, error: str) -> None:
        self._worker = None
        logger.error("Target splitter execution error: %s", error)
        self._preview_summary.setText(f"Execution failed: {error}")
        self._apply_btn.setEnabled(True)
        self._apply_btn.setText("Retry")
        self._preview_back_btn.setEnabled(True)
        self._strategy_combo.setEnabled(True)

    # ------------------------------------------------------------------
    # Close handling
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            event.ignore()
            return
        super().closeEvent(event)
