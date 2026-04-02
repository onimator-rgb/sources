"""
BulkDiscoveryHistoryDialog — view past bulk discovery runs with drill-down.
"""
import json
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QWidget,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QSplitter, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.bulk_discovery import (
    BulkDiscoveryRun, BulkDiscoveryItem,
    BULK_COMPLETED, BULK_FAILED, BULK_CANCELLED,
    ITEM_DONE, ITEM_FAILED,
)
from oh.ui.style import sc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table column indices — Runs
# ---------------------------------------------------------------------------

_RUN_COL_DATE      = 0
_RUN_COL_STATUS    = 1
_RUN_COL_THRESHOLD = 2
_RUN_COL_TOPN      = 3
_RUN_COL_ACCOUNTS  = 4
_RUN_COL_ADDED     = 5
_RUN_COL_MACHINE   = 6

_RUN_HEADERS = ["Date", "Status", "Threshold", "Top N", "Accounts", "Added", "Machine"]

# ---------------------------------------------------------------------------
# Table column indices — Items
# ---------------------------------------------------------------------------

_ITM_COL_ACCOUNT = 0
_ITM_COL_DEVICE  = 1
_ITM_COL_BEFORE  = 2
_ITM_COL_ADDED   = 3
_ITM_COL_AFTER   = 4
_ITM_COL_STATUS  = 5
_ITM_COL_ERROR   = 6

_ITM_HEADERS = ["Account", "Device", "Before", "Added", "After", "Status", "Error"]

# ---------------------------------------------------------------------------
# Status colors
# ---------------------------------------------------------------------------

_RUN_STATUS_COLORS = {
    BULK_COMPLETED: "success",
    BULK_FAILED:    "error",
    BULK_CANCELLED: "muted",
}

_ITEM_STATUS_COLORS = {
    ITEM_DONE:   "success",
    ITEM_FAILED: "error",
}


class BulkDiscoveryHistoryDialog(QDialog):
    """View past bulk discovery runs with drill-down into per-account items."""

    def __init__(self, parent, bulk_discovery_service) -> None:
        super().__init__(parent)
        self._service = bulk_discovery_service
        self._runs: List[BulkDiscoveryRun] = []
        self._revert_worker = None

        self.setWindowTitle("Bulk Discovery History")
        self.setMinimumSize(900, 550)
        self.setModal(True)
        self._build_ui()
        self._load_runs()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(6)
        lo.setContentsMargins(12, 12, 12, 12)

        lo.addWidget(QLabel(
            "Each row is one bulk discovery run. "
            "Select a row to see per-account details."
        ))

        splitter = QSplitter(Qt.Orientation.Vertical)

        # -- Runs table --
        self._runs_table = self._make_runs_table()
        splitter.addWidget(self._runs_table)

        # -- Items detail pane --
        splitter.addWidget(self._make_items_pane())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)

        lo.addWidget(splitter, stretch=1)

        # -- Footer --
        footer = QHBoxLayout()

        self._revert_btn = QPushButton("Revert Run")
        self._revert_btn.setFixedHeight(28)
        self._revert_btn.setEnabled(False)
        self._revert_btn.setToolTip("Revert all sources added in the selected run")
        self._revert_btn.setStyleSheet(
            f"QPushButton:enabled {{ color: {sc('warning').name()}; }}"
            f"QPushButton:enabled:hover {{ background: #2e2a1a; }}"
        )
        self._revert_btn.clicked.connect(self._on_revert_clicked)
        footer.addWidget(self._revert_btn)

        footer.addStretch()

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(28)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)

        lo.addLayout(footer)

    def _make_runs_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_RUN_HEADERS))
        t.setHorizontalHeaderLabels(_RUN_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)

        hdr = t.horizontalHeader()
        for col in range(6):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_RUN_COL_MACHINE, QHeaderView.ResizeMode.Stretch)

        t.setColumnWidth(_RUN_COL_DATE, 150)
        t.setColumnWidth(_RUN_COL_STATUS, 90)
        t.setColumnWidth(_RUN_COL_THRESHOLD, 80)
        t.setColumnWidth(_RUN_COL_TOPN, 60)
        t.setColumnWidth(_RUN_COL_ACCOUNTS, 80)
        t.setColumnWidth(_RUN_COL_ADDED, 70)

        t.selectionModel().selectionChanged.connect(self._on_run_selected)
        return t

    def _make_items_pane(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(4)

        self._items_header = QLabel("Select a run above to see account details.")
        self._items_header.setStyleSheet(
            f"color: {sc('muted').name()}; font-size: 11px;"
        )
        lo.addWidget(self._items_header)

        t = QTableWidget(0, len(_ITM_HEADERS))
        t.setHorizontalHeaderLabels(_ITM_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_ITM_COL_ACCOUNT, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(_ITM_COL_DEVICE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_ITM_COL_BEFORE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_ITM_COL_ADDED, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_ITM_COL_AFTER, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_ITM_COL_STATUS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(_ITM_COL_ERROR, QHeaderView.ResizeMode.Stretch)

        t.setColumnWidth(_ITM_COL_DEVICE, 140)
        t.setColumnWidth(_ITM_COL_BEFORE, 60)
        t.setColumnWidth(_ITM_COL_ADDED, 60)
        t.setColumnWidth(_ITM_COL_AFTER, 60)
        t.setColumnWidth(_ITM_COL_STATUS, 70)

        self._items_table = t
        lo.addWidget(t, stretch=1)
        return w

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_runs(self) -> None:
        try:
            self._runs = self._service.get_all_runs()
        except Exception as e:
            logger.exception("Failed to load bulk discovery runs: %s", e)
            self._runs = []

        self._runs_table.setRowCount(0)
        center = Qt.AlignmentFlag.AlignCenter

        if not self._runs:
            self._runs_table.insertRow(0)
            msg = QTableWidgetItem("No bulk discovery runs yet.")
            msg.setTextAlignment(center)
            msg.setForeground(sc("muted"))
            self._runs_table.setItem(0, 0, msg)
            self._runs_table.setSpan(0, 0, 1, len(_RUN_HEADERS))
            return

        for run in self._runs:
            r = self._runs_table.rowCount()
            self._runs_table.insertRow(r)

            # Date
            date_str = (
                run.started_at[:16].replace("T", "  ")
                if run.started_at else "\u2014"
            )
            date_item = QTableWidgetItem(date_str)
            date_item.setData(Qt.ItemDataRole.UserRole, run.id)
            self._runs_table.setItem(r, _RUN_COL_DATE, date_item)

            # Status
            if run.revert_status:
                status_text = "reverted"
                status_color = sc("muted")
            else:
                status_text = run.status.capitalize() if run.status else "\u2014"
                color_key = _RUN_STATUS_COLORS.get(run.status, "muted")
                status_color = sc(color_key)
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(center)
            status_item.setForeground(status_color)
            self._runs_table.setItem(r, _RUN_COL_STATUS, status_item)

            # Threshold
            thresh_item = QTableWidgetItem(str(run.min_threshold))
            thresh_item.setTextAlignment(center)
            self._runs_table.setItem(r, _RUN_COL_THRESHOLD, thresh_item)

            # Top N
            topn_item = QTableWidgetItem(str(run.auto_add_top_n))
            topn_item.setTextAlignment(center)
            self._runs_table.setItem(r, _RUN_COL_TOPN, topn_item)

            # Accounts
            acct_item = QTableWidgetItem(str(run.total_accounts))
            acct_item.setTextAlignment(center)
            self._runs_table.setItem(r, _RUN_COL_ACCOUNTS, acct_item)

            # Added
            added_item = QTableWidgetItem(str(run.total_added))
            added_item.setTextAlignment(center)
            if run.total_added > 0:
                added_item.setForeground(sc("success"))
            self._runs_table.setItem(r, _RUN_COL_ADDED, added_item)

            # Machine
            self._runs_table.setItem(
                r, _RUN_COL_MACHINE,
                QTableWidgetItem(run.machine or ""),
            )

    # ------------------------------------------------------------------
    # Run selection — load items
    # ------------------------------------------------------------------

    def _on_run_selected(self) -> None:
        selected = self._runs_table.selectedItems()
        if not selected:
            self._items_header.setText("Select a run above to see account details.")
            self._items_table.setRowCount(0)
            self._revert_btn.setEnabled(False)
            return

        row = selected[0].row()
        date_item = self._runs_table.item(row, _RUN_COL_DATE)
        if not date_item:
            self._revert_btn.setEnabled(False)
            return
        run_id = date_item.data(Qt.ItemDataRole.UserRole)
        if run_id is None:
            self._revert_btn.setEnabled(False)
            return

        # Find run in cached list
        run = next((r for r in self._runs if r.id == run_id), None)

        # Load items
        items: List[BulkDiscoveryItem] = []
        try:
            run_detail = self._service.get_run_details(run_id)
            if run_detail and run_detail.items:
                items = run_detail.items
        except Exception as e:
            logger.warning("Failed to load items for run #%s: %s", run_id, e)

        # Revert eligibility
        can_revert = (
            run is not None
            and run.status == BULK_COMPLETED
            and run.revert_status is None
            and run.total_added > 0
        )
        self._revert_btn.setEnabled(can_revert)
        if can_revert:
            self._revert_btn.setToolTip("Revert all sources added in this run")
        elif run and run.revert_status:
            self._revert_btn.setToolTip("This run has already been reverted")
        else:
            self._revert_btn.setToolTip("Only completed runs with added sources can be reverted")

        self._items_header.setText(
            f"Accounts in this run ({len(items)}):"
        )

        # Populate items table
        center = Qt.AlignmentFlag.AlignCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        self._items_table.setRowCount(0)

        for item in items:
            r = self._items_table.rowCount()
            self._items_table.insertRow(r)

            # Account
            self._items_table.setItem(
                r, _ITM_COL_ACCOUNT, QTableWidgetItem(item.username),
            )

            # Device
            self._items_table.setItem(
                r, _ITM_COL_DEVICE, QTableWidgetItem(item.device_id),
            )

            # Before
            before_item = QTableWidgetItem(str(item.sources_before))
            before_item.setTextAlignment(right)
            self._items_table.setItem(r, _ITM_COL_BEFORE, before_item)

            # Added
            added_item = QTableWidgetItem(str(item.sources_added))
            added_item.setTextAlignment(right)
            if item.sources_added > 0:
                added_item.setForeground(sc("success"))
            self._items_table.setItem(r, _ITM_COL_ADDED, added_item)

            # After
            after_item = QTableWidgetItem(str(item.sources_after))
            after_item.setTextAlignment(right)
            self._items_table.setItem(r, _ITM_COL_AFTER, after_item)

            # Status
            status_text = item.status.upper() if item.status else "\u2014"
            if item.status == ITEM_DONE:
                status_text = "OK"
            elif item.status == ITEM_FAILED:
                status_text = "ERR"
            status_item = QTableWidgetItem(status_text)
            status_item.setTextAlignment(center)
            color_key = _ITEM_STATUS_COLORS.get(item.status, "muted")
            status_item.setForeground(sc(color_key))
            self._items_table.setItem(r, _ITM_COL_STATUS, status_item)

            # Error
            error_text = item.error_message or ""
            error_item = QTableWidgetItem(error_text)
            if error_text:
                error_item.setForeground(sc("error"))
            self._items_table.setItem(r, _ITM_COL_ERROR, error_item)

    # ------------------------------------------------------------------
    # Revert
    # ------------------------------------------------------------------

    def _on_revert_clicked(self) -> None:
        selected = self._runs_table.selectedItems()
        if not selected:
            return

        row = selected[0].row()
        date_item = self._runs_table.item(row, _RUN_COL_DATE)
        if not date_item:
            return
        run_id = date_item.data(Qt.ItemDataRole.UserRole)
        if run_id is None:
            return

        run = next((r for r in self._runs if r.id == run_id), None)
        if run is None:
            QMessageBox.warning(self, "Revert Error", "Run not found.")
            return

        reply = QMessageBox.question(
            self,
            "Confirm Revert",
            f"This will remove all {run.total_added} sources added "
            f"during bulk discovery run #{run_id}.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self._revert_btn.setEnabled(False)
        self._revert_btn.setText("Reverting...")

        from oh.ui.workers import WorkerThread
        self._revert_worker = WorkerThread(self._service.revert_run, run_id)
        self._revert_worker.result.connect(self._on_revert_done)
        self._revert_worker.error.connect(self._on_revert_fail)
        self._revert_worker.start()

    def _on_revert_done(self, result) -> None:
        reverted, failed, errors = result
        msg = f"Accounts reverted: {reverted}"
        if failed:
            msg += f"\nFailed: {failed}"
        if errors:
            msg += "\n\nErrors:\n" + "\n".join(errors[:5])
        QMessageBox.information(self, "Revert Complete", msg)
        self._revert_btn.setText("Revert Run")
        self._load_runs()
        self._items_table.setRowCount(0)
        self._revert_btn.setEnabled(False)

    def _on_revert_fail(self, error_msg: str) -> None:
        logger.exception("Revert failed")
        QMessageBox.critical(self, "Revert Failed", f"Error during revert:\n\n{error_msg}")
        self._revert_btn.setText("Revert Run")
        self._revert_btn.setEnabled(False)
