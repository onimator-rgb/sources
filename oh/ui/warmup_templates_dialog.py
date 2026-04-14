"""
WarmupTemplatesDialog — manage warmup configuration templates.

Provides a split-panel UI: template list on the left, editor form on the right.
Opened from the Settings tab via the "Manage Warmup Templates" button.
"""
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QGroupBox,
    QFormLayout, QLineEdit, QSpinBox, QCheckBox,
    QMessageBox, QTextEdit, QSplitter, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from oh.models.warmup_template import WarmupTemplate
from oh.repositories.warmup_template_repo import WarmupTemplateRepository
from oh.ui.style import sc, BTN_HEIGHT_SM, BTN_HEIGHT_MD

logger = logging.getLogger(__name__)


class WarmupTemplatesDialog(QDialog):
    """Dialog for creating, editing, and deleting warmup templates."""

    def __init__(
        self,
        repo: WarmupTemplateRepository,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._current_template: Optional[WarmupTemplate] = None

        self.setWindowTitle("Warmup Templates")
        self.resize(850, 520)
        self._build_ui()
        self._refresh_list()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(10)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ---- Left panel: template list ----
        left = QWidget()
        left_lo = QVBoxLayout(left)
        left_lo.setContentsMargins(0, 0, 0, 0)

        lbl = QLabel("Templates")
        lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        left_lo.addWidget(lbl)

        self._table = QTableWidget(0, 5)
        self._table.setHorizontalHeaderLabels(
            ["Name", "Follow", "Like", "Auto-incr", "Created"]
        )
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.Stretch
        )
        self._table.verticalHeader().setVisible(False)
        self._table.currentItemChanged.connect(self._on_selection_changed)
        left_lo.addWidget(self._table)

        btn_row = QHBoxLayout()
        self._new_btn = QPushButton("New")
        self._new_btn.setFixedHeight(BTN_HEIGHT_SM)
        self._new_btn.clicked.connect(self._on_new)
        btn_row.addWidget(self._new_btn)

        self._delete_btn = QPushButton("Delete")
        self._delete_btn.setFixedHeight(BTN_HEIGHT_SM)
        self._delete_btn.clicked.connect(self._on_delete)
        btn_row.addWidget(self._delete_btn)

        btn_row.addStretch()
        left_lo.addLayout(btn_row)

        splitter.addWidget(left)

        # ---- Right panel: editor form ----
        right = QWidget()
        right_lo = QVBoxLayout(right)
        right_lo.setContentsMargins(0, 0, 0, 0)

        editor_lbl = QLabel("Template Editor")
        editor_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        right_lo.addWidget(editor_lbl)

        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Template name (unique)")
        form.addRow("Name:", self._name_edit)

        self._desc_edit = QTextEdit()
        self._desc_edit.setMaximumHeight(50)
        self._desc_edit.setPlaceholderText("Short description")
        form.addRow("Description:", self._desc_edit)

        # Follow settings
        self._follow_start_spin = QSpinBox()
        self._follow_start_spin.setRange(1, 500)
        self._follow_start_spin.setValue(10)
        form.addRow("Follow Start /day:", self._follow_start_spin)

        self._follow_incr_spin = QSpinBox()
        self._follow_incr_spin.setRange(1, 50)
        self._follow_incr_spin.setValue(5)
        form.addRow("Follow Increment:", self._follow_incr_spin)

        self._follow_cap_spin = QSpinBox()
        self._follow_cap_spin.setRange(10, 1000)
        self._follow_cap_spin.setValue(50)
        form.addRow("Follow Cap:", self._follow_cap_spin)

        # Like settings
        self._like_start_spin = QSpinBox()
        self._like_start_spin.setRange(1, 500)
        self._like_start_spin.setValue(20)
        form.addRow("Like Start /day:", self._like_start_spin)

        self._like_incr_spin = QSpinBox()
        self._like_incr_spin.setRange(1, 50)
        self._like_incr_spin.setValue(5)
        form.addRow("Like Increment:", self._like_incr_spin)

        self._like_cap_spin = QSpinBox()
        self._like_cap_spin.setRange(10, 1000)
        self._like_cap_spin.setValue(80)
        form.addRow("Like Cap:", self._like_cap_spin)

        # Toggle checkboxes
        self._auto_incr_check = QCheckBox("Enable auto-increment")
        self._auto_incr_check.setChecked(True)
        form.addRow("", self._auto_incr_check)

        self._enable_follow_check = QCheckBox("Enable follow action")
        self._enable_follow_check.setChecked(True)
        form.addRow("", self._enable_follow_check)

        self._enable_like_check = QCheckBox("Enable like action")
        self._enable_like_check.setChecked(True)
        form.addRow("", self._enable_like_check)

        right_lo.addLayout(form)

        self._save_btn = QPushButton("Save Template")
        self._save_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._save_btn.clicked.connect(self._on_save)
        right_lo.addWidget(self._save_btn)

        right_lo.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([380, 470])
        root.addWidget(splitter, stretch=1)

        # ---- Footer ----
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(BTN_HEIGHT_SM)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, self.reject)

    # ------------------------------------------------------------------
    # List management
    # ------------------------------------------------------------------

    def _refresh_list(self) -> None:
        """Reload templates from the database and repopulate the table."""
        templates = self._repo.get_all()
        self._table.setRowCount(len(templates))
        for i, t in enumerate(templates):
            self._table.setItem(i, 0, QTableWidgetItem(t.name))
            follow_str = f"{t.follow_start} +{t.follow_increment} -> {t.follow_cap}"
            self._table.setItem(i, 1, QTableWidgetItem(follow_str))
            like_str = f"{t.like_start} +{t.like_increment} -> {t.like_cap}"
            self._table.setItem(i, 2, QTableWidgetItem(like_str))
            self._table.setItem(i, 3, QTableWidgetItem("ON" if t.auto_increment else "OFF"))
            created = (t.created_at or "")[:10]
            self._table.setItem(i, 4, QTableWidgetItem(created))

            # Store template id in the first column item
            self._table.item(i, 0).setData(Qt.ItemDataRole.UserRole, t.id)

    def _on_selection_changed(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            self._clear_editor()
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        template = self._repo.get_by_id(tid)
        if template is None:
            return
        self._current_template = template
        self._populate_editor(template)

    def _populate_editor(self, t: WarmupTemplate) -> None:
        self._name_edit.setText(t.name)
        self._desc_edit.setPlainText(t.description or "")
        self._follow_start_spin.setValue(t.follow_start)
        self._follow_incr_spin.setValue(t.follow_increment)
        self._follow_cap_spin.setValue(t.follow_cap)
        self._like_start_spin.setValue(t.like_start)
        self._like_incr_spin.setValue(t.like_increment)
        self._like_cap_spin.setValue(t.like_cap)
        self._auto_incr_check.setChecked(t.auto_increment)
        self._enable_follow_check.setChecked(t.enable_follow)
        self._enable_like_check.setChecked(t.enable_like)

    def _clear_editor(self) -> None:
        self._current_template = None
        self._name_edit.clear()
        self._desc_edit.clear()
        self._follow_start_spin.setValue(10)
        self._follow_incr_spin.setValue(5)
        self._follow_cap_spin.setValue(50)
        self._like_start_spin.setValue(20)
        self._like_incr_spin.setValue(5)
        self._like_cap_spin.setValue(80)
        self._auto_incr_check.setChecked(True)
        self._enable_follow_check.setChecked(True)
        self._enable_like_check.setChecked(True)

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def _on_new(self) -> None:
        """Clear editor for a fresh template."""
        self._table.clearSelection()
        self._clear_editor()
        self._name_edit.setFocus()

    def _on_delete(self) -> None:
        row = self._table.currentRow()
        if row < 0:
            return
        item = self._table.item(row, 0)
        if item is None:
            return
        tid = item.data(Qt.ItemDataRole.UserRole)
        name = item.text()

        reply = QMessageBox.question(
            self,
            "Delete Template",
            f"Delete warmup template \"{name}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._repo.delete(tid)
            logger.info("Deleted warmup template id=%s name=%s", tid, name)
        except Exception as exc:
            logger.error("Failed to delete warmup template %s: %s", tid, exc)
            QMessageBox.critical(self, "Error", f"Could not delete template:\n{exc}")
            return

        self._clear_editor()
        self._refresh_list()

    def _on_save(self) -> None:
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Validation", "Template name is required.")
            self._name_edit.setFocus()
            return

        if self._current_template is not None:
            # Update existing
            t = self._current_template
            t.name = name
            t.description = self._desc_edit.toPlainText().strip() or None
            t.follow_start = self._follow_start_spin.value()
            t.follow_increment = self._follow_incr_spin.value()
            t.follow_cap = self._follow_cap_spin.value()
            t.like_start = self._like_start_spin.value()
            t.like_increment = self._like_incr_spin.value()
            t.like_cap = self._like_cap_spin.value()
            t.auto_increment = self._auto_incr_check.isChecked()
            t.enable_follow = self._enable_follow_check.isChecked()
            t.enable_like = self._enable_like_check.isChecked()
            try:
                self._repo.update(t)
                logger.info("Updated warmup template id=%s name=%s", t.id, t.name)
            except Exception as exc:
                logger.error("Failed to update warmup template: %s", exc)
                QMessageBox.critical(self, "Error", f"Could not save template:\n{exc}")
                return
        else:
            # Create new
            t = WarmupTemplate(
                name=name,
                description=self._desc_edit.toPlainText().strip() or None,
                follow_start=self._follow_start_spin.value(),
                follow_increment=self._follow_incr_spin.value(),
                follow_cap=self._follow_cap_spin.value(),
                like_start=self._like_start_spin.value(),
                like_increment=self._like_incr_spin.value(),
                like_cap=self._like_cap_spin.value(),
                auto_increment=self._auto_incr_check.isChecked(),
                enable_follow=self._enable_follow_check.isChecked(),
                enable_like=self._enable_like_check.isChecked(),
            )
            try:
                self._repo.create(t)
                self._current_template = t
                logger.info("Created warmup template id=%s name=%s", t.id, t.name)
            except Exception as exc:
                logger.error("Failed to create warmup template: %s", exc)
                QMessageBox.critical(self, "Error", f"Could not create template:\n{exc}")
                return

        self._refresh_list()

        # Re-select the saved template
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == t.id:
                self._table.setCurrentCell(row, 0)
                break
