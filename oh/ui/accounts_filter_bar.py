"""
AccountsFilterBar — filter controls for the Accounts tab.

Emits ``filters_changed`` whenever the operator changes any filter so that
MainWindow can re-run ``_apply_filter`` without accessing individual widgets.
"""
from __future__ import annotations

from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QComboBox, QLineEdit,
    QCheckBox, QPushButton, QMenu, QTableWidget,
)
from PySide6.QtCore import Signal

from oh.ui.style import sc
from oh.repositories.settings_repo import SettingsRepository

# ---------------------------------------------------------------------------
# Filter option constants — importable by MainWindow for _apply_filter
# ---------------------------------------------------------------------------

FBR_FILTER_ALL        = "All FBR states"
FBR_FILTER_ATTENTION  = "Needs attention"
FBR_FILTER_NEVER      = "Never analyzed"
FBR_FILTER_ERRORS     = "Has errors"
FBR_FILTER_NO_QUALITY = "No quality sources"
FBR_FILTER_HAS_QUALITY = "Has quality sources"

STATUS_FILTER_ACTIVE   = "Active only"
STATUS_FILTER_REMOVED  = "Removed only"
STATUS_FILTER_ALL      = "All accounts"

TAGS_FILTER_ALL     = "All tags"
TAGS_FILTER_TB      = "TB"
TAGS_FILTER_LIMITS  = "limits"
TAGS_FILTER_SLAVE   = "SLAVE"
TAGS_FILTER_START   = "START"
TAGS_FILTER_PK      = "PK"
TAGS_FILTER_CUSTOM  = "Custom"

ACTIVITY_FILTER_ALL      = "All activity"
ACTIVITY_FILTER_ZERO     = "0 actions today"
ACTIVITY_FILTER_HAS      = "Has actions"
ACTIVITY_FILTER_BLOCKED  = "Blocked"

TIMESLOT_FILTER_ALL = "All slots"
TIMESLOT_FILTER_1   = "Slot 1 (0-6)"
TIMESLOT_FILTER_2   = "Slot 2 (6-12)"
TIMESLOT_FILTER_3   = "Slot 3 (12-18)"
TIMESLOT_FILTER_4   = "Slot 4 (18-24)"

HEALTH_FILTER_ALL    = "All health"
HEALTH_FILTER_GREEN  = "Green (70+)"
HEALTH_FILTER_YELLOW = "Yellow (40-69)"
HEALTH_FILTER_RED    = "Red (<40)"


class AccountsFilterBar(QWidget):
    """Horizontal bar with all account-list filter controls."""

    filters_changed = Signal()

    def __init__(
        self,
        settings_repo: SettingsRepository,
        table: QTableWidget,
        column_headers: list,
        always_visible_cols: set,
        col_labels: dict,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_repo
        self._table = table
        self._column_headers = column_headers
        self._always_visible_cols = always_visible_cols
        self._col_labels = col_labels
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_filter_state(self) -> dict:
        """Return current values of all filters as a plain dict."""
        return {
            "status": self._status_filter.currentText(),
            "fbr": self._fbr_filter.currentText(),
            "device": self._device_filter.currentText(),
            "tags": self._tags_filter.currentText(),
            "activity": self._activity_filter.currentText(),
            "group": self._group_filter.currentText(),
            "timeslot": self._timeslot_filter.currentText(),
            "health": self._health_filter.currentText(),
            "review_only": self._review_cb.isChecked(),
            "query": self._search_box.text().strip().lower(),
            "show_orphans": self._show_orphans_cb.isChecked(),
        }

    def update_device_list(self, devices: list) -> None:
        """Rebuild the device dropdown, preserving the current selection."""
        current = self._device_filter.currentText()
        self._device_filter.blockSignals(True)
        self._device_filter.clear()
        items = ["All devices"] + devices
        self._device_filter.addItems(items)
        idx = self._device_filter.findText(current)
        self._device_filter.setCurrentIndex(max(idx, 0))
        self._device_filter.blockSignals(False)

    def update_group_list(self, groups: list) -> None:
        """Rebuild the group dropdown, preserving the current selection.

        ``groups`` is a list of group name strings.
        """
        current = self._group_filter.currentText()
        self._group_filter.blockSignals(True)
        self._group_filter.clear()
        self._group_filter.addItem("All groups")
        for name in groups:
            self._group_filter.addItem(name)
        idx = self._group_filter.findText(current)
        self._group_filter.setCurrentIndex(max(idx, 0))
        self._group_filter.blockSignals(False)

    def set_count_text(self, text: str) -> None:
        """Update the account-count label."""
        self._count_label.setText(text)

    def clear_filters(self) -> None:
        """Reset all filters to defaults without triggering multiple repaints."""
        widgets = (
            self._status_filter, self._fbr_filter, self._device_filter,
            self._search_box, self._show_orphans_cb,
            self._tags_filter, self._activity_filter, self._group_filter,
            self._timeslot_filter, self._health_filter,
            self._review_cb,
        )
        for w in widgets:
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

        for w in widgets:
            w.blockSignals(False)

        self.filters_changed.emit()

    def apply_column_visibility(self) -> None:
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
                if 0 <= col < len(self._column_headers) and col not in self._always_visible_cols:
                    self._table.setColumnHidden(col, True)
            except ValueError:
                pass

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        self.setObjectName("filterBar")
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 4, 0, 4)
        lo.setSpacing(4)

        # Status filter
        lo.addWidget(QLabel("Status:"))
        self._status_filter = QComboBox()
        self._status_filter.addItems([
            STATUS_FILTER_ACTIVE,
            STATUS_FILTER_REMOVED,
            STATUS_FILTER_ALL,
        ])
        self._status_filter.setMinimumWidth(80)
        self._status_filter.setMaximumWidth(130)
        self._status_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._status_filter)

        # FBR state filter
        lo.addWidget(QLabel("FBR:"))
        self._fbr_filter = QComboBox()
        self._fbr_filter.addItems([
            FBR_FILTER_ALL,
            FBR_FILTER_ATTENTION,
            FBR_FILTER_NEVER,
            FBR_FILTER_ERRORS,
            FBR_FILTER_NO_QUALITY,
            FBR_FILTER_HAS_QUALITY,
        ])
        self._fbr_filter.setMinimumWidth(100)
        self._fbr_filter.setMaximumWidth(170)
        self._fbr_filter.setToolTip(
            "Needs attention = never analyzed or zero quality sources"
        )
        self._fbr_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._fbr_filter)

        # Device filter
        lo.addWidget(QLabel("Device:"))
        self._device_filter = QComboBox()
        self._device_filter.setMinimumWidth(80)
        self._device_filter.setMaximumWidth(150)
        self._device_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._device_filter)

        # Text search
        lo.addWidget(QLabel("Search:"))
        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("username or device\u2026")
        self._search_box.setMinimumWidth(100)
        self._search_box.setMaximumWidth(250)
        self._search_box.textChanged.connect(self._on_filter_changed)
        lo.addWidget(self._search_box)

        # Tags filter
        lo.addWidget(QLabel("Tags:"))
        self._tags_filter = QComboBox()
        self._tags_filter.addItems([
            TAGS_FILTER_ALL, TAGS_FILTER_TB, TAGS_FILTER_LIMITS,
            TAGS_FILTER_SLAVE, TAGS_FILTER_START, TAGS_FILTER_PK,
            TAGS_FILTER_CUSTOM,
        ])
        self._tags_filter.setMinimumWidth(70)
        self._tags_filter.setMaximumWidth(110)
        self._tags_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._tags_filter)

        # Activity filter
        lo.addWidget(QLabel("Activity:"))
        self._activity_filter = QComboBox()
        self._activity_filter.addItems([
            ACTIVITY_FILTER_ALL, ACTIVITY_FILTER_ZERO, ACTIVITY_FILTER_HAS,
            ACTIVITY_FILTER_BLOCKED,
        ])
        self._activity_filter.setMinimumWidth(80)
        self._activity_filter.setMaximumWidth(140)
        self._activity_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._activity_filter)

        # Timeslot filter
        lo.addWidget(QLabel("Slot:"))
        self._timeslot_filter = QComboBox()
        self._timeslot_filter.addItems([
            TIMESLOT_FILTER_ALL, TIMESLOT_FILTER_1,
            TIMESLOT_FILTER_2, TIMESLOT_FILTER_3, TIMESLOT_FILTER_4,
        ])
        self._timeslot_filter.setMinimumWidth(70)
        self._timeslot_filter.setMaximumWidth(120)
        self._timeslot_filter.setToolTip("Filter by timeslot (derived from working hours)")
        self._timeslot_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._timeslot_filter)

        # Health filter
        lo.addWidget(QLabel("Health:"))
        self._health_filter = QComboBox()
        self._health_filter.addItems([
            HEALTH_FILTER_ALL, HEALTH_FILTER_GREEN,
            HEALTH_FILTER_YELLOW, HEALTH_FILTER_RED,
        ])
        self._health_filter.setMinimumWidth(70)
        self._health_filter.setMaximumWidth(120)
        self._health_filter.setToolTip("Filter by health score color band")
        self._health_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._health_filter)

        # Group filter
        lo.addWidget(QLabel("Group:"))
        self._group_filter = QComboBox()
        self._group_filter.addItem("All groups")
        self._group_filter.setMinimumWidth(80)
        self._group_filter.setMaximumWidth(140)
        self._group_filter.currentIndexChanged.connect(self._on_filter_changed)
        lo.addWidget(self._group_filter)

        # Review only checkbox
        self._review_cb = QCheckBox("Review only")
        self._review_cb.setToolTip("Show only accounts flagged for review")
        self._review_cb.stateChanged.connect(self._on_filter_changed)
        lo.addWidget(self._review_cb)

        # Orphans checkbox
        self._show_orphans_cb = QCheckBox("Show orphans")
        self._show_orphans_cb.setToolTip(
            "Orphan: folder exists on disk but not registered in accounts.db"
        )
        self._show_orphans_cb.stateChanged.connect(self._on_filter_changed)
        lo.addWidget(self._show_orphans_cb)

        # Clear button
        clear_btn = QPushButton("Clear")
        clear_btn.setFixedHeight(28)
        clear_btn.setToolTip("Reset all filters to defaults")
        clear_btn.clicked.connect(self.clear_filters)
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

    def _on_filter_changed(self) -> None:
        """Relay any filter change to the parent via signal."""
        self.filters_changed.emit()

    def _show_column_chooser(self, btn: QPushButton) -> None:
        """Show a popup menu with checkable column names."""
        menu = QMenu(self)
        actions = []
        for col in range(len(self._column_headers)):
            label = self._col_labels.get(col, self._column_headers[col])
            action = menu.addAction(label)
            action.setCheckable(True)
            action.setChecked(not self._table.isColumnHidden(col))
            if col in self._always_visible_cols:
                action.setEnabled(False)
            actions.append((col, action))

        menu.addSeparator()
        show_all = menu.addAction("Show All Columns")

        chosen = menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

        if chosen == show_all:
            for col in range(len(self._column_headers)):
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
        for col in range(len(self._column_headers)):
            if self._table.isColumnHidden(col) and col not in self._always_visible_cols:
                hidden.append(str(col))
        self._settings.set("hidden_columns", ",".join(hidden))
