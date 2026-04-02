"""
BulkDiscoveryDialog — 3-step wizard for bulk source discovery.

Pages:
  1. Preview  — qualifying accounts table with checkboxes
  2. Progress — live progress per account
  3. Results  — summary with drill-down + revert
"""
import json
import logging
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QWidget, QStackedWidget,
    QMessageBox, QCheckBox, QSpinBox, QSplitter,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QColor, QKeySequence, QShortcut

from oh.models.bulk_discovery import (
    BulkDiscoveryRun, BulkDiscoveryItem,
    ITEM_DONE, ITEM_FAILED, ITEM_SKIPPED,
)
from oh.ui.style import sc, BTN_HEIGHT_MD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table column indices — Preview
# ---------------------------------------------------------------------------

_PRV_COL_CHECK    = 0
_PRV_COL_USERNAME = 1
_PRV_COL_DEVICE   = 2
_PRV_COL_SOURCES  = 3
_PRV_COL_DEFICIT  = 4

_PRV_HEADERS = ["", "Username", "Device", "Sources", "Deficit"]

# ---------------------------------------------------------------------------
# Table column indices — Progress
# ---------------------------------------------------------------------------

_PGR_COL_USERNAME = 0
_PGR_COL_STATUS   = 1
_PGR_COL_FOUND    = 2
_PGR_COL_ADDED    = 3

_PGR_HEADERS = ["Username", "Status", "Found", "Added"]

# ---------------------------------------------------------------------------
# Table column indices — Results
# ---------------------------------------------------------------------------

_RES_COL_ACCOUNT = 0
_RES_COL_DEVICE  = 1
_RES_COL_BEFORE  = 2
_RES_COL_ADDED   = 3
_RES_COL_AFTER   = 4
_RES_COL_STATUS  = 5

_RES_HEADERS = ["Account", "Device", "Before", "Added", "After", "Status"]

# ---------------------------------------------------------------------------
# Detail table columns (bottom pane on Results page)
# ---------------------------------------------------------------------------

_DET_COL_SOURCE    = 0
_DET_COL_FOLLOWERS = 1
_DET_COL_ER        = 2
_DET_COL_SCORE     = 3

_DET_HEADERS = ["Source Added", "Followers", "ER%", "AI Score"]

# ---------------------------------------------------------------------------
# Status text helpers
# ---------------------------------------------------------------------------

_STATUS_TEXT = {
    "queued":  "...",
    "running": "...",
    "done":    "OK",
    "failed":  "ERR",
    "skipped": "SKIP",
}


def _status_color(status: str) -> QColor:
    if status == ITEM_DONE:
        return sc("success")
    if status == ITEM_FAILED:
        return sc("error")
    if status == "running":
        return sc("link")
    return sc("muted")


# ---------------------------------------------------------------------------
# Sortable numeric item
# ---------------------------------------------------------------------------

class _NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by numeric value."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text().replace(",", "")) < float(other.text().replace(",", ""))
        except ValueError:
            return self.text() < other.text()


# ---------------------------------------------------------------------------
# Worker thread
# ---------------------------------------------------------------------------

class BulkDiscoveryWorker(QThread):
    """Runs bulk source discovery on a background thread."""

    account_started = Signal(int, str)
    account_done = Signal(int, str, int, int)
    account_error = Signal(int, str, str)
    step_progress = Signal(int, str)
    rate_limit_pause = Signal(int)
    finished_signal = Signal(object)

    def __init__(
        self,
        service,
        account_ids: List[int],
        min_threshold: int,
        auto_add_top_n: int,
        bot_root: str,
    ) -> None:
        super().__init__()
        self._service = service
        self._account_ids = account_ids
        self._min_threshold = min_threshold
        self._auto_add_top_n = auto_add_top_n
        self._bot_root = bot_root
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def cancel(self) -> None:
        self._cancelled = True

    def run(self) -> None:
        try:
            result = self._service.run_bulk_discovery(
                account_ids=self._account_ids,
                min_threshold=self._min_threshold,
                auto_add_top_n=self._auto_add_top_n,
                bot_root=self._bot_root,
                progress_callback=self._on_progress,
                cancel_check=lambda: self._cancelled,
            )
            if not self._cancelled:
                self.finished_signal.emit(result)
        except Exception as e:
            if not self._cancelled:
                logger.exception("BulkDiscoveryWorker error: %s", e)
                self.account_error.emit(-1, "", str(e))

    def _on_progress(
        self,
        account_index: int,
        username: str,
        status: str,
        step_pct: int,
        step_msg: str,
    ) -> None:
        if self._cancelled:
            return
        if status == ITEM_RUNNING and step_pct == 0 and "Starting" in step_msg:
            self.account_started.emit(account_index, username)
        elif status == ITEM_DONE:
            # Parse added count from message like "Done — added 5 sources"
            added = 0
            try:
                for part in step_msg.split():
                    if part.isdigit():
                        added = int(part)
                        break
            except (ValueError, AttributeError):
                pass
            self.account_done.emit(account_index, username, step_pct, added)
        elif status == ITEM_FAILED:
            self.account_error.emit(account_index, username, step_msg)
        elif status == ITEM_RUNNING:
            # Regular step progress during search pipeline
            self.step_progress.emit(step_pct, step_msg)
            if "rate limit" in step_msg.lower():
                try:
                    secs = int(step_msg.split()[-1].rstrip("s."))
                except (ValueError, IndexError):
                    secs = 60
                self.rate_limit_pause.emit(secs)


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class BulkDiscoveryDialog(QDialog):
    """
    3-step wizard for bulk source discovery.

    Pages:
      0 — Preview: qualifying accounts with checkboxes
      1 — Progress: live progress per account
      2 — Results: summary with drill-down and revert
    """

    _PAGE_PREVIEW  = 0
    _PAGE_PROGRESS = 1
    _PAGE_RESULTS  = 2

    def __init__(
        self,
        parent,
        service,
        qualifying_accounts: list,
        settings_repo,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._qualifying_accounts = qualifying_accounts  # List[Tuple[AccountRecord, int]]
        self._settings_repo = settings_repo
        self._checkboxes: List[QCheckBox] = []
        self._worker: Optional[BulkDiscoveryWorker] = None
        self._revert_worker = None
        self._run_result: Optional[BulkDiscoveryRun] = None
        self._error_count = 0
        self._rate_limit_count = 0

        self.setWindowTitle("Bulk Source Discovery")
        self.setMinimumSize(900, 650)
        self.setModal(True)

        self._build_ui()
        QShortcut(QKeySequence("Escape"), self, self.close)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(0)
        lo.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_preview_page())
        self._stack.addWidget(self._build_progress_page())
        self._stack.addWidget(self._build_results_page())
        lo.addWidget(self._stack)

    # ---- Page 0: Preview ------------------------------------------------

    def _build_preview_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        # Header
        header = QLabel("Bulk Source Discovery")
        header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        # Settings row
        settings_row = QHBoxLayout()
        settings_row.setSpacing(12)

        settings_row.addWidget(QLabel("Min sources threshold:"))
        self._threshold_spin = QSpinBox()
        self._threshold_spin.setRange(1, 50)
        self._threshold_spin.setValue(self._load_setting("min_source_for_bulk_discovery", 10))
        self._threshold_spin.setFixedWidth(60)
        self._threshold_spin.valueChanged.connect(self._on_threshold_changed)
        settings_row.addWidget(self._threshold_spin)

        settings_row.addSpacing(20)

        settings_row.addWidget(QLabel("Auto-add top N:"))
        self._topn_spin = QSpinBox()
        self._topn_spin.setRange(1, 10)
        self._topn_spin.setValue(self._load_setting("bulk_auto_add_top_n", 5))
        self._topn_spin.setFixedWidth(60)
        settings_row.addWidget(self._topn_spin)

        settings_row.addStretch()
        lo.addLayout(settings_row)

        # Summary
        self._preview_summary = QLabel()
        self._preview_summary.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()}; padding: 2px 0;"
        )
        lo.addWidget(self._preview_summary)

        # Select All / Deselect All
        select_row = QHBoxLayout()
        select_row.setContentsMargins(0, 0, 0, 0)
        select_row.setSpacing(6)
        sel_all = QPushButton("Select All")
        sel_all.setMaximumWidth(100)
        sel_all.setToolTip("Select all accounts for discovery")
        sel_all.clicked.connect(self._on_select_all)
        select_row.addWidget(sel_all)
        desel_all = QPushButton("Deselect All")
        desel_all.setMaximumWidth(100)
        desel_all.setToolTip("Deselect all accounts")
        desel_all.clicked.connect(self._on_deselect_all)
        select_row.addWidget(desel_all)
        select_row.addStretch()
        lo.addLayout(select_row)

        # Table
        self._preview_table = self._make_preview_table()
        lo.addWidget(self._preview_table, stretch=1)

        self._populate_preview()

        # Footer
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        footer.addWidget(cancel_btn)
        footer.addStretch()
        self._start_btn = QPushButton("Start Discovery")
        self._start_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._start_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; padding: 5px 14px; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
            f"QPushButton:disabled {{ background: {sc('muted').name()}; "
            f"color: {sc('text_secondary').name()}; }}"
        )
        self._start_btn.clicked.connect(self._on_start)
        footer.addWidget(self._start_btn)
        lo.addLayout(footer)

        return page

    def _make_preview_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_PRV_HEADERS))
        t.setHorizontalHeaderLabels(_PRV_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_PRV_COL_CHECK, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_PRV_COL_USERNAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_PRV_COL_DEVICE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_PRV_COL_SOURCES, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_PRV_COL_DEFICIT, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_PRV_COL_CHECK, 35)
        t.setColumnWidth(_PRV_COL_DEVICE, 160)
        t.setColumnWidth(_PRV_COL_SOURCES, 80)
        t.setColumnWidth(_PRV_COL_DEFICIT, 80)

        return t

    def _populate_preview(self) -> None:
        threshold = self._threshold_spin.value()
        self._preview_table.setSortingEnabled(False)
        self._preview_table.setRowCount(0)
        self._checkboxes.clear()

        center = Qt.AlignmentFlag.AlignCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        visible_count = 0
        for account, src_count in self._qualifying_accounts:
            deficit = threshold - src_count
            row = self._preview_table.rowCount()
            self._preview_table.insertRow(row)

            # Checkbox
            cb = QCheckBox()
            cb.setChecked(deficit > 0)
            cb.stateChanged.connect(self._update_start_btn)
            self._checkboxes.append(cb)
            cb_widget = QFrame()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.addWidget(cb)
            self._preview_table.setCellWidget(row, _PRV_COL_CHECK, cb_widget)

            # Username
            self._preview_table.setItem(
                row, _PRV_COL_USERNAME,
                QTableWidgetItem(getattr(account, "username", "?")),
            )

            # Device
            device_id = getattr(account, "device_id", "")
            self._preview_table.setItem(
                row, _PRV_COL_DEVICE,
                QTableWidgetItem(str(device_id)),
            )

            # Sources
            src_item = _NumericItem(str(src_count))
            src_item.setTextAlignment(right)
            self._preview_table.setItem(row, _PRV_COL_SOURCES, src_item)

            # Deficit
            deficit_item = _NumericItem(str(max(deficit, 0)))
            deficit_item.setTextAlignment(right)
            if deficit > 0:
                deficit_item.setForeground(sc("warning"))
            else:
                deficit_item.setForeground(sc("muted"))
            self._preview_table.setItem(row, _PRV_COL_DEFICIT, deficit_item)

            # Hide row if count >= threshold
            if src_count >= threshold:
                self._preview_table.setRowHidden(row, True)
            else:
                visible_count += 1

            # Store account id for later retrieval
            self._preview_table.item(row, _PRV_COL_USERNAME).setData(
                Qt.ItemDataRole.UserRole, getattr(account, "id", None)
            )

        total = len(self._qualifying_accounts)
        self._preview_summary.setText(
            f"{visible_count} of {total} accounts below threshold ({threshold} sources)"
        )
        self._preview_table.setSortingEnabled(True)
        self._update_start_btn()

    def _on_threshold_changed(self, value: int) -> None:
        self._populate_preview()

    # ---- Page 1: Progress -----------------------------------------------

    def _build_progress_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        # Header
        self._progress_header = QLabel("Running Bulk Source Discovery...")
        self._progress_header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(self._progress_header)

        # Overall progress
        self._overall_bar = QProgressBar()
        self._overall_bar.setRange(0, 1)
        self._overall_bar.setValue(0)
        self._overall_bar.setFixedHeight(20)
        lo.addWidget(self._overall_bar)

        # Current account label
        self._current_label = QLabel("Preparing...")
        self._current_label.setStyleSheet(
            f"font-size: 12px; color: {sc('text').name()};"
        )
        lo.addWidget(self._current_label)

        # Step progress label
        self._step_label = QLabel("")
        self._step_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(self._step_label)

        # Progress table
        self._progress_table = self._make_progress_table()
        lo.addWidget(self._progress_table, stretch=1)

        # Stats label
        self._stats_label = QLabel("Errors: 0 | Rate limit pauses: 0")
        self._stats_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(self._stats_label)

        # Cancel button
        footer = QHBoxLayout()
        footer.addStretch()
        self._progress_cancel_btn = QPushButton("Cancel")
        self._progress_cancel_btn.setFixedWidth(80)
        self._progress_cancel_btn.clicked.connect(self._on_cancel_discovery)
        footer.addWidget(self._progress_cancel_btn)
        lo.addLayout(footer)

        return page

    def _make_progress_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_PGR_HEADERS))
        t.setHorizontalHeaderLabels(_PGR_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_PGR_COL_USERNAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_PGR_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_PGR_COL_FOUND, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_PGR_COL_ADDED, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_PGR_COL_STATUS, 80)
        t.setColumnWidth(_PGR_COL_FOUND, 80)
        t.setColumnWidth(_PGR_COL_ADDED, 80)

        return t

    # ---- Page 2: Results ------------------------------------------------

    def _build_results_page(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        # Summary header
        self._results_summary = QLabel("")
        self._results_summary.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(self._results_summary)

        # Splitter: results table + detail table
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Top: results table
        self._results_table = self._make_results_table()
        self._results_table.selectionModel().selectionChanged.connect(
            self._on_result_row_selected,
        )
        splitter.addWidget(self._results_table)

        # Bottom: detail pane
        splitter.addWidget(self._make_detail_pane())

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        lo.addWidget(splitter, stretch=1)

        # Footer
        footer = QHBoxLayout()
        footer.setContentsMargins(0, 4, 0, 0)

        self._revert_btn = QPushButton("Revert All")
        self._revert_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._revert_btn.setStyleSheet(
            f"QPushButton:enabled {{ color: {sc('warning').name()}; }}"
            f"QPushButton:enabled:hover {{ background: #2e2a1a; }}"
        )
        self._revert_btn.setToolTip("Revert all sources added in this run")
        self._revert_btn.clicked.connect(self._on_revert_all)
        footer.addWidget(self._revert_btn)

        footer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        lo.addLayout(footer)

        return page

    def _make_results_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_RES_HEADERS))
        t.setHorizontalHeaderLabels(_RES_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_RES_COL_ACCOUNT, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_RES_COL_DEVICE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_RES_COL_BEFORE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_RES_COL_ADDED, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_RES_COL_AFTER, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_RES_COL_STATUS, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_RES_COL_DEVICE, 160)
        t.setColumnWidth(_RES_COL_BEFORE, 70)
        t.setColumnWidth(_RES_COL_ADDED, 70)
        t.setColumnWidth(_RES_COL_AFTER, 70)
        t.setColumnWidth(_RES_COL_STATUS, 80)

        return t

    def _make_detail_pane(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)

        self._detail_header = QLabel("Select a row above to see added sources.")
        self._detail_header.setStyleSheet(
            f"color: {sc('muted').name()}; font-size: 11px;"
        )
        lo.addWidget(self._detail_header)

        t = QTableWidget(0, len(_DET_HEADERS))
        t.setHorizontalHeaderLabels(_DET_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_DET_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_DET_COL_FOLLOWERS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_DET_COL_ER, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_DET_COL_SCORE, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_DET_COL_FOLLOWERS, 90)
        t.setColumnWidth(_DET_COL_ER, 70)
        t.setColumnWidth(_DET_COL_SCORE, 80)

        self._detail_table = t
        lo.addWidget(t, stretch=1)
        return w

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _load_setting(self, key: str, default: int) -> int:
        try:
            val = self._settings_repo.get(key)
            return int(val) if val is not None else default
        except Exception:
            return default

    def _update_start_btn(self) -> None:
        checked = sum(1 for cb in self._checkboxes if cb.isChecked())
        self._start_btn.setEnabled(checked > 0)

    def _on_select_all(self) -> None:
        for row in range(self._preview_table.rowCount()):
            if not self._preview_table.isRowHidden(row):
                idx = row
                if idx < len(self._checkboxes):
                    self._checkboxes[idx].setChecked(True)

    def _on_deselect_all(self) -> None:
        for cb in self._checkboxes:
            cb.setChecked(False)

    def _selected_account_ids(self) -> List[int]:
        ids: List[int] = []
        for row in range(self._preview_table.rowCount()):
            if self._preview_table.isRowHidden(row):
                continue
            if row < len(self._checkboxes) and self._checkboxes[row].isChecked():
                item = self._preview_table.item(row, _PRV_COL_USERNAME)
                if item:
                    acc_id = item.data(Qt.ItemDataRole.UserRole)
                    if acc_id is not None:
                        ids.append(acc_id)
        return ids

    # ------------------------------------------------------------------
    # Start discovery
    # ------------------------------------------------------------------

    def _on_start(self) -> None:
        account_ids = self._selected_account_ids()
        if not account_ids:
            return

        threshold = self._threshold_spin.value()
        top_n = self._topn_spin.value()

        # Save settings for next time
        try:
            self._settings_repo.set("min_source_for_bulk_discovery", str(threshold))
            self._settings_repo.set("bulk_auto_add_top_n", str(top_n))
        except Exception:
            pass

        # Prepare progress page
        self._error_count = 0
        self._rate_limit_count = 0
        total = len(account_ids)
        self._overall_bar.setRange(0, total)
        self._overall_bar.setValue(0)
        self._current_label.setText(f"Preparing... (0/{total})")
        self._step_label.setText("")
        self._stats_label.setText("Errors: 0 | Rate limit pauses: 0")

        # Populate progress table with queued rows
        self._progress_table.setRowCount(0)
        center = Qt.AlignmentFlag.AlignCenter

        # Build a map from account id to username
        acc_map = {}
        for account, _ in self._qualifying_accounts:
            acc_map[getattr(account, "id", None)] = getattr(account, "username", "?")

        for idx, acc_id in enumerate(account_ids):
            self._progress_table.insertRow(idx)
            username = acc_map.get(acc_id, "?")
            self._progress_table.setItem(idx, _PGR_COL_USERNAME, QTableWidgetItem(username))
            status_item = QTableWidgetItem("...")
            status_item.setTextAlignment(center)
            status_item.setForeground(sc("muted"))
            self._progress_table.setItem(idx, _PGR_COL_STATUS, status_item)
            self._progress_table.setItem(idx, _PGR_COL_FOUND, QTableWidgetItem(""))
            self._progress_table.setItem(idx, _PGR_COL_ADDED, QTableWidgetItem(""))

        # Switch to progress page
        self._stack.setCurrentIndex(self._PAGE_PROGRESS)

        # Get bot_root from parent if available
        bot_root = ""
        try:
            bot_root = self._settings_repo.get("bot_root_path") or ""
        except Exception:
            pass

        # Start worker
        self._worker = BulkDiscoveryWorker(
            service=self._service,
            account_ids=account_ids,
            min_threshold=threshold,
            auto_add_top_n=top_n,
            bot_root=bot_root,
        )
        self._worker.account_started.connect(self._on_account_started)
        self._worker.account_done.connect(self._on_account_done)
        self._worker.account_error.connect(self._on_account_error)
        self._worker.step_progress.connect(self._on_step_progress)
        self._worker.rate_limit_pause.connect(self._on_rate_limit)
        self._worker.finished_signal.connect(self._on_discovery_finished)
        self._worker.start()

    # ------------------------------------------------------------------
    # Progress callbacks
    # ------------------------------------------------------------------

    def _on_account_started(self, index: int, username: str) -> None:
        total = self._overall_bar.maximum()
        self._current_label.setText(
            f"Processing @{username} ({index + 1}/{total})..."
        )
        if 0 <= index < self._progress_table.rowCount():
            status_item = self._progress_table.item(index, _PGR_COL_STATUS)
            if status_item:
                status_item.setText("...")
                status_item.setForeground(sc("link"))

    def _on_account_done(
        self, index: int, username: str, found_count: int, added_count: int,
    ) -> None:
        self._overall_bar.setValue(self._overall_bar.value() + 1)
        center = Qt.AlignmentFlag.AlignCenter
        if 0 <= index < self._progress_table.rowCount():
            status_item = self._progress_table.item(index, _PGR_COL_STATUS)
            if status_item:
                status_item.setText("OK")
                status_item.setForeground(sc("success"))
            found_item = QTableWidgetItem(str(found_count))
            found_item.setTextAlignment(center)
            self._progress_table.setItem(index, _PGR_COL_FOUND, found_item)
            added_item = QTableWidgetItem(str(added_count))
            added_item.setTextAlignment(center)
            self._progress_table.setItem(index, _PGR_COL_ADDED, added_item)

    def _on_account_error(self, index: int, username: str, error_msg: str) -> None:
        self._error_count += 1
        self._stats_label.setText(
            f"Errors: {self._error_count} | Rate limit pauses: {self._rate_limit_count}"
        )

        if index == -1:
            # Fatal error from worker
            QMessageBox.critical(
                self, "Discovery Failed",
                f"Bulk discovery failed:\n\n{error_msg}",
            )
            self._stack.setCurrentIndex(self._PAGE_PREVIEW)
            return

        self._overall_bar.setValue(self._overall_bar.value() + 1)
        if 0 <= index < self._progress_table.rowCount():
            status_item = self._progress_table.item(index, _PGR_COL_STATUS)
            if status_item:
                status_item.setText("ERR")
                status_item.setForeground(sc("error"))

    def _on_step_progress(self, pct: int, msg: str) -> None:
        self._step_label.setText(msg)

    def _on_rate_limit(self, seconds: int) -> None:
        self._rate_limit_count += 1
        self._step_label.setText(f"Rate limited — pausing {seconds}s...")
        self._stats_label.setText(
            f"Errors: {self._error_count} | Rate limit pauses: {self._rate_limit_count}"
        )

    def _on_cancel_discovery(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(3000)
            self._worker = None
        self._stack.setCurrentIndex(self._PAGE_PREVIEW)

    # ------------------------------------------------------------------
    # Discovery finished
    # ------------------------------------------------------------------

    def _on_discovery_finished(self, result: object) -> None:
        self._run_result = result  # type: ignore[assignment]
        if self._worker is not None:
            self._worker.quit()
            self._worker.wait(3000)
            self._worker = None

        run = self._run_result  # type: BulkDiscoveryRun  # noqa
        if run is None:
            self._stack.setCurrentIndex(self._PAGE_PREVIEW)
            return

        items = run.items or []
        total_done = sum(1 for it in items if it.status == ITEM_DONE)
        total_failed = sum(1 for it in items if it.status == ITEM_FAILED)
        total_skipped = sum(1 for it in items if it.status == ITEM_SKIPPED)
        total_added = run.total_added

        self._results_summary.setText(
            f"{len(items)} accounts processed, {total_added} sources added, "
            f"{total_failed} errors"
        )

        # Can only revert a completed run
        can_revert = (
            run.status in ("completed",)
            and run.revert_status is None
            and total_added > 0
        )
        self._revert_btn.setEnabled(can_revert)

        # Populate results table
        self._populate_results(items)

        self._stack.setCurrentIndex(self._PAGE_RESULTS)

    def _populate_results(self, items: List[BulkDiscoveryItem]) -> None:
        self._results_table.setSortingEnabled(False)
        self._results_table.setRowCount(0)
        center = Qt.AlignmentFlag.AlignCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        for item in items:
            row = self._results_table.rowCount()
            self._results_table.insertRow(row)

            # Account
            acc_item = QTableWidgetItem(item.username)
            acc_item.setData(Qt.ItemDataRole.UserRole, item)
            self._results_table.setItem(row, _RES_COL_ACCOUNT, acc_item)

            # Device
            self._results_table.setItem(
                row, _RES_COL_DEVICE, QTableWidgetItem(item.device_id),
            )

            # Before
            before_item = _NumericItem(str(item.sources_before))
            before_item.setTextAlignment(right)
            self._results_table.setItem(row, _RES_COL_BEFORE, before_item)

            # Added
            added_item = _NumericItem(str(item.sources_added))
            added_item.setTextAlignment(right)
            if item.sources_added > 0:
                added_item.setForeground(sc("success"))
            self._results_table.setItem(row, _RES_COL_ADDED, added_item)

            # After
            after_item = _NumericItem(str(item.sources_after))
            after_item.setTextAlignment(right)
            self._results_table.setItem(row, _RES_COL_AFTER, after_item)

            # Status
            status_text = _STATUS_TEXT.get(item.status, item.status)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(center)
            status_item.setForeground(_status_color(item.status))
            self._results_table.setItem(row, _RES_COL_STATUS, status_item)

        self._results_table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Result drill-down
    # ------------------------------------------------------------------

    def _on_result_row_selected(self) -> None:
        selected = self._results_table.selectedItems()
        if not selected:
            self._detail_header.setText("Select a row above to see added sources.")
            self._detail_table.setRowCount(0)
            return

        row = selected[0].row()
        acc_item = self._results_table.item(row, _RES_COL_ACCOUNT)
        if not acc_item:
            return

        item = acc_item.data(Qt.ItemDataRole.UserRole)  # type: BulkDiscoveryItem
        if item is None:
            return

        # Parse added sources from JSON
        sources: List[str] = []
        if item.added_sources_json:
            try:
                sources = json.loads(item.added_sources_json)
            except (json.JSONDecodeError, TypeError):
                pass

        if not sources:
            self._detail_header.setText(
                f"No sources added for @{item.username}."
            )
            self._detail_table.setRowCount(0)
            return

        self._detail_header.setText(
            f"Sources added for @{item.username} ({len(sources)}):"
        )

        self._detail_table.setRowCount(0)
        center = Qt.AlignmentFlag.AlignCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        for src in sources:
            r = self._detail_table.rowCount()
            self._detail_table.insertRow(r)
            self._detail_table.setItem(r, _DET_COL_SOURCE, QTableWidgetItem(str(src)))

            # Placeholder values — detail data is optional
            for col in (_DET_COL_FOLLOWERS, _DET_COL_ER, _DET_COL_SCORE):
                placeholder = QTableWidgetItem("--")
                placeholder.setTextAlignment(right)
                placeholder.setForeground(sc("muted"))
                self._detail_table.setItem(r, col, placeholder)

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def _on_revert_all(self) -> None:
        if self._run_result is None:
            return

        run_id = self._run_result.id
        if run_id is None:
            QMessageBox.warning(self, "Revert Error", "Run ID not available.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Revert",
            f"This will remove all {self._run_result.total_added} sources added "
            f"during this bulk discovery run.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._revert_btn.setEnabled(False)
        self._revert_btn.setText("Reverting...")

        from oh.ui.workers import WorkerThread
        self._revert_worker = WorkerThread(self._service.revert_run, run_id)
        self._revert_worker.result.connect(self._on_revert_complete)
        self._revert_worker.error.connect(self._on_revert_error)
        self._revert_worker.start()

    def _on_revert_complete(self, result) -> None:
        reverted, failed, errors = result
        msg = f"Reverted bulk discovery run.\n"
        msg += f"Accounts reverted: {reverted}"
        if failed:
            msg += f"\nFailed: {failed}"
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Revert Complete", msg)
        self._revert_btn.setText("Revert All")
        self._revert_btn.setEnabled(False)

    def _on_revert_error(self, error_msg: str) -> None:
        logger.exception("Revert failed")
        QMessageBox.critical(self, "Revert Failed", f"Error during revert:\n\n{error_msg}")
        self._revert_btn.setText("Revert All")
        self._revert_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(3000)
            self._worker = None
        super().closeEvent(event)
