"""
SettingsCopierDialog — 3-step wizard for copying bot settings between accounts.

Step 1: Select source account + choose which settings to copy (collapsible categories)
Step 2: Select target accounts + preview diff (with category group headers)
Step 3: Results summary (with category breakdown)
"""
import logging
from typing import Dict, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QCheckBox, QStackedWidget, QMessageBox,
    QWidget, QSplitter, QFrame, QScrollArea, QGridLayout,
    QGroupBox, QToolButton, QSizePolicy,
)
from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QFont

from oh.models.account import AccountRecord
from oh.models.settings_copy import (
    COPYABLE_SETTINGS,
    COPYABLE_TEXT_FILES,
    SETTINGS_CATEGORIES,
    ALL_COPYABLE_KEYS,
    SettingsCategory,
    SettingDef,
    SettingsSnapshot,
    SettingsDiff,
    SettingsDiffEntry,
    SettingsCopyBatchResult,
)
from oh.services.settings_copier_service import SettingsCopierService
from oh.ui.style import sc
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# Number of columns in the settings grid inside each collapsible section
_GRID_COLUMNS = 2


class CollapsibleSection(QWidget):
    """A section with a clickable header that shows/hides content."""

    def __init__(self, title: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._title = title
        self._checkboxes: List[tuple] = []  # (key, QCheckBox)

        main_lo = QVBoxLayout(self)
        main_lo.setContentsMargins(0, 0, 0, 0)
        main_lo.setSpacing(0)

        # --- Header row ---
        header = QWidget()
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header_lo = QHBoxLayout(header)
        header_lo.setContentsMargins(4, 4, 8, 4)
        header_lo.setSpacing(6)

        # Arrow toggle button
        self._toggle_btn = QToolButton()
        self._toggle_btn.setArrowType(Qt.ArrowType.RightArrow)
        self._toggle_btn.setAutoRaise(True)
        self._toggle_btn.setFixedSize(QSize(20, 20))
        self._toggle_btn.clicked.connect(self.toggle)
        header_lo.addWidget(self._toggle_btn)

        # Category title (bold)
        self._title_label = QLabel(title)
        title_font = QFont()
        title_font.setBold(True)
        self._title_label.setFont(title_font)
        self._title_label.setCursor(Qt.CursorShape.PointingHandCursor)
        header_lo.addWidget(self._title_label)

        header_lo.addStretch()

        # "Select All" checkbox for this category
        self._select_all_cb = QCheckBox("Select All")
        self._select_all_cb.stateChanged.connect(self._on_select_all_changed)
        header_lo.addWidget(self._select_all_cb)

        # Count label (e.g. "0/45 selected")
        self._count_label = QLabel("0/0 selected")
        self._count_label.setStyleSheet(f"color: {sc('muted').name()};")
        header_lo.addWidget(self._count_label)

        # Make header clickable for toggle
        header.mousePressEvent = lambda _event: self.toggle()
        main_lo.addWidget(header)

        # Separator line
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        main_lo.addWidget(sep)

        # --- Content area (collapsible) ---
        self._content = QWidget()
        self._content_layout = QGridLayout(self._content)
        self._content_layout.setContentsMargins(28, 4, 4, 8)
        self._content_layout.setSpacing(4)
        main_lo.addWidget(self._content)

        # Start collapsed
        self._expanded = False
        self._content.setVisible(False)

    def toggle(self) -> None:
        """Show/hide content widget and change arrow direction."""
        self._expanded = not self._expanded
        self._content.setVisible(self._expanded)
        arrow = Qt.ArrowType.DownArrow if self._expanded else Qt.ArrowType.RightArrow
        self._toggle_btn.setArrowType(arrow)

    def set_expanded(self, expanded: bool) -> None:
        """Programmatically expand or collapse."""
        if self._expanded != expanded:
            self.toggle()

    def add_setting_checkbox(
        self,
        setting_key: str,
        display_name: str,
        value_text: str,
        has_value: bool,
        row: int,
        col: int,
    ) -> QCheckBox:
        """Add a single setting checkbox to the grid layout."""
        text = display_name
        if value_text:
            text = f"{display_name}: {value_text}"

        cb = QCheckBox(text)
        cb.setChecked(has_value)
        cb.setEnabled(has_value)
        if not has_value:
            cb.setStyleSheet(f"color: {sc('muted').name()};")
        cb.stateChanged.connect(lambda _: self._on_child_changed())
        self._checkboxes.append((setting_key, cb))
        self._content_layout.addWidget(cb, row, col)
        return cb

    def get_selected_keys(self) -> List[str]:
        """Return list of keys that are checked."""
        return [key for key, cb in self._checkboxes if cb.isChecked()]

    def set_all_checked(self, checked: bool) -> None:
        """Check or uncheck all enabled checkboxes."""
        for _key, cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(checked)
        self.update_count_label()

    def update_count_label(self) -> None:
        """Update the 'X/Y selected' count label."""
        total = len(self._checkboxes)
        selected = sum(1 for _, cb in self._checkboxes if cb.isChecked())
        self._count_label.setText(f"{selected}/{total} selected")

        # Update select-all checkbox state without triggering its signal
        self._select_all_cb.blockSignals(True)
        enabled_cbs = [(k, cb) for k, cb in self._checkboxes if cb.isEnabled()]
        if enabled_cbs:
            all_checked = all(cb.isChecked() for _, cb in enabled_cbs)
            any_checked = any(cb.isChecked() for _, cb in enabled_cbs)
            if all_checked:
                self._select_all_cb.setCheckState(Qt.CheckState.Checked)
            elif any_checked:
                self._select_all_cb.setCheckState(Qt.CheckState.PartiallyChecked)
            else:
                self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        else:
            self._select_all_cb.setCheckState(Qt.CheckState.Unchecked)
        self._select_all_cb.blockSignals(False)

    def _on_select_all_changed(self, state: int) -> None:
        """Handle 'Select All' checkbox for this category."""
        checked = bool(state == Qt.CheckState.Checked or state == 2)
        self.set_all_checked(checked)

    def _on_child_changed(self) -> None:
        """When an individual checkbox changes, update counts."""
        self.update_count_label()

    @property
    def checkboxes(self) -> List[tuple]:
        return self._checkboxes

    @property
    def category_title(self) -> str:
        return self._title


class SettingsCopierDialog(QDialog):
    """3-step wizard for copying settings between accounts."""

    def __init__(
        self,
        service: SettingsCopierService,
        accounts: List[AccountRecord],
        pre_selected_source_id: Optional[int] = None,
        pre_selected_target_ids: Optional[List[int]] = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._accounts = [a for a in accounts if a.is_active]
        self._pre_selected_source_id = pre_selected_source_id
        self._pre_selected_target_ids = pre_selected_target_ids or []

        self._source_snapshot: Optional[SettingsSnapshot] = None
        self._diffs: List[SettingsDiff] = []
        self._worker: Optional[WorkerThread] = None
        self._sections: List[CollapsibleSection] = []
        self._text_file_checkboxes: List[tuple] = []  # (filename, QCheckBox)
        self._target_checkboxes: list = []

        self.setWindowTitle("Copy Settings")
        self.setMinimumSize(800, 600)
        self.resize(900, 700)
        self.setModal(True)

        self._build_ui()

        # Pre-select source if provided
        if pre_selected_source_id is not None:
            self._pre_select_source(pre_selected_source_id)

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_lo = QVBoxLayout(self)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"font-size: 14px; font-weight: bold; color: {sc('heading').name()};"
        )
        main_lo.addWidget(self._title_label)

        self._stack = QStackedWidget()
        self._stack.addWidget(self._build_step1())
        self._stack.addWidget(self._build_step2())
        self._stack.addWidget(self._build_step3())
        main_lo.addWidget(self._stack, 1)

        # Navigation buttons
        nav_lo = QHBoxLayout()
        self._back_btn = QPushButton("<< Back")
        self._back_btn.clicked.connect(self._on_back)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        self._next_btn = QPushButton("Next >>")
        self._next_btn.clicked.connect(self._on_next)

        nav_lo.addWidget(self._back_btn)
        nav_lo.addStretch()
        nav_lo.addWidget(self._cancel_btn)
        nav_lo.addWidget(self._next_btn)
        main_lo.addLayout(nav_lo)

        self._go_to_step(0)

    def _build_step1(self) -> QWidget:
        """Step 1: Select source account and settings to copy."""
        w = QWidget()
        lo = QVBoxLayout(w)

        # Source account combo
        src_lo = QHBoxLayout()
        src_lo.addWidget(QLabel("Source account:"))
        self._source_combo = QComboBox()
        self._source_combo.setMinimumWidth(300)
        self._source_combo.addItem("\u2014 Select account \u2014", None)
        for acc in self._accounts:
            label = f"{acc.username}  ({acc.device_name or acc.device_id[:12]})"
            self._source_combo.addItem(label, acc.id)
        self._source_combo.currentIndexChanged.connect(self._on_source_changed)
        src_lo.addWidget(self._source_combo, 1)
        lo.addLayout(src_lo)

        # Global controls
        controls_lo = QHBoxLayout()
        controls_lo.addWidget(QLabel("Settings to copy:"))
        controls_lo.addStretch()

        self._select_all_global_btn = QPushButton("Select All")
        self._select_all_global_btn.clicked.connect(lambda: self._global_select(True))
        controls_lo.addWidget(self._select_all_global_btn)

        self._deselect_all_global_btn = QPushButton("Deselect All")
        self._deselect_all_global_btn.clicked.connect(lambda: self._global_select(False))
        controls_lo.addWidget(self._deselect_all_global_btn)

        self._select_limits_btn = QPushButton("Select Limits Only")
        self._select_limits_btn.clicked.connect(self._select_limits_only)
        controls_lo.addWidget(self._select_limits_btn)

        lo.addLayout(controls_lo)

        # Scroll area for categories
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        self._categories_container = QWidget()
        self._categories_layout = QVBoxLayout(self._categories_container)
        self._categories_layout.setContentsMargins(0, 0, 0, 0)
        self._categories_layout.setSpacing(2)

        # Placeholder for category sections (populated when source is selected)
        self._categories_layout.addStretch()

        scroll.setWidget(self._categories_container)
        lo.addWidget(scroll, 1)

        # Text files group (populated when source is selected)
        self._text_files_group = QGroupBox("Text Files")
        self._text_files_layout = QVBoxLayout(self._text_files_group)
        self._text_files_group.setVisible(False)
        lo.addWidget(self._text_files_group)

        # Error label
        self._step1_error = QLabel("")
        self._step1_error.setStyleSheet(f"color: {sc('error').name()};")
        lo.addWidget(self._step1_error)

        return w

    def _build_step2(self) -> QWidget:
        """Step 2: Select targets + preview diff."""
        w = QWidget()
        lo = QVBoxLayout(w)

        # Quick-select buttons
        btn_lo = QHBoxLayout()
        btn_lo.addWidget(QLabel("Select target accounts:"))
        btn_lo.addStretch()
        self._sel_all_btn = QPushButton("Select All")
        self._sel_all_btn.clicked.connect(lambda: self._toggle_all_targets(True))
        self._sel_none_btn = QPushButton("Select None")
        self._sel_none_btn.clicked.connect(lambda: self._toggle_all_targets(False))
        self._sel_device_btn = QPushButton("Select Same Device")
        self._sel_device_btn.clicked.connect(self._select_same_device)
        btn_lo.addWidget(self._sel_all_btn)
        btn_lo.addWidget(self._sel_none_btn)
        btn_lo.addWidget(self._sel_device_btn)
        lo.addLayout(btn_lo)

        # Splitter: target list on top, diff preview on bottom
        splitter = QSplitter(Qt.Orientation.Vertical)

        # Target account list
        self._target_table = QTableWidget()
        self._target_table.setColumnCount(3)
        self._target_table.setHorizontalHeaderLabels(["Select", "Account", "Changes"])
        self._target_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._target_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._target_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.ResizeToContents
        )
        self._target_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._target_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._target_table.verticalHeader().setVisible(False)
        self._target_table.currentCellChanged.connect(self._on_target_selected)
        splitter.addWidget(self._target_table)

        # Diff preview
        diff_frame = QFrame()
        diff_lo = QVBoxLayout(diff_frame)
        self._diff_label = QLabel("Preview:")
        diff_lo.addWidget(self._diff_label)
        self._diff_table = QTableWidget()
        self._diff_table.setColumnCount(3)
        self._diff_table.setHorizontalHeaderLabels(["Setting", "Current", "New"])
        self._diff_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._diff_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._diff_table.verticalHeader().setVisible(False)
        diff_lo.addWidget(self._diff_table)
        splitter.addWidget(diff_frame)

        lo.addWidget(splitter, 1)
        return w

    def _build_step3(self) -> QWidget:
        """Step 3: Results summary."""
        w = QWidget()
        lo = QVBoxLayout(w)

        self._result_summary = QLabel("")
        self._result_summary.setStyleSheet("font-size: 13px;")
        lo.addWidget(self._result_summary)

        self._result_table = QTableWidget()
        self._result_table.setColumnCount(4)
        self._result_table.setHorizontalHeaderLabels(
            ["Account", "Device", "Status", "Keys Changed"]
        )
        self._result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._result_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._result_table.verticalHeader().setVisible(False)
        lo.addWidget(self._result_table, 1)

        return w

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_step(self, step: int) -> None:
        self._stack.setCurrentIndex(step)

        if step == 0:
            self._title_label.setText("Copy Settings \u2014 Step 1 of 3")
            self._back_btn.setVisible(False)
            self._next_btn.setText("Next >>")
            self._next_btn.setVisible(True)
            self._cancel_btn.setText("Cancel")
            self._update_step1_next_state()
        elif step == 1:
            self._title_label.setText("Copy Settings \u2014 Step 2 of 3")
            self._back_btn.setVisible(True)
            self._next_btn.setText("Apply")
            self._next_btn.setVisible(True)
            self._cancel_btn.setText("Cancel")
            self._update_apply_state()
        elif step == 2:
            self._title_label.setText("Copy Settings \u2014 Results")
            self._back_btn.setVisible(False)
            self._next_btn.setVisible(False)
            self._cancel_btn.setText("Close")

    def _on_back(self) -> None:
        current = self._stack.currentIndex()
        if current > 0:
            self._go_to_step(current - 1)

    def _on_next(self) -> None:
        current = self._stack.currentIndex()
        if current == 0:
            self._enter_step2()
        elif current == 1:
            self._on_apply()

    # ------------------------------------------------------------------
    # Step 1 logic
    # ------------------------------------------------------------------

    def _pre_select_source(self, account_id: int) -> None:
        for i in range(self._source_combo.count()):
            if self._source_combo.itemData(i) == account_id:
                self._source_combo.setCurrentIndex(i)
                break

    def _on_source_changed(self) -> None:
        account_id = self._source_combo.currentData()
        if account_id is None:
            self._source_snapshot = None
            self._clear_categories()
            self._step1_error.setText("")
            self._update_step1_next_state()
            return

        # Disable combo while loading to prevent re-entrant calls
        self._source_combo.setEnabled(False)
        self._step1_error.setText("Loading settings...")

        self._worker = WorkerThread(
            self._service.read_source_settings, account_id
        )
        self._worker.result.connect(self._on_source_loaded)
        self._worker.error.connect(self._on_source_load_error)
        self._worker.start()

    def _on_source_loaded(self, snapshot) -> None:
        """Handle result from background read_source_settings."""
        self._source_combo.setEnabled(True)
        self._source_snapshot = snapshot

        if snapshot.error:
            self._step1_error.setText(f"Error: {snapshot.error}")
            self._clear_categories()
            self._update_step1_next_state()
            return

        self._step1_error.setText("")
        self._populate_categories(snapshot)
        self._populate_text_files(snapshot)
        self._update_step1_next_state()

    def _on_source_load_error(self, msg: str) -> None:
        """Handle error from background read_source_settings."""
        self._source_combo.setEnabled(True)
        self._step1_error.setText(f"Error loading settings: {msg}")
        logger.error(f"Failed to read source settings: {msg}")

    def _clear_categories(self) -> None:
        """Remove all category sections and text file checkboxes."""
        self._sections.clear()
        self._text_file_checkboxes.clear()

        # Clear categories layout
        while self._categories_layout.count():
            item = self._categories_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        self._categories_layout.addStretch()

        # Clear text files
        while self._text_files_layout.count():
            item = self._text_files_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()
        self._text_files_group.setVisible(False)

    def _populate_categories(self, snapshot: SettingsSnapshot) -> None:
        """Build collapsible sections for each settings category."""
        self._sections.clear()

        # Clear categories layout
        while self._categories_layout.count():
            item = self._categories_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        for category in SETTINGS_CATEGORIES:
            section = CollapsibleSection(
                f"{category.name} ({len(category.settings)})", self
            )

            for idx, setting in enumerate(category.settings):
                row = idx // _GRID_COLUMNS
                col = idx % _GRID_COLUMNS

                has_value = setting.key in snapshot.values
                val = snapshot.values.get(setting.key)
                if val is not None:
                    val_str = str(val)
                    # Truncate long values
                    if len(val_str) > 30:
                        val_str = val_str[:27] + "..."
                else:
                    val_str = "(not set)" if not has_value else "None"

                section.add_setting_checkbox(
                    setting_key=setting.key,
                    display_name=setting.display_name,
                    value_text=val_str,
                    has_value=has_value,
                    row=row,
                    col=col,
                )

            section.update_count_label()

            # Connect child changes to update Next button state
            for _key, cb in section.checkboxes:
                cb.stateChanged.connect(lambda _: self._update_step1_next_state())

            self._sections.append(section)
            self._categories_layout.addWidget(section)

        self._categories_layout.addStretch()

    def _populate_text_files(self, snapshot: SettingsSnapshot) -> None:
        """Populate the text files group box."""
        self._text_file_checkboxes.clear()

        # Clear existing
        while self._text_files_layout.count():
            item = self._text_files_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

        if not COPYABLE_TEXT_FILES:
            self._text_files_group.setVisible(False)
            return

        text_files = snapshot.text_files or {}

        for filename, display_name in COPYABLE_TEXT_FILES:
            exists = filename in text_files and text_files[filename] is not None
            indicator = "(exists)" if exists else "(missing)"
            cb = QCheckBox(f"{display_name}  {indicator}")
            cb.setChecked(exists)
            cb.setEnabled(exists)
            if not exists:
                cb.setStyleSheet(f"color: {sc('muted').name()};")
            cb.stateChanged.connect(lambda _: self._update_step1_next_state())
            self._text_file_checkboxes.append((filename, cb))
            self._text_files_layout.addWidget(cb)

        self._text_files_group.setVisible(True)

    def _global_select(self, checked: bool) -> None:
        """Select or deselect all settings in all categories + text files."""
        for section in self._sections:
            section.set_all_checked(checked)
        for _fn, cb in self._text_file_checkboxes:
            if cb.isEnabled():
                cb.setChecked(checked)
        self._update_step1_next_state()

    def _select_limits_only(self) -> None:
        """Quick-select only limit/cap related settings."""
        limit_keywords = {"limit", "cap", "perday", "per_day", "daily"}

        # Deselect everything first
        self._global_select(False)

        for section in self._sections:
            for key, cb in section.checkboxes:
                if cb.isEnabled():
                    key_lower = key.lower()
                    if any(kw in key_lower for kw in limit_keywords):
                        cb.setChecked(True)
            section.update_count_label()

        self._update_step1_next_state()

    def _get_selected_keys(self) -> List[str]:
        """Return list of all selected keys (settings + text files)."""
        keys = []
        for section in self._sections:
            keys.extend(section.get_selected_keys())
        # Text files use "file:" prefix
        for filename, cb in self._text_file_checkboxes:
            if cb.isChecked():
                keys.append(f"file:{filename}")
        return keys

    def _update_step1_next_state(self) -> None:
        has_source = (
            self._source_snapshot is not None
            and self._source_snapshot.error is None
        )
        has_keys = len(self._get_selected_keys()) > 0
        self._next_btn.setEnabled(has_source and has_keys)

    # ------------------------------------------------------------------
    # Step 2 logic
    # ------------------------------------------------------------------

    def _enter_step2(self) -> None:
        """Transition from step 1 to step 2: compute diffs in background."""
        if self._source_snapshot is None:
            return

        selected_keys = self._get_selected_keys()
        source_id = self._source_snapshot.account_id

        # Get target account IDs (all active except source)
        target_ids = [a.id for a in self._accounts if a.id != source_id]

        if not target_ids:
            QMessageBox.information(
                self, "No Targets",
                "No other active accounts found to copy settings to.",
            )
            return

        # Disable navigation while computing diffs
        self._next_btn.setEnabled(False)
        self._step1_error.setText("Computing diffs...")

        self._worker = WorkerThread(
            self._service.preview_diff,
            self._source_snapshot, target_ids, selected_keys,
        )
        self._worker.result.connect(self._on_diffs_loaded)
        self._worker.error.connect(self._on_diffs_error)
        self._worker.start()

    def _on_diffs_loaded(self, diffs) -> None:
        """Handle result from background preview_diff."""
        self._step1_error.setText("")
        self._next_btn.setEnabled(True)
        self._diffs = diffs

        self._populate_target_table()
        self._go_to_step(1)

        # Pre-select targets if provided
        if self._pre_selected_target_ids:
            self._apply_pre_selected_targets()

    def _on_diffs_error(self, msg: str) -> None:
        """Handle error from background preview_diff."""
        self._next_btn.setEnabled(True)
        self._step1_error.setText(f"Error computing diffs: {msg}")
        logger.error(f"Failed to compute diffs: {msg}")

    def _populate_target_table(self) -> None:
        self._target_table.setRowCount(len(self._diffs))
        self._target_checkboxes = []

        for row_idx, diff in enumerate(self._diffs):
            # Checkbox
            cb = QCheckBox()
            has_changes = diff.different_count > 0
            cb.setChecked(has_changes)
            cb.setEnabled(has_changes)
            cb.stateChanged.connect(lambda _: self._update_apply_state())
            self._target_checkboxes.append((diff.target_account_id, cb))

            cb_widget = QWidget()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.addWidget(cb)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            self._target_table.setCellWidget(row_idx, 0, cb_widget)

            # Account name
            dev_label = diff.target_device_name or "?"
            name_item = QTableWidgetItem(f"{diff.target_username} @ {dev_label}")
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_changes:
                name_item.setForeground(sc('muted'))
            self._target_table.setItem(row_idx, 1, name_item)

            # Changes count
            if has_changes:
                changes_text = f"{diff.different_count} change(s)"
            else:
                changes_text = "0 changes (identical)"
            changes_item = QTableWidgetItem(changes_text)
            changes_item.setFlags(changes_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not has_changes:
                changes_item.setForeground(sc('muted'))
            self._target_table.setItem(row_idx, 2, changes_item)

    def _apply_pre_selected_targets(self) -> None:
        """Check pre-selected targets from constructor."""
        pre_ids = set(self._pre_selected_target_ids)
        for target_id, cb in self._target_checkboxes:
            if target_id in pre_ids and cb.isEnabled():
                cb.setChecked(True)
        self._update_apply_state()

    def _toggle_all_targets(self, checked: bool) -> None:
        for _, cb in self._target_checkboxes:
            if cb.isEnabled():
                cb.setChecked(checked)
        self._update_apply_state()

    def _select_same_device(self) -> None:
        """Select only targets on the same device as the source."""
        if self._source_snapshot is None:
            return
        source_device = self._source_snapshot.device_id

        for row_idx, (target_id, cb) in enumerate(self._target_checkboxes):
            if not cb.isEnabled():
                continue
            diff = self._diffs[row_idx]
            # Find the account to check device_id
            acc = None
            for a in self._accounts:
                if a.id == target_id:
                    acc = a
                    break
            if acc and acc.device_id == source_device:
                cb.setChecked(True)
            else:
                cb.setChecked(False)
        self._update_apply_state()

    def _on_target_selected(self, row: int, _col: int, _prev_row: int, _prev_col: int) -> None:
        """When a target row is clicked, show its diff in the preview table."""
        if row < 0 or row >= len(self._diffs):
            self._diff_table.setRowCount(0)
            self._diff_label.setText("Preview:")
            return

        diff = self._diffs[row]
        dev_label = diff.target_device_name or "?"
        self._diff_label.setText(f"Preview ({diff.target_username} @ {dev_label}):")
        self._populate_diff_table(diff)

    def _populate_diff_table(self, diff: SettingsDiff) -> None:
        """Populate diff table with category group headers (gray separator rows)."""
        # Build a mapping: category_name -> list of entries
        # For entries belonging to a category, group them; text file entries go at the end
        selected_keys = self._get_selected_keys()

        # Build category key sets for grouping
        cat_key_map: Dict[str, str] = {}  # setting key -> category name
        for cat in SETTINGS_CATEGORIES:
            for sd in cat.settings:
                cat_key_map[sd.key] = cat.name

        # Group entries by category
        grouped: Dict[str, List[SettingsDiffEntry]] = {}
        text_file_entries: List[SettingsDiffEntry] = []
        for entry in diff.entries:
            if entry.key.startswith("file:"):
                text_file_entries.append(entry)
            else:
                cat_name = cat_key_map.get(entry.key, "Other")
                if cat_name not in grouped:
                    grouped[cat_name] = []
                grouped[cat_name].append(entry)

        # Count total rows: category headers + entries + text file header + text entries
        total_rows = 0
        ordered_cats = []
        for cat in SETTINGS_CATEGORIES:
            if cat.name in grouped:
                ordered_cats.append(cat.name)
                total_rows += 1 + len(grouped[cat.name])  # header + entries
        if text_file_entries:
            total_rows += 1 + len(text_file_entries)  # header + entries

        self._diff_table.setRowCount(total_rows)

        row_idx = 0
        header_font = QFont()
        header_font.setBold(True)

        for cat_name in ordered_cats:
            entries = grouped[cat_name]

            # Category header row
            header_item = QTableWidgetItem(f"\u25B8 {cat_name}")
            header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            header_item.setFont(header_font)
            header_item.setForeground(sc('heading'))
            header_item.setBackground(sc('bg_note'))
            # Span across all 3 columns visually — set empty items for other cols
            self._diff_table.setItem(row_idx, 0, header_item)
            for col in (1, 2):
                spacer = QTableWidgetItem("")
                spacer.setFlags(spacer.flags() & ~Qt.ItemFlag.ItemIsEditable)
                spacer.setBackground(sc('bg_note'))
                self._diff_table.setItem(row_idx, col, spacer)
            self._diff_table.setSpan(row_idx, 0, 1, 3)
            row_idx += 1

            # Setting entries
            for entry in entries:
                row_idx = self._add_diff_entry_row(row_idx, entry)

        # Text file section
        if text_file_entries:
            header_item = QTableWidgetItem("\u25B8 Text Files")
            header_item.setFlags(header_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            header_item.setFont(header_font)
            header_item.setForeground(sc('heading'))
            header_item.setBackground(sc('bg_note'))
            self._diff_table.setItem(row_idx, 0, header_item)
            for col in (1, 2):
                spacer = QTableWidgetItem("")
                spacer.setFlags(spacer.flags() & ~Qt.ItemFlag.ItemIsEditable)
                spacer.setBackground(sc('bg_note'))
                self._diff_table.setItem(row_idx, col, spacer)
            self._diff_table.setSpan(row_idx, 0, 1, 3)
            row_idx += 1

            for entry in text_file_entries:
                row_idx = self._add_diff_entry_row(row_idx, entry)

    def _add_diff_entry_row(self, row_idx: int, entry: SettingsDiffEntry) -> int:
        """Add a single diff entry row and return the next row index."""
        # Setting name
        name_item = QTableWidgetItem(entry.display_name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._diff_table.setItem(row_idx, 0, name_item)

        # Current value
        current_text = str(entry.target_value) if entry.target_value is not None else "(not set)"
        current_item = QTableWidgetItem(current_text)
        current_item.setFlags(current_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self._diff_table.setItem(row_idx, 1, current_item)

        # New value
        new_text = str(entry.source_value) if entry.source_value is not None else "(not set)"
        new_item = QTableWidgetItem(new_text)
        new_item.setFlags(new_item.flags() & ~Qt.ItemFlag.ItemIsEditable)

        if entry.is_different:
            bold_font = QFont()
            bold_font.setBold(True)
            new_item.setFont(bold_font)
            new_item.setForeground(sc('warning'))
            name_item.setFont(bold_font)
        else:
            current_item.setForeground(sc('muted'))
            new_item.setForeground(sc('muted'))
            name_item.setForeground(sc('muted'))

        self._diff_table.setItem(row_idx, 2, new_item)
        return row_idx + 1

    def _get_checked_target_ids(self) -> List[int]:
        """Return list of target account IDs that are checked."""
        return [tid for tid, cb in self._target_checkboxes if cb.isChecked()]

    def _update_apply_state(self) -> None:
        checked = self._get_checked_target_ids()
        count = len(checked)
        if count > 0:
            self._next_btn.setText(f"Apply to {count} account(s)")
            self._next_btn.setEnabled(True)
        else:
            self._next_btn.setText("Apply")
            self._next_btn.setEnabled(False)

    # ------------------------------------------------------------------
    # Apply logic
    # ------------------------------------------------------------------

    def _on_apply(self) -> None:
        """Confirm and execute the copy operation."""
        target_ids = self._get_checked_target_ids()
        selected_keys = self._get_selected_keys()

        if not target_ids or not selected_keys:
            return

        # Count settings vs text files for the confirmation message
        settings_count = sum(1 for k in selected_keys if not k.startswith("file:"))
        text_count = sum(1 for k in selected_keys if k.startswith("file:"))
        parts = []
        if settings_count:
            parts.append(f"{settings_count} setting(s)")
        if text_count:
            parts.append(f"{text_count} text file(s)")
        items_desc = " + ".join(parts)

        reply = QMessageBox.question(
            self,
            "Confirm Copy",
            f"Apply {items_desc} to {len(target_ids)} account(s)?\n\n"
            f"A backup of each settings.db will be created before writing.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        # Disable controls during execution
        self._next_btn.setEnabled(False)
        self._back_btn.setEnabled(False)
        self._cancel_btn.setEnabled(False)

        # Run in background thread
        self._worker = WorkerThread(
            self._service.apply_copy,
            self._source_snapshot,
            target_ids,
            selected_keys,
        )
        self._worker.result.connect(self._on_apply_done)
        self._worker.error.connect(self._on_apply_error)
        self._worker.start()

    def _on_apply_done(self, batch_result: SettingsCopyBatchResult) -> None:
        """Handle successful completion of the apply operation."""
        self._worker = None
        self._cancel_btn.setEnabled(True)
        self._show_results(batch_result)
        self._go_to_step(2)

    def _on_apply_error(self, error_msg: str) -> None:
        """Handle error during apply operation."""
        self._worker = None
        self._next_btn.setEnabled(True)
        self._back_btn.setEnabled(True)
        self._cancel_btn.setEnabled(True)
        QMessageBox.critical(
            self, "Error",
            f"Copy operation failed:\n{error_msg}",
        )

    def _show_results(self, batch: SettingsCopyBatchResult) -> None:
        """Populate step 3 with results including category breakdown."""
        selected_keys = self._get_selected_keys()

        # Build category breakdown
        cat_counts: Dict[str, int] = {}
        text_file_count = 0
        for key in selected_keys:
            if key.startswith("file:"):
                text_file_count += 1
            else:
                for cat in SETTINGS_CATEGORIES:
                    cat_key_set = {sd.key for sd in cat.settings}
                    if key in cat_key_set:
                        cat_counts[cat.name] = cat_counts.get(cat.name, 0) + 1
                        break

        summary_parts = [
            f"Copied settings from <b>{batch.source_username}</b>:",
            f"&nbsp;&nbsp;{batch.success_count} / {batch.total_targets} accounts updated successfully",
        ]
        if batch.fail_count > 0:
            summary_parts.append(
                f"&nbsp;&nbsp;<span style='color:{sc('error').name()}'>"
                f"{batch.fail_count} failed</span>"
            )

        # Category breakdown
        if cat_counts or text_file_count:
            breakdown = []
            for cat_name, cnt in cat_counts.items():
                breakdown.append(f"{cat_name}: {cnt}")
            if text_file_count:
                breakdown.append(f"Text Files: {text_file_count}")
            summary_parts.append(
                f"&nbsp;&nbsp;Categories: {', '.join(breakdown)}"
            )

        self._result_summary.setText("<br>".join(summary_parts))

        self._result_table.setRowCount(len(batch.results))
        for row_idx, result in enumerate(batch.results):
            # Account
            name_item = QTableWidgetItem(result.target_username)
            name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._result_table.setItem(row_idx, 0, name_item)

            # Device
            dev_item = QTableWidgetItem(result.target_device_name or "?")
            dev_item.setFlags(dev_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self._result_table.setItem(row_idx, 1, dev_item)

            # Status
            if result.success:
                status_text = "OK"
                status_color = sc('success')
            else:
                status_text = "FAILED"
                status_color = sc('error')
            status_item = QTableWidgetItem(status_text)
            status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            status_item.setForeground(status_color)
            self._result_table.setItem(row_idx, 2, status_item)

            # Keys changed / error
            if result.success:
                # Show breakdown: N settings + M text files
                settings_written = [k for k in result.keys_written if not k.startswith("file:")]
                files_written = [k for k in result.keys_written if k.startswith("file:")]
                detail_parts = []
                if settings_written:
                    detail_parts.append(f"{len(settings_written)} settings")
                if files_written:
                    detail_parts.append(f"{len(files_written)} files")
                detail = ", ".join(detail_parts) if detail_parts else "0"
            else:
                detail = result.error or "Unknown error"
            detail_item = QTableWidgetItem(detail)
            detail_item.setFlags(detail_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            if not result.success:
                detail_item.setForeground(sc('error'))
            self._result_table.setItem(row_idx, 3, detail_item)
