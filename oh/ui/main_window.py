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
    QAbstractItemView, QFrame, QMessageBox, QMenu, QInputDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap

from datetime import date

from oh.models.account import AccountRecord, DiscoveredAccount
from oh.models.fbr_snapshot import FBRSnapshotRecord, BatchFBRResult, SNAPSHOT_OK, SNAPSHOT_ERROR
from oh.models.session import AccountSessionRecord, slot_for_times
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
from oh.services.session_service import SessionService
from oh.services.operator_action_service import OperatorActionService
from oh.services.recommendation_service import RecommendationService
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
COL_TAGS        = 3
COL_FOLLOW      = 4
COL_UNFOLLOW    = 5
COL_LIMIT       = 6
COL_FOLLOW_TODAY = 7
COL_LIKE_TODAY   = 8
COL_FOLLOW_LIM   = 9
COL_LIKE_LIM     = 10
COL_REVIEW       = 11
COL_DATA_DB     = 12
COL_SOURCES_TXT = 13
COL_DISCOVERED  = 14
COL_LAST_SEEN   = 15
COL_SRC_COUNT   = 16   # active source count — from source_assignments
COL_FBR_QUALITY = 17   # "3/12" quality/total — from latest snapshot
COL_FBR_BEST    = 18   # best FBR % — from latest snapshot
COL_FBR_DATE    = 19   # date of last FBR analysis
COL_ACTIONS     = 20

COLUMN_HEADERS = [
    "Username", "Device", "Status", "Tags",
    "Follow", "Unfollow", "Limit/Day",
    "Follow Today", "Like Today", "F. Limit", "L. Limit", "Review",
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

_TAGS_FILTER_ALL     = "All tags"
_TAGS_FILTER_TB      = "TB"
_TAGS_FILTER_LIMITS  = "limits"
_TAGS_FILTER_SLAVE   = "SLAVE"
_TAGS_FILTER_START   = "START"
_TAGS_FILTER_PK      = "PK"
_TAGS_FILTER_CUSTOM  = "Custom"

_ACTIVITY_FILTER_ALL      = "All activity"
_ACTIVITY_FILTER_ZERO     = "0 actions today"
_ACTIVITY_FILTER_HAS      = "Has actions"


class MainWindow(QMainWindow):
    def __init__(
        self,
        conn: sqlite3.Connection,
        scan_service: ScanService,
        fbr_service: FBRService,
        global_sources_service: GlobalSourcesService,
        source_delete_service: SourceDeleteService,
        session_service: Optional[SessionService] = None,
        operator_action_service: Optional[OperatorActionService] = None,
        operator_action_repo=None,
        tag_repo=None,
        recommendation_service: Optional[RecommendationService] = None,
    ) -> None:
        super().__init__()
        self._scan_service            = scan_service
        self._fbr_service             = fbr_service
        self._global_sources_service  = global_sources_service
        self._source_delete_service   = source_delete_service
        self._session_service         = session_service
        self._operator_action_service = operator_action_service
        self._operator_action_repo    = operator_action_repo
        self._tag_repo                = tag_repo
        self._recommendation_service  = recommendation_service
        self._settings                = SettingsRepository(conn)
        self._accounts                = AccountRepository(conn)
        self._sync_repo               = SyncRepository(conn)

        self._conn                    = conn
        self._worker: Optional[WorkerThread] = None
        self._all_accounts: list = []
        self._last_discovery: list = []
        self._fbr_map: dict[int, FBRSnapshotRecord] = {}
        self._source_count_map: dict[int, int] = {}
        self._session_map: dict[int, AccountSessionRecord] = {}
        self._device_status_map: dict[str, str] = {}  # device_id → last_known_status
        self._op_tags_map: dict[int, str] = {}  # account_id → "TB3 | limits 2"

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

        self._report_btn = QPushButton("Session Report")
        self._report_btn.setFixedHeight(32)
        self._report_btn.setToolTip("Open session report for today")
        self._report_btn.clicked.connect(self._on_session_report)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("font-style: italic; color: #aaa;")

        self._last_sync_label = QLabel("")
        self._last_sync_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._last_sync_label.setStyleSheet("color: #777; font-size: 11px;")

        self._cockpit_btn = QPushButton("Cockpit")
        self._cockpit_btn.setFixedHeight(32)
        self._cockpit_btn.setToolTip("Daily operations overview")
        self._cockpit_btn.clicked.connect(self._on_cockpit)

        self._history_btn = QPushButton("Action History")
        self._history_btn.setFixedHeight(32)
        self._history_btn.setToolTip("Show recent operator actions")
        self._history_btn.clicked.connect(self._on_action_history)

        self._recs_btn = QPushButton("Recommendations")
        self._recs_btn.setFixedHeight(32)
        self._recs_btn.setToolTip("Generate and view operational recommendations")
        self._recs_btn.clicked.connect(self._on_recommendations)

        lo.addWidget(self._cockpit_btn)
        lo.addWidget(self._scan_btn)
        lo.addWidget(self._fbr_btn)
        lo.addWidget(refresh_btn)
        lo.addWidget(self._report_btn)
        lo.addWidget(self._recs_btn)
        lo.addWidget(self._history_btn)
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

        lo.addSpacing(4)

        # Tags filter
        lo.addWidget(QLabel("Tags:"))
        self._tags_filter = QComboBox()
        self._tags_filter.addItems([
            _TAGS_FILTER_ALL, _TAGS_FILTER_TB, _TAGS_FILTER_LIMITS,
            _TAGS_FILTER_SLAVE, _TAGS_FILTER_START, _TAGS_FILTER_PK,
            _TAGS_FILTER_CUSTOM,
        ])
        self._tags_filter.setFixedWidth(90)
        self._tags_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._tags_filter)

        lo.addSpacing(4)

        # Activity filter
        lo.addWidget(QLabel("Activity:"))
        self._activity_filter = QComboBox()
        self._activity_filter.addItems([
            _ACTIVITY_FILTER_ALL, _ACTIVITY_FILTER_ZERO, _ACTIVITY_FILTER_HAS,
        ])
        self._activity_filter.setFixedWidth(120)
        self._activity_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._activity_filter)

        lo.addSpacing(4)

        # Review only checkbox
        self._review_cb = QCheckBox("Review only")
        self._review_cb.setToolTip("Show only accounts flagged for review")
        self._review_cb.stateChanged.connect(self._apply_filter)
        lo.addWidget(self._review_cb)

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
        for col in (COL_USERNAME, COL_DEVICE, COL_TAGS, COL_DISCOVERED, COL_LAST_SEEN):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        for col in (COL_STATUS, COL_FOLLOW, COL_UNFOLLOW, COL_LIMIT,
                    COL_FOLLOW_TODAY, COL_LIKE_TODAY, COL_FOLLOW_LIM, COL_LIKE_LIM,
                    COL_REVIEW,
                    COL_DATA_DB, COL_SOURCES_TXT, COL_SRC_COUNT,
                    COL_FBR_QUALITY, COL_FBR_BEST, COL_FBR_DATE,
                    COL_ACTIONS):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(COL_USERNAME,     160)
        t.setColumnWidth(COL_DEVICE,       110)
        t.setColumnWidth(COL_STATUS,        68)
        t.setColumnWidth(COL_TAGS,         100)
        t.setColumnWidth(COL_FOLLOW,        52)
        t.setColumnWidth(COL_UNFOLLOW,      62)
        t.setColumnWidth(COL_LIMIT,         62)
        t.setColumnWidth(COL_FOLLOW_TODAY,  78)
        t.setColumnWidth(COL_LIKE_TODAY,    70)
        t.setColumnWidth(COL_FOLLOW_LIM,    56)
        t.setColumnWidth(COL_LIKE_LIM,      52)
        t.setColumnWidth(COL_REVIEW,        55)
        t.setColumnWidth(COL_DATA_DB,       56)
        t.setColumnWidth(COL_SOURCES_TXT,   76)
        t.setColumnWidth(COL_DISCOVERED,    90)
        t.setColumnWidth(COL_LAST_SEEN,     90)
        t.setColumnWidth(COL_SRC_COUNT,     70)
        t.setColumnWidth(COL_FBR_QUALITY,   82)
        t.setColumnWidth(COL_FBR_BEST,      70)
        t.setColumnWidth(COL_FBR_DATE,      80)
        t.setColumnWidth(COL_ACTIONS,      180)

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
        if self._session_service:
            self._session_map = self._session_service.get_session_map(
                date.today().isoformat()
            )
        # Load operator tags map
        if self._tag_repo:
            try:
                self._op_tags_map = self._tag_repo.get_operator_tags_map()
            except Exception:
                self._op_tags_map = {}
        # Build device status map for color dots
        try:
            rows = self._conn.execute(
                "SELECT device_id, last_known_status FROM oh_devices"
            ).fetchall()
            self._device_status_map = {r[0]: r[1] for r in rows}
        except Exception:
            self._device_status_map = {}
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
        for w in (self._status_filter, self._fbr_filter, self._device_filter,
                  self._search_box, self._show_orphans_cb,
                  self._tags_filter, self._activity_filter, self._review_cb):
            w.blockSignals(True)

        self._status_filter.setCurrentIndex(0)
        self._fbr_filter.setCurrentIndex(0)
        self._device_filter.setCurrentIndex(0)
        self._tags_filter.setCurrentIndex(0)
        self._activity_filter.setCurrentIndex(0)
        self._search_box.clear()
        self._show_orphans_cb.setChecked(False)
        self._review_cb.setChecked(False)

        for w in (self._status_filter, self._fbr_filter, self._device_filter,
                  self._search_box, self._show_orphans_cb,
                  self._tags_filter, self._activity_filter, self._review_cb):
            w.blockSignals(False)

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
        status_filt   = self._status_filter.currentText()
        fbr_filt      = self._fbr_filter.currentText()
        device_filt   = self._device_filter.currentText()
        tags_filt     = self._tags_filter.currentText()
        activity_filt = self._activity_filter.currentText()
        review_only   = self._review_cb.isChecked()
        query         = self._search_box.text().strip().lower()
        show_orphans  = self._show_orphans_cb.isChecked()

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

            # --- tags dimension ---
            if tags_filt != _TAGS_FILTER_ALL:
                raw = (acc.bot_tags_raw or "").upper()
                if tags_filt == _TAGS_FILTER_TB and "TB" not in raw:
                    continue
                elif tags_filt == _TAGS_FILTER_LIMITS and "[" not in raw:
                    continue
                elif tags_filt == _TAGS_FILTER_SLAVE and "SLAVE" not in raw:
                    continue
                elif tags_filt == _TAGS_FILTER_START and "START" not in raw:
                    continue
                elif tags_filt == _TAGS_FILTER_PK and " PK" not in raw and raw != "PK":
                    continue
                elif tags_filt == _TAGS_FILTER_CUSTOM:
                    # custom = has tags but none of the known keywords
                    known = {"SLAVE", "AI", "START", "PK"}
                    tokens = raw.split("]")[-1].split() if "]" in raw else raw.split()
                    if not any(t for t in tokens if t not in known and not t.startswith("TB")):
                        continue

            # --- review dimension ---
            if review_only and not acc.review_flag:
                continue

            # --- activity dimension ---
            if activity_filt != _ACTIVITY_FILTER_ALL and acc.id is not None:
                sess = self._session_map.get(acc.id)
                has_act = sess.has_activity if sess else False
                if activity_filt == _ACTIVITY_FILTER_ZERO and has_act:
                    continue
                if activity_filt == _ACTIVITY_FILTER_HAS and not has_act:
                    continue

            # --- text search ---
            if query:
                name_match   = query in acc.username.lower()
                device_match = bool(acc.device_name and query in acc.device_name.lower())
                tags_match   = bool(acc.bot_tags_raw and query in acc.bot_tags_raw.lower())
                if not name_match and not device_match and not tags_match:
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

        # Device column with status color dot prefix
        device_name = acc.device_name or acc.device_id
        dev_status = self._device_status_map.get(acc.device_id)
        if dev_status == "running":
            dot = "\u25cf "  # filled circle
            dot_color = C_YES    # green
        elif dev_status == "stop":
            dot = "\u25cf "
            dot_color = C_REMOVED  # gray
        else:
            dot = "\u25cf "
            dot_color = C_NO     # red — unknown/offline
        device_item = self._make_item(dot + device_name, dimmed=removed)
        if not removed:
            device_item.setForeground(dot_color)
        self._table.setItem(row, COL_DEVICE, device_item)

        self._table.setItem(row, COL_STATUS,      self._make_item(status_text, center, status_color))

        # Tags — combine bot tags + operator tags
        parts = []
        if acc.bot_tags_raw:
            parts.append(acc.bot_tags_raw)
        op_tags = self._op_tags_map.get(acc.id) if acc.id else None
        if op_tags:
            parts.append("OP:" + op_tags.replace(" | ", " OP:"))
        tags_text = " | ".join(parts) if parts else "\u2014"
        tags_color = C_WARN if op_tags else None  # amber highlight if operator tags exist
        self._table.setItem(row, COL_TAGS, self._make_item(
            tags_text, color=tags_color, dimmed=removed))

        self._table.setItem(row, COL_FOLLOW,      self._make_bool_item(acc.follow_enabled, dimmed=removed))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_bool_item(acc.unfollow_enabled, dimmed=removed))
        self._table.setItem(row, COL_LIMIT,       self._make_item(acc.limit_per_day or "—", center, dimmed=removed))

        # Session data columns
        sess = self._session_map.get(acc.id) if acc.id is not None else None
        follow_today = sess.follow_count if sess else 0
        like_today = sess.like_count if sess else 0

        # Follow Today — red if 0 in active slot with follow enabled
        ft_color = None
        if not removed and acc.follow_enabled and follow_today == 0 and sess is not None:
            ft_color = C_NO
        elif follow_today > 0:
            ft_color = C_YES
        ft_item = _SortableItem(str(follow_today) if sess else "—", follow_today if sess else -1)
        ft_item.setTextAlignment(center)
        if removed:
            ft_item.setForeground(C_REMOVED)
        elif ft_color:
            ft_item.setForeground(ft_color)
        self._table.setItem(row, COL_FOLLOW_TODAY, ft_item)

        # Like Today — neutral rendering (no red for 0 — we can't distinguish
        # accounts without like flow enabled from those that failed)
        lt_color = C_YES if like_today > 0 else None
        lt_item = _SortableItem(str(like_today) if sess else "—", like_today if sess else -1)
        lt_item.setTextAlignment(center)
        if removed:
            lt_item.setForeground(C_REMOVED)
        elif lt_color:
            lt_item.setForeground(lt_color)
        self._table.setItem(row, COL_LIKE_TODAY, lt_item)

        # Follow Limit / Like Limit
        self._table.setItem(row, COL_FOLLOW_LIM, self._make_item(
            acc.follow_limit_perday or "—", center, dimmed=removed))
        self._table.setItem(row, COL_LIKE_LIM, self._make_item(
            acc.like_limit_perday or "—", center, dimmed=removed))

        # Review flag
        review_text = "!" if acc.review_flag else ""
        review_color = C_WARN if acc.review_flag else None
        self._table.setItem(row, COL_REVIEW, self._make_item(
            review_text, center, review_color, dimmed=removed))

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

        act_btn = QPushButton("\u2026")  # "…"
        act_btn.setFixedHeight(24)
        act_btn.setFixedWidth(32)
        act_btn.setEnabled(not removed and self._operator_action_service is not None)
        act_btn.setToolTip("Operator actions")
        act_btn.clicked.connect(lambda _, a=acc, b=act_btn: self._show_action_menu(a, b))

        self._table.setCellWidget(row, COL_ACTIONS, self._wrap_btns(open_btn, src_btn, act_btn))

    def _fill_orphan_row(self, row: int, disc: DiscoveredAccount) -> None:
        center = Qt.AlignmentFlag.AlignCenter

        self._table.setItem(row, COL_USERNAME,    self._make_item(disc.username))
        self._table.setItem(row, COL_DEVICE,      self._make_item(disc.device_name))
        self._table.setItem(row, COL_STATUS,      self._make_item("Orphan", center, C_ORPHAN))
        self._table.setItem(row, COL_TAGS,        self._make_item(disc.bot_tags_raw or "—", center))
        self._table.setItem(row, COL_FOLLOW,      self._make_item("—", center))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_item("—", center))
        self._table.setItem(row, COL_LIMIT,       self._make_item("—", center))
        self._table.setItem(row, COL_FOLLOW_TODAY, self._make_item("—", center))
        self._table.setItem(row, COL_LIKE_TODAY,   self._make_item("—", center))
        self._table.setItem(row, COL_FOLLOW_LIM,   self._make_item("—", center))
        self._table.setItem(row, COL_LIKE_LIM,     self._make_item("—", center))
        self._table.setItem(row, COL_REVIEW,       self._make_item("", center))
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
        self._refresh_table()

        active = sum(1 for a in self._all_accounts if a.is_active)
        n_crit = 0
        if self._recommendation_service:
            try:
                recs = self._generate_recommendations()
                n_crit = sum(1 for r in recs if r.severity == "CRITICAL")
            except Exception:
                pass

        parts = [
            f"Sync complete: {active} accounts",
            f"+{sync_run.accounts_added}" if sync_run.accounts_added else None,
            f"-{sync_run.accounts_removed}" if sync_run.accounts_removed else None,
            f"~{sync_run.accounts_updated}" if sync_run.accounts_updated else None,
        ]
        msg = ",  ".join(p for p in parts if p)
        if n_crit:
            msg += f"  \u2014  {n_crit} CRITICAL \u2014 Open Cockpit to review"
        else:
            msg += "  \u2014  Ready"
        self._set_status(msg)

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

        # Build the delete callback for single-account deletion
        def _handle_account_delete(src_name: str):
            from oh.ui.delete_confirm_dialog import DeleteConfirmDialog
            short_device = device_id[:10] + "..." if len(device_id) > 10 else device_id
            dlg = DeleteConfirmDialog.for_single_account(
                src_name, username, short_device, parent=self
            )
            if dlg.exec() != DeleteConfirmDialog.DialogCode.Accepted:
                return None
            return self._source_delete_service.delete_source_for_account(
                src_name, account_id, device_id, username,
                short_device, bot_root
            )

        on_delete = _handle_account_delete if account_id is not None else None

        # Build cleanup callback for batch non-quality removal
        def _handle_account_cleanup():
            if account_id is None:
                return None
            return self._handle_rec_clean_account(account_id)

        on_cleanup = _handle_account_cleanup if account_id is not None else None

        self._set_status("Ready.")
        dlg = SourceDialog(
            inspection, fbr_result, usage_result,
            on_delete=on_delete, on_cleanup=on_cleanup, parent=self,
        )
        dlg.exec()

        # Repopulate table so updated FBR cells are visible immediately
        self._apply_filter()

    # ------------------------------------------------------------------
    # User actions — session report
    # ------------------------------------------------------------------

    def _on_cockpit(self) -> None:
        from oh.ui.cockpit_dialog import CockpitDialog
        data = self._gather_cockpit_data()
        if data is None:
            return
        accounts, recs, review, deletions, actions = data
        dlg = CockpitDialog(
            accounts=accounts,
            recommendations=recs,
            review_accounts=review,
            recent_deletions=deletions,
            recent_actions=actions,
            operator_action_service=self._operator_action_service,
            on_navigate_account=self._focus_account,
            on_navigate_source=self._focus_source,
            on_open_session_report=self._on_session_report,
            on_open_recommendations=self._on_recommendations,
            on_open_delete_history=self._open_delete_history,
            on_open_action_history=self._on_action_history,
            on_refresh=self._gather_cockpit_data,
            parent=self,
        )
        dlg.exec()

    def _gather_cockpit_data(self):
        """Collect all data needed for the cockpit dialog."""
        from datetime import date as _date
        recs = self._generate_recommendations() if self._recommendation_service else []
        review = self._accounts.get_flagged_for_review()
        deletions = (
            self._source_delete_service.history_repo.get_recent_actions(10)
        )
        today_str = _date.today().isoformat()
        all_actions = (
            self._operator_action_repo.get_recent(50)
            if self._operator_action_repo else []
        )
        today_actions = [
            a for a in all_actions
            if a.performed_at and a.performed_at[:10] == today_str
        ][:20]
        return (self._all_accounts, recs, review, deletions, today_actions)

    def _on_recommendations(self) -> None:
        if not self._recommendation_service:
            return
        from oh.ui.recommendations_dialog import RecommendationsDialog
        recs = self._generate_recommendations()
        dlg = RecommendationsDialog(
            recommendations=recs,
            operator_action_service=self._operator_action_service,
            on_refresh=self._generate_recommendations,
            on_navigate_account=self._focus_account,
            on_navigate_source=self._focus_source,
            on_delete_source=self._handle_rec_delete_source,
            on_clean_account=self._handle_rec_clean_account,
            on_open_history=self._open_delete_history,
            parent=self,
        )
        dlg.exec()
        self._refresh_table()

    def _handle_rec_delete_source(self, source_name):
        """Callback: delete a source globally from RecommendationsDialog."""
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return None
        from oh.ui.delete_confirm_dialog import DeleteConfirmDialog
        assignments = self._source_delete_service.get_active_assignments_for_source(
            source_name
        )
        if not assignments:
            return None
        dlg = DeleteConfirmDialog.for_single(source_name, assignments, parent=self)
        if dlg.exec() != DeleteConfirmDialog.DialogCode.Accepted:
            return None
        result = self._source_delete_service.delete_source_globally(
            source_name, bot_root
        )
        self._refresh_after_source_op()
        return result

    def _handle_rec_clean_account(self, account_id):
        """Callback: clean non-quality sources for one account."""
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return None
        candidates = self._source_delete_service.preview_account_cleanup(
            account_id
        )
        if not candidates:
            QMessageBox.information(
                self, "No Candidates",
                "No non-quality sources found.\n"
                "Run Analyze FBR first if data is missing.",
            )
            return None
        acc = self._accounts.get_by_id(account_id)
        if not acc:
            return None
        src_count = self._source_count_map.get(account_id, 0)
        from oh.ui.delete_confirm_dialog import DeleteConfirmDialog
        dlg = DeleteConfirmDialog.for_account_cleanup(
            acc.username,
            acc.device_name or acc.device_id,
            candidates,
            total_active=src_count,
            parent=self,
        )
        if dlg.exec() != DeleteConfirmDialog.DialogCode.Accepted:
            return None
        selected = dlg.selected_sources
        if not selected:
            return None
        result = self._source_delete_service.delete_sources_for_account(
            source_names=[s.source_name for s in selected],
            account_id=account_id,
            device_id=acc.device_id,
            username=acc.username,
            device_name=acc.device_name or acc.device_id,
            bot_root=bot_root,
        )
        self._refresh_after_source_op()
        return result

    def _refresh_after_source_op(self) -> None:
        """Refresh accounts table + source counts after any source operation."""
        self._source_count_map = self._global_sources_service.get_active_source_counts()
        self._all_accounts = self._accounts.get_all()
        self._apply_filter()

    def _open_delete_history(self) -> None:
        """Switch to Sources tab and open Delete History dialog."""
        self._tabs.setCurrentIndex(1)
        self._sources_tab.set_bot_root(self._settings.get_bot_root())
        self._sources_tab.load_data()
        self._sources_tab._on_show_history()

    def _focus_account(self, account_id: int) -> None:
        """Navigate to an account row in the Accounts tab."""
        self._tabs.setCurrentIndex(0)  # Switch to Accounts tab
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_USERNAME)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data[0] == "account" and data[1] == account_id:
                    self._table.selectRow(row)
                    self._table.scrollToItem(item)
                    return

    def _focus_source(self, source_name: str) -> None:
        """Navigate to the Sources tab and filter by source name."""
        self._tabs.setCurrentIndex(1)  # Switch to Sources tab
        self._sources_tab.set_bot_root(self._settings.get_bot_root())
        self._sources_tab.load_data()
        # Set the search filter to the source name
        if hasattr(self._sources_tab, '_search_box'):
            self._sources_tab._search_box.setText(source_name)

    def _generate_recommendations(self) -> list:
        """Generate recommendations from current in-memory data."""
        return self._recommendation_service.generate(
            session_map=self._session_map,
            fbr_map=self._fbr_map,
            device_status_map=self._device_status_map,
            op_tags_map=self._op_tags_map,
        )

    def _on_action_history(self) -> None:
        if not self._operator_action_repo:
            return
        from oh.ui.operator_action_history_dialog import OperatorActionHistoryDialog
        dlg = OperatorActionHistoryDialog(
            action_repo=self._operator_action_repo,
            parent=self,
        )
        dlg.exec()

    def _on_session_report(self) -> None:
        from oh.ui.session_report_dialog import SessionReportDialog
        dlg = SessionReportDialog(
            accounts=self._all_accounts,
            session_map=self._session_map,
            fbr_map=self._fbr_map,
            device_status_map=self._device_status_map,
            operator_action_service=self._operator_action_service,
            parent=self,
        )
        dlg.exec()
        # Refresh table in case report actions changed data
        self._refresh_table()

    # ------------------------------------------------------------------
    # User actions — operator action menu (per-account)
    # ------------------------------------------------------------------

    def _show_action_menu(self, acc: AccountRecord, btn: QPushButton) -> None:
        """Show a popup menu of operator actions for this account."""
        svc = self._operator_action_service
        if not svc:
            return

        menu = QMenu(self)

        if acc.review_flag:
            menu.addAction("Clear Review", lambda: self._do_clear_review(acc))
        else:
            menu.addAction("Set Review", lambda: self._do_set_review(acc))

        menu.addSeparator()
        menu.addAction("TB +1", lambda: self._do_tb_increment(acc))
        menu.addAction("Limits +1", lambda: self._do_limits_increment(acc))

        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _do_set_review(self, acc: AccountRecord) -> None:
        note, ok = QInputDialog.getText(
            self, "Set Review", f"Note for {acc.username} (optional):"
        )
        if not ok:
            return
        result = self._operator_action_service.set_review(acc.id, note or None)
        self._set_status(f"Review set: {acc.username}")
        self._refresh_table()

    def _do_clear_review(self, acc: AccountRecord) -> None:
        result = self._operator_action_service.clear_review(acc.id)
        self._set_status(f"Review cleared: {acc.username}")
        self._refresh_table()

    def _do_tb_increment(self, acc: AccountRecord) -> None:
        reply = QMessageBox.question(
            self, "Confirm TB +1",
            f"Increment TB level for {acc.username}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._operator_action_service.increment_tb(acc.id)
        if result == "tb5_max":
            QMessageBox.warning(
                self, "TB5 Max",
                f"{acc.username}: TB5 reached \u2014 konto wymaga przeniesienia na inne urz\u0105dzenie.",
            )
            self._set_status(f"{acc.username}: TB5 max \u2014 przeniesienie wymagane")
        else:
            self._set_status(f"{acc.username}: \u2192 {result}")
        self._refresh_table()

    def _do_limits_increment(self, acc: AccountRecord) -> None:
        reply = QMessageBox.question(
            self, "Confirm Limits +1",
            f"Increment limits level for {acc.username}?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        result = self._operator_action_service.increment_limits(acc.id)
        if result == "limits5_max":
            QMessageBox.warning(
                self, "Limits 5 Max",
                f"{acc.username}: limits 5 reached \u2014 rozwa\u017c wymian\u0119 \u017ar\u00f3de\u0142.",
            )
            self._set_status(f"{acc.username}: limits 5 max \u2014 wymiana \u017ar\u00f3de\u0142")
        else:
            self._set_status(f"{acc.username}: \u2192 {result}")
        self._refresh_table()

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
