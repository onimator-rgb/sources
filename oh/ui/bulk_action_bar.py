"""
BulkActionBar — toolbar shown when multiple account rows are selected.

Emits signals so MainWindow can handle actions without the bar
needing access to services or the table.
"""
from __future__ import annotations

from PySide6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy
from PySide6.QtCore import Signal

from oh.ui.style import sc


class BulkActionBar(QWidget):
    """Horizontal bar with bulk-action buttons, hidden by default."""

    # Emitted with action name: "set_review", "clear_review", "tb", "limits", "assign_group"
    bulk_action_requested = Signal(str)
    # Emitted when user clicks "Apply Warmup"
    bulk_warmup_requested = Signal()

    def __init__(self, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._build_ui()
        self.setVisible(False)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def update_selection(self, account_ids: list) -> None:
        """Show/hide bar and update the count label."""
        if len(account_ids) > 1:
            self._label.setText(f"{len(account_ids)} selected")
            self.setVisible(True)
        else:
            self.setVisible(False)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(6)

        self._label = QLabel("")
        self._label.setStyleSheet(f"font-weight: bold; color: {sc('link').name()};")
        lo.addWidget(self._label)

        _bp = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        for text, action in [
            ("Set Review", "set_review"),
            ("Clear Review", "clear_review"),
            ("TB +1", "tb"),
            ("Limits +1", "limits"),
            ("Assign Group", "assign_group"),
        ]:
            btn = QPushButton(text)
            btn.setFixedHeight(28)
            btn.setSizePolicy(_bp)
            btn.clicked.connect(lambda checked=False, a=action: self.bulk_action_requested.emit(a))
            lo.addWidget(btn)

        warmup_btn = QPushButton("Apply Warmup")
        warmup_btn.setFixedHeight(28)
        warmup_btn.setSizePolicy(_bp)
        warmup_btn.clicked.connect(self.bulk_warmup_requested.emit)
        lo.addWidget(warmup_btn)

        lo.addStretch()
