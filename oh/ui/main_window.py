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
    QComboBox, QTabWidget, QFrame, QMessageBox, QMenu, QInputDialog,
    QSplitter, QApplication,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QPixmap, QKeyEvent

from datetime import date

from oh.models.account import AccountRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord, BatchFBRResult, SNAPSHOT_ERROR
from oh.models.session import AccountSessionRecord
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
from oh.ui.detail_drawer_controller import DetailDrawerController
from oh.ui.device_fleet_tab import DeviceFleetTab
from oh.ui.notifications_tab import NotificationsTab
from oh.services.notification_service import NotificationService
from oh.ui.settings_tab import SettingsTab
from oh.ui.source_dialog import SourceDialog
from oh.ui.source_profiles_tab import SourceProfilesTab
from oh.ui.sources_tab import SourcesTab
from oh.ui.like_sources_tab import LikeSourcesTab
from oh.ui.sources_tab_container import SourcesTabContainer
from oh.ui.accounts_toolbar import AccountsToolbar
from oh.ui.bulk_action_bar import BulkActionBar
from oh.ui.accounts_filter_bar import (
    AccountsFilterBar,
    FBR_FILTER_ALL, FBR_FILTER_ATTENTION, FBR_FILTER_NEVER,
    FBR_FILTER_ERRORS, FBR_FILTER_NO_QUALITY, FBR_FILTER_HAS_QUALITY,
    STATUS_FILTER_ACTIVE, STATUS_FILTER_REMOVED, STATUS_FILTER_ALL,
    TAGS_FILTER_ALL, TAGS_FILTER_TB, TAGS_FILTER_LIMITS,
    TAGS_FILTER_SLAVE, TAGS_FILTER_START, TAGS_FILTER_PK, TAGS_FILTER_CUSTOM,
    ACTIVITY_FILTER_ALL, ACTIVITY_FILTER_ZERO, ACTIVITY_FILTER_HAS,
    ACTIVITY_FILTER_BLOCKED,
    TIMESLOT_FILTER_ALL, TIMESLOT_FILTER_1, TIMESLOT_FILTER_2,
    TIMESLOT_FILTER_3, TIMESLOT_FILTER_4,
    HEALTH_FILTER_ALL, HEALTH_FILTER_GREEN, HEALTH_FILTER_YELLOW,
    HEALTH_FILTER_RED,
)
from oh.ui.workers import WorkerThread
from oh.repositories.source_profile_repo import SourceProfileRepository
from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
from oh.repositories.like_source_assignment_repo import LikeSourceAssignmentRepository
from oh.services.global_like_sources_service import GlobalLikeSourcesService
from oh.services.lbr_service import LBRService
from oh.services.settings_copier_service import SettingsCopierService
from oh.services.warmup_template_service import WarmupTemplateService
from oh.ui.accounts_table import (
    AccountsTable,
    COL_TIMESLOT, COL_USERNAME, COL_DEVICE, COL_HOURS, COL_STATUS, COL_TAGS,
    COL_FOLLOW, COL_UNFOLLOW, COL_LIMIT, COL_FOLLOW_TODAY, COL_LIKE_TODAY,
    COL_FOLLOW_LIM, COL_LIKE_LIM, COL_REVIEW, COL_DATA_DB, COL_SOURCES_TXT,
    COL_DISCOVERED, COL_LAST_SEEN, COL_SRC_COUNT, COL_FBR_QUALITY,
    COL_FBR_BEST, COL_FBR_DATE, COL_HEALTH, COL_TREND, COL_BLOCK, COL_GROUP,
    COL_ACTIONS, COLUMN_HEADERS,
)

from oh.ui.style import sc

logger = logging.getLogger(__name__)



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
        self._refresh_worker: Optional[WorkerThread] = None
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
        self._refresh_last_sync_label()

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

        # Table must be created before the filter bar (filter bar needs a ref)
        self._accounts_table = AccountsTable(parent=page)
        self._table = self._accounts_table.table  # convenience alias

        # Connect AccountsTable signals
        self._accounts_table.action_requested.connect(self._on_table_action_requested)
        self._accounts_table.view_sources_requested.connect(self._on_view_sources)
        self._accounts_table.open_folder_requested.connect(self._open_account_folder)
        self._accounts_table.find_sources_requested.connect(self._on_find_sources)
        self._accounts_table.copy_settings_requested.connect(
            lambda aid: self._open_settings_copier(pre_source_id=aid)
        )
        self._accounts_table.trend_double_clicked.connect(self._on_trend_double_clicked)
        self._accounts_table.row_double_clicked.connect(
            lambda index: self._drawer_ctrl._on_account_selected(index)
        )

        show_tips = (self._settings.get("show_help_tips") or "1") == "1"
        self._toolbar = AccountsToolbar(show_help_tips=show_tips, parent=page)
        self._toolbar.cockpit_requested.connect(self._on_cockpit)
        self._toolbar.scan_requested.connect(self._on_scan_and_sync)
        self._toolbar.fbr_requested.connect(self._on_analyze_fbr)
        self._toolbar.lbr_requested.connect(self._on_analyze_lbr)
        self._toolbar.refresh_requested.connect(self._refresh_table)
        self._toolbar.session_requested.connect(self._on_session_report)
        self._toolbar.recs_requested.connect(self._on_recommendations)
        self._toolbar.history_requested.connect(self._on_action_history)
        self._toolbar.export_csv_requested.connect(self._on_export_csv)
        self._toolbar.groups_requested.connect(self._on_manage_groups)
        self._toolbar.report_problem_requested.connect(self._on_report_problem)
        self._toolbar.cancel_requested.connect(self._on_cancel_worker)
        page_lo.addWidget(self._toolbar)

        self._filter_bar = AccountsFilterBar(
            settings_repo=self._settings,
            table=self._table,
            column_headers=COLUMN_HEADERS,
            always_visible_cols=self._ALWAYS_VISIBLE,
            col_labels=self._COL_LABELS,
            parent=page,
        )
        self._filter_bar.filters_changed.connect(self._apply_filter)
        self._filter_bar.apply_column_visibility()
        page_lo.addWidget(self._filter_bar)

        self._bulk_bar = BulkActionBar(parent=page)
        self._bulk_bar.bulk_action_requested.connect(self._bulk_action)
        self._bulk_bar.bulk_warmup_requested.connect(self._on_bulk_warmup)
        page_lo.addWidget(self._bulk_bar)

        # Build splitter: left = table, right = detail panel (hidden initially)
        self._accounts_splitter = QSplitter(Qt.Orientation.Horizontal)

        self._accounts_splitter.addWidget(self._accounts_table)

        self._detail_panel = AccountDetailPanel(service=self._account_detail_service)
        self._detail_panel.setVisible(False)
        self._accounts_splitter.addWidget(self._detail_panel)

        # Give the table most of the space; panel gets the rest
        self._accounts_splitter.setStretchFactor(0, 3)
        self._accounts_splitter.setStretchFactor(1, 1)

        # Detail drawer controller — manages panel lifecycle, data loading,
        # debounced navigation, and keyboard shortcuts.
        self._drawer_ctrl = DetailDrawerController(
            table=self._table,
            panel=self._detail_panel,
            conn=self._conn,
            accounts_repo=self._accounts,
            account_detail_service=self._account_detail_service,
            operator_action_repo=self._operator_action_repo,
            settings_repo=self._settings,
            parent=self,
        )
        self._drawer_ctrl.action_requested.connect(self._on_detail_action_requested)

        self._table.selectionModel().selectionChanged.connect(
            lambda: self._bulk_bar.update_selection(self._accounts_table.get_selected_account_ids_multi())
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

    # _make_toolbar extracted → oh/ui/accounts_toolbar.py (AccountsToolbar)

    def _bulk_action(self, action: str) -> None:
        """Execute a bulk action on all selected accounts."""
        ids = self._accounts_table.get_selected_account_ids_multi()
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
        ids = self._accounts_table.get_selected_account_ids_multi()
        if not ids:
            return
        menu = QMenu(self)
        self._populate_warmup_submenu(menu, ids)
        menu.exec(self.cursor().pos())

    # _make_table extracted → oh/ui/accounts_table.py (AccountsTable)

    # ------------------------------------------------------------------
    # Data loading and display
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        # Skip if a background refresh is already running
        if self._refresh_worker is not None and self._refresh_worker.isRunning():
            logger.debug("Refresh already in progress — skipping")
            return

        # Remember selection before refresh
        self._refresh_selected_id = self._accounts_table.get_selected_account_id()

        # Show loading indicator
        self._set_status("Loading accounts…")

        self._refresh_worker = WorkerThread(self._load_table_data)
        self._refresh_worker.result.connect(self._on_refresh_data_loaded)
        self._refresh_worker.error.connect(self._on_refresh_error)
        self._refresh_worker.start()

    def _load_table_data(self) -> dict:
        """Load all table data from DB/services (runs in background thread).

        Returns a dict with all the data needed to populate the table.
        """
        data: dict = {}
        data["all_accounts"] = self._accounts.get_all()
        data["fbr_map"] = self._fbr_service.get_latest_map()
        data["source_count_map"] = self._global_sources_service.get_active_source_counts()

        if self._session_service:
            data["session_map"] = self._session_service.get_session_map(
                date.today().isoformat()
            )
        else:
            data["session_map"] = {}

        # Operator tags
        if self._tag_repo:
            try:
                data["op_tags_map"] = self._tag_repo.get_operator_tags_map()
            except Exception:
                data["op_tags_map"] = {}
        else:
            data["op_tags_map"] = {}

        # Device status map
        try:
            rows = self._conn.execute(
                "SELECT device_id, last_known_status FROM oh_devices"
            ).fetchall()
            data["device_status_map"] = {r[0]: r[1] for r in rows}
        except Exception:
            data["device_status_map"] = {}

        # Block map
        if self._block_detection_service:
            try:
                data["block_map"] = self._block_detection_service.get_active_blocks()
            except Exception:
                data["block_map"] = {}
        else:
            data["block_map"] = {}

        # Group membership map
        if self._account_group_repo:
            try:
                data["group_map"] = self._account_group_repo.get_membership_map()
            except Exception:
                data["group_map"] = {}
        else:
            data["group_map"] = {}

        # Trend data
        if self._trend_service:
            try:
                active_ids = [a.id for a in data["all_accounts"]
                              if a.is_active and a.id]
                data["trend_map"] = self._trend_service.get_trends_map(
                    active_ids, days=14,
                )
            except Exception:
                data["trend_map"] = {}
        else:
            data["trend_map"] = {}

        return data

    def _on_refresh_data_loaded(self, data: dict) -> None:
        """Apply loaded data to instance state and populate the table (main thread)."""
        self._refresh_worker = None

        # Apply data to instance variables
        self._all_accounts = data["all_accounts"]
        self._fbr_map = data["fbr_map"]
        self._source_count_map = data["source_count_map"]
        self._session_map = data["session_map"]
        self._op_tags_map = data["op_tags_map"]
        self._device_status_map = data["device_status_map"]
        self._block_map = data["block_map"]
        self._group_map = data["group_map"]
        self._trend_map = data["trend_map"]

        # Populate UI (must run on main thread)
        self._update_device_filter()
        self._apply_filter()
        self._refresh_last_sync_label()

        # Restore selection
        selected_id = getattr(self, "_refresh_selected_id", None)
        if selected_id is not None:
            self._accounts_table.select_account_by_id(selected_id)

        # Update drawer controller data context and reload if open
        if hasattr(self, '_drawer_ctrl'):
            self._drawer_ctrl.set_data_context(
                all_accounts=self._all_accounts,
                fbr_map=self._fbr_map,
                lbr_map=self._lbr_map,
                source_count_map=self._source_count_map,
                session_map=self._session_map,
                device_status_map=self._device_status_map,
                op_tags_map=self._op_tags_map,
            )
            self._drawer_ctrl.reload_current()

        self._set_status("Ready.")

    def _on_refresh_error(self, error_msg: str) -> None:
        """Handle background refresh failure."""
        self._refresh_worker = None
        logger.error("Background table refresh failed: %s", error_msg)
        self._set_status(f"Refresh failed: {error_msg}")

    # ------------------------------------------------------------------
    # Keyboard shortcuts
    # ------------------------------------------------------------------

    def keyPressEvent(self, event: QKeyEvent) -> None:
        """Delegate drawer-related keys to the controller, pass the rest up."""
        if hasattr(self, '_drawer_ctrl') and self._drawer_ctrl.handle_key_press(event):
            return
        super().keyPressEvent(event)

    # ------------------------------------------------------------------
    # Detail panel — action dispatch (stays in MainWindow because
    # actions call MainWindow methods like _do_set_review, etc.)
    # ------------------------------------------------------------------

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
            self._drawer_ctrl.copy_diagnostic(acc)
        elif action_type == "apply_warmup":
            self._show_warmup_picker_for_account(acc.id)
        else:
            logger.warning("Unknown detail panel action: %s", action_type)
            return

        # After any action completes, reload the drawer so it reflects new state.
        if action_type not in ("open_folder", "copy_diagnostic", "apply_warmup", "open_sources"):
            self._drawer_ctrl.reload_current()

    def _refresh_source_counts(self) -> None:
        """Called by SourcesTab (via parent-chain walk) after a delete operation."""
        self._source_count_map = self._global_sources_service.get_active_source_counts()
        self._apply_filter()

    def _update_device_filter(self) -> None:
        """Rebuild the device dropdown from the current account list."""
        seen: set = set()
        devices: list = []
        for acc in self._all_accounts:
            label = acc.device_name or acc.device_id
            if label and label not in seen:
                seen.add(label)
                devices.append(label)
        self._filter_bar.update_device_list(devices)
        # Also rebuild group filter
        self._update_group_filter()

    def _update_group_filter(self) -> None:
        """Rebuild the group dropdown from current groups."""
        group_names: list = []
        if self._account_group_repo:
            try:
                groups = self._account_group_repo.get_all_groups()
                group_names = [g.name for g in groups]
            except Exception:
                pass
        self._filter_bar.update_group_list(group_names)

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

    # _get_slot_number extracted → oh/ui/accounts_table.py (AccountsTable._get_slot_number)

    @staticmethod
    def _fbr_filter_matches(filt: str, snap: Optional[FBRSnapshotRecord]) -> bool:
        """Return True if the account should be included under the given FBR filter."""
        if filt == FBR_FILTER_ALL:
            return True
        if filt == FBR_FILTER_NEVER:
            return snap is None
        if filt == FBR_FILTER_ERRORS:
            return snap is not None and snap.status == SNAPSHOT_ERROR
        if filt == FBR_FILTER_NO_QUALITY:
            return snap is None or snap.quality_sources == 0
        if filt == FBR_FILTER_HAS_QUALITY:
            return snap is not None and snap.quality_sources > 0
        if filt == FBR_FILTER_ATTENTION:
            # needs attention = never analyzed OR zero quality sources
            return snap is None or snap.quality_sources == 0
        return True

    def _build_data_context(self) -> dict:
        """Build the data_context dict for AccountsTable.populate()."""
        accounts_by_id = {}
        for acc in self._all_accounts:
            if acc.id is not None:
                accounts_by_id[acc.id] = acc
        return {
            "device_status_map": self._device_status_map,
            "op_tags_map": self._op_tags_map,
            "session_map": self._session_map,
            "source_count_map": self._source_count_map,
            "fbr_map": self._fbr_map,
            "block_map": self._block_map,
            "group_map": self._group_map,
            "trend_map": self._trend_map,
            "min_source_count_warning": self._settings.get_min_source_count_warning(),
            "has_operator_action_service": self._operator_action_service is not None,
            "has_source_finder_service": self._source_finder_service is not None,
            "has_settings_copier_service": self._settings_copier_service is not None,
            "has_warmup_template_service": self._warmup_template_service is not None,
            "has_trend_service": self._trend_service is not None,
            "populate_warmup_submenu": self._populate_warmup_submenu,
            "accounts_by_id": accounts_by_id,
        }

    def _apply_filter(self) -> None:
        fs            = self._filter_bar.get_filter_state()
        status_filt   = fs["status"]
        fbr_filt      = fs["fbr"]
        device_filt   = fs["device"]
        tags_filt     = fs["tags"]
        activity_filt = fs["activity"]
        group_filt    = fs["group"]
        timeslot_filt = fs["timeslot"]
        health_filt   = fs["health"]
        review_only   = fs["review_only"]
        query         = fs["query"]
        show_orphans  = fs["show_orphans"]

        # Map timeslot filter to slot number for comparison
        _slot_number_map = {
            TIMESLOT_FILTER_1: 1, TIMESLOT_FILTER_2: 2,
            TIMESLOT_FILTER_3: 3, TIMESLOT_FILTER_4: 4,
        }
        required_slot = _slot_number_map.get(timeslot_filt)

        active_accounts = [a for a in self._all_accounts if a.is_active]
        total_active    = len(active_accounts)

        rows: list = []

        for acc in self._all_accounts:
            # --- status dimension ---
            if status_filt == STATUS_FILTER_ACTIVE and not acc.is_active:
                continue
            if status_filt == STATUS_FILTER_REMOVED and acc.is_active:
                continue

            # --- device dimension ---
            if device_filt != "All devices":
                label = acc.device_name or acc.device_id
                if label != device_filt:
                    continue

            # --- timeslot dimension ---
            if required_slot is not None:
                acc_slot = AccountsTable._get_slot_number(acc)
                if acc_slot != required_slot:
                    continue

            # --- health dimension ---
            if health_filt != HEALTH_FILTER_ALL and acc.id is not None:
                snap_h = self._fbr_map.get(acc.id) if acc.id is not None else None
                sess_h = self._session_map.get(acc.id) if acc.id is not None else None
                src_h = self._source_count_map.get(acc.id, 0)
                op_h = self._op_tags_map.get(acc.id) if acc.id else None
                min_h = self._settings.get_min_source_count_warning()
                score = AccountHealthService.compute_score(
                    acc, snap_h, sess_h, src_h, op_h or "", min_h,
                )
                if health_filt == HEALTH_FILTER_GREEN and score < 70:
                    continue
                if health_filt == HEALTH_FILTER_YELLOW and (score < 40 or score >= 70):
                    continue
                if health_filt == HEALTH_FILTER_RED and score >= 40:
                    continue

            # --- FBR dimension ---
            snap = self._fbr_map.get(acc.id) if acc.id is not None else None
            if not self._fbr_filter_matches(fbr_filt, snap):
                continue

            # --- tags dimension ---
            if tags_filt != TAGS_FILTER_ALL:
                raw = (acc.bot_tags_raw or "").upper()
                if tags_filt == TAGS_FILTER_TB and "TB" not in raw:
                    continue
                elif tags_filt == TAGS_FILTER_LIMITS and "[" not in raw:
                    continue
                elif tags_filt == TAGS_FILTER_SLAVE and "SLAVE" not in raw:
                    continue
                elif tags_filt == TAGS_FILTER_START and "START" not in raw:
                    continue
                elif tags_filt == TAGS_FILTER_PK and " PK" not in raw and raw != "PK":
                    continue
                elif tags_filt == TAGS_FILTER_CUSTOM:
                    # custom = has tags but none of the known keywords
                    known = {"SLAVE", "AI", "START", "PK"}
                    tokens = raw.split("]")[-1].split() if "]" in raw else raw.split()
                    if not any(t for t in tokens if t not in known and not t.startswith("TB")):
                        continue

            # --- review dimension ---
            if review_only and not acc.review_flag:
                continue

            # --- activity dimension ---
            if activity_filt != ACTIVITY_FILTER_ALL and acc.id is not None:
                if activity_filt == ACTIVITY_FILTER_BLOCKED:
                    if acc.id not in self._block_map:
                        continue
                else:
                    sess = self._session_map.get(acc.id)
                    has_act = sess.has_activity if sess else False
                    if activity_filt == ACTIVITY_FILTER_ZERO and has_act:
                        continue
                    if activity_filt == ACTIVITY_FILTER_HAS and not has_act:
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

        self._accounts_table.populate(rows, self._build_data_context())

        shown = len(rows)
        total = len(self._all_accounts)
        if status_filt == STATUS_FILTER_ACTIVE:
            total = total_active
        self._filter_bar.set_count_text(f"Showing {shown} of {total} accounts")

    # _populate_table extracted → oh/ui/accounts_table.py (AccountsTable.populate)

    def _refresh_last_sync_label(self) -> None:
        run = self._sync_repo.get_latest_run()
        if run:
            date = run.completed_at[:16].replace("T", "  ") if run.completed_at else "—"
            self._toolbar.update_last_sync(f"Last sync: {date}")
        else:
            self._toolbar.update_last_sync("Last sync: never")

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
        self._worker.cancelled.connect(self._on_worker_cancelled)
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
        self._toolbar.set_busy_message("Syncing registry…")

        def do_sync():
            return self._scan_service.sync(discovered)

        self._worker = WorkerThread(do_sync)
        self._worker.result.connect(self._on_sync_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.cancelled.connect(self._on_worker_cancelled)
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
        self._worker.cancelled.connect(self._on_worker_cancelled)
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
        self._worker.cancelled.connect(self._on_worker_cancelled)
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
        self._accounts_table.select_account_by_id(account_id)
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

    # _on_table_context_menu, _show_action_menu, _show_orphan_action_menu
    # extracted → oh/ui/accounts_table.py (AccountsTable)

    def _on_table_action_requested(self, action_type: str, acc_or_id) -> None:
        """Dispatch action requests from AccountsTable signals."""
        # acc_or_id is an AccountRecord (from action menu / context menu)
        acc = acc_or_id
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
        else:
            logger.warning("Unknown table action: %s", action_type)

    def _on_trend_double_clicked(self, account_id: int) -> None:
        """Handle double-click on the Trend column."""
        if not self._trend_service:
            return
        acc = self._accounts.get_by_id(account_id)
        if acc:
            from oh.ui.trend_dialog import TrendDialog
            dlg = TrendDialog(
                self._trend_service, acc.id, acc.username,
                acc.device_name or acc.device_id, parent=self,
            )
            dlg.exec()

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

    # _on_row_double_clicked extracted → oh/ui/accounts_table.py (AccountsTable)

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

    def _on_cancel_worker(self) -> None:
        """Cancel the currently running background operation."""
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._toolbar.set_busy_message("Cancelling…")
            self._toolbar.set_cancel_enabled(False)

    def _on_worker_cancelled(self) -> None:
        """Handle the cancelled signal from WorkerThread."""
        self._set_busy(False)
        self._set_status("Operation cancelled.")
        logger.info("Background operation cancelled by operator")

    def _on_worker_error(self, error: str) -> None:
        self._set_busy(False)
        logger.error(f"Background worker error: {error}")
        QMessageBox.critical(self, "Operation Failed", error)

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._toolbar.set_busy(busy, message)
        if not busy:
            self._worker = None
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
