"""
LikeSourcesTab — global like source aggregation view.

Shows all like sources known across accounts, with per-source LBR metrics,
assignment counts, and drill-down to per-account detail.

Data is always read from the OH database (no disk access on open).
Use "Analyze LBR" to compute Like-Back Rate for all accounts.
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

from oh.models.global_like_source import GlobalLikeSourceRecord, LikeSourceAccountDetail
from oh.services.global_like_sources_service import GlobalLikeSourcesService
from oh.services.lbr_service import LBRService
from oh.ui.style import sc, BTN_HEIGHT_MD
from oh.ui.table_utils import SortableItem
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indexes — global like sources table
# ---------------------------------------------------------------------------

_COL_SOURCE  = 0
_COL_ACTIVE  = 1
_COL_HIST    = 2
_COL_LIKES   = 3
_COL_FBACKS  = 4
_COL_AVG_LBR = 5
_COL_WTD_LBR = 6
_COL_QUALITY = 7
_COL_UPDATED = 8

_SOURCE_HEADERS = [
    "Source", "Active Accs", "Hist. Accs",
    "Total Likes", "Followbacks", "Avg LBR %", "Wtd LBR %",
    "Quality", "Last Updated",
]

# Column indexes — detail pane
_D_USERNAME = 0
_D_DEVICE   = 1
_D_LIKES    = 2
_D_FBACKS   = 3
_D_LBR      = 4
_D_QUALITY  = 5
_D_ACTIVE   = 6

_DETAIL_HEADERS = [
    "Username", "Device", "Likes", "Followbacks",
    "LBR %", "Quality", "Active",
]

# ---------------------------------------------------------------------------
# Palette helpers
# ---------------------------------------------------------------------------

def _c_active():  return sc("success")
def _c_hist():    return sc("muted")
def _c_quality(): return sc("success")
def _c_low():     return sc("muted")
def _c_dim():     return sc("text_secondary")

# ---------------------------------------------------------------------------
# LBR quality filter values
# ---------------------------------------------------------------------------

_FILT_ALL       = "All sources"
_FILT_QUALITY   = "Quality only"
_FILT_ATTENTION = "Needs attention"
_FILT_NO_DATA   = "No LBR data"
_FILT_ACTIVE    = "Active only"




# ---------------------------------------------------------------------------
# LikeSourcesTab
# ---------------------------------------------------------------------------

class LikeSourcesTab(QWidget):
    def __init__(
        self,
        global_like_sources_service: GlobalLikeSourcesService,
        lbr_service: LBRService,
        settings_repo=None,
        conn=None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service     = global_like_sources_service
        self._lbr_service = lbr_service
        self._settings_repo = settings_repo
        self._worker: Optional[WorkerThread] = None
        self._all_sources: list = []
        self._bot_root: Optional[str] = None

        self._build_ui()

    # ------------------------------------------------------------------
    # Bot root — updated by container when the user saves the path
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

        self._refresh_btn = QPushButton("Refresh")
        self._refresh_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._refresh_btn.setToolTip(
            "Reload like source data from the OH database."
        )
        self._refresh_btn.clicked.connect(self._on_refresh)
        lo.addWidget(self._refresh_btn)

        self._analyze_btn = QPushButton("Analyze LBR")
        self._analyze_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._analyze_btn.setToolTip(
            "Run LBR analysis for all active accounts that have likes.db\n"
            "and save results to the OH database."
        )
        self._analyze_btn.clicked.connect(self._on_analyze_lbr)
        lo.addWidget(self._analyze_btn)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._export_btn.setToolTip("Export filtered like source table to CSV file.")
        self._export_btn.clicked.connect(self._on_export_csv)
        lo.addWidget(self._export_btn)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet(
            f"font-style: italic; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(self._busy_label, stretch=1)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet(
            f"color: {sc('muted').name()}; font-size: 11px;"
        )
        lo.addWidget(self._status_label)
        return w

    def _make_filter_bar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(8)

        lo.addWidget(QLabel("Source:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("filter by name...")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filters)
        lo.addWidget(self._search_box)

        lo.addSpacing(4)
        lo.addWidget(QLabel("Min active accs:"))
        self._min_active = QSpinBox()
        self._min_active.setRange(0, 9999)
        self._min_active.setValue(1)
        self._min_active.setFixedWidth(60)
        self._min_active.setToolTip("Only show sources assigned to at least N active accounts")
        self._min_active.valueChanged.connect(self._apply_filters)
        lo.addWidget(self._min_active)

        lo.addSpacing(4)
        lo.addWidget(QLabel("Min likes:"))
        self._min_likes = QSpinBox()
        self._min_likes.setRange(0, 9_999_999)
        self._min_likes.setValue(20)
        self._min_likes.setSingleStep(10)
        self._min_likes.setFixedWidth(80)
        self._min_likes.setToolTip("Only show sources with at least N total likes across all accounts")
        self._min_likes.valueChanged.connect(self._apply_filters)
        lo.addWidget(self._min_likes)

        lo.addSpacing(4)
        lo.addWidget(QLabel("LBR:"))
        self._lbr_filter = QComboBox()
        self._lbr_filter.addItems([
            _FILT_ALL,
            _FILT_QUALITY,
            _FILT_ATTENTION,
            _FILT_NO_DATA,
            _FILT_ACTIVE,
        ])
        self._lbr_filter.setFixedWidth(150)
        self._lbr_filter.setToolTip(
            f"{_FILT_QUALITY}: at least one quality account uses this source\n"
            f"{_FILT_ATTENTION}: has active accounts but zero quality usage\n"
            f"{_FILT_NO_DATA}: total likes = 0 (no LBR data available yet)\n"
            f"{_FILT_ACTIVE}: at least one account currently has it in like-source-followers.txt"
        )
        self._lbr_filter.currentIndexChanged.connect(self._apply_filters)
        lo.addWidget(self._lbr_filter)

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
        t.setColumnWidth(_COL_LIKES,    100)
        t.setColumnWidth(_COL_FBACKS,   95)
        t.setColumnWidth(_COL_AVG_LBR,  80)
        t.setColumnWidth(_COL_WTD_LBR,  80)
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
        self._detail_header.setStyleSheet(
            f"color: {sc('muted').name()}; font-size: 11px; padding: 2px 4px;"
        )
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
        for col in (_D_DEVICE, _D_LIKES, _D_FBACKS, _D_LBR, _D_QUALITY, _D_ACTIVE):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(_D_DEVICE,   110)
        t.setColumnWidth(_D_LIKES,     80)
        t.setColumnWidth(_D_FBACKS,    90)
        t.setColumnWidth(_D_LBR,       70)
        t.setColumnWidth(_D_QUALITY,   70)
        t.setColumnWidth(_D_ACTIVE,    70)

        self._detail_table = t
        lo.addWidget(t, stretch=1)
        return w

    # ------------------------------------------------------------------
    # Public interface — called by container / MainWindow
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """Reload like source aggregates from DB."""
        self._all_sources = self._service.get_all()
        self._apply_filters()

        if not self._all_sources:
            self._set_status(
                "No like source data yet. "
                "Run 'Analyze LBR' to compute Like-Back Rate for all accounts."
            )
        else:
            self._set_status("")

    # ------------------------------------------------------------------
    # Analyze LBR
    # ------------------------------------------------------------------

    def _on_analyze_lbr(self) -> None:
        if not self._bot_root:
            self._set_status(
                "Bot root not set — configure the Onimator path first."
            )
            return

        self._set_busy(True, "Running LBR analysis...")

        bot_root = self._bot_root
        svc = self._lbr_service

        def do_lbr():
            return svc.analyze_all_active(bot_root)

        self._worker = WorkerThread(do_lbr)
        self._worker.result.connect(self._on_lbr_done)
        self._worker.error.connect(self._on_lbr_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_lbr_done(self, result) -> None:
        self._set_status(f"LBR analysis complete — {result.status_line()}")
        self.load_data()

    def _on_lbr_error(self, error: str) -> None:
        logger.error(f"LBR analysis error: {error}")
        self._set_status(f"LBR analysis failed: {error}")

    # ------------------------------------------------------------------
    # Refresh (re-read from DB, no disk access)
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self.load_data()

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filters(self) -> None:
        query      = self._search_box.text().strip().lower()
        min_active = self._min_active.value()
        min_likes  = self._min_likes.value()
        lbr_filt   = self._lbr_filter.currentText()

        visible = []
        for src in self._all_sources:
            if query and query not in src.source_name.lower():
                continue
            if min_active > 0 and src.active_accounts < min_active:
                continue
            if min_likes > 0 and src.total_likes < min_likes:
                continue
            if not self._lbr_quality_matches(lbr_filt, src):
                continue
            visible.append(src)

        self._populate_sources_table(visible)
        self._count_label.setText(
            f"Showing {len(visible)} of {len(self._all_sources)} sources"
        )

    @staticmethod
    def _lbr_quality_matches(filt: str, src: GlobalLikeSourceRecord) -> bool:
        if filt == _FILT_ALL:
            return True
        if filt == _FILT_ACTIVE:
            return src.active_accounts > 0
        if filt == _FILT_NO_DATA:
            return src.total_likes == 0
        if filt == _FILT_QUALITY:
            return src.quality_account_count > 0
        if filt == _FILT_ATTENTION:
            return src.active_accounts > 0 and src.quality_account_count == 0
        return True

    def _clear_filters(self) -> None:
        for widget in (self._search_box, self._min_active, self._min_likes, self._lbr_filter):
            widget.blockSignals(True)
        self._search_box.clear()
        self._min_active.setValue(1)
        self._min_likes.setValue(20)
        self._lbr_filter.setCurrentIndex(0)
        for widget in (self._search_box, self._min_active, self._min_likes, self._lbr_filter):
            widget.blockSignals(False)
        self._apply_filters()

    # ------------------------------------------------------------------
    # Sources table population
    # ------------------------------------------------------------------

    def _populate_sources_table(self, rows: list) -> None:
        self._sources_table.setSortingEnabled(False)
        self._sources_table.setRowCount(0)

        if not rows:
            self._sources_table.insertRow(0)
            if self._all_sources:
                msg_text = "No sources match the current filters."
            else:
                msg_text = (
                    "No like source data. Run 'Analyze LBR' to compute "
                    "Like-Back Rate for all accounts."
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

        def _si(text: str, key, color: Optional[QColor] = None) -> SortableItem:
            item = SortableItem(text, key)
            item.setTextAlignment(center)
            if color:
                item.setForeground(color)
            return item

        for src in rows:
            r = self._sources_table.rowCount()
            self._sources_table.insertRow(r)

            # Source name
            name_item = SortableItem(src.source_name, src.source_name.lower())
            name_item.setData(Qt.ItemDataRole.UserRole, src.source_name)
            self._sources_table.setItem(r, _COL_SOURCE, name_item)

            # Account counts
            act_col = _c_active() if src.active_accounts > 0 else _c_dim()
            hst_col = _c_hist() if src.historical_accounts > 0 else _c_dim()
            self._sources_table.setItem(
                r, _COL_ACTIVE, _si(str(src.active_accounts), src.active_accounts, act_col)
            )
            self._sources_table.setItem(
                r, _COL_HIST, _si(str(src.historical_accounts), src.historical_accounts, hst_col)
            )

            # Volume
            self._sources_table.setItem(
                r, _COL_LIKES, _si(f"{src.total_likes:,}", src.total_likes)
            )
            self._sources_table.setItem(
                r, _COL_FBACKS, _si(f"{src.total_followbacks:,}", src.total_followbacks)
            )

            # Avg LBR %
            if src.avg_lbr_pct is not None:
                avg_col = _c_quality() if src.avg_lbr_pct >= 5.0 else _c_low()
                self._sources_table.setItem(
                    r, _COL_AVG_LBR, _si(f"{src.avg_lbr_pct:.1f}%", src.avg_lbr_pct, avg_col)
                )
            else:
                self._sources_table.setItem(
                    r, _COL_AVG_LBR, _si("--", -1.0, _c_dim())
                )

            # Weighted LBR %
            if src.weighted_lbr_pct is not None:
                wtd_col = _c_quality() if src.weighted_lbr_pct >= 5.0 else _c_low()
                self._sources_table.setItem(
                    r, _COL_WTD_LBR, _si(f"{src.weighted_lbr_pct:.1f}%", src.weighted_lbr_pct, wtd_col)
                )
            else:
                self._sources_table.setItem(
                    r, _COL_WTD_LBR, _si("--", -1.0, _c_dim())
                )

            # Quality: quality_count / total_accounts
            total_accs = src.active_accounts + src.historical_accounts
            if total_accs > 0:
                q_text = f"{src.quality_account_count}/{total_accs}"
                q_color = _c_quality() if src.quality_account_count > 0 else _c_low()
            else:
                q_text = "--"
                q_color = _c_dim()
            self._sources_table.setItem(
                r, _COL_QUALITY, _si(q_text, src.quality_account_count, q_color)
            )

            # Last updated
            date_str = src.last_analyzed_at[:10] if src.last_analyzed_at else "--"
            date_sort = src.last_analyzed_at[:10] if src.last_analyzed_at else ""
            self._sources_table.setItem(
                r, _COL_UPDATED,
                _si(date_str, date_sort, None if src.last_analyzed_at else _c_dim()),
            )

        self._sources_table.setSortingEnabled(True)
        self._clear_detail_pane()

    # ------------------------------------------------------------------
    # Detail pane
    # ------------------------------------------------------------------

    def _on_source_selected(self) -> None:
        selected = self._sources_table.selectedItems()
        if not selected:
            self._clear_detail_pane()
            return

        row = selected[0].row()
        name_item = self._sources_table.item(row, _COL_SOURCE)
        if not name_item:
            self._clear_detail_pane()
            return

        source_name = name_item.data(Qt.ItemDataRole.UserRole)
        if not source_name:
            self._clear_detail_pane()
            return

        accounts = self._service.get_detail(source_name)
        self._populate_detail_pane(source_name, accounts)

    def _clear_detail_pane(self) -> None:
        self._detail_table.setRowCount(0)
        self._detail_header.setText(
            "Select a source above to see which accounts use it."
        )

    def _populate_detail_pane(
        self, source_name: str, accounts: list,
    ) -> None:
        active_count = sum(1 for a in accounts if a.is_active)
        hist_count = len(accounts) - active_count

        # Build header line
        parts = [f"  {source_name}"]
        if active_count:
            parts.append(f"{active_count} active")
        if hist_count:
            parts.append(f"{hist_count} historical")
        self._detail_header.setText("  ·  ".join(parts))

        center = Qt.AlignmentFlag.AlignCenter

        def _si(text: str, key, color: Optional[QColor] = None) -> SortableItem:
            item = SortableItem(text, key)
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

            # Username
            u_item = QTableWidgetItem(acc.username)
            u_item.setForeground(_c_active() if acc.is_active else _c_hist())
            self._detail_table.setItem(r, _D_USERNAME, u_item)

            # Device
            d_item = QTableWidgetItem(acc.device_name or acc.device_id[:12])
            d_item.setTextAlignment(center)
            d_item.setForeground(_c_dim())
            self._detail_table.setItem(r, _D_DEVICE, d_item)

            # Likes
            self._detail_table.setItem(
                r, _D_LIKES, _si(f"{acc.like_count:,}", acc.like_count)
            )

            # Followbacks
            self._detail_table.setItem(
                r, _D_FBACKS, _si(f"{acc.followback_count:,}", acc.followback_count)
            )

            # LBR %
            if acc.lbr_percent is not None:
                lbr_color = _c_quality() if acc.is_quality else _c_low()
                self._detail_table.setItem(
                    r, _D_LBR, _si(f"{acc.lbr_percent:.1f}%", acc.lbr_percent, lbr_color)
                )
            else:
                no_data = "--" if acc.last_analyzed_at else "Not analyzed"
                self._detail_table.setItem(
                    r, _D_LBR, _si(no_data, -1.0, _c_dim())
                )

            # Quality
            if acc.last_analyzed_at:
                q_text = "Yes" if acc.is_quality else "No"
                q_color = _c_quality() if acc.is_quality else _c_low()
                self._detail_table.setItem(
                    r, _D_QUALITY, _si(q_text, 1 if acc.is_quality else 0, q_color)
                )
            else:
                self._detail_table.setItem(
                    r, _D_QUALITY, _si("--", -1, _c_dim())
                )

            # Active
            active_text = "Yes" if acc.is_active else "No"
            active_color = _c_active() if acc.is_active else _c_hist()
            self._detail_table.setItem(
                r, _D_ACTIVE, _si(active_text, 1 if acc.is_active else 0, active_color)
            )

        self._detail_table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Export CSV
    # ------------------------------------------------------------------

    def _on_export_csv(self) -> None:
        if not self._all_sources:
            self._set_status("No data to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Like Sources CSV", "like_sources.csv",
            "CSV Files (*.csv);;All Files (*)",
        )
        if not path:
            return

        try:
            # Get currently filtered data
            query = self._search_box.text().strip().lower()
            min_active = self._min_active.value()
            min_likes = self._min_likes.value()
            lbr_filt = self._lbr_filter.currentText()

            visible = []
            for src in self._all_sources:
                if query and query not in src.source_name.lower():
                    continue
                if min_active > 0 and src.active_accounts < min_active:
                    continue
                if min_likes > 0 and src.total_likes < min_likes:
                    continue
                if not self._lbr_quality_matches(lbr_filt, src):
                    continue
                visible.append(src)

            with open(path, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(_SOURCE_HEADERS)
                for src in visible:
                    total_accs = src.active_accounts + src.historical_accounts
                    writer.writerow([
                        src.source_name,
                        src.active_accounts,
                        src.historical_accounts,
                        src.total_likes,
                        src.total_followbacks,
                        f"{src.avg_lbr_pct:.1f}" if src.avg_lbr_pct is not None else "",
                        f"{src.weighted_lbr_pct:.1f}" if src.weighted_lbr_pct is not None else "",
                        f"{src.quality_account_count}/{total_accs}" if total_accs > 0 else "",
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
        self._analyze_btn.setEnabled(not busy)
        self._busy_label.setText(message if busy else "")

    def _set_status(self, message: str) -> None:
        self._status_label.setText(message)
