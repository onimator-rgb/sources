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
from __future__ import annotations

import os
import subprocess
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QComboBox, QTabWidget, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QMessageBox, QMenu, QInputDialog, QSizePolicy,
    QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPixmap, QKeyEvent

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
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.sync_repo import SyncRepository
from oh.services.account_health_service import AccountHealthService
from oh.services.fbr_service import FBRService
from oh.services.global_sources_service import GlobalSourcesService
from oh.services.scan_service import ScanService
from oh.services.session_service import SessionService
from oh.services.operator_action_service import OperatorActionService
from oh.services.recommendation_service import RecommendationService
from oh.services.source_delete_service import SourceDeleteService
from oh.services.target_splitter_service import TargetSplitterService
from oh.resources import asset_path, asset_exists
from oh.ui.account_detail_panel import AccountDetailPanel
from oh.ui.device_fleet_tab import DeviceFleetTab
from oh.ui.notifications_tab import NotificationsTab
from oh.services.notification_service import NotificationService
from oh.ui.settings_tab import SettingsTab
from oh.ui.source_dialog import SourceDialog
from oh.ui.source_profiles_tab import SourceProfilesTab
from oh.ui.sources_tab import SourcesTab
from oh.ui.like_sources_tab import LikeSourcesTab
from oh.ui.sources_tab_container import SourcesTabContainer
from oh.ui.help_button import HelpButton
from oh.ui.workers import WorkerThread
from oh.repositories.source_profile_repo import SourceProfileRepository
from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
from oh.repositories.like_source_assignment_repo import LikeSourceAssignmentRepository
from oh.services.global_like_sources_service import GlobalLikeSourcesService
from oh.services.lbr_service import LBRService
from oh.services.settings_copier_service import SettingsCopierService
from oh.services.warmup_template_service import WarmupTemplateService
from oh.ui.table_utils import SortableItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table column indexes
# ---------------------------------------------------------------------------

COL_TIMESLOT    = 0   # slot number 1-4 (derived from working hours)
COL_USERNAME    = 1
COL_DEVICE      = 2
COL_HOURS       = 3   # working hours (start_time - end_time)
COL_STATUS      = 4
COL_TAGS        = 5
COL_FOLLOW      = 6
COL_UNFOLLOW    = 7
COL_LIMIT       = 8
COL_FOLLOW_TODAY = 9
COL_LIKE_TODAY   = 10
COL_FOLLOW_LIM   = 11
COL_LIKE_LIM     = 12
COL_REVIEW       = 13
COL_DATA_DB     = 14
COL_SOURCES_TXT = 15
COL_DISCOVERED  = 16
COL_LAST_SEEN   = 17
COL_SRC_COUNT   = 18   # active source count — from source_assignments
COL_FBR_QUALITY = 19   # "3/12" quality/total — from latest snapshot
COL_FBR_BEST    = 20   # best FBR % — from latest snapshot
COL_FBR_DATE    = 21   # date of last FBR analysis
COL_HEALTH      = 22   # composite health score (0-100)
COL_TREND       = 23   # sparkline trend
COL_BLOCK       = 24   # block/ban indicator
COL_GROUP       = 25   # account group name(s)
COL_ACTIONS     = 26

COLUMN_HEADERS = [
    "Slot", "Username", "Device", "Hours", "Status", "Tags",
    "Fol", "Unf", "Lmt/D",
    "Fol Today", "Like Today", "F.Lmt", "L.Lmt", "Rev",
    "Data D", "Sources.tx",
    "Discovered", "Last Seen",
    "Actve Src",
    "Qlty/Tot", "Best FBR%", "Last FBR",
    "Health", "Trend", "Block", "Group",
    "Actions",
]

# ---------------------------------------------------------------------------
# Semantic palette — resolved at render time via sc()
# ---------------------------------------------------------------------------

from oh.ui.style import sc

def C_ACTIVE():   return sc("success")
def C_REMOVED():  return sc("dimmed")
def C_YES():      return sc("yes")
def C_NO():       return sc("no")
def C_WARN():     return sc("warning")
def C_ORPHAN():   return sc("orphan")
def C_QUALITY():  return sc("success")
def C_LOW_FBR():  return sc("muted")
def C_ERROR():    return sc("error")
def C_NEVER():    return sc("warning")



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
_ACTIVITY_FILTER_BLOCKED  = "Blocked"

_TIMESLOT_FILTER_ALL = "All slots"
_TIMESLOT_FILTER_1   = "Slot 1 (0-6)"
_TIMESLOT_FILTER_2   = "Slot 2 (6-12)"
_TIMESLOT_FILTER_3   = "Slot 3 (12-18)"
_TIMESLOT_FILTER_4   = "Slot 4 (18-24)"

_HEALTH_FILTER_ALL    = "All health"
_HEALTH_FILTER_GREEN  = "Green (70+)"
_HEALTH_FILTER_YELLOW = "Yellow (40-69)"
_HEALTH_FILTER_RED    = "Red (<40)"


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
        source_finder_service=None,
        bulk_discovery_service=None,
        account_detail_service=None,
        blacklist_repo=None,
        error_report_service=None,
        block_detection_service=None,
        account_group_service=None,
        account_group_repo=None,
        trend_service=None,
        auto_fix_service=None,
        settings_copier_service: Optional[SettingsCopierService] = None,
        warmup_template_service: Optional[WarmupTemplateService] = None,
    ) -> None:
        super().__init__()
        self._warmup_template_service = warmup_template_service
        self._settings_copier_service = settings_copier_service
        self._auto_fix_service        = auto_fix_service
        self._error_report_service    = error_report_service
        self._block_detection_service = block_detection_service
        self._account_group_service   = account_group_service
        self._account_group_repo      = account_group_repo
        self._trend_service           = trend_service
        self._blacklist_repo          = blacklist_repo
        self._account_detail_service  = account_detail_service
        self._scan_service            = scan_service
        self._fbr_service             = fbr_service
        self._global_sources_service  = global_sources_service
        self._source_delete_service   = source_delete_service
        self._session_service         = session_service
        self._operator_action_service = operator_action_service
        self._operator_action_repo    = operator_action_repo
        self._tag_repo                = tag_repo
        self._recommendation_service  = recommendation_service
        self._source_finder_service   = source_finder_service
        self._bulk_discovery_service  = bulk_discovery_service
        self._settings                = SettingsRepository(conn)
        self._accounts                = AccountRepository(conn)
        self._sync_repo               = SyncRepository(conn)

        self._conn                    = conn
        self._worker: Optional[WorkerThread] = None
        self._all_accounts: list = []
        self._last_discovery: list = []
        self._fbr_map: dict[int, FBRSnapshotRecord] = {}
        self._lbr_map: dict = {}  # account_id → LBRSnapshotRecord
        self._source_count_map: dict[int, int] = {}
        self._session_map: dict[int, AccountSessionRecord] = {}
        self._device_status_map: dict[str, str] = {}  # device_id → last_known_status
        self._op_tags_map: dict[int, str] = {}  # account_id → "TB3 | limits 2"
        self._block_map: dict = {}  # account_id → [BlockEvent]
        self._group_map: dict = {}  # account_id → [AccountGroup]
        self._trend_map: dict = {}  # account_id → AccountTrends

        # Debounce timer for arrow-key navigation in the detail drawer
        self._detail_debounce_timer: Optional[QTimer] = None

        self.setWindowTitle("OH — Operational Hub")
        self.setMinimumSize(1100, 650)

        self._target_splitter_service = TargetSplitterService(
            assignment_repo=SourceAssignmentRepository(conn),
            operator_action_repo=operator_action_repo,
            account_repo=self._accounts,
        )

        self._sources_tab  = SourcesTab(
            global_sources_service, source_delete_service,
            bulk_discovery_service=self._bulk_discovery_service,
            settings_repo=self._settings,
            conn=conn,
            target_splitter_service=self._target_splitter_service,
            account_group_repo=self._account_group_repo,
        )

        # LBR repos + services
        self._lbr_snapshot_repo = LBRSnapshotRepository(conn)
        self._like_assignment_repo = LikeSourceAssignmentRepository(conn)
        self._global_like_sources_service = GlobalLikeSourcesService(
            self._lbr_snapshot_repo,
            self._like_assignment_repo,
            self._accounts,
        )
        self._lbr_service = LBRService(
            self._lbr_snapshot_repo,
            self._accounts,
            self._settings,
            self._like_assignment_repo,
        )
        self._like_sources_tab = LikeSourcesTab(
            self._global_like_sources_service,
            self._lbr_service,
            settings_repo=self._settings,
            conn=conn,
        )
        self._sources_container = SourcesTabContainer(
            self._sources_tab, self._like_sources_tab,
        )

        self._settings_tab = SettingsTab(
            self._settings,
            source_finder_service=self._source_finder_service,
            blacklist_repo=self._blacklist_repo,
        )
        self._source_profile_repo = SourceProfileRepository(conn)
        self._source_profiles_tab = SourceProfilesTab(self._source_profile_repo)
        self._fleet_tab = DeviceFleetTab(conn)
        self._notification_service = NotificationService(conn)
        self._notifications_tab = NotificationsTab(self._notification_service)
        self._build_ui()
        self._refresh_table()
        self._update_last_sync_label()

        # Auto-scan timer
        self._auto_scan_timer = QTimer(self)
        self._auto_scan_timer.timeout.connect(self._on_auto_scan)
        self._setup_auto_scan()

        # Reconfigure auto-scan when settings are saved
        self._settings_tab.settings_saved.connect(self._setup_auto_scan)

        # Check for updates after 3 second delay (don't block startup)
        QTimer.singleShot(3000, self._check_for_updates)

        # Onboarding + What's New (after 500ms to let window render)
        QTimer.singleShot(500, self._show_startup_dialogs)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        outer = QVBoxLayout(root)
        outer.setSpacing(8)
        outer.setContentsMargins(12, 10, 12, 8)

        # Brand bar + settings bar sit above the tabs
        outer.addWidget(self._make_brand_bar())
        outer.addWidget(self._make_settings_bar())

        self._tabs = QTabWidget()
        self._tabs.setObjectName("tabWidget")
        self._tabs.addTab(self._make_accounts_page(), "Accounts")
        self._tabs.addTab(self._sources_container, "Sources")
        self._tabs.addTab(self._source_profiles_tab, "Source Profiles")
        self._tabs.addTab(self._fleet_tab, "Fleet")
        self._tabs.addTab(self._notifications_tab, "Notifications")
        self._tabs.addTab(self._settings_tab, "Settings")
        self._tabs.currentChanged.connect(self._on_tab_changed)
        outer.addWidget(self._tabs, stretch=1)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._set_status("Ready.")

    def _make_accounts_page(self) -> QWidget:
        """Wrap the existing toolbar + filter bar + table into the Accounts tab.

        The table area is placed inside a QSplitter (horizontal) so that the
        AccountDetailPanel can be shown/hidden on the right side.
        """
        page = QWidget()
        page_lo = QVBoxLayout(page)
        page_lo.setContentsMargins(0, 6, 0, 0)
        page_lo.setSpacing(6)
        page_lo.addWidget(self._make_toolbar())
        page_lo.addWidget(self._make_filter_bar())
        page_lo.addWidget(self._make_bulk_bar())

        # Build splitter: left = table, right = detail panel (hidden initially)
        self._accounts_splitter = QSplitter(Qt.Orientation.Horizontal)

        table_widget = self._make_table()
        self._accounts_splitter.addWidget(table_widget)

        self._detail_panel = AccountDetailPanel(service=self._account_detail_service)
        self._detail_panel.setVisible(False)
        self._detail_panel.close_requested.connect(self._close_detail_panel)
        self._detail_panel.action_requested.connect(self._on_detail_action_requested)
        self._accounts_splitter.addWidget(self._detail_panel)

        # Give the table most of the space; panel gets the rest
        self._accounts_splitter.setStretchFactor(0, 3)
        self._accounts_splitter.setStretchFactor(1, 1)

        # Connect single-click to open detail panel
        self._table.clicked.connect(self._on_account_selected)

        # Connect selection model for debounced drawer updates on arrow keys
        self._table.selectionModel().currentRowChanged.connect(
            self._on_table_row_changed
        )
        self._table.selectionModel().selectionChanged.connect(
            lambda: self._update_bulk_bar()
        )

        page_lo.addWidget(self._accounts_splitter, stretch=1)
        return page

    def _on_tab_changed(self, index: int) -> None:
        if index == 1:  # Sources tab (container with Follow + Like sub-tabs)
            self._sources_container.set_bot_root(self._settings.get_bot_root())
            self._sources_container.load_data()
        elif index == 2:  # Source Profiles tab
            self._source_profiles_tab.load_data()
        elif index == 3:  # Fleet tab
            if not self._fleet_tab._loaded:
                self._fleet_tab.load_data()
        elif index == 4:  # Notifications tab
            self._notifications_tab.set_bot_root(self._settings.get_bot_root())
            if not self._notifications_tab._loaded:
                self._notifications_tab.load_data()
        elif index == 5:  # Settings tab — reload in case values changed externally
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
        _sec = sc("text_secondary").name()
        _hdg = sc("heading").name()
        title_lbl = QLabel(f"Wizzysocial  <span style='color:{_sec};font-size:9px;'>&middot; OH Operational Hub</span>")
        title_lbl.setTextFormat(Qt.TextFormat.RichText)
        title_lbl.setStyleSheet(f"color: {_hdg}; font-size: 12px; font-weight: 600;")

        lo.addWidget(logo_lbl)
        lo.addWidget(title_lbl)
        lo.addStretch()

        # Brand bar button style
        from oh.ui.style import sc as _sc
        _brand_btn_style = (
            f"QPushButton {{ font-size: 10px; padding: 2px 10px; "
            f"border: 1px solid {_sc('border').name()}; border-radius: 3px; "
            f"color: {_sc('text_secondary').name()}; background: transparent; }}"
            f"QPushButton:hover {{ background: {_sc('bg_note').name()}; "
            f"color: {_sc('text').name()}; }}"
        )

        # Take a Tour button
        tour_btn = QPushButton("Take a Tour")
        tour_btn.setFixedHeight(22)
        tour_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tour_btn.setStyleSheet(_brand_btn_style)
        tour_btn.clicked.connect(self._start_guided_tour)
        lo.addWidget(tour_btn)

        # Check for Updates button
        update_btn = QPushButton("Check for Updates")
        update_btn.setObjectName("checkUpdatesBtn")
        update_btn.setFixedHeight(22)
        update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        update_btn.setStyleSheet(_brand_btn_style)
        update_btn.clicked.connect(self._on_check_for_updates_manual)
        lo.addWidget(update_btn)

        try:
            from oh.version import BUILD_VERSION
            ver_text = f"build {BUILD_VERSION}"
        except ImportError:
            ver_text = "dev"
        ver_lbl = QLabel(ver_text)
        ver_lbl.setStyleSheet(f"color: {sc('muted').name()}; font-size: 9px;")
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
        lo.setContentsMargins(0, 4, 0, 4)
        lo.setSpacing(6)

        _btn_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._scan_btn = QPushButton("Scan && Sync")
        self._scan_btn.setObjectName("scanBtn")
        self._scan_btn.setFixedHeight(34)
        self._scan_btn.setSizePolicy(_btn_policy)
        self._scan_btn.setToolTip(
            "Discover accounts from the Onimator folder and sync with the OH registry"
        )
        self._scan_btn.clicked.connect(self._on_scan_and_sync)

        self._fbr_btn = QPushButton("Analyze FBR")
        self._fbr_btn.setFixedHeight(34)
        self._fbr_btn.setSizePolicy(_btn_policy)
        self._fbr_btn.setToolTip(
            "Run FBR analysis for all active accounts that have data.db\n"
            "and save results to the OH database"
        )
        self._fbr_btn.clicked.connect(self._on_analyze_fbr)

        self._lbr_btn = QPushButton("Analyze LBR")
        self._lbr_btn.setFixedHeight(34)
        self._lbr_btn.setSizePolicy(_btn_policy)
        self._lbr_btn.setToolTip(
            "Run LBR (Like-Back Rate) analysis for all active accounts\n"
            "that have likes.db and save results to the OH database"
        )
        self._lbr_btn.clicked.connect(self._on_analyze_lbr)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(34)
        refresh_btn.setSizePolicy(_btn_policy)
        refresh_btn.setToolTip("Reload the account list from the OH database (no scan)")
        refresh_btn.clicked.connect(self._refresh_table)

        self._report_btn = QPushButton("Session")
        self._report_btn.setFixedHeight(34)
        self._report_btn.setSizePolicy(_btn_policy)
        self._report_btn.setToolTip("Open session report for today")
        self._report_btn.clicked.connect(self._on_session_report)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet(f"font-style: italic; color: {sc('text_secondary').name()};")

        self._last_sync_label = QLabel("")
        self._last_sync_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._last_sync_label.setStyleSheet(f"color: {sc('muted').name()}; font-size: 11px;")

        self._cockpit_btn = QPushButton("Cockpit")
        self._cockpit_btn.setObjectName("cockpitBtn")
        self._cockpit_btn.setFixedHeight(34)
        self._cockpit_btn.setSizePolicy(_btn_policy)
        self._cockpit_btn.setToolTip("Daily operations overview")
        self._cockpit_btn.clicked.connect(self._on_cockpit)

        self._history_btn = QPushButton("History")
        self._history_btn.setFixedHeight(34)
        self._history_btn.setSizePolicy(_btn_policy)
        self._history_btn.setToolTip("Show recent operator actions")
        self._history_btn.clicked.connect(self._on_action_history)

        self._recs_btn = QPushButton("Recs")
        self._recs_btn.setFixedHeight(34)
        self._recs_btn.setSizePolicy(_btn_policy)
        self._recs_btn.setToolTip("Generate and view operational recommendations")
        self._recs_btn.clicked.connect(self._on_recommendations)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(34)
        self._export_btn.setSizePolicy(_btn_policy)
        self._export_btn.setToolTip("Export visible accounts to CSV file")
        self._export_btn.clicked.connect(self._on_export_csv)

        self._groups_btn = QPushButton("Groups")
        self._groups_btn.setFixedHeight(34)
        self._groups_btn.setSizePolicy(_btn_policy)
        self._groups_btn.setToolTip("Manage account groups (clients, campaigns)")
        self._groups_btn.clicked.connect(self._on_manage_groups)

        self._report_problem_btn = QPushButton("Report Problem")
        self._report_problem_btn.setFixedHeight(34)
        self._report_problem_btn.setSizePolicy(_btn_policy)
        self._report_problem_btn.setToolTip("Send an anonymous problem report to the developer")
        self._report_problem_btn.clicked.connect(self._on_report_problem)

        lo.addWidget(self._cockpit_btn)
        lo.addWidget(HelpButton(
            "Daily operations overview. Open at the start of each shift "
            "to see what needs attention.",
        ))
        lo.addWidget(self._scan_btn)
        lo.addWidget(self._fbr_btn)
        lo.addWidget(self._lbr_btn)
        lo.addWidget(HelpButton(
            "FBR = Follow-Back Rate (from follow sources).\n"
            "LBR = Like-Back Rate (from like sources).\n"
            "Shows which sources bring followers back.",
        ))
        lo.addWidget(refresh_btn)
        lo.addWidget(self._report_btn)
        lo.addWidget(HelpButton(
            "Detailed analysis of today's bot activity across all accounts.",
        ))
        lo.addWidget(self._recs_btn)
        lo.addWidget(HelpButton(
            "Automated recommendations sorted by priority. Reviews weak "
            "sources, inactive accounts, and more.",
        ))
        lo.addWidget(self._history_btn)
        lo.addWidget(self._export_btn)
        lo.addWidget(self._groups_btn)
        lo.addSpacing(12)
        lo.addWidget(self._busy_label, stretch=1)
        lo.addWidget(self._report_problem_btn)
        lo.addWidget(self._last_sync_label)

        # Apply initial help button visibility
        show_tips = (self._settings.get("show_help_tips") or "1") == "1"
        if not show_tips:
            HelpButton.set_all_visible(False)

        return w

    def _make_filter_bar(self) -> QWidget:
        w = QWidget()
        w.setObjectName("filterBar")
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 4, 0, 4)
        lo.setSpacing(4)

        # Status filter
        lo.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems([
            _STATUS_FILTER_ACTIVE,
            _STATUS_FILTER_REMOVED,
            _STATUS_FILTER_ALL,
        ])
        self._status_filter.setMinimumWidth(80)
        self._status_filter.setMaximumWidth(130)
        self._status_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._status_filter)

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
        self._fbr_filter.setMinimumWidth(100)
        self._fbr_filter.setMaximumWidth(170)
        self._fbr_filter.setToolTip(
            "Needs attention = never analyzed or zero quality sources"
        )
        self._fbr_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._fbr_filter)

        # Device filter
        lo.addWidget(QLabel("Device:"))
        self._device_filter = QComboBox()
        self._device_filter.setMinimumWidth(80)
        self._device_filter.setMaximumWidth(150)
        self._device_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._device_filter)

        # Text search
        lo.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("username or device…")
        self._search_box.setMinimumWidth(100)
        self._search_box.setMaximumWidth(250)
        self._search_box.textChanged.connect(self._apply_filter)
        lo.addWidget(self._search_box)

        # Tags filter
        lo.addWidget(QLabel("Tags:"))
        self._tags_filter = QComboBox()
        self._tags_filter.addItems([
            _TAGS_FILTER_ALL, _TAGS_FILTER_TB, _TAGS_FILTER_LIMITS,
            _TAGS_FILTER_SLAVE, _TAGS_FILTER_START, _TAGS_FILTER_PK,
            _TAGS_FILTER_CUSTOM,
        ])
        self._tags_filter.setMinimumWidth(70)
        self._tags_filter.setMaximumWidth(110)
        self._tags_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._tags_filter)

        # Activity filter
        lo.addWidget(QLabel("Activity:"))
        self._activity_filter = QComboBox()
        self._activity_filter.addItems([
            _ACTIVITY_FILTER_ALL, _ACTIVITY_FILTER_ZERO, _ACTIVITY_FILTER_HAS,
            _ACTIVITY_FILTER_BLOCKED,
        ])
        self._activity_filter.setMinimumWidth(80)
        self._activity_filter.setMaximumWidth(140)
        self._activity_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._activity_filter)

        # Timeslot filter
        lo.addWidget(QLabel("Slot:"))
        self._timeslot_filter = QComboBox()
        self._timeslot_filter.addItems([
            _TIMESLOT_FILTER_ALL, _TIMESLOT_FILTER_1,
            _TIMESLOT_FILTER_2, _TIMESLOT_FILTER_3, _TIMESLOT_FILTER_4,
        ])
        self._timeslot_filter.setMinimumWidth(70)
        self._timeslot_filter.setMaximumWidth(120)
        self._timeslot_filter.setToolTip("Filter by timeslot (derived from working hours)")
        self._timeslot_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._timeslot_filter)

        # Health filter
        lo.addWidget(QLabel("Health:"))
        self._health_filter = QComboBox()
        self._health_filter.addItems([
            _HEALTH_FILTER_ALL, _HEALTH_FILTER_GREEN,
            _HEALTH_FILTER_YELLOW, _HEALTH_FILTER_RED,
        ])
        self._health_filter.setMinimumWidth(70)
        self._health_filter.setMaximumWidth(120)
        self._health_filter.setToolTip("Filter by health score color band")
        self._health_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._health_filter)

        # Group filter
        lo.addWidget(QLabel("Group:"))
        self._group_filter = QComboBox()
        self._group_filter.addItem("All groups")
        self._group_filter.setMinimumWidth(80)
        self._group_filter.setMaximumWidth(140)
        self._group_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._group_filter)

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
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(28)
        clear_btn.setToolTip("Reset all filters to defaults")
        clear_btn.clicked.connect(self._clear_filters)
        lo.addWidget(clear_btn)

        # Column visibility chooser
        cols_btn = QPushButton("Columns \u25BE")
        cols_btn.setFixedHeight(28)
        cols_btn.setToolTip("Show/hide table columns")
        cols_btn.clicked.connect(lambda: self._show_column_chooser(cols_btn))
        lo.addWidget(cols_btn)

        lo.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {sc('muted').name()}; font-size: 11px;")
        lo.addWidget(self._count_label)
        return w

    def _make_bulk_bar(self) -> QWidget:
        """Bulk action toolbar — visible when multiple rows are selected."""
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(6)

        self._bulk_label = QLabel("")
        self._bulk_label.setStyleSheet(f"font-weight: bold; color: {sc('link').name()};")
        lo.addWidget(self._bulk_label)

        _bp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._bulk_review_btn = QPushButton("Set Review")
        self._bulk_review_btn.setFixedHeight(28)
        self._bulk_review_btn.setSizePolicy(_bp)
        self._bulk_review_btn.clicked.connect(lambda: self._bulk_action("set_review"))
        lo.addWidget(self._bulk_review_btn)

        self._bulk_clear_btn = QPushButton("Clear Review")
        self._bulk_clear_btn.setFixedHeight(28)
        self._bulk_clear_btn.setSizePolicy(_bp)
        self._bulk_clear_btn.clicked.connect(lambda: self._bulk_action("clear_review"))
        lo.addWidget(self._bulk_clear_btn)

        self._bulk_tb_btn = QPushButton("TB +1")
        self._bulk_tb_btn.setFixedHeight(28)
        self._bulk_tb_btn.setSizePolicy(_bp)
        self._bulk_tb_btn.clicked.connect(lambda: self._bulk_action("tb"))
        lo.addWidget(self._bulk_tb_btn)

        self._bulk_limits_btn = QPushButton("Limits +1")
        self._bulk_limits_btn.setFixedHeight(28)
        self._bulk_limits_btn.setSizePolicy(_bp)
        self._bulk_limits_btn.clicked.connect(lambda: self._bulk_action("limits"))
        lo.addWidget(self._bulk_limits_btn)

        self._bulk_group_btn = QPushButton("Assign Group")
        self._bulk_group_btn.setFixedHeight(28)
        self._bulk_group_btn.setSizePolicy(_bp)
        self._bulk_group_btn.clicked.connect(lambda: self._bulk_action("assign_group"))
        lo.addWidget(self._bulk_group_btn)

        self._bulk_warmup_btn = QPushButton("Apply Warmup")
        self._bulk_warmup_btn.setFixedHeight(28)
        self._bulk_warmup_btn.setSizePolicy(_bp)
        self._bulk_warmup_btn.clicked.connect(self._on_bulk_warmup)
        lo.addWidget(self._bulk_warmup_btn)

        lo.addStretch()

        self._bulk_bar = w
        w.setVisible(False)
        return w

    def _get_selected_account_ids_multi(self) -> list:
        """Return account IDs for all selected rows."""
        ids = []
        for idx in self._table.selectionModel().selectedRows():
            item = self._table.item(idx.row(), COL_USERNAME)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data[0] == "account" and data[1] is not None:
                    ids.append(data[1])
        return ids

    def _update_bulk_bar(self) -> None:
        """Show/hide bulk bar based on selection count."""
        ids = self._get_selected_account_ids_multi()
        if len(ids) > 1:
            self._bulk_label.setText(f"{len(ids)} selected")
            self._bulk_bar.setVisible(True)
        else:
            self._bulk_bar.setVisible(False)

    def _bulk_action(self, action: str) -> None:
        """Execute a bulk action on all selected accounts."""
        ids = self._get_selected_account_ids_multi()
        if len(ids) < 2:
            return

        if not self._operator_action_service:
            return

        from oh.ui.bulk_action_dialog import BulkActionDialog

        if action == "set_review":
            dlg = BulkActionDialog(
                "Set Review", ids,
                lambda aid, note=None: self._operator_action_service.set_review(aid, note),
                show_note=True, parent=self,
            )
        elif action == "clear_review":
            dlg = BulkActionDialog(
                "Clear Review", ids,
                lambda aid: self._operator_action_service.clear_review(aid),
                parent=self,
            )
        elif action == "tb":
            dlg = BulkActionDialog(
                "TB +1", ids,
                lambda aid: self._operator_action_service.increment_tb(aid),
                parent=self,
            )
        elif action == "limits":
            dlg = BulkActionDialog(
                "Limits +1", ids,
                lambda aid: self._operator_action_service.increment_limits(aid),
                parent=self,
            )
        elif action == "assign_group":
            if not self._account_group_service or not self._account_group_repo:
                return
            groups = self._account_group_repo.get_all_groups()
            if not groups:
                QMessageBox.information(self, "No Groups", "Create a group first via Groups button.")
                return
            group_names = [g.name for g in groups]
            from PySide6.QtWidgets import QInputDialog
            name, ok = QInputDialog.getItem(
                self, "Assign Group", "Select group:", group_names, 0, False
            )
            if not ok:
                return
            group = next((g for g in groups if g.name == name), None)
            if group:
                added = self._account_group_service.assign_accounts(group.id, ids)
                self._set_status(f"Added {added} accounts to group '{name}'")
                self._refresh_table()
            return
        else:
            return

        dlg.exec()
        self._refresh_table()

    def _on_bulk_warmup(self) -> None:
        """Show warmup template picker for currently selected accounts."""
        if self._warmup_template_service is None:
            return
        ids = self._get_selected_account_ids_multi()
        if not ids:
            return
        menu = QMenu(self)
        self._populate_warmup_submenu(menu, ids)
        menu.exec(self.cursor().pos())

    # Default column widths — wide enough so headers are never truncated
    _DEFAULT_COL_WIDTHS = {
        COL_TIMESLOT:    36,
        COL_USERNAME:   160,
        COL_DEVICE:     120,
        COL_HOURS:       60,
        COL_STATUS:      60,
        COL_TAGS:       120,
        COL_FOLLOW:      38,
        COL_UNFOLLOW:    38,
        COL_LIMIT:       50,
        COL_FOLLOW_TODAY: 78,
        COL_LIKE_TODAY:   78,
        COL_FOLLOW_LIM:  46,
        COL_LIKE_LIM:    46,
        COL_REVIEW:      38,
        COL_DATA_DB:     52,
        COL_SOURCES_TXT: 80,
        COL_DISCOVERED:  90,
        COL_LAST_SEEN:   90,
        COL_SRC_COUNT:   76,
        COL_FBR_QUALITY: 72,
        COL_FBR_BEST:    80,
        COL_FBR_DATE:    76,
        COL_HEALTH:      56,
        COL_TREND:       52,
        COL_BLOCK:       48,
        COL_GROUP:       80,
        COL_ACTIONS:     74,
    }

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, len(COLUMN_HEADERS))
        t.setObjectName("accountsTable")
        t.setHorizontalHeaderLabels(COLUMN_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        # Enable horizontal scrollbar so columns don't squeeze into the viewport
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        hdr = t.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setStretchLastSection(False)   # do NOT stretch — allow h-scroll instead
        hdr_font = hdr.font()
        hdr_font.setPointSize(8)
        hdr.setFont(hdr_font)

        # All columns are Interactive (user can resize by dragging) —
        # none are Stretch so the table can scroll horizontally.
        for col in range(len(COLUMN_HEADERS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

        for col, w in self._DEFAULT_COL_WIDTHS.items():
            t.setColumnWidth(col, w)

        # Restore hidden columns from settings
        self._apply_column_visibility(t)

        # Tooltips on header items so operators see full names on hover
        _HEADER_TOOLTIPS = {
            COL_TIMESLOT: "Timeslot 1-4 (1=0-6h, 2=6-12h, 3=12-18h, 4=18-24h)",
            COL_USERNAME: "Account username",
            COL_DEVICE: "Device name (dot = status: green=running, gray=stop, red=offline)",
            COL_HOURS: "Working hours (start - end)",
            COL_STATUS: "Account status (Active / Removed)",
            COL_TAGS: "Bot tags + operator tags",
            COL_FOLLOW: "Follow enabled", COL_UNFOLLOW: "Unfollow enabled",
            COL_LIMIT: "Limit per day", COL_FOLLOW_TODAY: "Follows today",
            COL_LIKE_TODAY: "Likes today", COL_FOLLOW_LIM: "Follow limit/day",
            COL_LIKE_LIM: "Like limit/day", COL_REVIEW: "Review flag",
            COL_DATA_DB: "Data DB exists", COL_SOURCES_TXT: "Sources.txt exists",
            COL_DISCOVERED: "Date account was discovered",
            COL_LAST_SEEN: "Date account was last seen during sync",
            COL_SRC_COUNT: "Active sources count",
            COL_FBR_QUALITY: "Quality / Total sources",
            COL_FBR_BEST: "Best FBR %", COL_FBR_DATE: "Last FBR analysis date",
            COL_HEALTH: "Health score (0-100, green=70+, yellow=40-69, red=<40)",
            COL_TREND: "Performance trend (14-day)",
            COL_BLOCK: "Block/ban indicator",
            COL_GROUP: "Account group name(s)",
            COL_ACTIONS: "Quick actions menu",
        }
        for col_idx, tip in _HEADER_TOOLTIPS.items():
            header_item = t.horizontalHeaderItem(col_idx)
            if header_item:
                header_item.setToolTip(tip)

        t.doubleClicked.connect(self._on_row_double_clicked)
        self._table = t
        return t

    # ------------------------------------------------------------------
    # Data loading and display
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        # Remember selection
        selected_id = self._get_selected_account_id()

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
        # Load block map
        if self._block_detection_service:
            try:
                self._block_map = self._block_detection_service.get_active_blocks()
            except Exception:
                self._block_map = {}
        # Load group membership map
        if self._account_group_repo:
            try:
                self._group_map = self._account_group_repo.get_membership_map()
            except Exception:
                self._group_map = {}
        # Load trend data
        if self._trend_service:
            try:
                active_ids = [a.id for a in self._all_accounts if a.is_active and a.id]
                self._trend_map = self._trend_service.get_trends_map(active_ids, days=14)
            except Exception:
                self._trend_map = {}
        else:
            self._trend_map = {}
        self._update_device_filter()
        self._apply_filter()
        self._update_last_sync_label()

        # Restore selection
        if selected_id is not None:
            self._select_account_by_id(selected_id)

        # Reload detail panel if it is currently open
        if (hasattr(self, '_detail_panel')
                and self._detail_panel.isVisible()
                and self._detail_panel.current_account_id() is not None):
            self._load_detail_for_account(self._detail_panel.current_account_id())

    def _get_selected_account_id(self) -> int:
        """Return the account_id of the currently selected row, or None."""
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self._table.item(selected[0].row(), COL_USERNAME)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "account":
                return data[1]
        return None

    def _select_account_by_id(self, account_id: int) -> None:
        """Find and select the row for the given account_id."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_USERNAME)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data[0] == "account" and data[1] == account_id:
                    self._table.selectRow(row)
                    self._table.scrollToItem(item)
                    return

    # ------------------------------------------------------------------
    # Detail panel — selection, loading, closing
    # ------------------------------------------------------------------

    def _on_account_selected(self, index) -> None:
        """Handle single-click on a table row: open detail panel for the account."""
        row = index.row()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind != "account":
            return
        account_id = payload
        if account_id is None:
            return
        self._load_detail_for_account(account_id)
        if not self._detail_panel.isVisible():
            self._detail_panel.setVisible(True)

    def _load_detail_for_account(self, account_id: int) -> None:
        """Fetch account data and populate the detail panel."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            self._detail_panel.clear()
            return

        if self._account_detail_service is not None:
            try:
                detail_data = self._account_detail_service.get_summary_data(
                    account=acc,
                    fbr_map=self._fbr_map,
                    source_count_map=self._source_count_map,
                    session_map=self._session_map,
                    device_status_map=self._device_status_map,
                    op_tags_map=self._op_tags_map,
                )
                self._detail_panel.load_account(detail_data)
                self._load_peer_and_related(detail_data, acc)
                self._load_detail_sources_and_history(account_id)
                return
            except Exception:
                logger.debug(
                    "account_detail_service.get_summary_data failed for %s, "
                    "falling back to minimal data",
                    account_id,
                    exc_info=True,
                )

        # Fallback: build a minimal data object from the AccountRecord
        # so the panel can still render header information.
        from types import SimpleNamespace
        dev_status = self._device_status_map.get(acc.device_id)
        fallback = SimpleNamespace(
            account_id=acc.id,
            username=acc.username,
            device_name=acc.device_name or acc.device_id,
            device_status=dev_status,
            is_active=acc.is_active,
            review_flag=acc.review_flag,
            review_note=acc.review_note,
        )
        self._detail_panel.load_account(fallback)
        self._load_detail_sources_and_history(account_id)

    def _load_detail_sources_and_history(self, account_id: int) -> None:
        """Load Sources and History tab data for the detail drawer."""
        # --- Sources tab ---
        try:
            snap = self._fbr_map.get(account_id)
            if snap is not None and snap.id is not None:
                from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
                fbr_repo = FBRSnapshotRepository(self._conn)
                source_results = fbr_repo.get_source_results(snap.id)
                sources_data = []
                for sr in source_results:
                    sources_data.append({
                        "source_name": sr.source_name,
                        "is_active": True,
                        "follow_count": sr.follow_count,
                        "followback_count": sr.followback_count,
                        "fbr_percent": sr.fbr_percent,
                        "is_quality": sr.is_quality,
                    })
                self._detail_panel._sources_tab.load_sources(sources_data)
            else:
                self._detail_panel._sources_tab.load_sources([])
        except Exception as exc:
            logger.debug("Failed to load sources for drawer: %s", exc)

        # --- Like Sources (LBR) ---
        try:
            lbr_snap = self._lbr_map.get(account_id)
            if lbr_snap is not None and lbr_snap.id is not None:
                from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
                lbr_repo = LBRSnapshotRepository(self._conn)
                lbr_results = lbr_repo.get_source_results(lbr_snap.id)
                like_data = []
                for lr in lbr_results:
                    like_data.append({
                        "source_name": lr.source_name,
                        "is_active": True,
                        "like_count": lr.like_count,
                        "followback_count": lr.followback_count,
                        "lbr_percent": lr.lbr_percent,
                        "is_quality": lr.is_quality,
                    })
                self._detail_panel._sources_tab.load_like_sources(like_data)
            else:
                self._detail_panel._sources_tab.load_like_sources([])
        except Exception as exc:
            logger.debug("Failed to load like sources for drawer: %s", exc)

        # --- History tab ---
        try:
            actions = []
            if self._operator_action_repo is not None:
                actions = self._operator_action_repo.get_for_account(account_id)

            fbr_snapshots = []
            try:
                from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
                fbr_repo = FBRSnapshotRepository(self._conn)
                fbr_snapshots = fbr_repo.get_for_account(account_id)
            except Exception:
                pass

            self._detail_panel._history_tab.load_history(
                actions=actions,
                fbr_snapshots=fbr_snapshots,
                sessions=[],
            )
        except Exception as exc:
            logger.debug("Failed to load history for drawer: %s", exc)

    def _load_peer_and_related(self, data, acc) -> None:
        """Compute peer comparison and related accounts for the detail panel."""
        device_accounts = []  # type: list
        acc_id = None
        # Peer comparison
        try:
            acc_id = data.account.id if hasattr(data, "account") else getattr(data, "account_id", None)
            device_id = data.account.device_id if hasattr(data, "account") else getattr(data, "device_id", "")
            min_src_th = self._settings.get_min_source_count_warning()

            # This account's health
            acc_health = AccountHealthService.compute_score(
                data.account, data.fbr_snapshot, data.session,
                data.source_count or 0, data.operator_tags or "",
                min_src_th,
            )

            # Device avg — accounts on same device
            device_accounts = [
                a for a in self._all_accounts
                if a.device_id == device_id and a.removed_at is None
            ]
            device_healths = []
            for da in device_accounts:
                dh = AccountHealthService.compute_score(
                    da, self._fbr_map.get(da.id), self._session_map.get(da.id),
                    self._source_count_map.get(da.id, 0),
                    self._op_tags_map.get(da.id, "") or "",
                    min_src_th,
                )
                device_healths.append(dh)
            device_avg = sum(device_healths) / len(device_healths) if device_healths else 0

            # Fleet avg — all active accounts
            fleet_healths = []
            for fa in self._all_accounts:
                if fa.removed_at is not None:
                    continue
                fh = AccountHealthService.compute_score(
                    fa, self._fbr_map.get(fa.id), self._session_map.get(fa.id),
                    self._source_count_map.get(fa.id, 0),
                    self._op_tags_map.get(fa.id, "") or "",
                    min_src_th,
                )
                fleet_healths.append(fh)
            fleet_avg = sum(fleet_healths) / len(fleet_healths) if fleet_healths else 0

            peer_data = {
                "account_health": acc_health,
                "device_avg_health": round(device_avg, 1),
                "fleet_avg_health": round(fleet_avg, 1),
            }
            self._detail_panel._summary_tab.load_peer_data(peer_data)
        except Exception:
            logger.debug("Failed to compute peer comparison", exc_info=True)

        # Related accounts
        try:
            if not device_accounts:
                device_id = acc.device_id if acc else ""
                device_accounts = [
                    a for a in self._all_accounts
                    if a.device_id == device_id and a.removed_at is None
                ]
            if acc_id is None:
                acc_id = data.account.id if hasattr(data, "account") else getattr(data, "account_id", None)

            related = []
            for ra in device_accounts:
                if ra.id == acc_id:
                    continue
                rh = AccountHealthService.compute_score(
                    ra, self._fbr_map.get(ra.id), self._session_map.get(ra.id),
                    self._source_count_map.get(ra.id, 0),
                    self._op_tags_map.get(ra.id, "") or "",
                    self._settings.get_min_source_count_warning(),
                )
                related.append({"username": ra.username, "health_score": rh})
            related.sort(key=lambda x: x["health_score"])
            self._detail_panel.load_related_accounts(related)
        except Exception:
            logger.debug("Failed to compute related accounts", exc_info=True)

    def _close_detail_panel(self) -> None:
        """Hide the detail panel and give full width back to the table."""
        self._detail_panel.setVisible(False)
        self._detail_panel.clear()

    # ------------------------------------------------------------------
    # Debounced row-change handler (arrow-key navigation)
    # ------------------------------------------------------------------

    def _on_table_row_changed(self, current, previous) -> None:
        """Called when the table selection changes (arrow keys or click).

        If the drawer is open, start/restart a 150ms debounce timer so that
        rapid arrow-key navigation does not trigger a load for every row.
        """
        if not self._detail_panel.isVisible():
            return

        if self._detail_debounce_timer is not None:
            self._detail_debounce_timer.stop()
            self._detail_debounce_timer.deleteLater()

        self._detail_debounce_timer = QTimer(self)
        self._detail_debounce_timer.setSingleShot(True)
        self._detail_debounce_timer.setInterval(150)
        self._detail_debounce_timer.timeout.connect(
            lambda: self._debounced_load_row(current.row())
        )
        self._detail_debounce_timer.start()

    def _debounced_load_row(self, row: int) -> None:
        """Load the detail panel for the given table row after debounce."""
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind != "account":
            return
        account_id = payload
        if account_id is None:
            return
        self._load_detail_for_account(account_id)

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Handle keyboard shortcuts for the detail drawer.

        Space  -- toggle drawer for selected row (only when table has focus)
        Escape -- close drawer if open
        Left/Right arrows -- switch drawer tabs (only when table has focus
                             and drawer is visible)
        """
        # Determine if the focus is on an input widget that should consume keys
        focus = QApplication.focusWidget()
        focus_is_input = isinstance(focus, (QLineEdit, QComboBox, QInputDialog))

        key = event.key()

        # Escape: close drawer regardless of focus
        if key == Qt.Key.Key_Escape:
            if self._detail_panel.isVisible():
                self._close_detail_panel()
                return
            # Let parent handle Escape if drawer is not open
            super().keyPressEvent(event)
            return

        # The following shortcuts only apply when focus is NOT on an input
        if focus_is_input:
            super().keyPressEvent(event)
            return

        # Space: toggle drawer open/close for selected row
        if key == Qt.Key.Key_Space:
            if self._detail_panel.isVisible():
                self._close_detail_panel()
            else:
                # Try to open for the currently selected row
                current = self._table.currentIndex()
                if current.isValid():
                    self._on_account_selected(current)
            return

        # Left/Right arrows: switch drawer tabs when drawer is visible
        if self._detail_panel.isVisible():
            if key == Qt.Key.Key_Left:
                self._detail_panel.switch_tab(-1)
                return
            elif key == Qt.Key.Key_Right:
                self._detail_panel.switch_tab(1)
                return

        super().keyPressEvent(event)

    def _on_detail_action_requested(self, action_type: str, account_id: int) -> None:
        """Dispatch action requests from the detail panel to existing handlers."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return

        if action_type == "set_review":
            self._do_set_review(acc)
        elif action_type == "clear_review":
            self._do_clear_review(acc)
        elif action_type == "tb_plus_1":
            self._do_tb_increment(acc)
        elif action_type == "limits_plus_1":
            self._do_limits_increment(acc)
        elif action_type == "open_folder":
            self._open_account_folder(acc.device_id, acc.username)
        elif action_type == "open_sources":
            self._on_view_sources(acc.device_id, acc.username, acc.id)
        elif action_type == "copy_diagnostic":
            self._copy_diagnostic(acc)
        elif action_type == "apply_warmup":
            self._show_warmup_picker_for_account(acc.id)
        else:
            logger.warning("Unknown detail panel action: %s", action_type)
            return

        # After any action completes, refresh the table and reload the drawer
        # for the same account so the panel reflects the new state.
        # Note: _do_set_review etc. already call _refresh_table(), but we
        # still need to reload the drawer.  Guard against open_folder/copy
        # which don't mutate state.
        if action_type not in ("open_folder", "copy_diagnostic", "apply_warmup", "open_sources"):
            self._load_detail_for_account(account_id)

    def _copy_diagnostic(self, acc) -> None:
        """Copy a diagnostic summary for the account to the clipboard."""
        # Try the rich format from the service first
        if self._account_detail_service is not None:
            try:
                detail_data = self._account_detail_service.get_summary_data(
                    account=acc,
                    fbr_map=self._fbr_map,
                    source_count_map=self._source_count_map,
                    session_map=self._session_map,
                    device_status_map=self._device_status_map,
                    op_tags_map=self._op_tags_map,
                )
                text = self._account_detail_service.format_diagnostic(detail_data)
                QApplication.clipboard().setText(text)
                logger.info("Diagnostic copied (rich) for %s", acc.username)
                return
            except Exception:
                logger.debug(
                    "format_diagnostic via service failed, using fallback",
                    exc_info=True,
                )

        # Fallback: simple text summary
        snap = self._fbr_map.get(acc.id) if acc.id is not None else None
        src_count = self._source_count_map.get(acc.id, 0) if acc.id is not None else 0
        sess = self._session_map.get(acc.id) if acc.id is not None else None
        dev_status = self._device_status_map.get(acc.device_id, "unknown")

        lines = [
            "Account: %s" % acc.username,
            "Device: %s (%s)" % (acc.device_name or acc.device_id, dev_status),
            "Status: %s" % ("Active" if acc.is_active else "Removed"),
            "Follow: %s  Unfollow: %s  Limit: %s" % (
                acc.follow_enabled, acc.unfollow_enabled, acc.limit_per_day or "-"),
            "Active sources: %s" % src_count,
        ]
        if snap:
            lines.append("FBR: %s/%s quality  best=%.1f%%  date=%s" % (
                snap.quality_sources, snap.total_sources,
                snap.best_fbr_pct if snap.best_fbr_pct is not None else 0,
                (snap.analyzed_at[:10] if snap.analyzed_at else "-"),
            ))
        if sess:
            lines.append("Today: follow=%s  like=%s" % (sess.follow_count, sess.like_count))
        if acc.review_flag:
            lines.append("Review: %s" % (acc.review_note or "(no note)"))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(lines))
        logger.info("Diagnostic copied for %s", acc.username)

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

        # Also rebuild group filter
        self._update_group_filter()

    def _update_group_filter(self) -> None:
        """Rebuild the group dropdown from current groups."""
        current = self._group_filter.currentText()
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem("All groups")
        if self._account_group_repo:
            try:
                groups = self._account_group_repo.get_all_groups()
                for g in groups:
                    self._group_filter.addItem(g.name)
            except Exception:
                pass
        idx = self._group_filter.findText(current)
        self._group_filter.setCurrentIndex(max(idx, 0))
        self._group_filter.blockSignals(False)

    def _clear_filters(self) -> None:
        """Reset all filters to their defaults without triggering multiple repaints."""
        for w in (self._status_filter, self._fbr_filter, self._device_filter,
                  self._search_box, self._show_orphans_cb,
                  self._tags_filter, self._activity_filter, self._group_filter,
                  self._timeslot_filter, self._health_filter,
                  self._review_cb):
            w.blockSignals(True)

        self._status_filter.setCurrentIndex(0)
        self._fbr_filter.setCurrentIndex(0)
        self._device_filter.setCurrentIndex(0)
        self._tags_filter.setCurrentIndex(0)
        self._activity_filter.setCurrentIndex(0)
        self._group_filter.setCurrentIndex(0)
        self._timeslot_filter.setCurrentIndex(0)
        self._health_filter.setCurrentIndex(0)
        self._search_box.clear()
        self._show_orphans_cb.setChecked(False)
        self._review_cb.setChecked(False)

        for w in (self._status_filter, self._fbr_filter, self._device_filter,
                  self._search_box, self._show_orphans_cb,
                  self._tags_filter, self._activity_filter, self._group_filter,
                  self._timeslot_filter, self._health_filter,
                  self._review_cb):
            w.blockSignals(False)

        self._apply_filter()

    # ------------------------------------------------------------------
    # Column visibility
    # ------------------------------------------------------------------

    # Columns that cannot be hidden (always visible)
    _ALWAYS_VISIBLE = {COL_USERNAME, COL_ACTIONS}

    # Human-readable labels for the column chooser menu
    _COL_LABELS = {
        COL_TIMESLOT: "Timeslot", COL_USERNAME: "Username",
        COL_DEVICE: "Device", COL_HOURS: "Hours",
        COL_STATUS: "Status", COL_TAGS: "Tags",
        COL_FOLLOW: "Follow", COL_UNFOLLOW: "Unfollow",
        COL_LIMIT: "Limit/Day",
        COL_FOLLOW_TODAY: "Follow Today", COL_LIKE_TODAY: "Like Today",
        COL_FOLLOW_LIM: "Follow Limit", COL_LIKE_LIM: "Like Limit",
        COL_REVIEW: "Review",
        COL_DATA_DB: "Data DB", COL_SOURCES_TXT: "Sources.txt",
        COL_DISCOVERED: "Discovered", COL_LAST_SEEN: "Last Seen",
        COL_SRC_COUNT: "Active Sources",
        COL_FBR_QUALITY: "Quality/Total", COL_FBR_BEST: "Best FBR%",
        COL_FBR_DATE: "Last FBR",
        COL_HEALTH: "Health", COL_TREND: "Trend",
        COL_BLOCK: "Block", COL_GROUP: "Group",
        COL_ACTIONS: "Actions",
    }

    def _show_column_chooser(self, btn: QPushButton) -> None:
        """Show a popup menu with checkable column names."""
        menu = QMenu(self)
        actions = []
        for col in range(len(COLUMN_HEADERS)):
            label = self._COL_LABELS.get(col, COLUMN_HEADERS[col])
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col))
            if col in self._ALWAYS_VISIBLE:
                action.setEnabled(False)
            actions.append((col, action))

        menu.addSeparator()
        show_all = menu.addAction("Show All Columns")

        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

        if chosen == show_all:
            for col in range(len(COLUMN_HEADERS)):
                self._table.setColumnHidden(col, False)
            self._save_column_visibility()
            return

        # Apply toggles
        for col, act in actions:
            self._table.setColumnHidden(col, not act.isChecked())
        self._save_column_visibility()

    def _save_column_visibility(self) -> None:
        """Persist hidden column indices to settings."""
        hidden = []
        for col in range(len(COLUMN_HEADERS)):
            if self._table.isColumnHidden(col) and col not in self._ALWAYS_VISIBLE:
                hidden.append(str(col))
        self._settings.set("hidden_columns", ",".join(hidden))

    def _apply_column_visibility(self, t: QTableWidget) -> None:
        """Restore hidden columns from settings."""
        raw = self._settings.get("hidden_columns") or ""
        if not raw:
            return
        for part in raw.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                col = int(part)
                if 0 <= col < len(COLUMN_HEADERS) and col not in self._ALWAYS_VISIBLE:
                    t.setColumnHidden(col, True)
            except ValueError:
                pass

    @staticmethod
    def _get_slot_number(acc: AccountRecord) -> int:
        """Return timeslot 1-4 based on account start_time, or 0 if unknown."""
        start_t = getattr(acc, "start_time", None) or ""
        if not start_t:
            return 0
        try:
            hour = int(start_t.split(":")[0])
        except (ValueError, IndexError):
            return 0
        if hour < 6:
            return 1
        elif hour < 12:
            return 2
        elif hour < 18:
            return 3
        else:
            return 4

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
        group_filt    = self._group_filter.currentText()
        timeslot_filt = self._timeslot_filter.currentText()
        health_filt   = self._health_filter.currentText()
        review_only   = self._review_cb.isChecked()
        query         = self._search_box.text().strip().lower()
        show_orphans  = self._show_orphans_cb.isChecked()

        # Map timeslot filter to slot number for comparison
        _slot_number_map = {
            _TIMESLOT_FILTER_1: 1, _TIMESLOT_FILTER_2: 2,
            _TIMESLOT_FILTER_3: 3, _TIMESLOT_FILTER_4: 4,
        }
        required_slot = _slot_number_map.get(timeslot_filt)

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

            # --- timeslot dimension ---
            if required_slot is not None:
                acc_slot = self._get_slot_number(acc)
                if acc_slot != required_slot:
                    continue

            # --- health dimension ---
            if health_filt != _HEALTH_FILTER_ALL and acc.id is not None:
                snap_h = self._fbr_map.get(acc.id) if acc.id is not None else None
                sess_h = self._session_map.get(acc.id) if acc.id is not None else None
                src_h = self._source_count_map.get(acc.id, 0)
                op_h = self._op_tags_map.get(acc.id) if acc.id else None
                min_h = self._settings.get_min_source_count_warning()
                score = AccountHealthService.compute_score(
                    acc, snap_h, sess_h, src_h, op_h or "", min_h,
                )
                if health_filt == _HEALTH_FILTER_GREEN and score < 70:
                    continue
                if health_filt == _HEALTH_FILTER_YELLOW and (score < 40 or score >= 70):
                    continue
                if health_filt == _HEALTH_FILTER_RED and score >= 40:
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
                if activity_filt == _ACTIVITY_FILTER_BLOCKED:
                    if acc.id not in self._block_map:
                        continue
                else:
                    sess = self._session_map.get(acc.id)
                    has_act = sess.has_activity if sess else False
                    if activity_filt == _ACTIVITY_FILTER_ZERO and has_act:
                        continue
                    if activity_filt == _ACTIVITY_FILTER_HAS and not has_act:
                        continue

            # --- group dimension ---
            if group_filt != "All groups" and acc.id is not None:
                acc_groups = self._group_map.get(acc.id, [])
                if not any(g.name == group_filt for g in acc_groups):
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
            msg.setForeground(sc("muted"))
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

        status_color = C_ACTIVE() if not removed else C_REMOVED()
        status_text  = "Active" if not removed else "Removed"

        disc_date = acc.discovered_at[:10] if acc.discovered_at else "—"
        seen_date = acc.last_seen_at[:10]  if acc.last_seen_at  else "—"

        # Timeslot column (1-4)
        slot_num = self._get_slot_number(acc)
        slot_text = str(slot_num) if slot_num > 0 else "\u2014"
        slot_item = SortableItem(slot_text, slot_num)
        slot_item.setTextAlignment(center)
        if removed:
            slot_item.setForeground(C_REMOVED())
        self._table.setItem(row, COL_TIMESLOT, slot_item)

        self._table.setItem(row, COL_USERNAME,    self._make_item(acc.username, dimmed=removed))

        # Device column with status color dot prefix
        device_name = acc.device_name or acc.device_id
        dev_status = self._device_status_map.get(acc.device_id)
        if dev_status == "running":
            dot = "\u25cf "  # filled circle
            dot_color = C_YES()    # green
        elif dev_status == "stop":
            dot = "\u25cf "
            dot_color = C_REMOVED()  # gray
        else:
            dot = "\u25cf "
            dot_color = C_NO()     # red — unknown/offline
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
        tags_color = C_WARN() if op_tags else None  # amber highlight if operator tags exist
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
            ft_color = C_NO()
        elif follow_today > 0:
            ft_color = C_YES()
        ft_item = SortableItem(str(follow_today) if sess else "—", follow_today if sess else -1)
        ft_item.setTextAlignment(center)
        if removed:
            ft_item.setForeground(C_REMOVED())
        elif ft_color:
            ft_item.setForeground(ft_color)
        self._table.setItem(row, COL_FOLLOW_TODAY, ft_item)

        # Like Today — neutral rendering (no red for 0 — we can't distinguish
        # accounts without like flow enabled from those that failed)
        lt_color = C_YES() if like_today > 0 else None
        lt_item = SortableItem(str(like_today) if sess else "—", like_today if sess else -1)
        lt_item.setTextAlignment(center)
        if removed:
            lt_item.setForeground(C_REMOVED())
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
        review_color = C_WARN() if acc.review_flag else None
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
                src_color = C_REMOVED()
            elif src_count < min_warn:
                src_color = C_WARN()
            else:
                src_color = None
            src_item = SortableItem(str(src_count), src_count)
            src_item.setTextAlignment(center)
            if src_color:
                src_item.setForeground(src_color)
            self._table.setItem(row, COL_SRC_COUNT, src_item)
        else:
            self._table.setItem(row, COL_SRC_COUNT, self._make_item("—", center))

        # FBR summary cells
        snap = self._fbr_map.get(acc.id) if acc.id is not None else None
        self._fill_fbr_cells(row, snap, dimmed=removed)

        # Working hours
        start_t = getattr(acc, "start_time", None) or ""
        end_t = getattr(acc, "end_time", None) or ""
        if start_t and end_t:
            hours_text = f"{start_t}-{end_t}"
        elif start_t:
            hours_text = f"{start_t}-?"
        else:
            hours_text = "\u2014"
        hours_item = QTableWidgetItem(hours_text)
        hours_item.setTextAlignment(center)
        if not start_t:
            hours_item.setForeground(C_NEVER())
        self._table.setItem(row, COL_HOURS, hours_item)

        # Health score (snap already fetched above for FBR cells)
        src_count_h = self._source_count_map.get(acc.id, 0) if acc.id is not None else 0
        op_tags_h = self._op_tags_map.get(acc.id) if acc.id else None
        min_src_th = self._settings.get_min_source_count_warning()
        health = AccountHealthService.compute_score(
            acc, snap, sess, src_count_h, op_tags_h or "", min_src_th,
        )
        health_item = SortableItem(f"{health:.0f}", health)
        health_item.setTextAlignment(center)
        if removed:
            health_item.setForeground(C_REMOVED())
        else:
            health_item.setForeground(sc(AccountHealthService.score_color_key(health)))
        self._table.setItem(row, COL_HEALTH, health_item)

        # Trend column — placeholder text, sparklines loaded lazily
        trend_text = ""
        if acc.id is not None and acc.id in self._trend_map:
            trend_data = self._trend_map[acc.id]
            arrow = {
                "up": "\u25b2", "down": "\u25bc", "stable": "\u25ac"
            }.get(trend_data.trend_direction, "")
            trend_text = arrow
        trend_item = self._make_item(trend_text, center, dimmed=removed)
        if trend_text == "\u25b2":
            trend_item.setForeground(sc("success"))
        elif trend_text == "\u25bc":
            trend_item.setForeground(sc("error"))
        self._table.setItem(row, COL_TREND, trend_item)

        # Block indicator
        blocks = self._block_map.get(acc.id, []) if acc.id else []
        if blocks and not removed:
            block_types = ", ".join(b.label for b in blocks)
            block_item = self._make_item("\u26a0", center, C_NO())
            block_item.setToolTip(f"Active: {block_types}")
        else:
            block_item = self._make_item("", center, dimmed=removed)
        self._table.setItem(row, COL_BLOCK, block_item)

        # Group column
        groups = self._group_map.get(acc.id, []) if acc.id else []
        if groups:
            group_names = ", ".join(g.name for g in groups)
            group_item = self._make_item(group_names, dimmed=removed)
        else:
            group_item = self._make_item("\u2014", center, dimmed=removed)
        self._table.setItem(row, COL_GROUP, group_item)

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("account", acc.id)
        )

        act_btn = QPushButton("Actions \u25BE")
        act_btn.setStyleSheet("min-height: 0px; padding: 2px 8px; font-size: 11px;")
        act_btn.setEnabled(not removed)
        act_btn.setToolTip("Open folder, view sources, operator actions")
        act_btn.clicked.connect(lambda _, a=acc, b=act_btn: self._show_action_menu(a, b))

        self._table.setCellWidget(row, COL_ACTIONS, act_btn)

    def _fill_orphan_row(self, row: int, disc: DiscoveredAccount) -> None:
        center = Qt.AlignmentFlag.AlignCenter

        self._table.setItem(row, COL_TIMESLOT,    self._make_item("\u2014", center))
        self._table.setItem(row, COL_USERNAME,    self._make_item(disc.username))
        self._table.setItem(row, COL_DEVICE,      self._make_item(disc.device_name))
        self._table.setItem(row, COL_STATUS,      self._make_item("Orphan", center, C_ORPHAN()))
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

        # Hours — not available for orphans
        self._table.setItem(row, COL_HOURS, self._make_item("—", center))

        # Health — not available for orphans
        self._table.setItem(row, COL_HEALTH, self._make_item("—", center))

        # Trend / Block / Group — not available for orphans
        self._table.setItem(row, COL_TREND, self._make_item("", center))
        self._table.setItem(row, COL_BLOCK, self._make_item("", center))
        self._table.setItem(row, COL_GROUP, self._make_item("—", center))

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("orphan", disc)
        )

        act_btn = QPushButton("Actions \u25BE")
        act_btn.setStyleSheet("min-height: 0px; padding: 2px 8px; font-size: 11px;")
        act_btn.setToolTip("Open folder, view sources")
        act_btn.clicked.connect(lambda _, d=disc, b=act_btn: self._show_orphan_action_menu(d, b))

        self._table.setCellWidget(row, COL_ACTIONS, act_btn)

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

        def _si(text: str, sort_key, color=None, _dimmed=False) -> SortableItem:
            item = SortableItem(text, sort_key)
            item.setTextAlignment(center)
            if _dimmed:
                item.setForeground(C_REMOVED())
            elif color:
                item.setForeground(color)
            return item

        if snap is None:
            # Never analyzed — use amber to draw operator attention
            self._table.setItem(row, COL_FBR_QUALITY, _si("—",     -2,   C_NEVER()))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",     -2.0, C_NEVER()))
            self._table.setItem(row, COL_FBR_DATE,    _si("Never", "",   C_NEVER()))
            return

        date_str  = snap.analyzed_at[:10] if snap.analyzed_at else "—"
        date_sort = snap.analyzed_at[:10] if snap.analyzed_at else ""

        if snap.status == SNAPSHOT_ERROR:
            self._table.setItem(row, COL_FBR_QUALITY, _si("Error", -1,   C_ERROR()))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",     -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        if snap.total_sources == 0:
            # Empty result — data.db exists but no qualifying source rows
            self._table.setItem(row, COL_FBR_QUALITY, _si("0/0", 0,    C_LOW_FBR()))
            self._table.setItem(row, COL_FBR_BEST,    _si("—",   -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        # Normal case: 'ok' status with data
        quality_text  = f"{snap.quality_sources}/{snap.total_sources}"
        quality_color = C_QUALITY() if snap.quality_sources > 0 else C_LOW_FBR()
        self._table.setItem(
            row, COL_FBR_QUALITY,
            _si(quality_text, snap.quality_sources, quality_color, _dimmed=dimmed),
        )

        if snap.best_fbr_pct is not None:
            fbr_color = C_QUALITY() if snap.quality_sources > 0 else C_LOW_FBR()
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
            i.setForeground(C_REMOVED())
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
        col  = C_REMOVED() if dimmed else (C_YES() if val else C_NO())
        i = QTableWidgetItem(text)
        i.setTextAlignment(center)
        i.setForeground(col)
        return i

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
        try:
            self._settings.set_bot_root(path)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Bot Root", str(exc))
            return
        self._sources_container.set_bot_root(path)
        self._notifications_tab.set_bot_root(path)
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

        # Detect auto-fix proposals (no execution — operator reviews first)
        auto_fix_msg = ""
        if self._auto_fix_service:
            bot_root = self._settings.get_bot_root() or ""
            if bot_root:
                try:
                    proposals = self._auto_fix_service.detect_all(bot_root)
                    if proposals:
                        from oh.ui.auto_fix_dialog import AutoFixProposalDialog
                        dlg = AutoFixProposalDialog(
                            proposals, self._auto_fix_service, parent=self
                        )
                        dlg.exec()
                        fix_result = dlg.result
                        self._last_auto_fix_result = fix_result
                        if fix_result.has_actions:
                            self._refresh_table()
                            lines = fix_result.summary_lines()
                            auto_fix_msg = "  |  Auto-fix: " + "; ".join(lines)
                            logger.info("Auto-fix applied: %s", "; ".join(lines))
                except Exception as exc:
                    logger.warning("Auto-fix detection failed: %s", exc)

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
        msg += auto_fix_msg
        self._set_status(msg)

    # ------------------------------------------------------------------
    # Update check
    # ------------------------------------------------------------------

    # TODO: Make onimator-rgb/oh-releases repo private once authenticated
    # download is set up (e.g. via a server API). Currently raw.githubusercontent
    # URLs require no auth for public repos; making it private would break both
    # START.bat and in-app update checks without a token/proxy.
    _UPDATE_URL = "https://raw.githubusercontent.com/onimator-rgb/oh-releases/main/update.json"

    def _check_for_updates(self) -> None:
        """Check for updates on startup (always runs)."""
        try:
            from oh.services.update_service import UpdateService
            svc = UpdateService(self._UPDATE_URL)
            info = svc.check_for_update()

            if info is None:
                return

            # Check if user skipped this version
            skipped = self._settings.get("update_skipped_version") or ""
            if skipped == info.version:
                logger.info("Update %s was skipped by user", info.version)
                return

            from oh.ui.update_dialog import UpdateDialog
            dlg = UpdateDialog(self, svc, info)
            result = dlg.exec()

            if result == 2:  # skip
                self._settings.set("update_skipped_version", info.version)

        except Exception as exc:
            logger.debug("Update check failed: %s", exc)

    def _on_check_for_updates_manual(self) -> None:
        """Manual 'Check for Updates' triggered from the brand bar button."""
        try:
            from oh.services.update_service import UpdateService
            svc = UpdateService(self._UPDATE_URL)
            info = svc.check_for_update()

            if info:
                from oh.ui.update_dialog import UpdateDialog
                dlg = UpdateDialog(self, svc, info)
                result = dlg.exec()
                if result == 2:  # skip
                    self._settings.set("update_skipped_version", info.version)
            else:
                QMessageBox.information(
                    self, "No Update",
                    f"You are running the latest version ({svc.current_version}).",
                )
        except Exception as exc:
            logger.warning("Manual update check failed: %s", exc)
            QMessageBox.warning(
                self, "Update Check Failed",
                f"Could not check for updates:\n{exc}",
            )

    # ------------------------------------------------------------------
    # Startup dialogs (onboarding + what's new)
    # ------------------------------------------------------------------

    def _show_startup_dialogs(self) -> None:
        """Show onboarding wizard and/or what's new dialog on startup."""
        # 1. Onboarding wizard for first-time users
        bot_root = self._settings.get_bot_root()
        onboarding_done = self._settings.get("onboarding_done") or "0"
        if not bot_root and onboarding_done != "1":
            from oh.ui.onboarding_dialog import OnboardingDialog
            dlg = OnboardingDialog(self._settings, self._scan_service, parent=self)
            dlg.tour_requested.connect(self._start_guided_tour)
            dlg.cockpit_requested.connect(self._on_cockpit)
            dlg.exec()
            # Refresh the path input in case user set it during onboarding
            saved = self._settings.get_bot_root()
            if saved:
                self._root_input.setText(saved)

        # 2. What's New dialog after version updates
        self._check_whats_new()

    def _check_whats_new(self) -> None:
        """Show What's New dialog if the version changed since last seen."""
        try:
            from oh.version import BUILD_VERSION
        except ImportError:
            return
        last_seen = self._settings.get("last_seen_version") or ""
        if last_seen == BUILD_VERSION:
            return
        from oh.ui.whats_new_dialog import WhatsNewDialog, WHATS_NEW
        if BUILD_VERSION not in WHATS_NEW:
            # No changelog for this version — just update the marker
            self._settings.set("last_seen_version", BUILD_VERSION)
            return
        dlg = WhatsNewDialog(BUILD_VERSION, parent=self)
        dlg.exec()
        self._settings.set("last_seen_version", BUILD_VERSION)

    # ------------------------------------------------------------------
    # Auto-scan scheduler
    # ------------------------------------------------------------------

    def _setup_auto_scan(self) -> None:
        """Configure auto-scan timer from settings."""
        enabled = self._settings.get("auto_scan_enabled") == "1"
        interval_h = int(self._settings.get("auto_scan_interval_hours") or "6")

        if enabled and interval_h > 0:
            interval_ms = interval_h * 3600 * 1000
            self._auto_scan_timer.start(interval_ms)
            logger.info("Auto-scan enabled: every %dh", interval_h)
        else:
            self._auto_scan_timer.stop()
            logger.info("Auto-scan disabled")

    def _on_auto_scan(self) -> None:
        """Execute automatic scan & sync in background."""
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            logger.warning("Auto-scan skipped: no bot root configured")
            return

        # Skip if a manual scan is already running
        if self._worker is not None:
            logger.info("Auto-scan skipped: operation already in progress")
            return

        logger.info("Auto-scan triggered")
        self._set_status("Auto-scan running\u2026")
        try:
            self._on_scan_and_sync()
        except Exception as exc:
            logger.warning("Auto-scan failed: %s", exc)
            self._set_status(f"Auto-scan failed: {exc}")

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
    # LBR analysis (Like-Back Rate)
    # ------------------------------------------------------------------

    def _on_analyze_lbr(self) -> None:
        bot_root = self._get_validated_root()
        if not bot_root:
            return

        self._set_busy(True, "Running LBR analysis...")

        def do_lbr():
            return self._lbr_service.analyze_all_active(bot_root)

        self._worker = WorkerThread(do_lbr)
        self._worker.result.connect(self._on_lbr_batch_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_lbr_batch_done(self, result) -> None:
        self._set_status(f"LBR analysis complete — {result.status_line()}")
        self._lbr_map = self._lbr_service.get_latest_map()

        # If the Sources tab is currently open, refresh like sources sub-tab
        if self._tabs.currentIndex() == 1:
            self._sources_container.load_data()

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

        # Fetch source date-added data
        source_dates = {}
        if account_id is not None:
            try:
                sa_repo = SourceAssignmentRepository(self._conn)
                source_dates = sa_repo.get_source_dates_for_account(account_id)
            except Exception:
                logger.debug("Could not load source dates", exc_info=True)

        self._set_status("Ready.")
        dlg = SourceDialog(
            inspection, fbr_result, usage_result,
            on_delete=on_delete, on_cleanup=on_cleanup,
            source_dates=source_dates, parent=self,
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

        # Get auto-fix summary lines if available
        auto_fix_lines = []
        if hasattr(self, '_last_auto_fix_result') and self._last_auto_fix_result:
            auto_fix_lines = self._last_auto_fix_result.summary_lines()

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
            auto_fix_lines=auto_fix_lines,
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
        self._tabs.setCurrentIndex(0)
        self._select_account_by_id(account_id)
        self._table.setFocus()

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
        """Show a popup menu of all actions for this account."""
        menu = QMenu(self)

        menu.addAction("Open Folder", lambda: self._open_account_folder(acc.device_id, acc.username))

        has_sources = acc.data_db_exists or acc.sources_txt_exists
        src_action = menu.addAction(
            "View Sources",
            lambda: self._on_view_sources(acc.device_id, acc.username, acc.id),
        )
        src_action.setEnabled(has_sources)

        if self._source_finder_service is not None:
            menu.addAction("Find Sources", lambda: self._on_find_sources(acc))

        svc = self._operator_action_service
        if svc:
            menu.addSeparator()
            if acc.review_flag:
                menu.addAction("Clear Review", lambda: self._do_clear_review(acc))
            else:
                menu.addAction("Set Review", lambda: self._do_set_review(acc))
            menu.addAction("TB +1", lambda: self._do_tb_increment(acc))
            menu.addAction("Limits +1", lambda: self._do_limits_increment(acc))

        if self._settings_copier_service is not None:
            menu.addSeparator()
            menu.addAction(
                "Copy Settings From This Account",
                lambda: self._open_settings_copier(pre_source_id=acc.id),
            )

        if self._warmup_template_service is not None:
            menu.addSeparator()
            warmup_sub = menu.addMenu("Apply Warmup")
            self._populate_warmup_submenu(warmup_sub, [acc.id])

        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _show_orphan_action_menu(self, disc: DiscoveredAccount, btn: QPushButton) -> None:
        """Show a popup menu for an orphan row."""
        menu = QMenu(self)
        menu.addAction("Open Folder", lambda: self._open_account_folder(disc.device_id, disc.username))

        has_sources = disc.data_db_exists or disc.sources_txt_exists
        src_action = menu.addAction(
            "View Sources",
            lambda: self._on_view_sources(disc.device_id, disc.username, None),
        )
        src_action.setEnabled(has_sources)

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

    def _open_settings_copier(
        self,
        pre_source_id: Optional[int] = None,
        pre_target_ids: Optional[list] = None,
    ) -> None:
        """Open the Settings Copier wizard dialog."""
        if self._settings_copier_service is None:
            return
        from oh.ui.settings_copier_dialog import SettingsCopierDialog
        dlg = SettingsCopierDialog(
            service=self._settings_copier_service,
            accounts=self._all_accounts,
            pre_selected_source_id=pre_source_id,
            pre_selected_target_ids=pre_target_ids,
            parent=self,
        )
        dlg.exec()
        self._refresh_table()

    def _populate_warmup_submenu(self, submenu, account_ids: list) -> None:
        """Fill a QMenu with warmup template choices."""
        templates = self._warmup_template_service.get_all_templates()
        if not templates:
            action = submenu.addAction("(no templates — configure in Settings)")
            action.setEnabled(False)
            return
        for tpl in templates:
            label = (
                f"{tpl.name}  (F:{tpl.follow_start} +{tpl.follow_increment}\u2192{tpl.follow_cap}, "
                f"L:{tpl.like_start} +{tpl.like_increment}\u2192{tpl.like_cap})"
            )
            # Factory to capture tpl.name in loop
            def _make_cb(name=tpl.name, ids=account_ids):
                return lambda: self._open_warmup_deploy(
                    pre_selected_ids=ids, pre_selected_template_name=name,
                )
            submenu.addAction(label, _make_cb())

    def _show_warmup_picker_for_account(self, account_id: int) -> None:
        """Show a popup menu to pick a warmup template for one account (from detail panel)."""
        if self._warmup_template_service is None:
            return
        menu = QMenu(self)
        self._populate_warmup_submenu(menu, [account_id])
        menu.exec(self.cursor().pos())

    def _open_warmup_deploy(
        self,
        pre_selected_ids: Optional[list] = None,
        pre_selected_template_name: Optional[str] = None,
    ) -> None:
        """Open the Warmup Deploy wizard dialog."""
        if self._warmup_template_service is None:
            return
        from oh.ui.warmup_deploy_dialog import WarmupDeployDialog
        dlg = WarmupDeployDialog(
            service=self._warmup_template_service,
            accounts=self._all_accounts,
            pre_selected_account_ids=pre_selected_ids,
            pre_selected_template_name=pre_selected_template_name,
            parent=self,
        )
        dlg.exec()
        self._refresh_table()

    def _on_find_sources(self, acc: AccountRecord) -> None:
        """Open the Source Finder dialog for an account."""
        bot_root = self._get_validated_root()
        if not bot_root:
            return

        hiker_key = self._settings.get("hiker_api_key") or ""
        if not hiker_key:
            QMessageBox.warning(
                self,
                "API Key Required",
                "HikerAPI key is not configured.\n\n"
                "Go to Settings tab and enter your HikerAPI key "
                "in the Source Finder section.",
            )
            return

        from oh.ui.source_finder_dialog import SourceFinderDialog

        dlg = SourceFinderDialog(
            self,
            self._source_finder_service,
            acc.id,
            acc.username,
            bot_root,
        )
        result = dlg.exec()
        if result == SourceFinderDialog.DialogCode.Accepted:
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
        os.startfile(str(folder))
        self._set_status(f"Opened: {folder}")

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        col = index.column()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data

        # Double-click on Trend column → open trend dialog
        if col == COL_TREND and kind == "account" and self._trend_service:
            acc = self._accounts.get_by_id(payload)
            if acc:
                from oh.ui.trend_dialog import TrendDialog
                dlg = TrendDialog(
                    self._trend_service, acc.id, acc.username,
                    acc.device_name or acc.device_id, parent=self,
                )
                dlg.exec()
            return

        # Double-click on any other column → open detail panel
        if kind in ("account", "orphan"):
            self._on_account_selected(index)

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

    def _on_export_csv(self) -> None:
        """Export visible (filtered) accounts table to CSV."""
        import csv

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Accounts", "oh_accounts.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                # Header
                headers = []
                for col in range(self._table.columnCount()):
                    hdr = self._table.horizontalHeaderItem(col)
                    headers.append(hdr.text() if hdr else "Col%d" % col)
                writer.writerow(headers)
                # Rows (only visible)
                for row in range(self._table.rowCount()):
                    if self._table.isRowHidden(row):
                        continue
                    row_data = []
                    for col in range(self._table.columnCount()):
                        item = self._table.item(row, col)
                        row_data.append(item.text() if item else "")
                    writer.writerow(row_data)

            self._set_status("Exported to %s" % path)
        except Exception as exc:
            QMessageBox.critical(self, "Export Failed", "Failed to export CSV:\n\n%s" % exc)

    # ------------------------------------------------------------------
    # Groups
    # ------------------------------------------------------------------

    def _on_manage_groups(self) -> None:
        """Open group management dialog."""
        if self._account_group_service is None or self._account_group_repo is None:
            QMessageBox.information(self, "Groups", "Group management is not available.")
            return
        from oh.ui.group_management_dialog import GroupManagementDialog
        dlg = GroupManagementDialog(
            self._account_group_service,
            self._all_accounts,
            parent=self,
        )
        dlg.exec()
        self._refresh_table()

    # ------------------------------------------------------------------
    # Error reporting
    # ------------------------------------------------------------------

    def _on_report_problem(self) -> None:
        """Open a dialog for the user to describe a problem, then send report."""
        if self._error_report_service is None:
            QMessageBox.information(
                self, "Report Problem",
                "Error reporting is not configured.",
            )
            return

        note, ok = QInputDialog.getMultiLineText(
            self, "Report Problem",
            "Describe what happened (optional).\n"
            "An anonymous report with technical logs will be sent.",
        )
        if not ok:
            return

        try:
            report = self._error_report_service.capture_manual(note or "")
            sent = self._error_report_service.send_report(report)
            if sent:
                self._set_status("Problem report sent successfully.")
                QMessageBox.information(
                    self, "Report Sent",
                    f"Report {report.report_id[:8]} sent. Thank you!",
                )
            else:
                self._set_status("Report saved locally (no endpoint configured or send failed).")
                QMessageBox.warning(
                    self, "Report Queued",
                    "Report saved locally. It will be sent when the endpoint is configured.",
                )
        except Exception as exc:
            logger.warning(f"Failed to create problem report: {exc}", exc_info=True)
            QMessageBox.critical(
                self, "Report Failed",
                f"Could not create report:\n\n{exc}",
            )

    def _start_guided_tour(self) -> None:
        """Launch the interactive guided tour overlay."""
        from oh.ui.guided_tour import GuidedTourOverlay
        overlay = GuidedTourOverlay(self._settings, parent=self)
        overlay.tour_finished.connect(overlay.deleteLater)
        overlay.show()
        overlay.raise_()

    def _set_status(self, message: str) -> None:
        self._statusbar.showMessage(message)
