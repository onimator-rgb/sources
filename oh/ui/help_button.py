"""
HelpButton — small "?" widget that shows a popup with contextual help text.

Usage:
    from oh.ui.help_button import HelpButton
    btn = HelpButton("Tooltip explanation text here.", parent=some_widget)

All instances can be toggled via HelpButton.set_all_visible(bool).
"""
import weakref
from typing import List

from PySide6.QtWidgets import QToolButton, QFrame, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QCursor

from oh.ui.style import sc


class HelpPopup(QFrame):
    """Frameless popup showing help text. Auto-hides after 10 seconds."""

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent, Qt.WindowType.Popup)
        self.setMaximumWidth(300)
        self._build(text)
        QTimer.singleShot(10_000, self._auto_close)

    # ------------------------------------------------------------------

    def _build(self, text: str) -> None:
        bg = sc("bg_note").name()
        border = sc("border").name()
        txt = sc("text").name()

        self.setStyleSheet(
            f"HelpPopup {{"
            f"  background: {bg}; border: 1px solid {border};"
            f"  border-radius: 6px; padding: 10px;"
            f"}}"
        )

        lo = QVBoxLayout(self)
        lo.setContentsMargins(10, 8, 10, 8)
        lo.setSpacing(4)

        body = QLabel(text)
        body.setWordWrap(True)
        body.setStyleSheet(f"color: {txt}; font-size: 12px; border: none;")
        lo.addWidget(body)

    def _auto_close(self) -> None:
        if self.isVisible():
            self.close()

    def keyPressEvent(self, event) -> None:  # type: ignore[override]
        if event.key() == Qt.Key.Key_Escape:
            self.close()
        else:
            super().keyPressEvent(event)


class HelpButton(QToolButton):
    """Small circular "?" button that shows a contextual help popup on click."""

    _instances: List[weakref.ref] = []

    def __init__(self, help_text: str, parent=None) -> None:
        super().__init__(parent)
        self._help_text = help_text
        self._popup = None  # type: ignore[assignment]

        self.setText("?")
        self.setFixedSize(18, 18)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._apply_style()

        self.clicked.connect(self._show_popup)
        HelpButton._instances.append(weakref.ref(self))

    # ------------------------------------------------------------------
    # Styling
    # ------------------------------------------------------------------

    def _apply_style(self) -> None:
        border = sc("border").name()
        txt_sec = sc("text_secondary").name()
        txt = sc("text").name()
        bg_note = sc("bg_note").name()

        self.setStyleSheet(
            f"QToolButton {{"
            f"  font-size: 11px; font-weight: bold;"
            f"  border: 1px solid {border}; border-radius: 9px;"
            f"  color: {txt_sec}; background: transparent;"
            f"  padding: 0px;"
            f"}}"
            f"QToolButton:hover {{"
            f"  border-color: {txt}; color: {txt};"
            f"  background: {bg_note};"
            f"}}"
        )

    # ------------------------------------------------------------------
    # Popup
    # ------------------------------------------------------------------

    def _show_popup(self) -> None:
        if self._popup is not None and self._popup.isVisible():
            self._popup.close()
            return

        self._popup = HelpPopup(self._help_text, parent=None)

        # Position below the button, slightly right
        pos = self.mapToGlobal(QPoint(0, self.height() + 4))

        # Adjust if popup would go off the right edge of the screen
        screen = self.screen()
        if screen is not None:
            screen_rect = screen.availableGeometry()
            self._popup.adjustSize()
            if pos.x() + self._popup.width() > screen_rect.right():
                pos.setX(screen_rect.right() - self._popup.width() - 4)
            if pos.y() + self._popup.height() > screen_rect.bottom():
                pos.setY(self.mapToGlobal(QPoint(0, -self._popup.height() - 4)).y())

        self._popup.move(pos)
        self._popup.show()

    # ------------------------------------------------------------------
    # Class-level visibility control
    # ------------------------------------------------------------------

    @classmethod
    def set_all_visible(cls, visible: bool) -> None:
        """Show or hide all HelpButton instances. Cleans up dead refs."""
        alive = []
        for ref in cls._instances:
            btn = ref()
            if btn is not None:
                btn.setVisible(visible)
                alive.append(ref)
        cls._instances = alive
