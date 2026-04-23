"""
SourceDialog — modal dialog showing source inspection + FBR analytics
+ source usage for a single account.

The table merges three result objects into one view:
  SourceInspectionResult  → file presence (sources.txt / data.db) + status label
  FBRAnalysisResult       → follow count, followback count, FBR%, quality flag
  SourceUsageResult       → USED count + USED % (processed users / total followers)

If FBR data is unavailable (no data.db or schema error) the FBR columns
show "—" and the summary panel shows the reason.

If usage data is unavailable (no sources/ dir or DB missing) the Used column
shows "—".  USED % shows "—" when the .stm percent file is missing or when
follows = 0 (denominator cannot be derived).

Table columns:
  Source | Status | sources.txt | data.db | Follows | Follow-backs | FBR% | Quality | Used | Used %
"""
import logging
from typing import Optional, Callable

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton, QFrame, QWidget,
    QMessageBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.ui.style import sc

from oh.models.source import (
    SourceInspectionResult, SourceRecord,
    STATUS_ACTIVE_WITH_ACTIVITY,
    STATUS_ACTIVE_NO_ACTIVITY,
    STATUS_HISTORICAL_ONLY,
)
from oh.models.fbr import FBRAnalysisResult, SourceFBRRecord
from oh.models.source_usage import SourceUsageResult, SourceUsageRecord

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table layout
# ---------------------------------------------------------------------------

COL_SOURCE     = 0
COL_STATUS     = 1
COL_ADDED      = 2   # date source was first added
COL_ACTIVE     = 3   # sources.txt
COL_HISTORY    = 4   # data.db
COL_FOLLOWS    = 5
COL_FOLLOWBACK = 6
COL_FBR        = 7
COL_QUALITY    = 8
COL_USED       = 9   # processed user count from sources/{name}.db
COL_USED_PCT   = 10  # used_count / total_source_followers * 100

_HEADERS = [
    "Source", "Status", "Added", "sources.txt", "data.db",
    "Follows", "Follow-backs", "FBR %", "Quality", "Used", "Used %",
]

# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def _C_ACTIVE_HIST(): return sc("success")    # green  — active + history
def _C_ACTIVE_NEW():  return sc("warning")    # amber  — active, not in data.db yet
def _C_HISTORICAL():  return sc("muted")      # grey   — historical only
def _C_YES():         return sc("success")
def _C_NO():          return sc("dimmed")
def _C_QUALITY():     return sc("success")    # green checkmark
def _C_LOW_FBR():     return sc("muted")      # grey   — below threshold or no data
def _C_ANOMALY():     return sc("error")      # red    — data anomaly
def _C_WARN_BG():
    return f"background: {sc('bg_note').name()}; color: {sc('warning').name()}; padding: 6px 10px; border-radius: 4px;"
def _C_ERR_BG():
    return f"background: {sc('bg_note').name()}; color: {sc('error').name()}; padding: 6px 10px; border-radius: 4px;"

_STATUS_COLOR_FN = {
    STATUS_ACTIVE_WITH_ACTIVITY: _C_ACTIVE_HIST,
    STATUS_ACTIVE_NO_ACTIVITY:   _C_ACTIVE_NEW,
    STATUS_HISTORICAL_ONLY:      _C_HISTORICAL,
}


# ---------------------------------------------------------------------------
# Sortable numeric item
# ---------------------------------------------------------------------------

class _NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by numeric value, not lexicographic order."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text()) < float(other.text())
        except ValueError:
            return self.text() < other.text()


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SourceDialog(QDialog):
    def __init__(
        self,
        inspection: SourceInspectionResult,
        fbr: FBRAnalysisResult,
        usage: Optional[SourceUsageResult] = None,
        on_delete: Optional[Callable] = None,
        on_cleanup: Optional[Callable] = None,
        source_dates: Optional[dict] = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._inspection = inspection
        self._fbr = fbr
        self._usage = usage
        self._on_delete = on_delete
        self._on_cleanup = on_cleanup
        self._source_dates = source_dates or {}  # {lowercase_name: "YYYY-MM-DD"}

        # Pre-build FBR lookup keyed by normalized (strip + lower) name so that
        # minor casing/whitespace differences between sources.txt and data.db
        # never prevent FBR data from appearing.
        self._fbr_map: dict[str, SourceFBRRecord] = {
            r.source_name.strip().lower(): r for r in fbr.records
        }

        # Pre-build usage lookup keyed by normalized name
        self._usage_map: dict[str, SourceUsageRecord] = (
            usage.as_map() if usage is not None else {}
        )

        # Warn if normalization collapsed duplicate FBR records onto the same key
        # (two data.db rows with same name in different cases).
        if len(self._fbr_map) < len(fbr.records):
            logger.warning(
                f"SourceDialog ({inspection.username}): FBR map has "
                f"{len(self._fbr_map)} keys for {len(fbr.records)} records — "
                f"duplicate normalized source names in data.db"
            )

        usage_summary = (
            f"usage: {usage.db_count_found} DBs read, "
            f"{usage.db_count_missing} missing"
            if usage is not None
            else "usage: not available"
        )
        logger.info(
            f"SourceDialog opened: {inspection.username} — "
            f"{inspection.total_count} source rows  "
            f"{len(fbr.records)} FBR records  "
            f"schema_valid={fbr.schema_valid}  "
            f"fbr_map_size={len(self._fbr_map)}  "
            f"{usage_summary}"
        )

        short_device = (
            inspection.device_id[:10] + "…"
            if len(inspection.device_id) > 10
            else inspection.device_id
        )
        self.setWindowTitle(
            f"Sources & FBR — {inspection.username}  [{short_device}]"
        )
        self.setMinimumSize(1100, 540)
        self._build_ui()

    # ------------------------------------------------------------------
    # Top-level layout
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(12, 12, 12, 12)

        layout.addWidget(self._make_header())
        layout.addWidget(self._make_fbr_summary())

        all_warnings = self._inspection.warnings + self._fbr.warnings
        if all_warnings:
            layout.addWidget(self._make_warning_banner(all_warnings, error=False))

        if not self._inspection.has_data:
            layout.addWidget(self._make_empty_state(), stretch=1)
        else:
            self._source_table = self._make_table()
            layout.addWidget(self._source_table, stretch=1)
            layout.addWidget(self._make_legend())
            # Enable delete button when a row is selected
            if self._on_delete is not None:
                self._source_table.selectionModel().selectionChanged.connect(
                    self._on_table_selection_changed
                )

        layout.addWidget(self._make_footer())

    # ------------------------------------------------------------------
    # Header row — account name + file availability
    # ------------------------------------------------------------------

    def _make_header(self) -> QWidget:
        r = self._inspection
        frame = QFrame()
        lo = QHBoxLayout(frame)
        lo.setContentsMargins(0, 0, 0, 2)

        title = QLabel(f"<b>{r.username}</b>")
        title.setStyleSheet("font-size: 14px;")

        txt_mark = "✓" if r.sources_txt_found else "—"
        db_mark  = "✓" if r.data_db_found     else "—"
        stats = QLabel(
            f"Sources total: <b>{r.total_count}</b>  ·  "
            f"Active: <b>{r.active_count}</b>  ·  "
            f"Historical: <b>{r.historical_count}</b>"
            f"    |    sources.txt {txt_mark}  ·  data.db {db_mark}"
        )
        stats.setStyleSheet("color: %s; font-size: 11px;" % sc("text_secondary").name())
        stats.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        lo.addWidget(title)
        lo.addStretch()
        lo.addWidget(stats)
        return frame

    # ------------------------------------------------------------------
    # FBR summary panel
    # ------------------------------------------------------------------

    def _make_fbr_summary(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setStyleSheet(
            "QFrame { background: %s; border-radius: 4px; }" % sc("bg_note").name()
        )
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(10, 8, 10, 8)
        lo.setSpacing(4)

        if not self._fbr.schema_valid:
            lbl = QLabel(f"FBR analytics unavailable: {self._fbr.schema_error}")
            lbl.setStyleSheet("color: %s; font-style: italic; font-size: 11px;" % sc("text_secondary").name())
            lo.addWidget(lbl)
            return frame

        if not self._fbr.has_data:
            lbl = QLabel(
                "FBR: no data in data.db yet — "
                "this account has not been followed/unfollowed by the bot."
            )
            lbl.setStyleSheet("color: %s; font-style: italic; font-size: 11px;" % sc("text_secondary").name())
            lo.addWidget(lbl)
            return frame

        fbr = self._fbr

        # Row 1: key stats
        best = fbr.best_source_by_fbr
        vol  = fbr.highest_volume_source

        best_str = (
            f"<b>{best.source_name}</b> ({best.fbr_percent:.1f}%)"
            if best else "—"
        )
        vol_str = (
            f"<b>{vol.source_name}</b> ({vol.follow_count:,} follows)"
            if vol else "—"
        )

        row1 = QLabel(
            f"Quality sources: <b style='color:{sc('success').name()}'>{fbr.quality_count}</b> / {fbr.total_count}"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"Best FBR: {best_str}"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"Highest volume: {vol_str}"
        )
        row1.setStyleSheet("font-size: 11px; color: %s;" % sc("text").name())
        row1.setWordWrap(True)
        lo.addWidget(row1)

        # Row 2: thresholds + secondary stats
        anomaly_note = (
            f"  ·  <span style='color:{sc('error').name()}'>{fbr.anomaly_count} anomaly(s)</span>"
            if fbr.anomaly_count else ""
        )
        row2 = QLabel(
            f"Thresholds: ≥{fbr.min_follows:,} follows  ·  ≥{fbr.min_fbr_pct:.0f}% FBR"
            f"&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
            f"Below volume floor: {fbr.below_volume_count}"
            f"{anomaly_note}"
        )
        row2.setStyleSheet("font-size: 10px; color: %s;" % sc("text_secondary").name())
        row2.setWordWrap(True)
        lo.addWidget(row2)

        return frame

    # ------------------------------------------------------------------
    # Warning / error banners
    # ------------------------------------------------------------------

    def _make_warning_banner(
        self, warnings: list[str], error: bool = False
    ) -> QLabel:
        prefix = "  ✕  " if error else "  ⚠  "
        style  = _C_ERR_BG() if error else _C_WARN_BG()
        lbl = QLabel(prefix + "   ·   ".join(warnings))
        lbl.setStyleSheet(style)
        lbl.setWordWrap(True)
        return lbl

    # ------------------------------------------------------------------
    # Empty state
    # ------------------------------------------------------------------

    def _make_empty_state(self) -> QLabel:
        r = self._inspection
        if not r.sources_txt_found and not r.data_db_found:
            msg = (
                "Neither sources.txt nor data.db was found for this account.\n"
                "Run a Scan & Sync first to confirm the account folder exists."
            )
        elif not r.sources_txt_found:
            msg = (
                "sources.txt was not found (no active sources).\n"
                "data.db exists but contains no valid source names."
            )
        elif not r.data_db_found:
            msg = (
                "data.db was not found (no FBR data).\n"
                "sources.txt exists but contained no valid source names."
            )
        else:
            msg = (
                "Both files exist but no valid source names were found.\n"
                "The files may be empty or contain only placeholder values."
            )

        lbl = QLabel(msg)
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lbl.setStyleSheet("color: %s; font-style: italic; padding: 40px;" % sc("text_secondary").name())
        lbl.setWordWrap(True)
        return lbl

    # ------------------------------------------------------------------
    # Main table
    # ------------------------------------------------------------------

    def _make_table(self) -> QTableWidget:
        sources = self._inspection.sources
        t = QTableWidget(len(sources), len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(False)   # MUST be disabled during row insertion; enabled after
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        for col in (COL_STATUS, COL_ADDED, COL_ACTIVE, COL_HISTORY,
                    COL_FOLLOWS, COL_FOLLOWBACK, COL_FBR, COL_QUALITY,
                    COL_USED, COL_USED_PCT):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(COL_STATUS,     145)
        t.setColumnWidth(COL_ADDED,       80)
        t.setColumnWidth(COL_ACTIVE,      85)
        t.setColumnWidth(COL_HISTORY,     65)
        t.setColumnWidth(COL_FOLLOWS,     75)
        t.setColumnWidth(COL_FOLLOWBACK,  90)
        t.setColumnWidth(COL_FBR,         70)
        t.setColumnWidth(COL_QUALITY,     65)
        t.setColumnWidth(COL_USED,        65)
        t.setColumnWidth(COL_USED_PCT,    65)

        n_with_fbr     = 0
        n_active_only  = 0
        n_unexpected   = 0

        for row, src in enumerate(sources):
            key       = src.source_name.strip().lower()
            fbr_rec   = self._fbr_map.get(key)
            usage_rec = self._usage_map.get(key)
            self._fill_row(t, row, src, fbr_rec, usage_rec)

            if fbr_rec is not None:
                n_with_fbr += 1
            elif src.is_active and not src.is_historical:
                n_active_only += 1          # new source — '—' is correct
            else:
                n_unexpected += 1           # historical but no FBR record
                logger.warning(
                    f"SourceDialog row miss: {src.source_name!r} "
                    f"is_active={src.is_active} is_historical={src.is_historical} "
                    f"— in data.db but no FBR record found (key={key!r})"
                )

            # Layer D: log first 5 rows to prove table is populated correctly
            if row < 5:
                used_str = (
                    str(usage_rec.used_count) if usage_rec and usage_rec.has_data
                    else ("err" if usage_rec and usage_rec.db_error else "—")
                )
                pct_str = (
                    f"{usage_rec.used_pct:.1f}%" if usage_rec and usage_rec.used_pct is not None
                    else "—"
                )
                if fbr_rec is not None:
                    logger.debug(
                        f"SourceDialog row {row}: source={src.source_name!r} "
                        f"status={src.status_label!r} active={src.is_active} hist={src.is_historical} "
                        f"follows={fbr_rec.follow_count} fb={fbr_rec.followback_count} "
                        f"fbr={fbr_rec.fbr_percent:.1f}% quality={fbr_rec.is_quality} "
                        f"used={used_str} used_pct={pct_str}"
                    )
                else:
                    logger.debug(
                        f"SourceDialog row {row}: source={src.source_name!r} "
                        f"status={src.status_label!r} active={src.is_active} hist={src.is_historical} "
                        f"follows=— (no FBR record) used={used_str} used_pct={pct_str}"
                    )

        logger.info(
            f"SourceDialog table filled: "
            f"{n_with_fbr} rows with FBR values  |  "
            f"{n_active_only} active-only (new source → '—' expected)  |  "
            f"{n_unexpected} unexpected misses (historical with no FBR record)"
        )
        if n_unexpected > 0:
            logger.warning(
                f"SourceDialog: {n_unexpected} historical source(s) have no FBR record. "
                f"Check that bot_root is correct and data.db is readable."
            )

        # Enable sorting only after all rows are fully populated.
        # Qt re-sorts on each setItem() call if sorting is enabled during insertion,
        # which moves rows to different logical positions and causes subsequent
        # column fills to land in the wrong rows — leaving most columns blank.
        t.setSortingEnabled(True)

        return t

    def _fill_row(
        self,
        t: QTableWidget,
        row: int,
        src: SourceRecord,
        fbr: Optional[SourceFBRRecord],
        usage: Optional[SourceUsageRecord],
    ) -> None:
        center = Qt.AlignmentFlag.AlignCenter
        right  = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        # Source name
        t.setItem(row, COL_SOURCE, QTableWidgetItem(src.source_name))

        # Status (from source inspector)
        status_item = QTableWidgetItem(src.status_label)
        status_item.setTextAlignment(center)
        status_item.setForeground(_STATUS_COLOR_FN[src.status]())
        t.setItem(row, COL_STATUS, status_item)

        # Date added (from source_assignments.created_at)
        key_lower = src.source_name.strip().lower()
        added_date = self._source_dates.get(key_lower, "\u2014")
        added_item = QTableWidgetItem(added_date)
        added_item.setTextAlignment(center)
        if added_date == "\u2014":
            added_item.setForeground(_C_LOW_FBR())
        t.setItem(row, COL_ADDED, added_item)

        # File presence
        t.setItem(row, COL_ACTIVE,  _bool_item(src.is_active))
        t.setItem(row, COL_HISTORY, _bool_item(src.is_historical))

        # FBR columns
        if fbr is None:
            # Active-only source — not yet in data.db, no analytics available
            for col in (COL_FOLLOWS, COL_FOLLOWBACK, COL_FBR, COL_QUALITY):
                i = QTableWidgetItem("—")
                i.setTextAlignment(center)
                i.setForeground(_C_LOW_FBR())
                t.setItem(row, col, i)
        else:
            anomaly_color = _C_ANOMALY() if fbr.anomaly else None

            follows_item = _NumericItem(f"{fbr.follow_count:,}")
            follows_item.setTextAlignment(right)
            if anomaly_color:
                follows_item.setForeground(anomaly_color)
            t.setItem(row, COL_FOLLOWS, follows_item)

            fb_item = _NumericItem(f"{fbr.followback_count:,}")
            fb_item.setTextAlignment(right)
            if anomaly_color:
                fb_item.setForeground(anomaly_color)
            t.setItem(row, COL_FOLLOWBACK, fb_item)

            fbr_item = _NumericItem(f"{fbr.fbr_percent:.1f}")
            fbr_item.setTextAlignment(right)
            if anomaly_color:
                fbr_item.setForeground(anomaly_color)
            elif fbr.fbr_percent >= self._fbr.min_fbr_pct and fbr.follow_count >= self._fbr.min_follows:
                fbr_item.setForeground(_C_QUALITY())
            else:
                fbr_item.setForeground(_C_LOW_FBR())
            t.setItem(row, COL_FBR, fbr_item)

            quality_item = QTableWidgetItem("✓" if fbr.is_quality else "✗")
            quality_item.setTextAlignment(center)
            quality_item.setForeground(_C_QUALITY if fbr.is_quality else _C_LOW_FBR)
            t.setItem(row, COL_QUALITY, quality_item)

        # Used column — COUNT(*) from sources/{name}.db source_followers table
        if usage is None or not usage.db_found:
            used_item = _NumericItem("—")
            used_item.setTextAlignment(center)
            used_item.setForeground(_C_LOW_FBR())
        elif usage.db_error is not None:
            used_item = _NumericItem("?")
            used_item.setTextAlignment(center)
            used_item.setForeground(_C_ANOMALY())
            used_item.setToolTip(f"Read error: {usage.db_error}")
        else:
            used_item = _NumericItem(f"{usage.used_count:,}")
            used_item.setTextAlignment(right)
        t.setItem(row, COL_USED, used_item)

        # Used % column — derived from .stm percent file + follows
        if usage is not None and usage.used_pct is not None:
            pct_item = _NumericItem(f"{usage.used_pct:.1f}")
            pct_item.setTextAlignment(right)
            if usage.total_followers_derived is not None:
                pct_item.setToolTip(
                    f"≈ {usage.used_count:,} processed / "
                    f"{usage.total_followers_derived:,} total followers"
                )
        else:
            pct_item = _NumericItem("—")
            pct_item.setTextAlignment(center)
            pct_item.setForeground(_C_LOW_FBR())
            if usage is not None and usage.pct_file_error:
                pct_item.setToolTip(f"Percent file error: {usage.pct_file_error}")
        t.setItem(row, COL_USED_PCT, pct_item)

    # ------------------------------------------------------------------
    # Legend
    # ------------------------------------------------------------------

    def _make_legend(self) -> QLabel:
        fbr_note = ""
        if self._fbr.has_data:
            fbr_note = (
                "&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp;"
                f"<span style='color:{sc('success').name()}'>✓</span> Quality = "
                f"≥{self._fbr.min_follows:,} follows AND "
                f"≥{self._fbr.min_fbr_pct:.0f}% FBR"
            )

        lbl = QLabel(
            f"<span style='color:{sc('success').name()}'>■</span> Active + history"
            "&nbsp;&nbsp;"
            f"<span style='color:{sc('warning').name()}'>■</span> Active (new)"
            "&nbsp;&nbsp;"
            f"<span style='color:{sc('muted').name()}'>■</span> Historical only"
            f"{fbr_note}"
        )
        lbl.setStyleSheet("font-size: 10px; color: %s; padding-top: 2px;" % sc("text_secondary").name())
        return lbl

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------

    def _make_footer(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 4, 0, 0)

        if self._on_delete is not None:
            self._delete_btn = QPushButton("Delete Selected")
            self._delete_btn.setFixedWidth(160)
            self._delete_btn.setEnabled(False)
            self._delete_btn.setStyleSheet(
                f"QPushButton:enabled {{ color: {sc('error').name()}; }}"
                f"QPushButton:enabled:hover {{ background: {sc('bg_note').name()}; }}"
            )
            self._delete_btn.setToolTip("Delete selected sources (multi-select with Ctrl/Shift)")
            self._delete_btn.clicked.connect(self._on_delete_clicked)
            lo.addWidget(self._delete_btn)

        if self._on_cleanup is not None:
            cleanup_btn = QPushButton("Remove Non-Quality Sources")
            cleanup_btn.setFixedWidth(200)
            cleanup_btn.setStyleSheet(
                f"QPushButton {{ color: {sc('warning').name()}; }}"
                f"QPushButton:hover {{ background: {sc('bg_note').name()}; }}"
            )
            cleanup_btn.clicked.connect(self._on_cleanup_clicked)
            lo.addWidget(cleanup_btn)

        lo.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self.accept)
        lo.addWidget(close_btn)
        return w

    def _on_table_selection_changed(self) -> None:
        """Enable/disable the Delete button based on table selection."""
        if not hasattr(self, "_delete_btn"):
            return
        selected_rows = self._source_table.selectionModel().selectedRows()
        count = len(selected_rows)
        self._delete_btn.setEnabled(count > 0)
        if count > 1:
            self._delete_btn.setText(f"Delete Selected ({count})")
        else:
            self._delete_btn.setText("Delete Selected")

    def _on_delete_clicked(self) -> None:
        """Handle Delete Selected button click — supports multi-select."""
        if self._on_delete is None:
            return

        selected_rows = self._source_table.selectionModel().selectedRows()
        if not selected_rows:
            return

        # Collect unique source names from selected rows
        sources_to_delete = []
        row_map = {}  # source_name -> row index
        for idx in selected_rows:
            row = idx.row()
            source_item = self._source_table.item(row, COL_SOURCE)
            if not source_item:
                continue
            name = source_item.text().strip()
            if not name or name.endswith("(deleted)"):
                continue
            sources_to_delete.append(name)
            row_map[name] = row

        if not sources_to_delete:
            return

        self._delete_btn.setEnabled(False)

        deleted = []
        not_found = []
        errors = []

        for source_name in sources_to_delete:
            try:
                result = self._on_delete(source_name)
                if result is None:
                    # User cancelled — stop entire batch
                    break
                if result.accounts_removed > 0:
                    deleted.append(source_name)
                    # Gray out the deleted row
                    row = row_map[source_name]
                    for col in range(self._source_table.columnCount()):
                        cell = self._source_table.item(row, col)
                        if cell:
                            cell.setForeground(_C_LOW_FBR())
                    si = self._source_table.item(row, COL_SOURCE)
                    if si:
                        si.setText(f"{source_name}  (deleted)")
                elif result.accounts_not_found > 0:
                    not_found.append(source_name)
                elif result.errors:
                    errors.extend(result.errors)
            except Exception as e:
                errors.append(f"{source_name}: {e}")

        # Summary message
        parts = []
        if deleted:
            parts.append(f"Deleted {len(deleted)} source(s).")
        if not_found:
            parts.append(f"{len(not_found)} already absent.")
        if errors:
            parts.append(f"{len(errors)} error(s).")

        if parts:
            msg = "\n".join(parts)
            if deleted:
                msg += "\n\nRevert available in Sources tab \u2192 History."
            QMessageBox.information(self, "Delete Results", msg)

    def _on_cleanup_clicked(self) -> None:
        """Handle Remove Non-Quality Sources button click."""
        if self._on_cleanup is None:
            return
        try:
            result = self._on_cleanup()
            if result is None:
                return  # cancelled or no candidates
            n = result.accounts_removed
            if n > 0:
                QMessageBox.information(
                    self,
                    "Cleanup Complete",
                    f"Removed {n} non-quality source(s) from "
                    f"{self._inspection.username}.\n\n"
                    "Revert available in Sources tab \u2192 History.",
                )
                # Gray out deleted rows in the table
                if hasattr(self, '_source_table'):
                    deleted_names = set(
                        s.lower() for s in result.sources_attempted
                    )
                    for row in range(self._source_table.rowCount()):
                        item = self._source_table.item(row, COL_SOURCE)
                        if item and item.text().strip().lower() in deleted_names:
                            for col in range(self._source_table.columnCount()):
                                cell = self._source_table.item(row, col)
                                if cell:
                                    cell.setForeground(_C_LOW_FBR())
            elif result.accounts_not_found > 0:
                QMessageBox.information(
                    self,
                    "Already Absent",
                    "Selected sources were not found in sources.txt.",
                )
        except Exception as e:
            QMessageBox.critical(
                self,
                "Cleanup Error",
                f"Error during cleanup:\n\n{e}",
            )


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------

def _bool_item(val: bool) -> QTableWidgetItem:
    i = QTableWidgetItem("Yes" if val else "No")
    i.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
    i.setForeground(_C_YES() if val else _C_NO())
    return i
