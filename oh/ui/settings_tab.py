"""
SettingsTab — configurable OH settings exposed to operators.

Groups:
  FBR Analysis     — follow count threshold, quality FBR%
  Source Cleanup   — weak-source delete threshold, min source count warning
"""
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QGroupBox, QPushButton, QLabel, QDoubleSpinBox, QSpinBox,
)
from PySide6.QtCore import Qt

from oh.repositories.settings_repo import SettingsRepository


class SettingsTab(QWidget):
    def __init__(self, settings_repo: SettingsRepository, parent=None) -> None:
        super().__init__(parent)
        self._settings = settings_repo
        self._build_ui()
        self._load()

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 16, 20, 16)
        outer.setSpacing(16)

        # -- FBR Analysis group --
        fbr_group = QGroupBox("FBR Analysis")
        fbr_form  = QFormLayout(fbr_group)
        fbr_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._min_follows_spin = QSpinBox()
        self._min_follows_spin.setRange(1, 999_999)
        self._min_follows_spin.setFixedWidth(100)
        self._min_follows_spin.setToolTip(
            "Sources with fewer follows than this are excluded from quality analysis."
        )
        fbr_form.addRow("Min follow count for quality:", self._min_follows_spin)

        self._min_fbr_spin = QDoubleSpinBox()
        self._min_fbr_spin.setRange(0.0, 100.0)
        self._min_fbr_spin.setDecimals(1)
        self._min_fbr_spin.setSuffix("  %")
        self._min_fbr_spin.setFixedWidth(100)
        self._min_fbr_spin.setToolTip(
            "A source is considered 'quality' if its FBR% meets or exceeds this value."
        )
        fbr_form.addRow("Min FBR% for quality:", self._min_fbr_spin)

        outer.addWidget(fbr_group)

        # -- Source Cleanup group --
        sc_group = QGroupBox("Source Cleanup")
        sc_form  = QFormLayout(sc_group)
        sc_form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self._delete_thresh_spin = QDoubleSpinBox()
        self._delete_thresh_spin.setRange(0.0, 100.0)
        self._delete_thresh_spin.setDecimals(1)
        self._delete_thresh_spin.setSuffix("  %")
        self._delete_thresh_spin.setFixedWidth(100)
        self._delete_thresh_spin.setToolTip(
            "Bulk 'delete weak sources' removes sources whose weighted FBR is\n"
            "at or below this threshold (only sources with sufficient follow data\n"
            "and at least one active account are affected)."
        )
        sc_form.addRow("Weak source delete threshold:", self._delete_thresh_spin)

        self._min_src_spin = QSpinBox()
        self._min_src_spin.setRange(0, 999)
        self._min_src_spin.setFixedWidth(100)
        self._min_src_spin.setToolTip(
            "Accounts with fewer active sources than this are highlighted in the\n"
            "Accounts tab as potentially under-resourced."
        )
        sc_form.addRow("Min active sources (warning threshold):", self._min_src_spin)

        outer.addWidget(sc_group)

        # -- Save button --
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        save_btn = QPushButton("Save Settings")
        save_btn.setFixedHeight(30)
        save_btn.clicked.connect(self._save)
        btn_row.addWidget(save_btn)
        outer.addLayout(btn_row)

        self._status_label = QLabel("")
        self._status_label.setStyleSheet("color: #4caf7d; font-size: 11px;")
        outer.addWidget(self._status_label, alignment=Qt.AlignmentFlag.AlignRight)

        outer.addStretch()

    def _load(self) -> None:
        min_f, min_fbr = self._settings.get_fbr_thresholds()
        self._min_follows_spin.setValue(min_f)
        self._min_fbr_spin.setValue(min_fbr)
        self._delete_thresh_spin.setValue(self._settings.get_weak_source_threshold())
        self._min_src_spin.setValue(self._settings.get_min_source_count_warning())

    def _save(self) -> None:
        self._settings.set("min_follows_threshold",        str(self._min_follows_spin.value()))
        self._settings.set("min_fbr_threshold",            str(self._min_fbr_spin.value()))
        self._settings.set("weak_source_delete_threshold", str(self._delete_thresh_spin.value()))
        self._settings.set("min_source_count_warning",     str(self._min_src_spin.value()))
        self._status_label.setText("Settings saved.")
