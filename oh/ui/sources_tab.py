"""
SourcesTab — global source aggregation view.

Shows all sources known across accounts, with per-source FBR metrics,
assignment counts, and drill-down to per-account detail.

Data is always read from the OH database (no disk access on open).
Use "Refresh Sources" to re-read sources.txt/data.db for all accounts.
"""
import csv
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter,
    QPushButton, QLabel, QLineEdit, QSpinBox, QComboBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QFileDialog, QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.models.global_source import GlobalSourceRecord, SourceAccountDetail
from oh.models.source_usage import SourceUsageRecord
from oh.modules.source_usage_reader import SourceUsageReader
from oh.services.global_sources_service import GlobalSourcesService
from oh.services.source_delete_service import SourceDeleteService
from oh.services.source_trend_service import SourceTrendService
from oh.ui.delete_confirm_dialog import DeleteConfirmDialog
from oh.ui.delete_history_dialog import DeleteHistoryDialog
from oh.ui.target_splitter_dialog import TargetSplitterDialog
from oh.ui.style import sc, BTN_HEIGHT_MD
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indexes — global sources table
# ---------------------------------------------------------------------------

_COL_SOURCE  = 0
_COL_ACTIVE  = 1
_COL_HIST    = 2
_COL_TOTAL   = 3
_COL_FOLLOWS = 4
_COL_FBACKS  = 5
_COL_AVG_FBR = 6
_COL_WTD_FBR = 7
_COL_QUALITY = 8
_COL_UPDATED = 9

_SOURCE_HEADERS = [
    "Source", "Active Accs", "Hist. Accs", "Total Accs",
    "Total Follows", "Followbacks", "Avg FBR %", "Wtd FBR %",
    "Quality", "Last Updated",
]

# Column indexes — detail pane
_D_USERNAME  = 0
_D_DEVICE    = 1
_D_ASSIGNED  = 2
_D_FOLLOWS   = 3
_D_FBACKS    = 4
_D_FBR       = 5
_D_QUALITY   = 6
_D_USED      = 7   # processed user count from sources/{name}.db
_D_USED_PCT  = 8   # used_count / total_source_followers * 100

_DETAIL_HEADERS = [
    "Username", "Device", "Assigned As",
    "Follows", "Followbacks", "FBR %", "Quality", "Used", "Used %",
]

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def _c_active():  return sc("success")
def _c_hist():    return sc("muted")
def _c_quality(): return sc("success")
def _c_low():     return sc("muted")
def _c_warn():    return sc("warning")
def _c_dim():     return sc("text_secondary")

# ---------------------------------------------------------------------------
# FBR quality filter values
# ---------------------------------------------------------------------------

_FILT_ALL       = "All sources"
_FILT_PERFORM   = "Performing"      # quality_account_count > 0
_FILT_ATTENTION = "Needs attention"  # active > 0 but quality_count == 0
_FILT_NO_DATA   = "No FBR data"     # total_follows == 0
_FILT_ACTIVE    = "Active only"      # active_accounts > 0


# ---------------------------------------------------------------------------
# Shared sortable item
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
# SourcesTab
# ---------------------------------------------------------------------------

class SourcesTab(QWidget):
    def __init__(
        self,
        global_sources_service: GlobalSourcesService,
        source_delete_service: SourceDeleteService,
        bulk_discovery_service=None,
        settings_repo=None,
        conn=None,
        target_splitter_service=None,
        account_group_repo=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service       = global_sources_service
        self._delete_svc    = source_delete_service
        self._bulk_discovery_svc = bulk_discovery_service
        self._settings_repo = settings_repo
        self._target_splitter_svc = target_splitter_service
        self._account_group_repo = account_group_repo
        self._trend_service: Optional[SourceTrendService] = (
            SourceTrendService(conn) if conn is not None else None
        )
        self._worker: Optional[WorkerThread] = None
        self._all_sources: list[GlobalSourceRecord] = []
        self._bot_root: Optional[str] = None
        self._history_dialog: Optional[DeleteHistoryDialog] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Bot root — updated by MainWindow when the user saves the path
    # ------------------------------------------------------------------

    def set_bot_root(self, bot_root: Optional[str]) -> None:
        self._bot_root = bot_root

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 6, 0, 0)
        lo.setSpacing(6)

        lo.addWidget(self._make_toolbar())
        lo.addWidget(self._make_filter_bar())

        splitter = QSplitter(Qt.Orientation.Vertical)
        splitter.addWidget(self._make_sources_table())
        splitter.addWidget(self._make_detail_pane())
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 1)
        lo.addWidget(splitter, stretch=1)

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        self._refresh_btn = QPushButton("⟳  Refresh Sources")
        self._refresh_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._refresh_btn.setToolTip(
            "Re-read sources.txt and data.db for all active accounts\n"
            "and update the source index.  Does not recompute FBR."
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        lo.addWidget(self._refresh_btn)

        lo.addSpacing(8)

        self._delete_btn = QPushButton("✕  Delete Source")
        self._delete_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._delete_btn.setEnabled(False)
        self._delete_btn.setToolTip(
            "Remove the selected source from sources.txt for all active accounts.\n"
            "Requires a source to be selected in the table."
        )
        self._delete_btn.setStyleSheet(
            f"QPushButton:enabled {{ color: {sc('error').name()}; }}"
            f"QPushButton:enabled:hover {{ background: #3a1a1a; }}"
        )
        self._delete_btn.clicked.connect(self._on_delete_source)
        lo.addWidget(self._delete_btn)

        self._bulk_delete_btn = QPushButton("⚠  Bulk Delete Weak Sources")
        self._bulk_delete_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._bulk_delete_btn.setToolTip(
            "Remove all sources whose weighted FBR is at or below the configured\n"
            "threshold from all active account assignments.\n"
            "Only sources with sufficient follow data are included."
        )
        self._bulk_delete_btn.setStyleSheet(
            f"QPushButton {{ color: {sc('warning').name()}; }}"
            f"QPushButton:hover {{ background: #2a2010; }}"
        )
        self._bulk_delete_btn.clicked.connect(self._on_bulk_delete)
        lo.addWidget(self._bulk_delete_btn)

        self._distribute_btn = QPushButton("Distribute Sources")
        self._distribute_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._distribute_btn.setToolTip(
            "Distribute a set of source names across multiple accounts.\n"
            "Supports even split and fill-up strategies with full preview."
        )
        self._distribute_btn.setStyleSheet(
            f"QPushButton {{ color: {sc('link').name()}; }}"
            f"QPushButton:hover {{ background: #1a2a3a; }}"
        )
        self._distribute_btn.clicked.connect(self._on_distribute_sources)
        lo.addWidget(self._distribute_btn)

        self._history_btn = QPushButton("History")
        self._history_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._history_btn.setToolTip("View source deletion history.")
        self._history_btn.clicked.connect(self._on_show_history)
        lo.addWidget(self._history_btn)

        lo.addSpacing(16)

        self._bulk_find_btn = QPushButton("Bulk Find Sources")
        self._bulk_find_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._bulk_find_btn.setToolTip(
            "Discover and add similar profiles in bulk for all accounts\n"
            "that have fewer active sources than the configured threshold."
        )
        self._bulk_find_btn.setStyleSheet(
            f"QPushButton {{ color: {sc('link').name()}; }}"
            f"QPushButton:hover {{ background: #1a2a3a; }}"
        )
        self._bulk_find_btn.clicked.connect(self._on_bulk_find_sources)
        lo.addWidget(self._bulk_find_btn)

        self._discovery_history_btn = QPushButton("Discovery History")
        self._discovery_history_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._discovery_history_btn.setToolTip("View past bulk source discovery runs.")
        self._discovery_history_btn.clicked.connect(self._on_show_discovery_history)
        lo.addWidget(self._discovery_history_btn)

        lo.addSpacing(8)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._export_btn.setToolTip("Export filtered follow source table to CSV file.")
        self._export_btn.clicked.connect(self._on_export_csv)
        lo.addWidget(self._export_btn)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet(f"font-style: italic; color: {sc('text_secondary').name()};")
        lo.addWidget(self._busy_label, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(f"color: {sc('muted').name()}; font-size: 11px;")
        lo.addWidget(self._status_label)
        return w

    def _make_filter_bar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(8)

        lo.addWidget(QLabel("Source:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("filter by name…")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        lo.addWidget(self._search_box)

        lo.addSpacing(4)
        lo.addWidget(QLabel("Min active accs:"))
        self._min_active = QSpinBox()
        self._min_active.setRange(0, 9999)
        self._min_active.setValue(0)
        self._min_active.setFixedWidth(60)
        self._min_active.setToolTip("Only show sources assigned to at least N active accounts")
        self._min_active.valueChanged.connect(self._apply_filter)
        lo.addWidget(self._min_active)

        lo.addSpacing(4)
        lo.addWidget(QLabel("Min follows:"))
        self._min_follows = QSpinBox()
        self._min_follows.setRange(0, 9_999_999)
        self._min_follows.setValue(0)
        self._min_follows.setSingleStep(100)
        self._min_follows.setFixedWidth(80)
        self._min_follows.setToolTip("Only show sources with at least N total follows across all accounts")
        self._min_follows.valueChanged.connect(self._apply_filter)
        lo.addWidget(self._min_follows)

        lo.addSpacing(4)
        lo.addWidget(QLabel("FBR:"))
        self._fbr_filter = QComboBox()
        self._fbr_filter.addItems([
            _FILT_ALL,
            _FILT_PERFORM,
            _FILT_ATTENTION,
            _FILT_NO_DATA,
            _FILT_ACTIVE,
        ])
        self._fbr_filter.setFixedWidth(150)
        self._fbr_filter.setToolTip(
            f"{_FILT_PERFORM}: at least one quality account uses this source\n"
            f"{_FILT_ATTENTION}: has active accounts but zero quality usage\n"
            f"{_FILT_NO_DATA}: total follows = 0 (no FBR data available yet)\n"
            f"{_FILT_ACTIVE}: at least one account currently has it in sources.txt"
        )
        self._fbr_filter.currentIndexChanged.connect(self._apply_filter)
        lo.addWidget(self._fbr_filter)

        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self._clear_filters)
        lo.addWidget(clear_btn)

        lo.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet(f"color: {sc('muted').name()}; font-size: 11px;")
        lo.addWidget(self._count_label)
        return w

    def _make_sources_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_SOURCE_HEADERS))
        t.setHorizontalHeaderLabels(_SOURCE_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        for col in range(1, len(_SOURCE_HEADERS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_COL_ACTIVE,   90)
        t.setColumnWidth(_COL_HIST,     80)
        t.setColumnWidth(_COL_TOTAL,    80)
        t.setColumnWidth(_COL_FOLLOWS,  100)
        t.setColumnWidth(_COL_FBACKS,   95)
        t.setColumnWidth(_COL_AVG_FBR,  80)
        t.setColumnWidth(_COL_WTD_FBR,  80)
        t.setColumnWidth(_COL_QUALITY,  75)
        t.setColumnWidth(_COL_UPDATED,  95)

        t.selectionModel().selectionChanged.connect(self._on_source_selected)
        self._sources_table = t
        return t

    def _make_detail_pane(self) -> QWidget:
        w = QWidget()
        lo = QVBoxLayout(w)
        lo.setContentsMargins(0, 4, 0, 0)
        lo.setSpacing(4)

        self._detail_header = QLabel(
            "Select a source above to see which accounts use it."
        )
        self._detail_header.setStyleSheet(f"color: {sc('muted').name()}; font-size: 11px; padding: 2px 4px;")
        lo.addWidget(self._detail_header)

        t = QTableWidget(0, len(_DETAIL_HEADERS))
        t.setHorizontalHeaderLabels(_DETAIL_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(_D_USERNAME, QHeaderView.ResizeMode.Stretch)
        for col in (_D_DEVICE, _D_ASSIGNED, _D_FOLLOWS, _D_FBACKS,
                    _D_FBR, _D_QUALITY, _D_USED, _D_USED_PCT):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_D_DEVICE,   110)
        t.setColumnWidth(_D_ASSIGNED, 100)
        t.setColumnWidth(_D_FOLLOWS,   80)
        t.setColumnWidth(_D_FBACKS,    90)
        t.setColumnWidth(_D_FBR,       70)
        t.setColumnWidth(_D_QUALITY,   70)
        t.setColumnWidth(_D_USED,      65)
        t.setColumnWidth(_D_USED_PCT,  65)

        self._detail_table = t
        lo.addWidget(t, stretch=1)
        return w

    # ------------------------------------------------------------------
    # Public interface — called by MainWindow
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """Reload source aggregates from DB. Called on tab activation and after refresh."""
        self._all_sources = self._service.get_global_sources()
        self._apply_filter()

        if not self._all_sources:
            self._set_status(
                "No source data yet. "
                "Run 'Analyze FBR' on the Accounts tab, or click 'Refresh Sources'."
            )
        else:
            self._set_status("")

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        query      = self._search_box.text().strip().lower()
        min_active = self._min_active.value()
        min_foll   = self._min_follows.value()
        fbr_filt   = self._fbr_filter.currentText()

        visible = []
        for src in self._all_sources:
            if query and query not in src.source_name.lower():
                continue
            if min_active > 0 and src.active_accounts < min_active:
                continue
            if min_foll > 0 and src.total_follows < min_foll:
                continue
            if not self._fbr_quality_matches(fbr_filt, src):
                continue
            visible.append(src)

        self._populate_sources_table(visible)
        self._count_label.setText(
            f"Showing {len(visible)} of {len(self._all_sources)} sources"
        )

    @staticmethod
    def _fbr_quality_matches(filt: str, src: GlobalSourceRecord) -> bool:
        if filt == _FILT_ALL:
            return True
        if filt == _FILT_ACTIVE:
            return src.active_accounts > 0
        if filt == _FILT_NO_DATA:
            return src.total_follows == 0
        if filt == _FILT_PERFORM:
            return src.quality_account_count > 0
        if filt == _FILT_ATTENTION:
            return src.active_accounts > 0 and src.quality_account_count == 0
        return True

    def _clear_filters(self) -> None:
        for widget in (self._search_box, self._min_active, self._min_follows, self._fbr_filter):
            widget.blockSignals(True)
        self._search_box.clear()
        self._min_active.setValue(0)
        self._min_follows.setValue(0)
        self._fbr_filter.setCurrentIndex(0)
        for widget in (self._search_box, self._min_active, self._min_follows, self._fbr_filter):
            widget.blockSignals(False)
        self._apply_filter()

    # ------------------------------------------------------------------
    # Sources table population
    # ------------------------------------------------------------------

    def _populate_sources_table(self, rows: list[GlobalSourceRecord]) -> None:
        self._sources_table.setSortingEnabled(False)
        self._sources_table.setRowCount(0)

        if not rows:
            self._sources_table.insertRow(0)
            if self._all_sources:
                msg_text = "No sources match the current filters."
            else:
                msg_text = (
                    "No source data. Run 'Analyze FBR' on the Accounts tab "
                    "or click 'Refresh Sources'."
                )
            msg = QTableWidgetItem(msg_text)
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._sources_table.setItem(0, 0, msg)
            self._sources_table.setSpan(0, 0, 1, len(_SOURCE_HEADERS))
            self._sources_table.setSortingEnabled(True)
            self._clear_detail_pane()
            return

        self._sources_table.setSpan(0, 0, 1, 1)
        center = Qt.AlignmentFlag.AlignCenter

        # Fetch FBR trends (once for the whole table)
        _trend_days = 14
        trends: dict = {}
        if self._trend_service is not None:
            try:
                trends = self._trend_service.get_source_trends(_trend_days)
            except Exception:
                logger.debug("Could not load source trends", exc_info=True)

        def _si(text: str, key, color: Optional[QColor] = None) -> _SortableItem:
            item = _SortableItem(text, key)
            item.setTextAlignment(center)
            if color:
                item.setForeground(color)
            return item

        for src in rows:
            r = self._sources_table.rowCount()
            self._sources_table.insertRow(r)

            # Source name — left-aligned, carries the name for detail lookup
            name_item = _SortableItem(src.source_name, src.source_name.lower())
            name_item.setData(Qt.ItemDataRole.UserRole, src.source_name)
            self._sources_table.setItem(r, _COL_SOURCE, name_item)

            # Account counts
            act_col = _c_active() if src.active_accounts > 0 else _c_dim()
            hst_col = _c_hist()   if src.historical_accounts > 0 else _c_dim()
            self._sources_table.setItem(r, _COL_ACTIVE, _si(str(src.active_accounts),   src.active_accounts,   act_col))
            self._sources_table.setItem(r, _COL_HIST,   _si(str(src.historical_accounts), src.historical_accounts, hst_col))
            self._sources_table.setItem(r, _COL_TOTAL,  _si(str(src.total_accounts),    src.total_accounts))

            # Volume
            self._sources_table.setItem(r, _COL_FOLLOWS, _si(f"{src.total_follows:,}",     src.total_follows))
            self._sources_table.setItem(r, _COL_FBACKS,  _si(f"{src.total_followbacks:,}", src.total_followbacks))

            # Avg FBR %
            if src.avg_fbr_pct is not None:
                avg_col = _c_quality() if src.avg_fbr_pct >= 10.0 else _c_low()
                self._sources_table.setItem(r, _COL_AVG_FBR, _si(f"{src.avg_fbr_pct:.1f}%", src.avg_fbr_pct, avg_col))
            else:
                self._sources_table.setItem(r, _COL_AVG_FBR, _si("—", -1.0, _c_dim()))

            # Weighted FBR %
            if src.weighted_fbr_pct is not None:
                wtd_col = _c_quality() if src.weighted_fbr_pct >= 10.0 else _c_low()
                wfbr_item = _si(f"{src.weighted_fbr_pct:.1f}%", src.weighted_fbr_pct, wtd_col)
            else:
                wfbr_item = _si("—", -1.0, _c_dim())

            # Apply trend tooltip to Wtd FBR cell
            trend_info = trends.get(src.source_name)
            if trend_info:
                _arrow = {"up": "\u2191", "down": "\u2193", "stable": "\u2192", "new": "\u2605"}.get(
                    trend_info["trend"], ""
                )
                wfbr_item.setToolTip(
                    f"{_arrow} {trend_info['change_pct']:+.1f}% vs {_trend_days}d ago"
                )
                if trend_info["trend"] == "down":
                    wfbr_item.setForeground(sc("error"))

            self._sources_table.setItem(r, _COL_WTD_FBR, wfbr_item)

            # Quality: quality_count / total_accounts
            if src.total_accounts > 0:
                q_text  = f"{src.quality_account_count}/{src.total_accounts}"
                q_color = _c_quality() if src.quality_account_count > 0 else _c_low()
            else:
                q_text  = "—"
                q_color = _c_dim()
            self._sources_table.setItem(r, _COL_QUALITY, _si(q_text, src.quality_account_count, q_color))

            # Last updated
            date_str  = src.last_analyzed_at[:10] if src.last_analyzed_at else "—"
            date_sort = src.last_analyzed_at[:10] if src.last_analyzed_at else ""
            self._sources_table.setItem(r, _COL_UPDATED, _si(date_str, date_sort, None if src.last_analyzed_at else _c_dim()))

        self._sources_table.setSortingEnabled(True)
        self._clear_detail_pane()

    # ------------------------------------------------------------------
    # Detail pane
    # ------------------------------------------------------------------

    def _on_source_selected(self) -> None:
        selected = self._sources_table.selectedItems()
        if not selected:
            self._delete_btn.setEnabled(False)
            self._clear_detail_pane()
            return

        row = selected[0].row()
        name_item = self._sources_table.item(row, _COL_SOURCE)
        if not name_item:
            self._delete_btn.setEnabled(False)
            self._clear_detail_pane()
            return

        source_name = name_item.data(Qt.ItemDataRole.UserRole)
        if not source_name:
            self._delete_btn.setEnabled(False)
            self._clear_detail_pane()
            return

        self._delete_btn.setEnabled(True)
        accounts = self._service.get_accounts_for_source(source_name)
        self._populate_detail_pane(source_name, accounts)

    def _clear_detail_pane(self) -> None:
        self._detail_table.setRowCount(0)
        self._detail_header.setText(
            "Select a source above to see which accounts use it."
        )

    def _populate_detail_pane(
        self, source_name: str, accounts: list[SourceAccountDetail]
    ) -> None:
        active_count = sum(1 for a in accounts if a.is_active)
        hist_count   = len(accounts) - active_count

        # Read per-account USED counts + USED % from source DB files (live disk read).
        # Also reads .stm percent files to derive used_pct.
        # Keyed by account_id (not username) to avoid collision when the same
        # username exists on different devices.
        usage_recs: dict[int, Optional[SourceUsageRecord]] = {}
        n_usage_found = 0
        n_pct_found   = 0
        total_used    = 0
        if self._bot_root:
            reader = SourceUsageReader(self._bot_root)
            for acc in accounts:
                if not acc.device_id:
                    usage_recs[acc.account_id] = None
                    continue
                rec = reader.read_single(
                    acc.device_id, acc.username, source_name, acc.follow_count
                )
                usage_recs[acc.account_id] = rec
                if rec.has_data:
                    n_usage_found += 1
                    total_used    += rec.used_count
                if rec.used_pct is not None:
                    n_pct_found += 1
            logger.info(
                f"[SourceUsage] detail pane for {source_name!r}: "
                f"{n_usage_found}/{len(accounts)} with used_count, "
                f"{n_pct_found} with used_pct — total_used={total_used}"
            )
        else:
            for acc in accounts:
                usage_recs[acc.account_id] = None

        # Build header line
        parts = [f"  {source_name}"]
        if active_count:
            parts.append(f"{active_count} active")
        if hist_count:
            parts.append(f"{hist_count} historical")
        if n_usage_found > 0:
            parts.append(f"total used: {total_used:,} across {n_usage_found} accs")
        self._detail_header.setText("  ·  ".join(parts))

        center = Qt.AlignmentFlag.AlignCenter
        right  = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        def _si(text: str, key, color: Optional[QColor] = None) -> _SortableItem:
            item = _SortableItem(text, key)
            item.setTextAlignment(center)
            if color:
                item.setForeground(color)
            return item

        self._detail_table.setSortingEnabled(False)
        self._detail_table.setRowCount(0)

        if not accounts:
            self._detail_table.insertRow(0)
            msg = QTableWidgetItem("No account data available for this source.")
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._detail_table.setItem(0, 0, msg)
            self._detail_table.setSpan(0, 0, 1, len(_DETAIL_HEADERS))
            self._detail_table.setSortingEnabled(True)
            return

        self._detail_table.setSpan(0, 0, 1, 1)

        for acc in accounts:
            r = self._detail_table.rowCount()
            self._detail_table.insertRow(r)

            # Username (left-aligned, coloured by assignment type)
            u_item = QTableWidgetItem(acc.username)
            u_item.setForeground(_c_active() if acc.is_active else _c_hist())
            self._detail_table.setItem(r, _D_USERNAME, u_item)

            # Device
            d_item = QTableWidgetItem(acc.device_name)
            d_item.setTextAlignment(center)
            d_item.setForeground(_c_dim())
            self._detail_table.setItem(r, _D_DEVICE, d_item)

            # Assignment type
            asgn_text  = "Active" if acc.is_active else "Historical"
            asgn_color = _c_active() if acc.is_active else _c_hist()
            a_item = QTableWidgetItem(asgn_text)
            a_item.setTextAlignment(center)
            a_item.setForeground(asgn_color)
            self._detail_table.setItem(r, _D_ASSIGNED, a_item)

            # Follows / followbacks
            self._detail_table.setItem(r, _D_FOLLOWS, _si(f"{acc.follow_count:,}",     acc.follow_count))
            self._detail_table.setItem(r, _D_FBACKS,  _si(f"{acc.followback_count:,}", acc.followback_count))

            # FBR %
            if acc.fbr_percent is not None:
                fbr_color = _c_quality() if acc.is_quality else _c_low()
                self._detail_table.setItem(r, _D_FBR, _si(f"{acc.fbr_percent:.1f}%", acc.fbr_percent, fbr_color))
            else:
                no_data = "—" if acc.last_analyzed_at else "Not analyzed"
                self._detail_table.setItem(r, _D_FBR, _si(no_data, -1.0, _c_dim()))

            # Quality
            if acc.last_analyzed_at:
                q_text  = "Yes" if acc.is_quality else "No"
                q_color = _c_quality() if acc.is_quality else _c_low()
                self._detail_table.setItem(r, _D_QUALITY, _si(q_text, 1 if acc.is_quality else 0, q_color))
            else:
                self._detail_table.setItem(r, _D_QUALITY, _si("—", -1, _c_dim()))

            # Used — COUNT(*) from sources/{source_name}.db for this account
            urec = usage_recs.get(acc.account_id)
            if urec is not None and urec.has_data:
                used_item = _SortableItem(f"{urec.used_count:,}", urec.used_count)
                used_item.setTextAlignment(right)
            else:
                used_item = _SortableItem("—", -1)
                used_item.setTextAlignment(center)
                used_item.setForeground(_c_dim())
            self._detail_table.setItem(r, _D_USED, used_item)

            # Used % — derived from .stm percent file + follows
            if urec is not None and urec.used_pct is not None:
                pct_item = _SortableItem(f"{urec.used_pct:.1f}%", urec.used_pct)
                pct_item.setTextAlignment(right)
                if urec.total_followers_derived is not None:
                    pct_item.setToolTip(
                        f"≈ {urec.used_count:,} processed / "
                        f"{urec.total_followers_derived:,} total followers"
                    )
            else:
                pct_item = _SortableItem("—", -1.0)
                pct_item.setTextAlignment(center)
                pct_item.setForeground(_c_dim())
            self._detail_table.setItem(r, _D_USED_PCT, pct_item)

        self._detail_table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Delete actions
    # ------------------------------------------------------------------

    def _get_selected_source_name(self) -> Optional[str]:
        selected = self._sources_table.selectedItems()
        if not selected:
            return None
        row = selected[0].row()
        item = self._sources_table.item(row, _COL_SOURCE)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_delete_source(self) -> None:
        if not self._bot_root:
            self._set_status("Bot root not set — configure the Onimator path first.")
            return

        source_name = self._get_selected_source_name()
        if not source_name:
            return

        assignments = self._delete_svc.get_active_assignments_for_source(source_name)
        if not assignments:
            self._set_status(f"No active assignments found for '{source_name}' — nothing to delete.")
            return

        dlg = DeleteConfirmDialog.for_single(source_name, assignments, parent=self)
        if dlg.exec() != DeleteConfirmDialog.DialogCode.Accepted:
            return

        self._set_busy(True, f"Deleting '{source_name}'…")
        bot_root    = self._bot_root
        svc         = self._delete_svc

        def do_delete():
            return svc.delete_source_globally(source_name, bot_root)

        self._worker = WorkerThread(do_delete)
        self._worker.result.connect(self._on_delete_done)
        self._worker.error.connect(self._on_delete_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_delete_done(self, result) -> None:
        self._set_status(result.summary_line())
        if result.errors:
            for err in result.errors:
                logger.warning(f"Delete error: {err}")
        self.load_data()
        # Signal parent to refresh source counts
        self._request_accounts_refresh()

    def _on_delete_error(self, error: str) -> None:
        logger.error(f"Delete worker error: {error}")
        self._set_status(f"Delete failed: {error}")

    def _on_bulk_delete(self) -> None:
        if not self._bot_root:
            self._set_status("Bot root not set — configure the Onimator path first.")
            return

        threshold = self._delete_svc.get_delete_threshold()
        sources   = self._delete_svc.preview_bulk_delete(threshold)

        if not sources:
            self._set_status(
                f"No sources found with weighted FBR ≤ {threshold:.1f}% "
                "and sufficient follow data.  Nothing to delete."
            )
            return

        dlg = DeleteConfirmDialog.for_bulk(threshold, sources, parent=self)
        if dlg.exec() != DeleteConfirmDialog.DialogCode.Accepted:
            return

        self._set_busy(True, f"Bulk-deleting {len(sources)} weak source(s)…")
        bot_root  = self._bot_root
        svc       = self._delete_svc

        def do_bulk():
            return svc.bulk_delete_weak_sources(threshold, bot_root)

        self._worker = WorkerThread(do_bulk)
        self._worker.result.connect(self._on_delete_done)
        self._worker.error.connect(self._on_delete_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_distribute_sources(self) -> None:
        """Open the Target Splitter wizard dialog."""
        if not self._bot_root:
            self._set_status(
                "Bot root not set — configure the Onimator path first."
            )
            return

        if self._target_splitter_svc is None:
            self._set_status("Distribute Sources is not available.")
            return

        # Pre-fill with selected source if any
        pre_selected: list = []
        selected = self._sources_table.selectedItems()
        if selected:
            seen: set = set()
            for item in selected:
                row = item.row()
                name_item = self._sources_table.item(row, _COL_SOURCE)
                if name_item:
                    name = name_item.data(Qt.ItemDataRole.UserRole)
                    if name and name not in seen:
                        pre_selected.append(name)
                        seen.add(name)

        dlg = TargetSplitterDialog(
            parent=self,
            service=self._target_splitter_svc,
            bot_root=self._bot_root,
            pre_selected_sources=pre_selected if pre_selected else None,
            account_group_repo=self._account_group_repo,
        )
        result = dlg.exec()
        if result == TargetSplitterDialog.DialogCode.Accepted:
            self.load_data()
            self._request_accounts_refresh()

    def _on_show_history(self) -> None:
        if self._history_dialog is None or not self._history_dialog.isVisible():
            def _handle_revert(action_id):
                if not self._bot_root:
                    raise ValueError("Bot root not set")
                return self._delete_svc.revert_action(action_id, self._bot_root)

            self._history_dialog = DeleteHistoryDialog(
                self._delete_svc.history_repo,
                on_revert=_handle_revert,
                parent=self,
            )
            self._history_dialog.finished.connect(self._on_history_closed)
            self._history_dialog.show()
        else:
            self._history_dialog.raise_()
            self._history_dialog.activateWindow()

    def _on_history_closed(self) -> None:
        """Reload sources tab data after history dialog closes (revert may have changed data)."""
        self.load_data()
        self._request_accounts_refresh()

    def _request_accounts_refresh(self) -> None:
        """Signal the main window to refresh account source counts."""
        # Walk up to MainWindow and call its refresh — loose coupling via parent traversal.
        p = self.parent()
        while p is not None:
            if hasattr(p, "_refresh_source_counts"):
                p._refresh_source_counts()
                break
            p = p.parent() if hasattr(p, "parent") else None

    # ------------------------------------------------------------------
    # Bulk Source Discovery
    # ------------------------------------------------------------------

    def _on_bulk_find_sources(self) -> None:
        """Open the Bulk Source Discovery wizard dialog."""
        if self._bulk_discovery_svc is None:
            return

        if not self._bot_root:
            QMessageBox.warning(
                self, "Bot Root Not Set",
                "Please set the Onimator installation path first.",
            )
            return

        hiker_key = ""
        if self._settings_repo is not None:
            hiker_key = self._settings_repo.get("hiker_api_key") or ""
        if not hiker_key:
            QMessageBox.warning(
                self, "API Key Required",
                "HikerAPI key is not configured.\n\n"
                "Go to Settings tab and enter your HikerAPI key "
                "in the Source Finder section.",
            )
            return

        min_threshold = 10
        if self._settings_repo is not None:
            min_threshold = int(self._settings_repo.get("min_source_for_bulk_discovery") or "10")

        try:
            qualifying = self._bulk_discovery_svc.get_qualifying_accounts(min_threshold)
        except Exception as exc:
            logger.error("Failed to get qualifying accounts: %s", exc)
            QMessageBox.critical(
                self, "Error",
                f"Failed to load qualifying accounts:\n\n{exc}",
            )
            return

        from oh.ui.bulk_discovery_dialog import BulkDiscoveryDialog
        dlg = BulkDiscoveryDialog(
            self,
            self._bulk_discovery_svc,
            qualifying,
            self._settings_repo,
        )
        dlg.exec()
        self.load_data()
        self._request_accounts_refresh()

    def _on_show_discovery_history(self) -> None:
        """Open the Bulk Discovery History dialog."""
        if self._bulk_discovery_svc is None:
            return

        from oh.ui.bulk_discovery_history_dialog import BulkDiscoveryHistoryDialog
        dlg = BulkDiscoveryHistoryDialog(self, self._bulk_discovery_svc)
        dlg.exec()
        self.load_data()
        self._request_accounts_refresh()

    # ------------------------------------------------------------------
    # Refresh (hits disk)
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        if not self._bot_root:
            self._set_status(
                "Bot root not set — configure the Onimator path on the Accounts tab first."
            )
            return

        self._set_busy(True, "Reading source files for all accounts…")
        bot_root = self._bot_root

        def do_refresh():
            return self._service.refresh_assignments(bot_root)

        self._worker = WorkerThread(do_refresh)
        self._worker.result.connect(self._on_refresh_done)
        self._worker.error.connect(self._on_refresh_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_refresh_done(self, result) -> None:
        self._set_status(result.status_line())
        self.load_data()

    def _on_refresh_error(self, error: str) -> None:
        logger.error(f"Source refresh error: {error}")
        self._set_status(f"Refresh failed: {error}")

    # ------------------------------------------------------------------
    # Export CSV
    # ------------------------------------------------------------------

    def _on_export_csv(self) -> None:
        if not self._all_sources:
            self._set_status("No data to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Follow Sources CSV", "follow_sources.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            # Get currently filtered data
            query = self._search_box.text().strip().lower()
            min_active = self._min_active.value()
            min_foll = self._min_follows.value()
            fbr_filt = self._fbr_filter.currentText()

            visible = []
            for src in self._all_sources:
                if query and query not in src.source_name.lower():
                    continue
                if min_active > 0 and src.active_accounts < min_active:
                    continue
                if min_foll > 0 and src.total_follows < min_foll:
                    continue
                if not self._fbr_quality_matches(fbr_filt, src):
                    continue
                visible.append(src)

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(_SOURCE_HEADERS)
                for src in visible:
                    writer.writerow([
                        src.source_name,
                        src.active_accounts,
                        src.historical_accounts,
                        src.total_accounts,
                        src.total_follows,
                        src.total_followbacks,
                        f"{src.avg_fbr_pct:.1f}" if src.avg_fbr_pct is not None else "",
                        f"{src.weighted_fbr_pct:.1f}" if src.weighted_fbr_pct is not None else "",
                        f"{src.quality_account_count}/{src.total_accounts}" if src.total_accounts > 0 else "",
                        src.last_analyzed_at[:10] if src.last_analyzed_at else "",
                    ])

            self._set_status(f"Exported {len(visible)} sources to {path}")
        except Exception as e:
            logger.error(f"CSV export failed: {e}")
            QMessageBox.critical(self, "Export Failed", str(e))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._refresh_btn.setEnabled(not busy)
        self._busy_label.setText(message if busy else "")

    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)
