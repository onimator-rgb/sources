"""
MainWindow — primary application window for OH.

Layout:
  ┌─────────────────────────────────────────────────────────────────┐
  │  [Settings bar: bot root path + Browse + Save]                  │
  ├─────────────────────────────────────────────────────────────────┤
  │  Tabs: [Accounts]  [Sources]  [Settings]                        │
  │                                                                 │
  │  Accounts tab:                                                  │
  │    [Scan & Sync]  [Analyze FBR]  [Refresh]   last sync: ...     │
  │    Status | FBR | Device | Search filters        N accounts     │
  │    Username | Device | Status | Follow | Unfollow | Limit/Day   │
  │    Data DB  | Sources.txt | Disc. | Seen | Active Sources       │
  │    Quality/Total | Best FBR % | Last FBR | Actions              │
  ├─────────────────────────────────────────────────────────────────┤
  │  Status bar                                                     │
  └─────────────────────────────────────────────────────────────────┘
"""
import subprocess
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QComboBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap

from oh.models.account import AccountRecord, DiscoveredAccount
from oh.models.fbr_snapshot import FBRSnapshotRecord, BatchFBRResult, SNAPSHOT_OK, SNAPSHOT_ERROR
from oh.models.sync import SyncRun
from oh.modules.discovery import DiscoveryError
from oh.modules.fbr_calculator import FBRCalculator
from oh.modules.source_inspector import SourceInspector
from oh.modules.source_usage_reader import SourceUsageReader
from oh.repositories.account_repo import AccountRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.sync_repo import SyncRepository
from oh.services.fbr_service import FBRService
from oh.services.global_sources_service import GlobalSourcesService
from oh.services.scan_service import ScanService
from oh.services.source_delete_service import SourceDeleteService
from oh.resources import asset_path, asset_exists
from oh.ui.settings_tab import SettingsTab
from oh.ui.source_dialog import SourceDialog
from oh.ui.sources_tab import SourcesTab
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table column indexes
# ---------------------------------------------------------------------------

COL_USERNAME    = 0
COL_DEVICE      = 1
COL_STATUS      = 2
COL_FOLLOW      = 3
COL_UNFOLLOW    = 4
COL_LIMIT       = 5
COL_DATA_DB     = 6
COL_SOURCES_TXT = 7
COL_DISCOVERED  = 8
COL_LAST_SEEN   = 9
COL_SRC_COUNT   = 10   # active source count — from source_assignments
COL_FBR_QUALITY = 11   # "3/12" quality/total — from latest snapshot
COL_FBR_BEST    = 12   # best FBR % — from latest snapshot
COL_FBR_DATE    = 13   # date of last FBR analysis
COL_ACTIONS     = 14

COLUMN_HEADERS = [
    "Username", "Device", "Status",
    "Follow", "Unfollow", "Limit/Day",
    "Data DB", "Sources.txt",
    "Discovered", "Last Seen",
    "Active Sources",
    "Quality/Total", "Best FBR %", "Last FBR",
    "Actions",
]

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

C_ACTIVE   = QColor("#4caf7d")
C_REMOVED  = QColor("#888888")
C_YES      = QColor("#4caf7d")
C_NO       = QColor("#e05555")
C_WARN     = QColor("#e6a817")
C_ORPHAN   = QColor("#cc8800")
C_QUALITY  = QColor("#4caf7d")
C_LOW_FBR  = QColor("#888888")
C_ERROR    = QColor("#e05555")
C_NEVER    = QColor("#e6a817")


# ---------------------------------------------------------------------------
# Sortable item — numeric/date sort for FBR columns
# ---------------------------------------------------------------------------

class _SortableItem(QTableWidgetItem):
    """QTableWidgetItem whose sort order is driven by an explicit sort key."""

    def __init__(self, display_text: str, sort_key) -> None:
        super().__init__(display_text)
        self._sort_key = sort_key

    def __lt__(self, other: "QTableWidgetItem") -> bool:
        if isinstance(other, _SortableItem):
            try:
                return self._sort_key < other._sort_key
            except TypeError:
                return str(self._sort_key) < str(other._sort_key)
        return self.text() < other.text()


# ---------------------------------------------------------------------------
# FBR filter option values
# ---------------------------------------------------------------------------

_FBR_FILTER_ALL        = "All FBR states"
_FBR_FILTER_ATTENTION  = "Needs attention"
_FBR_FILTER_NEVER      = "Never analyzed"
_FBR_FILTER_ERRORS     = "Has errors"
_FBR_FILTER_NO_QUALITY = "No quality sources"
_FBR_FILTER_HAS_QUALITY = "Has quality sources"

_STATUS_FILTER_ACTIVE   = "Active only"
_STATUS_FILTER_REMOVED  = "Removed only"
_STATUS_FILTER_ALL      = "All accounts"


class MainWindow(QMainWindow):
    def __init__(
        self,
        conn: sqlite3.Connection,
        scan_service: ScanService,
        fbr_service: FBRService,
        global_sources_service: GlobalSourcesService,
        source_delete_service: SourceDeleteService,
    ) -> None:
        super().__init__()
        self._scan_service            = scan_service
        self._fbr_service             = fbr_service
        self._global_sources_service  = global_sources_service
        self._settings                = SettingsRepository(conn)
        self._accounts                = AccountRepository(conn)
        self._sync_repo               = SyncRepository(conn)

        self._worker: Optional[WorkerThread] = None
        self._all_accounts: list = []
        self._last_discovery: list = []
        self._fbr_map: dict[int, FBRSnapshotRecord] = {}
        self._source_count_map: dict[int, int] = {}

        self.setWindowTitle("OH — Operational Hub")
        self.setMinimumSize(1400, 720)

        self._sources_tab  = SourcesTab(global_sources_service, source_delete_service)
        self._settings_tab = SettingsTab(self._settings)
        self._build_ui()
        self._refresh_table()
        self._update_last_sync_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(6)
        outer.setContentsMargins(10, 10, 10, 6)

        # Brand bar + settings bar sit above the tabs
        outer.addWidget(self._make_brand_bar())
        outer.addWidget(self._make_settings_bar())

        self._tabs = QTabWidget()
        self._tabs.addTab(self._make_accounts_page(), "Accounts")
        self._tabs.addTab(self._sources_tab, "Sources")
        self._tabs.addTab(self._settings_tab, "Settings")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self._tabs, stretch=1)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._set_status("Ready.")

    def _make_accounts_page(self) -> QWidget:
        """Wrap the existing toolbar + filter bar + table into the Accounts tab."""
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 6, 0, 0)
        lo.setSpacing(6)
        lo.addWidget(self._make_toolbar())
        lo.addWidget(self._make_filter_bar())
        lo.addWidget(self._make_table(), stretch=1)
        return w

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:  # Sources tab
            self._sources_tab.set_bot_root(self._settings.get_bot_root())
            self._sources_tab.load_data()
        elif index == 2:  # Settings tab — reload in case values changed externally
            self._settings_tab._load()

    def _make_brand_bar(self) -> QFrame:
        """Thin header bar showing the logo and product identity."""
        frame = QFrame()
        frame.setObjectName("brandBar")
        lo = QHBoxLayout(frame)
        lo.setContentsMargins(10, 0, 10, 0)
        lo.setSpacing(8)

        # Logo image — shown only if the asset file exists
        logo_lbl = QLabel()
        if asset_exists("logo.png"):
            px = QPixmap(str(asset_path("logo.png")))
            if not px.isNull():
                logo_lbl.setPixmap(
                    px.scaledToHeight(22, Qt.TransformationMode.SmoothTransformation)
                )

        # Product name
        title_lbl = QLabel("Wizzysocial  <span style='color:#555;font-size:9px;'>· OH Operational Hub</span>")
        title_lbl.setTextFormat(Qt.TextFormat.RichText)
        title_lbl.setStyleSheet("color: #c0d8f0; font-size: 12px; font-weight: 600;")

        lo.addWidget(logo_lbl)
        lo.addWidget(title_lbl)
        lo.addStretch()

        ver_lbl = QLabel("internal tool")
        ver_lbl.setStyleSheet("color: #444; font-size: 9px;")
        lo.addWidget(ver_lbl)

        return frame

    def _make_settings_bar(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setObjectName("settingsBar")

        lo = QHBoxLayout(frame)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(8)

        lbl = QLabel("Onimator Path:")
        lbl.setFixedWidth(110)

        self._root_input = QLineEdit()
        self._root_input.setPlaceholderText(
            "e.g.  C:\\Users\\Admin\\Desktop\\full_igbot_13.9.0"
        )
        saved = self._settings.get_bot_root()
        if saved:
            self._root_input.setText(saved)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse)

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(60)
        save_btn.clicked.connect(self._on_save_root)

        lo.addWidget(lbl)
        lo.addWidget(self._root_input, stretch=1)
        lo.addWidget(browse_btn)
        lo.addWidget(save_btn)
        return frame

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        self._scan_btn = QPushButton("⟳  Scan & Sync")
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.setToolTip(
            "Discover accounts from the Onimator folder and sync with the OH registry"
        )
        self._scan_btn.clicked.connect(self._on_scan_and_sync)

        self._fbr_btn = QPushButton("◈  Analyze FBR")
        self._fbr_btn.setFixedHeight(32)
        self._fbr_btn.setToolTip(
            "Run FBR analysis for all active accounts that have data.db\n"
            "and save results to the OH database"
        )
        self._fbr_btn.clicked.connect(self._on_analyze_fbr)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setToolTip("Reload the account list from the OH database (no scan)")
        refresh_btn.clicked.connect(self._refresh_table)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("font-style: italic; color: #aaa;")

        self._last_sync_label = QLabel("")
        self._last_sync_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._last_sync_label.setStyleSheet("color: #777; font-size: 11px;")

        lo.addWidget(self._scan_btn)
        lo.addWidget(self._fbr_btn)
        lo.addWidget(refresh_btn)
        lo.addSpacing(12)
        lo.addWidget(self._busy_label, stretch=1)
        lo.addWidget(self._last_sync_label)
        return w

    def _make_filter_bar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(8)

        # Status filter
        lo.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems([
            _STATUS_FILTER_ACTIVE,
            _STATUS_FILTER_REMOVED,
            _STATUS_FILTER_ALL,
        ])
        self._status_filter.setFixedWidth(110)
        self._status_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._status_filter)

        lo.addSpacing(4)

        # FBR state filter
        lo.addWidget(QLabel("FBR:"))
        self._fbr_filter = QComboBox()
        self._fbr_filter.addItems([
            _FBR_FILTER_ALL,
            _FBR_FILTER_ATTENTION,
            _FBR_FILTER_NEVER,
            _FBR_FILTER_ERRORS,
            _FBR_FILTER_NO_QUALITY,
            _FBR_FILTER_HAS_QUALITY,
        ])
        self._fbr_filter.setFixedWidth(150)
        self._fbr_filter.setToolTip(
            "Needs attention = never analyzed or zero quality sources"
        )
        self._fbr_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._fbr_filter)

        lo.addSpacing(4)

        # Device filter
        lo.addWidget(QLabel("Device:"))
        self._device_filter = QComboBox()
        self._device_filter.setFixedWidth(130)
        self._device_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._device_filter)

        lo.addSpacing(4)

        # Text search
        lo.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("username or device…")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        lo.addWidget(self._search_box)

        lo.addSpacing(4)

        # Orphans checkbox
        self._show_orphans_cb = QCheckBox("Show orphans")
        self._show_orphans_cb.setToolTip(
            "Orphan: folder exists on disk but not registered in accounts.db"
        )
        self._show_orphans_cb.stateChanged.connect(self._apply_filter)
        lo.addWidget(self._show_orphans_cb)

        # Clear button
        clear_btn = QPushButton("Clear filters")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear_filters)
        lo.addWidget(clear_btn)

        lo.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #777; font-size: 11px;")
        lo.addWidget(self._count_label)
        return w

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, len(COLUMN_HEADERS))
        t.setHorizontalHeaderLabels(COLUMN_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        for col in (COL_USERNAME, COL_DEVICE, COL_DISCOVERED, COL_LAST_SEEN):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        for col in (COL_STATUS, COL_FOLLOW, COL_UNFOLLOW, COL_LIMIT,
                    COL_DATA_DB, COL_SOURCES_TXT, COL_SRC_COUNT,
                    COL_FBR_QUALITY, COL_FBR_BEST, COL_FBR_DATE,
                    COL_ACTIONS):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(COL_USERNAME,     180)
        t.setColumnWidth(COL_DEVICE,       100)
        t.setColumnWidth(COL_STATUS,        80)
        t.setColumnWidth(COL_FOLLOW,        62)
        t.setColumnWidth(COL_UNFOLLOW,      72)
        t.setColumnWidth(COL_LIMIT,         76)
        t.setColumnWidth(COL_DATA_DB,       68)
        t.setColumnWidth(COL_SOURCES_TXT,   88)
        t.setColumnWidth(COL_DISCOVERED,   105)
        t.setColumnWidth(COL_LAST_SEEN,    105)
        t.setColumnWidth(COL_SRC_COUNT,     80)
        t.setColumnWidth(COL_FBR_QUALITY,   95)
        t.setColumnWidth(COL_FBR_BEST,      80)
        t.setColumnWidth(COL_FBR_DATE,      90)
        t.setColumnWidth(COL_ACTIONS,      210)

        t.doubleClicked.connect(self._on_row_double_clicked)
        self._table = t
        return t

    # ------------------------------------------------------------------
    # Data loading and display
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._all_accounts = self._accounts.get_all()
        self._fbr_map = self._fbr_service.get_latest_map()
        self._source_count_map = self._global_sources_service.get_active_source_counts()
        self._update_device_filter()
        self._apply_filter()
        self._update_last_sync_label()

    def _refresh_source_counts(self) -> None:
        """Called by SourcesTab (via parent-chain walk) after a delete operation."""
        self._source_count_map = self._global_sources_service.get_active_source_counts()
        self._apply_filter()

    def _update_device_filter(self) -> None:
        """Rebuild the device dropdown from the current account list."""
        current = self._device_filter.currentText()
        self._device_filter.blockSignals(True)
        self._device_filter.clear()

        devices: list[str] = ["All devices"]
        seen: set[str] = set()
        for acc in self._all_accounts:
            label = acc.device_name or acc.device_id
            if label and label not in seen:
                seen.add(label)
                devices.append(label)
        self._device_filter.addItems(devices)

        # Restore previous selection if it still exists
        idx = self._device_filter.findText(current)
        self._device_filter.setCurrentIndex(max(idx, 0))
        self._device_filter.blockSignals(False)

    def _clear_filters(self) -> None:
        """Reset all filters to their defaults without triggering multiple repaints."""
        self._status_filter.blockSignals(True)
        self._fbr_filter.blockSignals(True)
        self._device_filter.blockSignals(True)
        self._search_box.blockSignals(True)
        self._show_orphans_cb.blockSignals(True)

        self._status_filter.setCurrentIndex(0)   # Active only
        self._fbr_filter.setCurrentIndex(0)       # All FBR states
        self._device_filter.setCurrentIndex(0)    # All devices
        self._search_box.clear()
        self._show_orphans_cb.setChecked(False)

        self._status_filter.blockSignals(False)
        self._fbr_filter.blockSignals(False)
        self._device_filter.blockSignals(False)
        self._search_box.blockSignals(False)
        self._show_orphans_cb.blockSignals(False)

        self._apply_filter()

    @staticmethod
    def _fbr_filter_matches(filt: str, snap: Optional[FBRSnapshotRecord]) -> bool:
        """Return True if the account should be included under the given FBR filter."""
        if filt == _FBR_FILTER_ALL:
            return True
        if filt == _FBR_FILTER_NEVER:
            return snap is None
        if filt == _FBR_FILTER_ERRORS:
            return snap is not None and snap.status == SNAPSHOT_ERROR
        if filt == _FBR_FILTER_NO_QUALITY:
            return snap is None or snap.quality_sources == 0
        if filt == _FBR_FILTER_HAS_QUALITY:
            return snap is not None and snap.quality_sources > 0
        if filt == _FBR_FILTER_ATTENTION:
            # needs attention = never analyzed OR zero quality sources
            return snap is None or snap.quality_sources == 0
        return True

    def _apply_filter(self) -> None:
        status_filt  = self._status_filter.currentText()
        fbr_filt     = self._fbr_filter.currentText()
        device_filt  = self._device_filter.currentText()
        query        = self._search_box.text().strip().lower()
        show_orphans = self._show_orphans_cb.isChecked()

        active_accounts = [a for a in self._all_accounts if a.is_active]
        total_active    = len(active_accounts)

        rows: list = []

        for acc in self._all_accounts:
            # --- status dimension ---
            if status_filt == _STATUS_FILTER_ACTIVE and not acc.is_active:
                continue
            if status_filt == _STATUS_FILTER_REMOVED and acc.is_active:
                continue

            # --- device dimension ---
            if device_filt != "All devices":
                label = acc.device_name or acc.device_id
                if label != device_filt:
                    continue

            # --- FBR dimension ---
            snap = self._fbr_map.get(acc.id) if acc.id is not None else None
            if not self._fbr_filter_matches(fbr_filt, snap):
                continue

            # --- text search ---
            if query:
                name_match   = query in acc.username.lower()
                device_match = bool(acc.device_name and query in acc.device_name.lower())
                if not name_match and not device_match:
                    continue

            rows.append(("account", acc))

        if show_orphans:
            for disc in self._last_discovery:
                if disc.is_orphan_folder:
                    if query and query not in disc.username.lower():
                        continue
                    rows.append(("orphan", disc))

        self._populate_table(rows)

        shown = len(rows)
        total = len(self._all_accounts)
        if status_filt == _STATUS_FILTER_ACTIVE:
            total = total_active
        self._count_label.setText(f"Showing {shown} of {total} accounts")

    def _populate_table(self, rows: list) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        if not rows:
            self._table.insertRow(0)
            msg = QTableWidgetItem("No accounts match the current filters.")
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(QColor("#777777"))
            self._table.setItem(0, 0, msg)
            self._table.setSpan(0, 0, 1, len(COLUMN_HEADERS))
            self._table.setSortingEnabled(True)
            return

        # Clear any previous span before adding real rows
        self._table.setSpan(0, 0, 1, 1)

        for kind, obj in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            if kind == "account":
                self._fill_account_row(r, obj)
            else:
                self._fill_orphan_row(r, obj)

        self._table.setSortingEnabled(True)

    def _fill_account_row(self, row: int, acc: AccountRecord) -> None:
        removed = not acc.is_active
        center  = Qt.AlignmentFlag.AlignCenter

        status_color = C_ACTIVE if not removed else C_REMOVED
        status_text  = "Active" if not removed else "Removed"

        disc_date = acc.discovered_at[:10] if acc.discovered_at else "—"
        seen_date = acc.last_seen_at[:10]  if acc.last_seen_at  else "—"

        self._table.setItem(row, COL_USERNAME,    self._make_item(acc.username, dimmed=removed))
        self._table.setItem(row, COL_DEVICE,      self._make_item(acc.device_name or acc.device_id, dimmed=removed))
        self._table.setItem(row, COL_STATUS,      self._make_item(status_text, center, status_color))
        self._table.setItem(row, COL_FOLLOW,      self._make_bool_item(acc.follow_enabled, dimmed=removed))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_bool_item(acc.unfollow_enabled, dimmed=removed))
        self._table.setItem(row, COL_LIMIT,       self._make_item(acc.limit_per_day or "—", center, dimmed=removed))
        self._table.setItem(row, COL_DATA_DB,     self._make_bool_item(acc.data_db_exists, dimmed=removed))
        self._table.setItem(row, COL_SOURCES_TXT, self._make_bool_item(acc.sources_txt_exists, dimmed=removed))
        self._table.setItem(row, COL_DISCOVERED,  self._make_item(disc_date, center, dimmed=removed))
        self._table.setItem(row, COL_LAST_SEEN,   self._make_item(seen_date, center, dimmed=removed))

        # Active source count with low-source warning
        if acc.id is not None:
            src_count = self._source_count_map.get(acc.id, 0)
            min_warn  = self._settings.get_min_source_count_warning()
            if removed:
                src_color = C_REMOVED
            elif src_count < min_warn:
                src_color = C_WARN
            else:
                src_color = None
            src_item = _SortableItem(str(src_count), src_count)
            src_item.setTextAlignment(center)
            if src_color:
                src_item.setForeground(src_color)
            self._table.setItem(row, COL_SRC_COUNT, src_item)
        else:
            self._table.setItem(row, COL_SRC_COUNT, self._make_item("—", center))

        # FBR summary cells
        snap = self._fbr_map.get(acc.id) if acc.id is not None else None
        self._fill_fbr_cells(row, snap, dimmed=removed)

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("account", acc.id)
        )

        open_btn = QPushButton("Open Folder")
        open_btn.setFixedHeight(24)
        open_btn.setEnabled(not removed)
        open_btn.setToolTip("Open this account's folder in Windows Explorer")
        open_btn.clicked.connect(
            lambda _, a=acc: self._open_account_folder(a.device_id, a.username)
        )

        src_btn = QPushButton("Sources")
        src_btn.setFixedHeight(24)
        has_sources = acc.data_db_exists or acc.sources_txt_exists
        src_btn.setEnabled(has_sources)
        src_btn.setToolTip(
            "Inspect sources and FBR analytics for this account"
            if has_sources else
            "No source files found for this account"
        )
        src_btn.clicked.connect(
            lambda _, a=acc: self._on_view_sources(a.device_id, a.username, a.id)
        )

        self._table.setCellWidget(row, COL_ACTIONS, self._wrap_btns(open_btn, src_btn))

    def _fill_orphan_row(self, row: int, disc: DiscoveredAccount) -> None:
        center = Qt.AlignmentFlag.AlignCenter

        self._table.setItem(row, COL_USERNAME,    self._make_item(disc.username))
        self._table.setItem(row, COL_DEVICE,      self._make_item(disc.device_name))
        self._table.setItem(row, COL_STATUS,      self._make_item("Orphan", center, C_ORPHAN))
        self._table.setItem(row, COL_FOLLOW,      self._make_item("—", center))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_item("—", center))
        self._table.setItem(row, COL_LIMIT,       self._make_item("—", center))
        self._table.setItem(row, COL_DATA_DB,     self._make_bool_item(disc.data_db_exists))
        self._table.setItem(row, COL_SOURCES_TXT, self._make_bool_item(disc.sources_txt_exists))
        self._table.setItem(row, COL_DISCOVERED,  self._make_item("—", center))
        self._table.setItem(row, COL_LAST_SEEN,   self._make_item("—", center))
        self._table.setItem(row, COL_SRC_COUNT,   self._make_item("—", center))

        # Orphans have no OH account_id — no FBR snapshot
        self._fill_fbr_cells(row, snap=None, dimmed=False)

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("orphan", disc)
        )

        open_btn = QPushButton("Open Folder")
        open_btn.setFixedHeight(24)
        open_btn.setToolTip("Open orphan folder in Windows Explorer")
        open_btn.clicked.connect(
            lambda _, d=disc: self._open_account_folder(d.device_id, d.username)
        )

        src_btn = QPushButton("Sources")
        src_btn.setFixedHeight(24)
        has_sources = disc.data_db_exists or disc.sources_txt_exists
        src_btn.setEnabled(has_sources)
        src_btn.setToolTip(
            "Inspect source list for this orphan folder"
            if has_sources else
            "No source files found in this orphan folder"
        )
        src_btn.clicked.connect(
            lambda _, d=disc: self._on_view_sources(d.device_id, d.username, None)
        )

        self._table.setCellWidget(row, COL_ACTIONS, self._wrap_btns(open_btn, src_btn))

    def _fill_fbr_cells(
        self,
        row: int,
        snap: Optional[FBRSnapshotRecord],
        dimmed: bool,
    ) -> None:
        """Populate the three FBR summary columns for one row.

        Sort keys:
          COL_FBR_QUALITY  — int: -2=Never, -1=Error, else quality_sources
          COL_FBR_BEST     — float: -2.0=Never, -1.0=Error/empty, else best_fbr_pct
          COL_FBR_DATE     — str: ""=Never (sorts first asc), else ISO date
        """
        center = Qt.AlignmentFlag.AlignCenter

        def _si(text: str, sort_key, color=None, _dimmed=False) -> _SortableItem:
            item = _SortableItem(text, sort_key)
            item.setTextAlignment(center)
            if _dimmed:
                item.setForeground(C_REMOVED)
            elif color:
                item.setForeground(color)
            return item

        if snap is None:
            # Never analyzed — use amber to draw operator attention
            self._table.setItem(row, COL_FBR_QUALITY, _si("—",     -2,   C_NEVER))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",     -2.0, C_NEVER))
            self._table.setItem(row, COL_FBR_DATE,    _si("Never", "",   C_NEVER))
            return

        date_str  = snap.analyzed_at[:10] if snap.analyzed_at else "—"
        date_sort = snap.analyzed_at[:10] if snap.analyzed_at else ""

        if snap.status == SNAPSHOT_ERROR:
            self._table.setItem(row, COL_FBR_QUALITY, _si("Error", -1,   C_ERROR))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",     -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        if snap.total_sources == 0:
            # Empty result — data.db exists but no qualifying source rows
            self._table.setItem(row, COL_FBR_QUALITY, _si("0/0", 0,    C_LOW_FBR))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",   -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        # Normal case: 'ok' status with data
        quality_text  = f"{snap.quality_sources}/{snap.total_sources}"
        quality_color = C_QUALITY if snap.quality_sources > 0 else C_LOW_FBR
        self._table.setItem(
            row, COL_FBR_QUALITY,
            _si(quality_text, snap.quality_sources, quality_color, _dimmed=dimmed),
        )

        if snap.best_fbr_pct is not None:
            fbr_color = C_QUALITY if snap.quality_sources > 0 else C_LOW_FBR
            self._table.setItem(
                row, COL_FBR_BEST,
                _si(f"{snap.best_fbr_pct:.1f}%", snap.best_fbr_pct, fbr_color, _dimmed=dimmed),
            )
        else:
            self._table.setItem(row, COL_FBR_BEST, _si("—", -1.0))

        self._table.setItem(
            row, COL_FBR_DATE,
            _si(date_str, date_sort, _dimmed=dimmed),
        )

    # ------------------------------------------------------------------
    # Static cell helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_item(
        text: str,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        color: Optional[QColor] = None,
        dimmed: bool = False,
    ) -> QTableWidgetItem:
        i = QTableWidgetItem(text)
        i.setTextAlignment(align)
        if dimmed:
            i.setForeground(C_REMOVED)
        elif color:
            i.setForeground(color)
        return i

    @staticmethod
    def _make_bool_item(
        val: Optional[bool], dimmed: bool = False
    ) -> QTableWidgetItem:
        center = Qt.AlignmentFlag.AlignCenter
        if val is None:
            i = QTableWidgetItem("—")
            i.setTextAlignment(center)
            return i
        text = "Yes" if val else "No"
        col  = C_REMOVED if dimmed else (C_YES if val else C_NO)
        i = QTableWidgetItem(text)
        i.setTextAlignment(center)
        i.setForeground(col)
        return i

    @staticmethod
    def _wrap_btns(*btns: QPushButton) -> QWidget:
        wrapper = QWidget()
        lo = QHBoxLayout(wrapper)
        lo.setContentsMargins(4, 2, 4, 2)
        lo.setSpacing(4)
        for btn in btns:
            lo.addWidget(btn)
        return wrapper

    def _update_last_sync_label(self) -> None:
        run = self._sync_repo.get_latest_run()
        if run:
            date = run.completed_at[:16].replace("T", "  ") if run.completed_at else "—"
            self._last_sync_label.setText(f"Last sync: {date}")
        else:
            self._last_sync_label.setText("Last sync: never")

    # ------------------------------------------------------------------
    # User actions — scan flow
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        current = self._root_input.text().strip() or ""
        path = QFileDialog.getExistingDirectory(
            self, "Select Onimator Installation Folder", current
        )
        if path:
            self._root_input.setText(path)
            self._on_save_root()

    def _on_save_root(self) -> None:
        path = self._root_input.text().strip()
        if not path:
            return
        self._settings.set_bot_root(path)
        self._sources_tab.set_bot_root(path)
        self._set_status(f"Bot root saved: {path}")

    def _on_scan_and_sync(self) -> None:
        bot_root = self._get_validated_root()
        if not bot_root:
            return

        self._set_busy(True, "Scanning Onimator folder…")

        def do_scan():
            return self._scan_service.scan(bot_root)

        self._worker = WorkerThread(do_scan)
        self._worker.result.connect(self._on_scan_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_scan_done(self, discovered: list) -> None:
        self._last_discovery = discovered

        device_count  = len({d.device_id for d in discovered})
        regular_count = sum(1 for d in discovered if not d.is_orphan_folder)
        orphan_count  = sum(1 for d in discovered if d.is_orphan_folder)
        missing_count = sum(1 for d in discovered if d.is_missing_folder)

        notes = []
        if orphan_count:
            notes.append(f"{orphan_count} orphan folder(s)")
        if missing_count:
            notes.append(f"{missing_count} account(s) missing folder")
        note_str = "  ·  " + ",  ".join(notes) if notes else ""

        self._set_status(
            f"Scan done: {regular_count} account(s) on {device_count} device(s){note_str}. "
            "Syncing registry…"
        )
        self._busy_label.setText("Syncing registry…")

        def do_sync():
            return self._scan_service.sync(discovered)

        self._worker = WorkerThread(do_sync)
        self._worker.result.connect(self._on_sync_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_sync_done(self, sync_run: SyncRun) -> None:
        msg = (
            f"Sync complete — "
            f"+{sync_run.accounts_added} added,  "
            f"-{sync_run.accounts_removed} removed,  "
            f"~{sync_run.accounts_updated} updated,  "
            f"={sync_run.accounts_unchanged} unchanged"
        )
        self._set_status(msg)
        self._refresh_table()

    # ------------------------------------------------------------------
    # User actions — FBR batch flow
    # ------------------------------------------------------------------

    def _on_analyze_fbr(self) -> None:
        bot_root = self._get_validated_root()
        if not bot_root:
            return

        self._set_busy(True, "Running FBR analysis…")

        def do_fbr():
            return self._fbr_service.analyze_all_active(bot_root)

        self._worker = WorkerThread(do_fbr)
        self._worker.result.connect(self._on_fbr_batch_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_fbr_batch_done(self, result: BatchFBRResult) -> None:
        self._set_status(f"FBR analysis complete — {result.status_line()}")

        if result.errors:
            for err in result.errors:
                logger.warning(f"FBR batch error: {err}")

        # Reload FBR map and repopulate accounts table
        self._fbr_map = self._fbr_service.get_latest_map()
        self._apply_filter()

        # If the Sources tab is currently open, refresh it too
        if self._tabs.currentIndex() == 1:
            self._sources_tab.load_data()

    # ------------------------------------------------------------------
    # User actions — sources dialog
    # ------------------------------------------------------------------

    def _on_view_sources(
        self,
        device_id: str,
        username: str,
        account_id: Optional[int],
    ) -> None:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(
                self, "Bot Root Not Set",
                "Set the Onimator path before inspecting sources."
            )
            return

        logger.info(
            f"Opening source preview: {username}@{device_id[:12]}  "
            f"(account_id={account_id})"
        )
        self._set_status(f"Loading sources for {username}…")

        # --- Step 1: read source files ---
        try:
            inspection = SourceInspector(bot_root).inspect(device_id, username)
            logger.info(
                f"[Sources] Inspection done: {username} — "
                f"{inspection.total_count} total "
                f"({inspection.active_count} active, {inspection.historical_count} historical)  "
                f"sources_txt={inspection.sources_txt_found}  data_db={inspection.data_db_found}"
            )
            if inspection.warnings:
                for w in inspection.warnings:
                    logger.warning(f"[Sources] Inspection warning ({username}): {w}")
        except Exception as e:
            logger.exception(f"[Sources] Inspection failed for {username}")
            self._set_status("Ready.")
            QMessageBox.critical(self, "Source Inspection Failed", str(e))
            return

        # --- Step 2: compute FBR ---
        min_f, min_p = self._settings.get_fbr_thresholds()
        logger.info(
            f"[Sources] Computing FBR for {username} — "
            f"thresholds: min_follows={min_f}  min_fbr={min_p}%  "
            f"account_id={account_id}"
        )

        if account_id is not None:
            try:
                fbr_result, snapshot = self._fbr_service.analyze_and_save(
                    bot_root, device_id, username, account_id
                )
                # Update in-memory FBR map so the accounts table refreshes
                # without a DB round-trip when the dialog closes.
                self._fbr_map[account_id] = snapshot
                logger.info(
                    f"[Sources] FBR computed+saved: {username} — "
                    f"schema_valid={fbr_result.schema_valid}  "
                    f"records={len(fbr_result.records)}  "
                    f"quality={fbr_result.quality_count}  "
                    f"anomalies={fbr_result.anomaly_count}  "
                    f"snapshot_id={snapshot.id}"
                )
            except Exception as e:
                logger.exception(
                    f"[Sources] analyze_and_save failed for {username} — "
                    f"falling back to read-only FBR calculation"
                )
                fbr_result = FBRCalculator(bot_root, min_f, min_p).calculate(device_id, username)
                logger.warning(
                    f"[Sources] FBR fallback result: {username} — "
                    f"schema_valid={fbr_result.schema_valid}  "
                    f"records={len(fbr_result.records)}"
                )
                if not fbr_result.schema_valid:
                    logger.warning(f"[Sources] FBR fallback schema error: {fbr_result.schema_error}")
        else:
            # Orphan row — compute but do not persist (no account_id in OH registry)
            fbr_result = FBRCalculator(bot_root, min_f, min_p).calculate(device_id, username)
            logger.info(
                f"[Sources] FBR computed (orphan, no persist): {username} — "
                f"schema_valid={fbr_result.schema_valid}  "
                f"records={len(fbr_result.records)}"
            )
            if not fbr_result.schema_valid:
                logger.warning(f"[Sources] FBR schema error ({username}): {fbr_result.schema_error}")

        # --- Step 3: pre-dialog match summary ---
        # Compute how many sources will show FBR data vs '—' before opening the dialog.
        # This makes it easy to spot genuine mismatches in the log.
        _fbr_keys = {r.source_name.strip().lower() for r in fbr_result.records}
        _n_matched     = sum(1 for s in inspection.sources
                             if s.source_name.strip().lower() in _fbr_keys)
        _n_active_only = sum(1 for s in inspection.sources
                             if s.is_active and not s.is_historical)
        _n_unexpected  = inspection.total_count - _n_matched - _n_active_only

        logger.info(
            f"[Sources] Pre-dialog merge: {username} — "
            f"{_n_matched}/{inspection.total_count} rows will show FBR data  |  "
            f"{_n_active_only} active-only (new, '—' is correct)  |  "
            f"{_n_unexpected} unexpected misses (historical but no FBR record)"
        )
        if _n_unexpected > 0:
            for _s in inspection.sources:
                _k = _s.source_name.strip().lower()
                if _s.is_historical and _k not in _fbr_keys:
                    logger.warning(
                        f"[Sources] Unexpected miss: {_s.source_name!r} "
                        f"is in data.db (historical) but has no FBR record  "
                        f"(normalized key={_k!r})"
                    )

        # --- Step 4: read source usage + derive used % ---
        source_names = [s.source_name for s in inspection.sources]
        follows_map = {
            r.source_name.strip().lower(): r.follow_count
            for r in fbr_result.records
        }
        try:
            usage_result = SourceUsageReader(bot_root).read(
                device_id, username, source_names, follows_map
            )
            logger.info(
                f"[SourceUsage] {username}: "
                f"sources_dir={usage_result.sources_dir_found}  "
                f"found={usage_result.db_count_found}  "
                f"missing={usage_result.db_count_missing}  "
                f"with_pct={usage_result.pct_count_derived}"
            )
        except Exception as e:
            logger.warning(
                f"[SourceUsage] Failed to read usage for {username}: {e}"
            )
            from oh.models.source_usage import SourceUsageResult
            usage_result = SourceUsageResult(
                account_username=username, device_id=device_id
            )

        self._set_status("Ready.")
        dlg = SourceDialog(inspection, fbr_result, usage_result, parent=self)
        dlg.exec()

        # Repopulate table so updated FBR cells are visible immediately
        self._apply_filter()

    # ------------------------------------------------------------------
    # User actions — folder and row interaction
    # ------------------------------------------------------------------

    def _open_account_folder(self, device_id: str, username: str) -> None:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(self, "Bot Root Not Set",
                                "Set the Onimator path before opening folders.")
            return
        folder = Path(bot_root) / device_id / username
        self._launch_explorer(folder, username)

    def _launch_explorer(self, folder: Path, label: str) -> None:
        if not folder.exists():
            QMessageBox.warning(
                self, "Folder Not Found",
                f"Folder does not exist on disk:\n{folder}"
            )
            return
        subprocess.Popen(f'explorer "{folder}"', shell=True)
        self._set_status(f"Opened: {folder}")

    def _on_row_double_clicked(self, index) -> None:
        row  = index.row()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "account":
            acc = self._accounts.get_by_id(payload)
            if acc and acc.is_active:
                self._open_account_folder(acc.device_id, acc.username)
        elif kind == "orphan":
            self._open_account_folder(payload.device_id, payload.username)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_validated_root(self) -> Optional[str]:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(
                self, "Bot Root Not Set",
                "Please set the Onimator installation path first.\n\n"
                "Enter it in the path field at the top and click Save.",
            )
            return None
        if not Path(bot_root).is_dir():
            QMessageBox.warning(
                self, "Path Not Found",
                f"The configured path does not exist:\n{bot_root}\n\n"
                "Please update it and click Save.",
            )
            return None
        return bot_root

    def _on_worker_error(self, error: str) -> None:
        self._set_busy(False)
        logger.error(f"Background worker error: {error}")
        QMessageBox.critical(self, "Operation Failed", error)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._scan_btn.setEnabled(not busy)
        self._fbr_btn.setEnabled(not busy)
        self._busy_label.setText(message if busy else "")
        if not busy:
            self._set_status("Ready.")

    def _set_status(self, message: str) -> None:
        self._statusbar.showMessage(message)
