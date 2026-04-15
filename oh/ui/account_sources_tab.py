"""
AccountSourcesTab -- embedded sources table in the account detail drawer.

Shows active + historical Follow sources (FBR) and Like sources (LBR)
for one account, each in its own section.
"""
import logging
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt

from oh.ui.style import sc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helper for building a sources table
# ---------------------------------------------------------------------------

def _build_sources_table(
    headers: List[str],
    stretch_col: int = 0,
) -> QTableWidget:
    """Create a pre-configured QTableWidget for source data."""
    table = QTableWidget(0, len(headers))
    table.setHorizontalHeaderLabels(headers)
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    table.verticalHeader().setVisible(False)
    table.setAlternatingRowColors(True)
    table.setStyleSheet("font-size: 11px;")

    header = table.horizontalHeader()
    header.setSectionResizeMode(stretch_col, QHeaderView.ResizeMode.Stretch)
    for col in range(len(headers)):
        if col != stretch_col:
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

    return table


def _populate_table(
    table: QTableWidget,
    sources: List[dict],
    count_key: str,
    back_key: str,
    rate_key: str,
    rate_label: str,
    count_label: str,
    back_label: str,
) -> None:
    """Fill a sources table with data rows."""
    green = sc("success")
    muted = sc("muted")

    table.setRowCount(len(sources))

    for row, src in enumerate(sources):
        # Source name (col 0)
        name_item = QTableWidgetItem(src.get("source_name", ""))
        table.setItem(row, 0, name_item)

        # Status (col 1)
        is_active = src.get("is_active", False)
        status_item = QTableWidgetItem("Active" if is_active else "Historical")
        status_item.setForeground(green if is_active else muted)
        table.setItem(row, 1, status_item)

        # Count (col 2) — follows or likes
        count_val = src.get(count_key, 0) or 0
        count_item = QTableWidgetItem(str(count_val))
        count_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 2, count_item)

        # Followbacks (col 3)
        backs = src.get(back_key, 0) or 0
        back_item = QTableWidgetItem(str(backs))
        back_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        table.setItem(row, 3, back_item)

        # Rate % (col 4) — FBR or LBR
        rate = src.get(rate_key, 0) or 0
        rate_item = QTableWidgetItem("%.1f%%" % rate)
        rate_item.setTextAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        if rate >= 10:
            rate_item.setForeground(green)
        elif rate < 5:
            rate_item.setForeground(muted)
        table.setItem(row, 4, rate_item)

        # Quality flag (col 5)
        is_quality = src.get("is_quality", False)
        quality_item = QTableWidgetItem("Y" if is_quality else "-")
        quality_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        quality_item.setForeground(green if is_quality else muted)
        table.setItem(row, 5, quality_item)


# ---------------------------------------------------------------------------
# Main widget
# ---------------------------------------------------------------------------

_FBR_HEADERS = ["Source", "Status", "Follows", "FBacks", "FBR %", "Quality"]
_LBR_HEADERS = ["Source", "Status", "Likes", "FBacks", "LBR %", "Quality"]


class AccountSourcesTab(QScrollArea):
    """Scrollable sources tab showing Follow + Like sources for one account."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._container = QWidget()
        self._root = QVBoxLayout(self._container)
        self._root.setContentsMargins(6, 6, 6, 6)
        self._root.setSpacing(6)

        # --- Follow Sources section ---
        self._follow_header = QLabel("Follow Sources")
        self._follow_header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: %s;" % sc("heading").name()
        )
        self._root.addWidget(self._follow_header)

        self._follow_table = _build_sources_table(_FBR_HEADERS)
        self._root.addWidget(self._follow_table)

        # --- Like Sources section ---
        self._like_header = QLabel("Like Sources")
        self._like_header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: %s;" % sc("heading").name()
        )
        self._root.addWidget(self._like_header)

        self._like_table = _build_sources_table(_LBR_HEADERS)
        self._root.addWidget(self._like_table)

        self._root.addStretch()
        self.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_sources(self, sources: List[dict]) -> None:
        """Populate the Follow sources table.

        Each dict should have keys:
            source_name, is_active, follow_count, followback_count,
            fbr_percent, is_quality
        """
        self._follow_table.setRowCount(0)

        if not sources:
            self._follow_header.setText("Follow Sources (none)")
            self._follow_table.setRowCount(1)
            msg = QTableWidgetItem(
                "No follow source data. Run FBR Analysis first."
            )
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._follow_table.setItem(0, 0, msg)
            self._follow_table.setSpan(0, 0, 1, self._follow_table.columnCount())
            return

        active = sum(1 for s in sources if s.get("is_active", False))
        hist = len(sources) - active
        self._follow_header.setText(
            "Follow Sources (%d active, %d historical)" % (active, hist)
        )

        sorted_sources = sorted(
            sources,
            key=lambda s: (
                not s.get("is_active", False),
                -(s.get("fbr_percent", 0) or 0),
            ),
        )

        _populate_table(
            self._follow_table, sorted_sources,
            count_key="follow_count",
            back_key="followback_count",
            rate_key="fbr_percent",
            rate_label="FBR %",
            count_label="Follows",
            back_label="FBacks",
        )

    def load_like_sources(self, sources: List[dict]) -> None:
        """Populate the Like sources table.

        Each dict should have keys:
            source_name, is_active, like_count, followback_count,
            lbr_percent, is_quality
        """
        self._like_table.setRowCount(0)

        if not sources:
            self._like_header.setText("Like Sources (none)")
            self._like_table.setRowCount(1)
            msg = QTableWidgetItem(
                "No like source data. Run LBR Analysis first."
            )
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._like_table.setItem(0, 0, msg)
            self._like_table.setSpan(0, 0, 1, self._like_table.columnCount())
            return

        active = sum(1 for s in sources if s.get("is_active", False))
        hist = len(sources) - active
        self._like_header.setText(
            "Like Sources (%d active, %d historical)" % (active, hist)
        )

        sorted_sources = sorted(
            sources,
            key=lambda s: (
                not s.get("is_active", False),
                -(s.get("lbr_percent", 0) or 0),
            ),
        )

        _populate_table(
            self._like_table, sorted_sources,
            count_key="like_count",
            back_key="followback_count",
            rate_key="lbr_percent",
            rate_label="LBR %",
            count_label="Likes",
            back_label="FBacks",
        )

    def clear(self) -> None:
        """Reset both tables to empty state."""
        self._follow_table.setRowCount(0)
        self._follow_header.setText("Follow Sources")
        self._like_table.setRowCount(0)
        self._like_header.setText("Like Sources")
