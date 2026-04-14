"""
WhatsNewDialog -- shows a changelog after version updates.

Displayed once per version, controlled by the ``last_seen_version`` setting.
"""
import logging
from typing import List, Optional, Tuple

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QWidget,
)
from PySide6.QtCore import Qt

from oh.ui.style import sc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Changelog entries — add a new key for each release that should show
# a What's New dialog.  Older entries are kept for reference.
# ---------------------------------------------------------------------------

WHATS_NEW: dict = {
    "1.4.0": [
        (
            "Target Splitter",
            "Distribute sources evenly across multiple accounts. "
            "Access from Sources tab.",
        ),
        (
            "Settings Copier",
            "Copy bot settings from one account to others. "
            "Access from account Actions menu.",
        ),
        (
            "Auto-Fix Proposals",
            "OH detects issues after each scan and shows proposals "
            "for your review. No changes without approval.",
        ),
        (
            "Improved Security",
            "Application compiled to native code. "
            "Updates verified with SHA256 checksums.",
        ),
        (
            "Full English UI",
            "All interface elements are now in English.",
        ),
    ],
}


class WhatsNewDialog(QDialog):
    """Modal dialog listing new features for a specific version."""

    def __init__(self, version: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._version = version

        self.setWindowTitle(f"What's New in OH v{version}")
        self.setFixedSize(500, 420)
        self.setModal(True)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)
        lo.setContentsMargins(20, 20, 20, 16)

        # Header
        header = QLabel(f"What's New in OH v{self._version}")
        header.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        # Scrollable list of features
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")

        container = QWidget()
        items_lo = QVBoxLayout(container)
        items_lo.setContentsMargins(0, 0, 0, 0)
        items_lo.setSpacing(8)

        entries: List[Tuple[str, str]] = WHATS_NEW.get(self._version, [])
        for title, description in entries:
            card = self._make_card(title, description)
            items_lo.addWidget(card)

        items_lo.addStretch()
        scroll.setWidget(container)
        lo.addWidget(scroll, stretch=1)

        # "Got it" button
        btn_lo = QHBoxLayout()
        btn_lo.addStretch()

        got_it_btn = QPushButton("Got it")
        got_it_btn.setFixedHeight(32)
        got_it_btn.setFixedWidth(100)
        got_it_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        got_it_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; padding: 4px 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
        )
        got_it_btn.clicked.connect(self.accept)

        btn_lo.addWidget(got_it_btn)
        btn_lo.addStretch()
        lo.addLayout(btn_lo)

    def _make_card(self, title: str, description: str) -> QFrame:
        card = QFrame()
        card.setStyleSheet(
            f"QFrame {{ background: {sc('bg_note').name()}; "
            f"border: 1px solid {sc('border').name()}; "
            f"border-radius: 6px; }}"
        )
        card_lo = QVBoxLayout(card)
        card_lo.setContentsMargins(12, 10, 12, 10)
        card_lo.setSpacing(4)

        title_lbl = QLabel(title)
        title_lbl.setStyleSheet(
            f"font-size: 13px; font-weight: bold; "
            f"color: {sc('text').name()}; border: none; background: transparent;"
        )
        card_lo.addWidget(title_lbl)

        desc_lbl = QLabel(description)
        desc_lbl.setWordWrap(True)
        desc_lbl.setStyleSheet(
            f"font-size: 12px; color: {sc('text_secondary').name()}; "
            f"border: none; background: transparent;"
        )
        card_lo.addWidget(desc_lbl)

        return card

    # ------------------------------------------------------------------
    # Escape to close
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.accept()
        else:
            super().keyPressEvent(event)
