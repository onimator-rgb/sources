"""
DeviceFleetTab — Device Fleet Dashboard.

Shows all devices with aggregated per-device metrics:
account count, active %, avg health score, source stats, and alerts.
"""
import logging
from datetime import date
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.account import AccountRecord, DeviceRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.session import AccountSessionRecord
from oh.repositories.account_repo import AccountRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
from oh.repositories.session_repo import SessionRepository
from oh.repositories.tag_repo import TagRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.services.account_health_service import AccountHealthService
from oh.ui.style import sc
from oh.ui.table_utils import SortableItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indexes — device table
# ---------------------------------------------------------------------------

_COL_DEVICE     = 0
_COL_STATUS     = 1
_COL_ACCOUNTS   = 2
_COL_ACTIVE     = 3
_COL_ACTIVE_PCT = 4
_COL_AVG_HEALTH = 5
_COL_AVG_FBR    = 6
_COL_SOURCES    = 7
_COL_REVIEW     = 8
_COL_LAST_SYNC  = 9

_HEADERS = [
    "Device", "Status", "Accounts", "Active", "Active %",
    "Avg Health", "Avg FBR%", "Avg Sources", "Review", "Last Sync",
]

# Column indexes — detail table (accounts on selected device)
_DET_USERNAME = 0
_DET_STATUS   = 1
_DET_HEALTH   = 2
_DET_SOURCES  = 3
_DET_FBR      = 4
_DET_TAGS     = 5

_DET_HEADERS = [
    "Username", "Status", "Health", "Active Sources", "Best FBR%", "Tags",
]


# ---------------------------------------------------------------------------
# DeviceFleetTab
# ---------------------------------------------------------------------------

class DeviceFleetTab(QWidget):
    def __init__(
        self,
        conn,
        account_health_service: Optional[AccountHealthService] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._conn = conn
        self._health_service = account_health_service or AccountHealthService()

        # Repositories
        self._account_repo = AccountRepository(conn)
        self._device_repo = DeviceRepository(conn)
        self._source_repo = SourceAssignmentRepository(conn)
        self._fbr_repo = FBRSnapshotRepository(conn)
        self._session_repo = SessionRepository(conn)
        self._tag_repo = TagRepository(conn)
        self._settings_repo = SettingsRepository(conn)

        self._loaded = False
        # Cache for detail pane
        self._device_accounts: Dict[str, List[AccountRecord]] = {}
        self._fbr_map: Dict[int, FBRSnapshotRecord] = {}
        self._source_count_map: Dict[int, int] = {}
        self._session_map: Dict[int, AccountSessionRecord] = {}
        self._op_tags_map: Dict[int, str] = {}

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 6, 0, 0)
        lo.setSpacing(6)

        lo.addWidget(self._make_toolbar())
        lo.addWidget(self._make_filter_bar())

        self._splitter = QSplitter(Qt.Orientation.Vertical)
        self._splitter.addWidget(self._make_device_table())
        self._splitter.addWidget(self._make_detail_pane())
        self._splitter.setStretchFactor(0, 3)
        self._splitter.setStretchFactor(1, 1)

        lo.addWidget(self._splitter, stretch=1)

    def _make_toolbar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 0, 8, 0)

        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedWidth(90)
        self._btn_refresh.clicked.connect(self._on_refresh)
        h.addWidget(self._btn_refresh)

        h.addSpacing(12)

        self._stats_label = QLabel("")
        h.addWidget(self._stats_label)
        h.addStretch()

        return bar

    def _make_filter_bar(self) -> QWidget:
        bar = QWidget()
        h = QHBoxLayout(bar)
        h.setContentsMargins(8, 0, 8, 0)

        self._status_combo = QComboBox()
        self._status_combo.setFixedWidth(120)
        self._status_combo.addItems(["All", "Online", "Offline"])
        self._status_combo.currentIndexChanged.connect(self._apply_filter)
        h.addWidget(self._status_combo)

        h.addSpacing(8)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search device...")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        h.addWidget(self._search_box)

        h.addStretch()

        self._count_label = QLabel("")
        h.addWidget(self._count_label)

        return bar

    def _make_device_table(self) -> QTableWidget:
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSortingEnabled(True)
        self._table.verticalHeader().setVisible(False)

        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)

        widths = {
            _COL_DEVICE: 160, _COL_STATUS: 80, _COL_ACCOUNTS: 80,
            _COL_ACTIVE: 70, _COL_ACTIVE_PCT: 75, _COL_AVG_HEALTH: 85,
            _COL_AVG_FBR: 80, _COL_SOURCES: 90, _COL_REVIEW: 70,
            _COL_LAST_SYNC: 150,
        }
        for col, w in widths.items():
            self._table.setColumnWidth(col, w)

        self._table.clicked.connect(self._on_device_selected)
        return self._table

    def _make_detail_pane(self) -> QWidget:
        wrapper = QWidget()
        lo = QVBoxLayout(wrapper)
        lo.setContentsMargins(0, 4, 0, 0)
        lo.setSpacing(4)

        self._detail_label = QLabel("Select a device to see its accounts.")
        lo.addWidget(self._detail_label)

        self._detail_table = QTableWidget(0, len(_DET_HEADERS))
        self._detail_table.setHorizontalHeaderLabels(_DET_HEADERS)
        self._detail_table.setAlternatingRowColors(True)
        self._detail_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._detail_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._detail_table.setSortingEnabled(True)
        self._detail_table.verticalHeader().setVisible(False)

        det_hdr = self._detail_table.horizontalHeader()
        det_hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        det_hdr.setStretchLastSection(True)

        det_widths = {
            _DET_USERNAME: 160, _DET_STATUS: 80, _DET_HEALTH: 70,
            _DET_SOURCES: 100, _DET_FBR: 80, _DET_TAGS: 200,
        }
        for col, w in det_widths.items():
            self._detail_table.setColumnWidth(col, w)

        lo.addWidget(self._detail_table, stretch=1)
        return wrapper

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """Public entry — called by MainWindow on tab switch."""
        try:
            devices = self._device_repo.get_all_active()
            all_accounts = self._account_repo.get_all()
            source_counts = self._source_repo.get_active_source_counts()
            fbr_map = self._fbr_repo.get_latest_map()
            today = date.today().isoformat()
            session_map = self._session_repo.get_map_for_date(today)
            op_tags_map = self._tag_repo.get_operator_tags_map()
        except Exception:
            logger.exception("Failed to load fleet data")
            self._stats_label.setText("Error loading fleet data.")
            return

        self._fbr_map = fbr_map
        self._source_count_map = source_counts
        self._session_map = session_map
        self._op_tags_map = op_tags_map
        self._loaded = True

        # Group accounts by device_id (include removed for total count)
        device_accounts: Dict[str, List[AccountRecord]] = {}
        for acc in all_accounts:
            device_accounts.setdefault(acc.device_id, []).append(acc)
        self._device_accounts = device_accounts

        self._populate_table(devices, device_accounts)
        self._update_stats_label(devices, all_accounts)

        # Clear detail pane
        self._detail_label.setText("Select a device to see its accounts.")
        self._detail_table.setRowCount(0)

    def _update_stats_label(
        self,
        devices: List[DeviceRecord],
        all_accounts: List[AccountRecord],
    ) -> None:
        n_devices = len(devices)
        active_accounts = [a for a in all_accounts if a.is_active]
        n_accounts = len(active_accounts)

        # Compute fleet-wide avg health
        health_scores: List[float] = []
        for acc in active_accounts:
            if acc.id is None:
                continue
            score = self._health_service.compute_score(
                account=acc,
                fbr=self._fbr_map.get(acc.id),
                session=self._session_map.get(acc.id),
                source_count=self._source_count_map.get(acc.id, 0),
                op_tags=self._op_tags_map.get(acc.id, ""),
            )
            health_scores.append(score)

        avg_health = sum(health_scores) / len(health_scores) if health_scores else 0.0
        self._stats_label.setText(
            f"{n_devices} devices, {n_accounts} active accounts, avg health {avg_health:.1f}"
        )

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(
        self,
        devices: List[DeviceRecord],
        device_accounts: Dict[str, List[AccountRecord]],
    ) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(devices))

        for row, dev in enumerate(devices):
            self._fill_device_row(row, dev, device_accounts.get(dev.device_id, []))

        self._table.setSortingEnabled(True)
        self._apply_filter()

    def _fill_device_row(
        self,
        row: int,
        dev: DeviceRecord,
        accounts: List[AccountRecord],
    ) -> None:
        active_accounts = [a for a in accounts if a.is_active]
        total = len(accounts)
        active = len(active_accounts)
        active_pct = (active / total * 100) if total > 0 else 0.0

        # Compute avg health
        health_scores: List[float] = []
        fbr_values: List[float] = []
        source_values: List[int] = []
        review_count = 0

        for acc in active_accounts:
            if acc.id is None:
                continue
            fbr = self._fbr_map.get(acc.id)
            session = self._session_map.get(acc.id)
            src_count = self._source_count_map.get(acc.id, 0)
            op_tags = self._op_tags_map.get(acc.id, "")

            score = self._health_service.compute_score(
                account=acc, fbr=fbr, session=session,
                source_count=src_count, op_tags=op_tags,
            )
            health_scores.append(score)

            if fbr is not None and fbr.best_fbr_pct is not None:
                fbr_values.append(fbr.best_fbr_pct)

            source_values.append(src_count)

            if acc.review_flag:
                review_count += 1

        avg_health = sum(health_scores) / len(health_scores) if health_scores else 0.0
        avg_fbr = sum(fbr_values) / len(fbr_values) if fbr_values else 0.0
        avg_sources = sum(source_values) / len(source_values) if source_values else 0.0

        # --- Device name ---
        item = QTableWidgetItem(dev.device_name or dev.device_id)
        item.setData(Qt.ItemDataRole.UserRole, dev.device_id)
        self._table.setItem(row, _COL_DEVICE, item)

        # --- Status ---
        status_str = dev.last_known_status or "unknown"
        is_online = status_str.lower() == "running"
        display_status = "Online" if is_online else "Offline"
        item = QTableWidgetItem(display_status)
        item.setForeground(sc("success") if is_online else sc("error"))
        self._table.setItem(row, _COL_STATUS, item)

        # --- Accounts ---
        item = SortableItem(str(total), total)
        self._table.setItem(row, _COL_ACCOUNTS, item)

        # --- Active ---
        item = SortableItem(str(active), active)
        self._table.setItem(row, _COL_ACTIVE, item)

        # --- Active % ---
        item = SortableItem(f"{active_pct:.0f}%", active_pct)
        if active_pct >= 90:
            item.setForeground(sc("success"))
        elif active_pct >= 70:
            item.setForeground(sc("warning"))
        else:
            item.setForeground(sc("error"))
        self._table.setItem(row, _COL_ACTIVE_PCT, item)

        # --- Avg Health ---
        item = SortableItem(f"{avg_health:.1f}", avg_health)
        if avg_health >= 70:
            item.setForeground(sc("success"))
        elif avg_health >= 40:
            item.setForeground(sc("warning"))
        else:
            item.setForeground(sc("error"))
        self._table.setItem(row, _COL_AVG_HEALTH, item)

        # --- Avg FBR ---
        item = SortableItem(f"{avg_fbr:.1f}" if fbr_values else "", avg_fbr)
        self._table.setItem(row, _COL_AVG_FBR, item)

        # --- Avg Sources ---
        item = SortableItem(f"{avg_sources:.1f}", avg_sources)
        self._table.setItem(row, _COL_SOURCES, item)

        # --- Review ---
        item = SortableItem(str(review_count) if review_count else "", review_count)
        if review_count > 0:
            item.setForeground(sc("warning"))
        self._table.setItem(row, _COL_REVIEW, item)

        # --- Last Sync ---
        sync_str = dev.last_synced_at or ""
        # Show only date+time portion if ISO format
        display_sync = sync_str[:19].replace("T", " ") if sync_str else ""
        item = SortableItem(display_sync, sync_str)
        self._table.setItem(row, _COL_LAST_SYNC, item)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        search = self._search_box.text().strip().lower()
        status_filter = self._status_combo.currentText()

        visible = 0
        for row in range(self._table.rowCount()):
            show = True

            # Status filter
            if status_filter != "All":
                status_item = self._table.item(row, _COL_STATUS)
                if status_item and status_item.text() != status_filter:
                    show = False

            # Search filter
            if show and search:
                device_item = self._table.item(row, _COL_DEVICE)
                if device_item and search not in device_item.text().lower():
                    show = False

            self._table.setRowHidden(row, not show)
            if show:
                visible += 1

        self._count_label.setText(f"{visible} shown")

    # ------------------------------------------------------------------
    # Detail pane — accounts for selected device
    # ------------------------------------------------------------------

    def _on_device_selected(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        device_item = self._table.item(row, _COL_DEVICE)
        if device_item is None:
            return

        device_id = device_item.data(Qt.ItemDataRole.UserRole)
        device_name = device_item.text()
        accounts = self._device_accounts.get(device_id, [])
        active_accounts = [a for a in accounts if a.is_active]

        self._detail_label.setText(
            f"Device: {device_name} — {len(active_accounts)} active accounts"
        )
        self._populate_detail_table(active_accounts)

    def _populate_detail_table(self, accounts: List[AccountRecord]) -> None:
        self._detail_table.setSortingEnabled(False)
        self._detail_table.setRowCount(len(accounts))

        for row, acc in enumerate(accounts):
            self._fill_detail_row(row, acc)

        self._detail_table.setSortingEnabled(True)

    def _fill_detail_row(self, row: int, acc: AccountRecord) -> None:
        # Username
        item = QTableWidgetItem(acc.username)
        self._detail_table.setItem(row, _DET_USERNAME, item)

        # Status
        status_text = "Active" if acc.is_active else "Removed"
        item = QTableWidgetItem(status_text)
        if not acc.is_active:
            item.setForeground(sc("muted"))
        self._detail_table.setItem(row, _DET_STATUS, item)

        # Health
        if acc.id is not None:
            score = self._health_service.compute_score(
                account=acc,
                fbr=self._fbr_map.get(acc.id),
                session=self._session_map.get(acc.id),
                source_count=self._source_count_map.get(acc.id, 0),
                op_tags=self._op_tags_map.get(acc.id, ""),
            )
            color_key = self._health_service.score_color_key(score)
            item = SortableItem(f"{score:.1f}", score)
            item.setForeground(sc(color_key))
        else:
            item = SortableItem("", 0.0)
        self._detail_table.setItem(row, _DET_HEALTH, item)

        # Active Sources
        src_count = self._source_count_map.get(acc.id, 0) if acc.id else 0
        item = SortableItem(str(src_count), src_count)
        self._detail_table.setItem(row, _DET_SOURCES, item)

        # Best FBR%
        fbr = self._fbr_map.get(acc.id) if acc.id else None
        if fbr is not None and fbr.best_fbr_pct is not None:
            item = SortableItem(f"{fbr.best_fbr_pct:.1f}", fbr.best_fbr_pct)
        else:
            item = SortableItem("", 0.0)
        self._detail_table.setItem(row, _DET_FBR, item)

        # Tags
        tags = self._op_tags_map.get(acc.id, "") if acc.id else ""
        item = QTableWidgetItem(tags)
        if tags:
            item.setForeground(sc("text_secondary"))
        self._detail_table.setItem(row, _DET_TAGS, item)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self.load_data()
