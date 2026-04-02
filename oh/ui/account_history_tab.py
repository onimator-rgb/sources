"""
AccountHistoryTab -- unified timeline in the account detail drawer.

Shows chronological history: operator actions, FBR snapshots, sessions.
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

# Column indices
_COL_DATE = 0    # Date/Time
_COL_TYPE = 1    # "Action" / "FBR" / "Session"
_COL_DETAIL = 2  # Description
_COL_VALUE = 3   # Value/result

_HEADERS = ["Date", "Type", "Detail", "Value"]

# Type colors (sc key)
_TYPE_COLORS = {
    "Action": "link",
    "FBR": "success",
    "Session": "muted",
}


class AccountHistoryTab(QScrollArea):
    """Scrollable history timeline for the account detail drawer."""

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
        self._header_label = QLabel("History")
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
        header.setSectionResizeMode(_COL_DATE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_TYPE, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(_COL_DETAIL, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(_COL_VALUE, QHeaderView.ResizeMode.ResizeToContents)

        self._root.addWidget(self._table)
        self._root.addStretch()
        self.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load_history(
        self,
        actions: Optional[List] = None,
        fbr_snapshots: Optional[List] = None,
        sessions: Optional[List] = None,
    ) -> None:
        """Merge all event types into a single chronological table.

        Parameters
        ----------
        actions : list of OperatorActionRecord
        fbr_snapshots : list of FBRSnapshotRecord
        sessions : list of AccountSessionRecord
        """
        self._table.setRowCount(0)

        events: List[tuple] = []  # (sort_key, date_str, type_str, detail, value)

        # --- Operator actions ---
        for act in (actions or []):
            ts = act.performed_at or ""
            old_val = act.old_value or ""
            new_val = act.new_value or ""
            detail = act.action_type or ""
            if old_val or new_val:
                detail = "%s: %s -> %s" % (act.action_type, old_val, new_val)
            value = act.note or ""
            events.append((ts, ts, "Action", detail, value))

        # --- FBR snapshots ---
        for snap in (fbr_snapshots or []):
            ts = getattr(snap, "analyzed_at", "") or ""
            quality = getattr(snap, "quality_sources", 0) or 0
            total = getattr(snap, "total_sources", 0) or 0
            best_pct = getattr(snap, "best_fbr_pct", None)
            detail = "Quality %d/%d" % (quality, total)
            value = "Best: %.1f%%" % best_pct if best_pct is not None else ""
            events.append((ts, ts, "FBR", detail, value))

        # --- Sessions ---
        for sess in (sessions or []):
            ts = getattr(sess, "snapshot_date", "") or ""
            collected = getattr(sess, "collected_at", "") or ts
            follow = getattr(sess, "follow_count", 0) or 0
            like = getattr(sess, "like_count", 0) or 0
            dm = getattr(sess, "dm_count", 0) or 0
            unfollow = getattr(sess, "unfollow_count", 0) or 0
            slot = getattr(sess, "slot", "") or ""
            detail = "F:%d L:%d DM:%d UF:%d" % (follow, like, dm, unfollow)
            value = slot
            events.append((collected, collected, "Session", detail, value))

        # Sort by date descending
        events.sort(key=lambda e: e[0], reverse=True)

        if not events:
            self._header_label.setText("History (empty)")
            return

        self._header_label.setText("History (%d events)" % len(events))
        self._table.setRowCount(len(events))

        for row, (_, date_str, type_str, detail, value) in enumerate(events):
            # Date — truncate to "YYYY-MM-DDTHH:MM" for readability
            date_str = date_str[:16]
            date_item = QTableWidgetItem(date_str)
            self._table.setItem(row, _COL_DATE, date_item)

            # Type with color
            type_item = QTableWidgetItem(type_str)
            color_key = _TYPE_COLORS.get(type_str, "muted")
            type_item.setForeground(sc(color_key))
            self._table.setItem(row, _COL_TYPE, type_item)

            # Detail
            detail_item = QTableWidgetItem(detail)
            self._table.setItem(row, _COL_DETAIL, detail_item)

            # Value
            value_item = QTableWidgetItem(value)
            self._table.setItem(row, _COL_VALUE, value_item)

    def clear(self) -> None:
        """Reset the table to empty state."""
        self._table.setRowCount(0)
        self._header_label.setText("History")
