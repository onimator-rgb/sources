"""
NotificationsTab — Notifications Browser.

Reads the bot's notificationdatabase.db and presents notifications in a
filterable, sortable table with type-based color coding.
"""
import logging
from datetime import date, timedelta
from typing import List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QDateEdit, QCheckBox, QMenu, QFileDialog,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QAction

from oh.models.notification import NOTIFICATION_TYPES, NotificationRecord
from oh.services.notification_service import NotificationService
from oh.ui.style import sc, BTN_HEIGHT_LG
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indexes
# ---------------------------------------------------------------------------

_COL_DEVICE       = 0
_COL_ACCOUNT      = 1
_COL_NOTIFICATION = 2
_COL_DATE         = 3
_COL_TIME         = 4

_HEADERS = ["Device", "Account", "Notification", "Date", "Time"]


# ---------------------------------------------------------------------------
# Sortable table item
# ---------------------------------------------------------------------------

class _SortableItem(QTableWidgetItem):
    """QTableWidgetItem sorted by an explicit key rather than display text."""

    def __init__(self, display_text: str, sort_key) -> None:
        super().__init__(display_text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, _SortableItem):
            try:
                return self._sort_key < other._sort_key
            except TypeError:
                return str(self._sort_key) < str(other._sort_key)
        return self.text() < other.text()


# ---------------------------------------------------------------------------
# NotificationsTab
# ---------------------------------------------------------------------------

class NotificationsTab(QWidget):
    def __init__(
        self,
        notification_service: NotificationService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = notification_service
        self._bot_root: Optional[str] = None
        self._loaded = False
        self._all_records: List[NotificationRecord] = []
        self._filtered_records: List[NotificationRecord] = []
        self._worker: Optional[WorkerThread] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_bot_root(self, path: str) -> None:
        """Store the bot root path for data loading."""
        self._bot_root = path

    def load_data(self) -> None:
        """Public entry — called by MainWindow on tab switch."""
        if not self._bot_root:
            self._status_label.setText("No bot root configured.")
            return

        self._btn_refresh.setEnabled(False)
        self._btn_export.setEnabled(False)
        self._status_label.setText("Loading notifications...")

        self._worker = WorkerThread(
            self._service.load_notifications, self._bot_root
        )
        self._worker.result.connect(self._populate)
        self._worker.error.connect(self._on_load_error)
        self._worker.start()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 6, 0, 0)
        lo.setSpacing(6)

        lo.addWidget(self._make_toolbar())
        lo.addWidget(self._make_filter_bar())
        lo.addWidget(self._make_table(), stretch=1)

    def _make_toolbar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 0, 8, 0)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedHeight(BTN_HEIGHT_LG)
        self._btn_refresh.setFixedWidth(90)
        self._btn_refresh.clicked.connect(self._on_refresh)
        h.addWidget(self._btn_refresh)

        self._btn_export = QPushButton("Export CSV")
        self._btn_export.setFixedHeight(BTN_HEIGHT_LG)
        self._btn_export.setFixedWidth(100)
        self._btn_export.clicked.connect(self._on_export_csv)
        h.addWidget(self._btn_export)

        h.addStretch()

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {sc('muted').name()};")
        h.addWidget(self._status_label)

        h.addSpacing(12)

        self._count_label = QLabel("Showing 0 of 0")
        h.addWidget(self._count_label)

        return bar

    def _make_filter_bar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 0, 8, 0)

        # Device combo
        self._device_combo = QComboBox()
        self._device_combo.setFixedWidth(160)
        self._device_combo.addItem("All Devices")
        self._device_combo.currentIndexChanged.connect(self._apply_filters)
        h.addWidget(self._device_combo)

        h.addSpacing(6)

        # Type combo
        self._type_combo = QComboBox()
        self._type_combo.setFixedWidth(130)
        self._type_combo.addItem("All Types")
        for ntype in NOTIFICATION_TYPES:
            self._type_combo.addItem(ntype)
        self._type_combo.currentIndexChanged.connect(self._apply_filters)
        h.addWidget(self._type_combo)

        h.addSpacing(6)

        # Account search
        self._account_search = QLineEdit()
        self._account_search.setPlaceholderText("Search account...")
        self._account_search.setFixedWidth(180)
        self._account_search.textChanged.connect(self._apply_filters)
        h.addWidget(self._account_search)

        h.addSpacing(6)

        # Date From
        h.addWidget(QLabel("From:"))
        self._date_from = QDateEdit()
        self._date_from.setCalendarPopup(True)
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_from.setDisplayFormat("yyyy-MM-dd")
        self._date_from.setFixedWidth(120)
        self._date_from.dateChanged.connect(self._apply_filters)
        h.addWidget(self._date_from)

        h.addSpacing(6)

        # Date To
        h.addWidget(QLabel("To:"))
        self._date_to = QDateEdit()
        self._date_to.setCalendarPopup(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setDisplayFormat("yyyy-MM-dd")
        self._date_to.setFixedWidth(120)
        self._date_to.dateChanged.connect(self._apply_filters)
        h.addWidget(self._date_to)

        h.addSpacing(6)

        # Include empty accounts checkbox
        self._chk_empty_accounts = QCheckBox("Include empty accounts")
        self._chk_empty_accounts.setChecked(True)
        self._chk_empty_accounts.stateChanged.connect(self._apply_filters)
        h.addWidget(self._chk_empty_accounts)

        h.addSpacing(6)

        # Clear Filters button
        self._btn_clear = QPushButton("Clear Filters")
        self._btn_clear.setFixedWidth(100)
        self._btn_clear.clicked.connect(self._on_clear_filters)
        h.addWidget(self._btn_clear)

        h.addStretch()

        return bar

    def _make_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)

        widths = {
            _COL_DEVICE: 160,
            _COL_ACCOUNT: 160,
            _COL_NOTIFICATION: 400,
            _COL_DATE: 100,
            _COL_TIME: 80,
        }
        for col, w in widths.items():
            self._table.setColumnWidth(col, w)

        # Context menu
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._on_context_menu)

        return self._table

    # ------------------------------------------------------------------
    # Data population
    # ------------------------------------------------------------------

    def _populate(self, records: List[NotificationRecord]) -> None:
        """Called when WorkerThread finishes loading."""
        self._all_records = records
        self._loaded = True
        self._btn_refresh.setEnabled(True)
        self._btn_export.setEnabled(True)

        # Populate device combo with discovered devices
        current_device = self._device_combo.currentText()
        self._device_combo.blockSignals(True)
        self._device_combo.clear()
        self._device_combo.addItem("All Devices")

        devices = sorted(set(
            rec.device_name or rec.device_id for rec in records
        ))
        for dev in devices:
            self._device_combo.addItem(dev)

        # Restore selection if possible
        idx = self._device_combo.findText(current_device)
        if idx >= 0:
            self._device_combo.setCurrentIndex(idx)
        self._device_combo.blockSignals(False)

        self._status_label.setText(f"Loaded {len(records)} notifications.")
        self._apply_filters()

    def _on_load_error(self, msg: str) -> None:
        """Called when WorkerThread encounters an error."""
        self._btn_refresh.setEnabled(True)
        self._btn_export.setEnabled(False)
        self._status_label.setText(f"Error: {msg}")
        logger.error(f"Failed to load notifications: {msg}")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filters(self) -> None:
        device_filter = self._device_combo.currentText()
        type_filter = self._type_combo.currentText()
        account_search = self._account_search.text().strip().lower()
        date_from = self._date_from.date().toString("yyyy-MM-dd")
        date_to = self._date_to.date().toString("yyyy-MM-dd")
        include_empty = self._chk_empty_accounts.isChecked()

        filtered: List[NotificationRecord] = []
        for rec in self._all_records:
            # Device filter
            if device_filter != "All Devices":
                display_device = rec.device_name or rec.device_id
                if display_device != device_filter:
                    continue

            # Type filter
            if type_filter != "All Types":
                if rec.notification_type != type_filter:
                    continue

            # Account search
            if account_search:
                if not rec.account or account_search not in rec.account.lower():
                    continue

            # Empty accounts filter
            if not include_empty and not rec.account:
                continue

            # Date range filter
            if rec.date:
                if rec.date < date_from or rec.date > date_to:
                    continue

            filtered.append(rec)

        self._filtered_records = filtered
        self._fill_table(filtered)
        self._count_label.setText(
            f"Showing {len(filtered)} of {len(self._all_records)}"
        )

    def _fill_table(self, records: List[NotificationRecord]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(records))

        for row, rec in enumerate(records):
            self._fill_row(row, rec)

        self._table.setSortingEnabled(True)

    def _fill_row(self, row: int, rec: NotificationRecord) -> None:
        # Device
        device_display = rec.device_name or rec.device_id
        item = QTableWidgetItem(device_display)
        item.setData(Qt.ItemDataRole.UserRole, rec.device_id)
        self._table.setItem(row, _COL_DEVICE, item)

        # Account
        account_display = rec.account or ""
        item = QTableWidgetItem(account_display)
        self._table.setItem(row, _COL_ACCOUNT, item)

        # Notification (colored by type) — store type as UserRole for sort-safe access
        item = QTableWidgetItem(rec.notification)
        color_key = NOTIFICATION_TYPES.get(rec.notification_type, "muted")
        item.setForeground(sc(color_key))
        item.setData(Qt.ItemDataRole.UserRole, rec.notification_type)
        self._table.setItem(row, _COL_NOTIFICATION, item)

        # Date
        item = _SortableItem(rec.date or "", rec.date or "")
        self._table.setItem(row, _COL_DATE, item)

        # Time
        item = _SortableItem(rec.time or "", rec.time or "")
        self._table.setItem(row, _COL_TIME, item)

    # ------------------------------------------------------------------
    # Context menu
    # ------------------------------------------------------------------

    def _on_context_menu(self, pos) -> None:
        row = self._table.rowAt(pos.y())
        if row < 0:
            return

        menu = QMenu(self)

        act_copy = QAction("Copy Row", self)
        act_copy.triggered.connect(lambda: self._copy_row(row))
        menu.addAction(act_copy)

        menu.addSeparator()

        act_filter_account = QAction("Filter by this Account", self)
        act_filter_account.triggered.connect(
            lambda: self._filter_by_account(row)
        )
        menu.addAction(act_filter_account)

        act_filter_device = QAction("Filter by this Device", self)
        act_filter_device.triggered.connect(
            lambda: self._filter_by_device(row)
        )
        menu.addAction(act_filter_device)

        act_filter_type = QAction("Filter by this Type", self)
        act_filter_type.triggered.connect(
            lambda: self._filter_by_type(row)
        )
        menu.addAction(act_filter_type)

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_row(self, row: int) -> None:
        parts = []
        for col in range(self._table.columnCount()):
            item = self._table.item(row, col)
            parts.append(item.text() if item else "")
        text = "\t".join(parts)

        from PySide6.QtWidgets import QApplication
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def _filter_by_account(self, row: int) -> None:
        item = self._table.item(row, _COL_ACCOUNT)
        if item and item.text():
            self._account_search.setText(item.text())

    def _filter_by_device(self, row: int) -> None:
        item = self._table.item(row, _COL_DEVICE)
        if item and item.text():
            idx = self._device_combo.findText(item.text())
            if idx >= 0:
                self._device_combo.setCurrentIndex(idx)

    def _filter_by_type(self, row: int) -> None:
        item = self._table.item(row, _COL_NOTIFICATION)
        if item:
            ntype = item.data(Qt.ItemDataRole.UserRole)
            if ntype:
                idx = self._type_combo.findText(ntype)
                if idx >= 0:
                    self._type_combo.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def _on_export_csv(self) -> None:
        if not self._filtered_records:
            self._status_label.setText("No records to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Notifications CSV", "notifications.csv",
            "CSV Files (*.csv)"
        )
        if not path:
            return

        try:
            self._service.export_csv(self._filtered_records, path)
            self._status_label.setText(
                f"Exported {len(self._filtered_records)} records to CSV."
            )
        except Exception as e:
            self._status_label.setText(f"Export failed: {e}")
            logger.exception(f"CSV export failed: {e}")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self.load_data()

    def _on_clear_filters(self) -> None:
        """Reset all filters to defaults."""
        self._device_combo.blockSignals(True)
        self._device_combo.setCurrentIndex(0)
        self._device_combo.blockSignals(False)

        self._type_combo.blockSignals(True)
        self._type_combo.setCurrentIndex(0)
        self._type_combo.blockSignals(False)

        self._account_search.blockSignals(True)
        self._account_search.clear()
        self._account_search.blockSignals(False)

        self._date_from.blockSignals(True)
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_from.blockSignals(False)

        self._date_to.blockSignals(True)
        self._date_to.setDate(QDate.currentDate())
        self._date_to.blockSignals(False)

        self._chk_empty_accounts.blockSignals(True)
        self._chk_empty_accounts.setChecked(True)
        self._chk_empty_accounts.blockSignals(False)

        self._apply_filters()
