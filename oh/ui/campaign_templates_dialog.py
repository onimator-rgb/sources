"""
CampaignTemplatesDialog — manage campaign configuration templates.

Provides a split-panel UI: template list on the left, editor form on the right.
Opened from the Settings tab via the "Manage Templates" button.
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QGroupBox,
    QFormLayout, QLineEdit, QSpinBox, QComboBox,
    QMessageBox, QTextEdit, QSplitter, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut

from oh.models.campaign_template import CampaignTemplate
from oh.repositories.campaign_template_repo import CampaignTemplateRepository
from oh.ui.style import sc, BTN_HEIGHT_SM, BTN_HEIGHT_MD

logger = logging.getLogger(__name__)


def _niche_options() -> List[str]:
    """Build niche dropdown options from NICHE_TAXONOMY keys."""
    try:
        from oh.modules.niche_classifier import NICHE_TAXONOMY
        return ["any"] + sorted(NICHE_TAXONOMY.keys())
    except Exception:
        logger.warning("Could not import NICHE_TAXONOMY, using fallback list")
        return ["any"]


class CampaignTemplatesDialog(QDialog):
    """Dialog for creating, editing, and deleting campaign templates."""

    def __init__(
        self,
        repo: CampaignTemplateRepository,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._repo = repo
        self._current_template: Optional[CampaignTemplate] = None
        self._niche_items = _niche_options()

        self.setWindowTitle("Campaign Templates")
        self.resize(800, 500)
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
            ["Name", "Niche", "Language", "Follow Limit", "Created"]
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

        self._niche_combo = QComboBox()
        self._niche_combo.addItems(self._niche_items)
        form.addRow("Niche:", self._niche_combo)

        self._lang_combo = QComboBox()
        self._lang_combo.addItems(["pl", "en"])
        form.addRow("Language:", self._lang_combo)

        self._min_sources_spin = QSpinBox()
        self._min_sources_spin.setRange(1, 50)
        self._min_sources_spin.setValue(10)
        form.addRow("Min Sources:", self._min_sources_spin)

        self._source_niche_combo = QComboBox()
        self._source_niche_combo.addItems(self._niche_items)
        form.addRow("Source Niche:", self._source_niche_combo)

        self._follow_limit_spin = QSpinBox()
        self._follow_limit_spin.setRange(50, 1000)
        self._follow_limit_spin.setValue(200)
        form.addRow("Follow Limit:", self._follow_limit_spin)

        self._like_limit_spin = QSpinBox()
        self._like_limit_spin.setRange(50, 500)
        self._like_limit_spin.setValue(100)
        form.addRow("Like Limit:", self._like_limit_spin)

        self._tb_spin = QSpinBox()
        self._tb_spin.setRange(1, 5)
        self._tb_spin.setValue(1)
        form.addRow("TB Level:", self._tb_spin)

        self._limits_spin = QSpinBox()
        self._limits_spin.setRange(1, 5)
        self._limits_spin.setValue(1)
        form.addRow("Limits Level:", self._limits_spin)

        right_lo.addLayout(form)

        self._save_btn = QPushButton("Save Template")
        self._save_btn.setFixedHeight(BTN_HEIGHT_MD)
        self._save_btn.clicked.connect(self._on_save)
        right_lo.addWidget(self._save_btn)

        right_lo.addStretch()
        splitter.addWidget(right)

        splitter.setSizes([340, 460])
        root.addWidget(splitter, stretch=1)

        # ---- Footer ----
        footer = QHBoxLayout()
        footer.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(BTN_HEIGHT_SM)
        close_btn.clicked.connect(self.accept)
        footer.addWidget(close_btn)
        root.addLayout(footer)

        # Keyboard shortcut: Escape to close
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
            self._table.setItem(i, 1, QTableWidgetItem(t.niche or ""))
            self._table.setItem(i, 2, QTableWidgetItem(t.language or ""))
            self._table.setItem(i, 3, QTableWidgetItem(str(t.follow_limit)))
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

    def _populate_editor(self, t: CampaignTemplate) -> None:
        self._name_edit.setText(t.name)
        self._desc_edit.setPlainText(t.description or "")
        self._set_combo(self._niche_combo, t.niche or "any")
        self._set_combo(self._lang_combo, t.language or "pl")
        self._min_sources_spin.setValue(t.min_sources)
        self._set_combo(self._source_niche_combo, t.source_niche or "any")
        self._follow_limit_spin.setValue(t.follow_limit)
        self._like_limit_spin.setValue(t.like_limit)
        self._tb_spin.setValue(t.tb_level)
        self._limits_spin.setValue(t.limits_level)

    def _clear_editor(self) -> None:
        self._current_template = None
        self._name_edit.clear()
        self._desc_edit.clear()
        self._niche_combo.setCurrentIndex(0)
        self._lang_combo.setCurrentIndex(0)
        self._min_sources_spin.setValue(10)
        self._source_niche_combo.setCurrentIndex(0)
        self._follow_limit_spin.setValue(200)
        self._like_limit_spin.setValue(100)
        self._tb_spin.setValue(1)
        self._limits_spin.setValue(1)

    @staticmethod
    def _set_combo(combo: QComboBox, value: str) -> None:
        idx = combo.findText(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)
        else:
            combo.setCurrentIndex(0)

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
            f"Delete template \"{name}\"?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            self._repo.delete(tid)
            logger.info("Deleted campaign template id=%s name=%s", tid, name)
        except Exception as exc:
            logger.error("Failed to delete template %s: %s", tid, exc)
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

        niche_val = self._niche_combo.currentText()
        if niche_val == "any":
            niche_val = None
        source_niche_val = self._source_niche_combo.currentText()
        if source_niche_val == "any":
            source_niche_val = None

        if self._current_template is not None:
            # Update existing
            t = self._current_template
            t.name = name
            t.description = self._desc_edit.toPlainText().strip() or None
            t.niche = niche_val
            t.language = self._lang_combo.currentText()
            t.min_sources = self._min_sources_spin.value()
            t.source_niche = source_niche_val
            t.follow_limit = self._follow_limit_spin.value()
            t.like_limit = self._like_limit_spin.value()
            t.tb_level = self._tb_spin.value()
            t.limits_level = self._limits_spin.value()
            try:
                self._repo.update(t)
                logger.info("Updated campaign template id=%s name=%s", t.id, t.name)
            except Exception as exc:
                logger.error("Failed to update template: %s", exc)
                QMessageBox.critical(self, "Error", f"Could not save template:\n{exc}")
                return
        else:
            # Create new
            t = CampaignTemplate(
                name=name,
                description=self._desc_edit.toPlainText().strip() or None,
                niche=niche_val,
                language=self._lang_combo.currentText(),
                min_sources=self._min_sources_spin.value(),
                source_niche=source_niche_val,
                follow_limit=self._follow_limit_spin.value(),
                like_limit=self._like_limit_spin.value(),
                tb_level=self._tb_spin.value(),
                limits_level=self._limits_spin.value(),
            )
            try:
                self._repo.create(t)
                self._current_template = t
                logger.info("Created campaign template id=%s name=%s", t.id, t.name)
            except Exception as exc:
                logger.error("Failed to create template: %s", exc)
                QMessageBox.critical(self, "Error", f"Could not create template:\n{exc}")
                return

        self._refresh_list()

        # Re-select the saved template
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == t.id:
                self._table.setCurrentCell(row, 0)
                break
