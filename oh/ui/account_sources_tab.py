"""
AccountSourcesTab -- embedded sources table in the account detail drawer.

Shows active + historical sources for one account with FBR metrics.
"""
import logging
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QScrollArea, QFrame,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from oh.ui.style import sc

logger = logging.getLogger(__name__)

# Column indices
_COL_SOURCE = 0   # Source name
_COL_STATUS = 1   # Active / Historical
_COL_FOLLOWS = 2  # Follow count
_COL_FBACKS = 3   # Followback count
_COL_FBR = 4      # FBR %
_COL_QUALITY = 5  # Quality flag

_HEADERS = ["Source", "Status", "Follows", "FBacks", "FBR %", "Quality"]


class AccountSourcesTab(QScrollArea):
    """Scrollable sources tab for the account detail drawer."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        self._container = QWidget()
        self._root = QVBoxLayout(self._container)
        self._root.setContentsMargins(6, 6, 6, 6)
        self._root.setSpacing(6)

        # Header label
        self._header_label = QLabel("Sources")
        self._header_label.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: %s;" % sc("heading").name()
        )
        self._root.addWidget(self._header_label)

        # Table
        self._table = QTableWidget(0, len(_HEADERS))
        self._table.setHorizontalHeaderLabels(_HEADERS)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.verticalHeader().setVisible(False)
        self._table.setAlternatingRowColors(True)
        self._table.setStyleSheet("font-size: 11px;")

        header = self._table.horizontalHeader()
        header.setSectionResizeMode(_COL_SOURCE, QHeaderView.ResizeMode.Stretch)
        for col in (_COL_STATUS, _COL_FOLLOWS, _COL_FBACKS, _COL_FBR, _COL_QUALITY):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.ResizeToContents)

        self._root.addWidget(self._table)
        self._root.addStretch()
        self.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_sources(self, sources: List[dict]) -> None:
        """Populate table from a list of source dicts.

        Each dict should have keys:
            source_name, is_active, follow_count, followback_count,
            fbr_percent, is_quality
        """
        self._table.setRowCount(0)

        if not sources:
            self._header_label.setText("Sources (none)")
            self._table.setRowCount(1)
            msg = QTableWidgetItem("No source data available. Run FBR Analysis first.")
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._table.setItem(0, 0, msg)
            self._table.setSpan(0, 0, 1, self._table.columnCount())
            return

        active_count = sum(1 for s in sources if s.get("is_active", False))
        hist_count = len(sources) - active_count
        self._header_label.setText(
            "Sources (%d active, %d historical)" % (active_count, hist_count)
        )

        # Sort: active first, then by FBR descending
        sorted_sources = sorted(
            sources,
            key=lambda s: (not s.get("is_active", False), -(s.get("fbr_percent", 0) or 0)),
        )

        self._table.setRowCount(len(sorted_sources))

        green = sc("success")
        red = sc("error")
        muted = sc("muted")

        for row, src in enumerate(sorted_sources):
            # Source name
            name_item = QTableWidgetItem(src.get("source_name", ""))
            self._table.setItem(row, _COL_SOURCE, name_item)

            # Status
            is_active = src.get("is_active", False)
            status_item = QTableWidgetItem("Active" if is_active else "Historical")
            status_item.setForeground(green if is_active else muted)
            self._table.setItem(row, _COL_STATUS, status_item)

            # Follow count
            follows = src.get("follow_count", 0) or 0
            follow_item = QTableWidgetItem(str(follows))
            follow_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, _COL_FOLLOWS, follow_item)

            # Followback count
            fbacks = src.get("followback_count", 0) or 0
            fback_item = QTableWidgetItem(str(fbacks))
            fback_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            self._table.setItem(row, _COL_FBACKS, fback_item)

            # FBR %
            fbr_pct = src.get("fbr_percent", 0) or 0
            fbr_item = QTableWidgetItem("%.1f%%" % fbr_pct)
            fbr_item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            if fbr_pct >= 10:
                fbr_item.setForeground(green)
            elif fbr_pct < 5:
                fbr_item.setForeground(muted)
            self._table.setItem(row, _COL_FBR, fbr_item)

            # Quality flag
            is_quality = src.get("is_quality", False)
            quality_item = QTableWidgetItem("Y" if is_quality else "-")
            quality_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            quality_item.setForeground(green if is_quality else muted)
            self._table.setItem(row, _COL_QUALITY, quality_item)

    def clear(self) -> None:
        """Reset the table to empty state."""
        self._table.setRowCount(0)
        self._header_label.setText("Sources")
