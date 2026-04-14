"""
GuidedTourOverlay — interactive tour that highlights UI elements one at a time.

Usage:
    from oh.ui.guided_tour import GuidedTourOverlay
    overlay = GuidedTourOverlay(settings_repo, parent=main_window)
    overlay.tour_finished.connect(overlay.deleteLater)
    overlay.show()
    overlay.raise_()
"""
import logging
from dataclasses import dataclass
from typing import Optional, List

from PySide6.QtWidgets import (
    QWidget, QFrame, QLabel, QPushButton, QCheckBox,
    QVBoxLayout, QHBoxLayout,
)
from PySide6.QtCore import Qt, Signal, QRect, QPoint
from PySide6.QtGui import QPainter, QColor, QRegion, QPen, QBrush

from oh.repositories.settings_repo import SettingsRepository
from oh.ui.style import sc

logger = logging.getLogger(__name__)


@dataclass
class TourStep:
    widget_name: str
    title: str
    description: str


TOUR_STEPS: List[TourStep] = [
    TourStep("settingsBar", "Set Onimator Path",
             "Enter your bot folder path here and click Save."),
    TourStep("scanBtn", "Scan & Sync",
             "Discovers all devices and accounts from the bot folder."),
    TourStep("cockpitBtn", "Daily Cockpit",
             "Your operations overview. Start each shift here."),
    TourStep("filterBar", "Filters",
             "Filter accounts by status, device, tags, activity, and more."),
    TourStep("accountsTable", "Accounts Table",
             "All your accounts. Click one, then press Space to open details."),
    TourStep("tabWidget", "Tabs",
             "Switch between Accounts, Sources, Source Profiles, Fleet, and Settings."),
    TourStep("checkUpdatesBtn", "Updates",
             "Check for new versions. OH also updates automatically via START.bat."),
]


class GuidedTourOverlay(QWidget):
    """Full-window overlay with spotlight cutout and tooltip card."""

    tour_finished = Signal()

    def __init__(self, settings_repo: SettingsRepository, parent: QWidget) -> None:
        super().__init__(parent)
        self._settings = settings_repo
        self._current = 0
        self._highlight_rect: Optional[QRect] = None

        # Fill the entire parent
        self.setGeometry(parent.rect())
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, False)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # Tooltip card (child widget)
        self._card = self._build_card()
        self._card.setParent(self)

        # Navigate to first valid step
        self._go_to_step(0)

    # ------------------------------------------------------------------
    # Card UI
    # ------------------------------------------------------------------

    def _build_card(self) -> QFrame:
        card = QFrame(self)
        card.setMaximumWidth(360)

        bg = sc("bg_note").name()
        border = sc("border").name()
        txt = sc("text").name()

        card.setStyleSheet(
            f"QFrame#tourCard {{"
            f"  background: {bg}; border: 1px solid {border};"
            f"  border-radius: 8px; padding: 12px;"
            f"}}"
        )
        card.setObjectName("tourCard")

        lo = QVBoxLayout(card)
        lo.setContentsMargins(14, 12, 14, 12)
        lo.setSpacing(6)

        self._step_label = QLabel()
        self._step_label.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px; border: none;"
        )
        lo.addWidget(self._step_label)

        self._title_label = QLabel()
        self._title_label.setStyleSheet(
            f"color: {txt}; font-size: 14px; font-weight: bold; border: none;"
        )
        lo.addWidget(self._title_label)

        self._desc_label = QLabel()
        self._desc_label.setWordWrap(True)
        self._desc_label.setStyleSheet(
            f"color: {txt}; font-size: 12px; border: none;"
        )
        lo.addWidget(self._desc_label)

        # Don't show again checkbox (only visible on last step)
        self._dont_show_cb = QCheckBox("Don't show again")
        self._dont_show_cb.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
        )
        self._dont_show_cb.setVisible(False)
        lo.addWidget(self._dont_show_cb)

        # Button row
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)

        self._skip_btn = QPushButton("Skip Tour")
        self._skip_btn.setFlat(True)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
            f"text-decoration: underline; border: none; padding: 4px 8px;"
        )
        self._skip_btn.clicked.connect(self._skip)
        btn_row.addWidget(self._skip_btn)

        btn_row.addStretch()

        self._back_btn = QPushButton("Back")
        self._back_btn.setFixedHeight(28)
        self._back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._back_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; padding: 4px 14px;"
            f"  border: 1px solid {border}; border-radius: 4px;"
            f"  color: {sc('text_secondary').name()}; background: transparent; }}"
            f"QPushButton:hover {{ background: {bg}; color: {txt}; }}"
        )
        self._back_btn.clicked.connect(self._back)
        btn_row.addWidget(self._back_btn)

        self._next_btn = QPushButton("Next")
        self._next_btn.setFixedHeight(28)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        link_color = sc("link").name()
        self._next_btn.setStyleSheet(
            f"QPushButton {{ font-size: 12px; font-weight: bold; padding: 4px 14px;"
            f"  border: 1px solid {link_color}; border-radius: 4px;"
            f"  color: {txt}; background: {link_color}; }}"
            f"QPushButton:hover {{ opacity: 0.9; }}"
        )
        self._next_btn.clicked.connect(self._next)
        btn_row.addWidget(self._next_btn)

        lo.addLayout(btn_row)
        return card

    # ------------------------------------------------------------------
    # Navigation
    # ------------------------------------------------------------------

    def _go_to_step(self, index: int) -> None:
        if index < 0 or index >= len(TOUR_STEPS):
            self._finish()
            return

        step = TOUR_STEPS[index]
        target = self.parent().findChild(QWidget, step.widget_name)

        if target is None or not target.isVisible():
            # Skip non-existent / hidden widgets
            direction = 1 if index >= self._current else -1
            next_index = index + direction
            if 0 <= next_index < len(TOUR_STEPS):
                self._current = index  # update so direction detection works
                self._go_to_step(next_index)
            else:
                self._finish()
            return

        self._current = index

        # Map target rect to overlay coordinates
        top_left = target.mapTo(self.parent(), QPoint(0, 0))
        self._highlight_rect = QRect(top_left, target.size())

        # Update card content
        total = len(TOUR_STEPS)
        self._step_label.setText(f"Step {index + 1} of {total}")
        self._title_label.setText(step.title)
        self._desc_label.setText(step.description)

        is_last = (index == total - 1)
        self._next_btn.setText("Finish" if is_last else "Next")
        self._back_btn.setVisible(index > 0)
        self._dont_show_cb.setVisible(is_last)
        self._dont_show_cb.setChecked(True)

        # Position the card
        self._position_card()
        self.update()

    def _position_card(self) -> None:
        """Place the tooltip card near the highlighted widget."""
        if self._highlight_rect is None:
            return

        self._card.adjustSize()
        card_w = self._card.width()
        card_h = self._card.height()
        margin = 12

        hr = self._highlight_rect
        overlay_rect = self.rect()

        # Try below the highlight
        x = hr.left()
        y = hr.bottom() + margin

        # If card goes below the overlay, try above
        if y + card_h > overlay_rect.bottom():
            y = hr.top() - card_h - margin

        # If still out of bounds, place at top with offset
        if y < overlay_rect.top():
            y = overlay_rect.top() + margin

        # Clamp horizontal
        if x + card_w > overlay_rect.right() - margin:
            x = overlay_rect.right() - card_w - margin
        if x < overlay_rect.left() + margin:
            x = overlay_rect.left() + margin

        self._card.move(x, y)

    def _next(self) -> None:
        if self._current >= len(TOUR_STEPS) - 1:
            self._finish()
        else:
            self._go_to_step(self._current + 1)

    def _back(self) -> None:
        if self._current > 0:
            self._go_to_step(self._current - 1)

    def _skip(self) -> None:
        self._settings.set("tour_completed", "1")
        self.tour_finished.emit()
        self.close()

    def _finish(self) -> None:
        if self._dont_show_cb.isChecked():
            self._settings.set("tour_completed", "1")
        self.tour_finished.emit()
        self.close()

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------

    def paintEvent(self, event) -> None:  # type: ignore[override]
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Semi-transparent overlay
        overlay_color = QColor(0, 0, 0, 180)
        overlay_region = QRegion(self.rect())

        if self._highlight_rect is not None:
            # Punch out the spotlight
            padded = self._highlight_rect.adjusted(-4, -4, 4, 4)
            spotlight_region = QRegion(padded)
            overlay_region = overlay_region.subtracted(spotlight_region)

        painter.setClipRegion(overlay_region)
        painter.fillRect(self.rect(), overlay_color)
        painter.setClipping(False)

        # Draw border around spotlight
        if self._highlight_rect is not None:
            padded = self._highlight_rect.adjusted(-4, -4, 4, 4)
            pen = QPen(QColor(sc("link").name()), 2)
            painter.setPen(pen)
            painter.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            painter.drawRoundedRect(padded, 4, 4)

        painter.end()

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self._skip()
        else:
            super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:  # type: ignore[override]
        """Keep overlay filling the parent when the window is resized."""
        super().resizeEvent(event)
        parent = self.parent()
        if parent is not None:
            self.setGeometry(parent.rect())
        if self._highlight_rect is not None:
            # Recalculate position of highlight
            step = TOUR_STEPS[self._current]
            target = self.parent().findChild(QWidget, step.widget_name)
            if target is not None and target.isVisible():
                top_left = target.mapTo(self.parent(), QPoint(0, 0))
                self._highlight_rect = QRect(top_left, target.size())
                self._position_card()

    def showEvent(self, event) -> None:  # type: ignore[override]
        super().showEvent(event)
        # Ensure overlay covers the full parent
        parent = self.parent()
        if parent is not None:
            self.setGeometry(parent.rect())
        self.setFocus()
