"""
SourceProfilesTab — Source Health Dashboard.

Shows all indexed source profiles with niche, language, FBR stats,
and health indicators. Leverages source_profiles and source_fbr_stats tables.
"""
import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QLineEdit, QComboBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont

from oh.models.source_profile import SourceProfile, SourceFBRStats
from oh.repositories.source_profile_repo import SourceProfileRepository
from oh.ui.table_utils import SortableItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Column indexes
# ---------------------------------------------------------------------------

_COL_SOURCE     = 0
_COL_NICHE      = 1
_COL_CONFIDENCE = 2
_COL_LANGUAGE   = 3
_COL_LOCATION   = 4
_COL_FOLLOWERS  = 5
_COL_ACCOUNTS   = 6
_COL_AVG_FBR    = 7
_COL_WFBR       = 8
_COL_QUALITY    = 9
_COL_STATUS     = 10

_HEADERS = [
    "Source", "Niche", "Conf%", "Lang", "Location",
    "Followers", "Accounts", "Avg FBR%", "Wtd FBR%", "Quality", "Status",
]

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

_C_GREEN = QColor("#4caf7d")
_C_RED   = QColor("#e05252")
_C_MUTED = QColor("#888888")


# ---------------------------------------------------------------------------
# SourceProfilesTab
# ---------------------------------------------------------------------------

class SourceProfilesTab(QWidget):
    def __init__(
        self,
        source_profile_repo: SourceProfileRepository,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._repo = source_profile_repo
        self._all_profiles: List[SourceProfile] = []
        self._fbr_map: Dict[str, SourceFBRStats] = {}
        self._loaded = False
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
        lo.addWidget(self._make_table(), stretch=1)

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

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search source...")
        self._search_box.setFixedWidth(200)
        self._search_box.textChanged.connect(self._apply_filter)
        h.addWidget(self._search_box)

        h.addSpacing(8)

        self._niche_combo = QComboBox()
        self._niche_combo.setFixedWidth(160)
        self._niche_combo.addItem("All niches")
        self._niche_combo.currentIndexChanged.connect(self._apply_filter)
        h.addWidget(self._niche_combo)

        h.addSpacing(8)

        self._lang_combo = QComboBox()
        self._lang_combo.setFixedWidth(100)
        self._lang_combo.addItems(["All", "PL", "EN", "Unknown"])
        self._lang_combo.currentIndexChanged.connect(self._apply_filter)
        h.addWidget(self._lang_combo)

        h.addSpacing(8)

        h.addWidget(QLabel("Min FBR%:"))
        self._min_fbr_spin = QDoubleSpinBox()
        self._min_fbr_spin.setRange(0.0, 100.0)
        self._min_fbr_spin.setValue(0.0)
        self._min_fbr_spin.setSingleStep(1.0)
        self._min_fbr_spin.setFixedWidth(80)
        self._min_fbr_spin.valueChanged.connect(self._apply_filter)
        h.addWidget(self._min_fbr_spin)

        h.addStretch()

        self._count_label = QLabel("")
        h.addWidget(self._count_label)

        return bar

    def _make_table(self) -> QTableWidget:
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

        # Sensible default widths
        widths = {
            _COL_SOURCE: 150, _COL_NICHE: 120, _COL_CONFIDENCE: 60,
            _COL_LANGUAGE: 50, _COL_LOCATION: 100, _COL_FOLLOWERS: 80,
            _COL_ACCOUNTS: 70, _COL_AVG_FBR: 75, _COL_WFBR: 75,
            _COL_QUALITY: 60, _COL_STATUS: 70,
        }
        for col, w in widths.items():
            self._table.setColumnWidth(col, w)

        return self._table

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """Public entry — called by MainWindow on tab switch."""
        try:
            profiles = self._repo.get_all_profiles(limit=5000)
            fbr_list = self._repo.get_all_fbr_stats()
        except Exception:
            logger.exception("Failed to load source profiles")
            self._stats_label.setText("Error loading profiles.")
            return

        self._all_profiles = profiles
        self._fbr_map = {s.source_name: s for s in fbr_list}
        self._loaded = True

        self._update_niche_combo(profiles)
        self._populate_table(profiles, self._fbr_map)
        self._update_stats_label(profiles, self._fbr_map)

    def _update_niche_combo(self, profiles: List[SourceProfile]) -> None:
        niches = sorted({
            p.niche_category for p in profiles
            if p.niche_category
        })
        self._niche_combo.blockSignals(True)
        current = self._niche_combo.currentText()
        self._niche_combo.clear()
        self._niche_combo.addItem("All niches")
        for n in niches:
            self._niche_combo.addItem(n)
        idx = self._niche_combo.findText(current)
        self._niche_combo.setCurrentIndex(max(idx, 0))
        self._niche_combo.blockSignals(False)

    def _update_stats_label(
        self,
        profiles: List[SourceProfile],
        fbr_map: Dict[str, SourceFBRStats],
    ) -> None:
        n_profiles = len(profiles)
        n_niches = len({p.niche_category for p in profiles if p.niche_category})
        fbr_values = [s.avg_fbr_pct for s in fbr_map.values() if s.avg_fbr_pct > 0]
        avg_fbr = sum(fbr_values) / len(fbr_values) if fbr_values else 0.0
        self._stats_label.setText(
            f"{n_profiles} profiles indexed  |  {n_niches} niches  |  avg FBR {avg_fbr:.1f}%"
        )

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(
        self,
        profiles: List[SourceProfile],
        fbr_map: Dict[str, SourceFBRStats],
    ) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(profiles))

        for row, p in enumerate(profiles):
            stats = fbr_map.get(p.source_name)
            self._fill_row(row, p, stats)

        self._table.setSortingEnabled(True)
        self._apply_filter()

    def _fill_row(
        self,
        row: int,
        p: SourceProfile,
        stats: Optional[SourceFBRStats],
    ) -> None:
        # Source name
        item = QTableWidgetItem(p.source_name)
        self._table.setItem(row, _COL_SOURCE, item)

        # Niche
        niche_text = p.niche_category or ""
        item = QTableWidgetItem(niche_text)
        self._table.setItem(row, _COL_NICHE, item)

        # Confidence
        conf = p.niche_confidence or 0.0
        item = SortableItem(f"{conf * 100:.0f}%" if conf else "", conf)
        if conf >= 0.7:
            item.setForeground(_C_GREEN)
        elif conf < 0.4 and conf > 0:
            item.setForeground(_C_MUTED)
        self._table.setItem(row, _COL_CONFIDENCE, item)

        # Language
        lang = p.language or ""
        item = QTableWidgetItem(lang)
        self._table.setItem(row, _COL_LANGUAGE, item)

        # Location
        loc = p.location or ""
        item = QTableWidgetItem(loc)
        self._table.setItem(row, _COL_LOCATION, item)

        # Followers
        fc = p.follower_count or 0
        item = SortableItem(f"{fc:,}" if fc else "", fc)
        if fc >= 10000:
            font = item.font()
            font.setBold(True)
            item.setFont(font)
        self._table.setItem(row, _COL_FOLLOWERS, item)

        # FBR stats columns
        accs = stats.total_accounts_used if stats else 0
        avg_fbr = stats.avg_fbr_pct if stats else 0.0
        wfbr = stats.weighted_fbr_pct if stats else 0.0
        quality = stats.quality_account_count if stats else 0

        # Accounts
        item = SortableItem(str(accs) if accs else "", accs)
        self._table.setItem(row, _COL_ACCOUNTS, item)

        # Avg FBR
        item = SortableItem(f"{avg_fbr:.1f}" if accs else "", avg_fbr)
        if accs > 0:
            if avg_fbr >= 10.0:
                item.setForeground(_C_GREEN)
            elif avg_fbr < 5.0:
                item.setForeground(_C_RED)
        self._table.setItem(row, _COL_AVG_FBR, item)

        # Weighted FBR
        item = SortableItem(f"{wfbr:.1f}" if accs else "", wfbr)
        if accs > 0:
            if wfbr >= 10.0:
                item.setForeground(_C_GREEN)
            elif wfbr < 5.0:
                item.setForeground(_C_RED)
        self._table.setItem(row, _COL_WFBR, item)

        # Quality
        item = SortableItem(str(quality) if accs else "", quality)
        self._table.setItem(row, _COL_QUALITY, item)

        # Status
        status_text = "Active" if p.is_active_source else "Inactive"
        item = QTableWidgetItem(status_text)
        if not p.is_active_source:
            item.setForeground(_C_MUTED)
        self._table.setItem(row, _COL_STATUS, item)

    # ------------------------------------------------------------------
    # Filtering
    # ------------------------------------------------------------------

    def _apply_filter(self) -> None:
        search = self._search_box.text().strip().lower()
        niche_filter = self._niche_combo.currentText()
        lang_filter = self._lang_combo.currentText()
        min_fbr = self._min_fbr_spin.value()

        visible = 0
        for row in range(self._table.rowCount()):
            show = True

            # Search filter
            if search:
                source_item = self._table.item(row, _COL_SOURCE)
                if source_item and search not in source_item.text().lower():
                    show = False

            # Niche filter
            if show and niche_filter != "All niches":
                niche_item = self._table.item(row, _COL_NICHE)
                if niche_item and niche_item.text() != niche_filter:
                    show = False

            # Language filter
            if show and lang_filter != "All":
                lang_item = self._table.item(row, _COL_LANGUAGE)
                lang_val = lang_item.text() if lang_item else ""
                if lang_filter == "Unknown":
                    if lang_val:
                        show = False
                elif lang_val != lang_filter:
                    show = False

            # Min FBR filter
            if show and min_fbr > 0:
                fbr_item = self._table.item(row, _COL_AVG_FBR)
                if fbr_item:
                    try:
                        val = float(fbr_item.text()) if fbr_item.text() else 0.0
                    except ValueError:
                        val = 0.0
                    if val < min_fbr:
                        show = False

            self._table.setRowHidden(row, not show)
            if show:
                visible += 1

        self._count_label.setText(f"{visible} shown")

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_refresh(self) -> None:
        self.load_data()
