"""
OnboardingDialog -- first-run wizard that walks new users through initial setup.

4-page QStackedWidget:
  Page 0: Welcome
  Page 1: Set Onimator path
  Page 2: First Scan
  Page 3: Done
"""
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QFileDialog, QStackedWidget, QWidget, QFrame,
    QCheckBox, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap

from oh.repositories.settings_repo import SettingsRepository
from oh.services.scan_service import ScanService
from oh.resources import asset_path, asset_exists
from oh.ui.style import sc
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

_PAGE_WELCOME = 0
_PAGE_PATH = 1
_PAGE_SCAN = 2
_PAGE_DONE = 3
_NUM_PAGES = 4


class OnboardingDialog(QDialog):
    """First-run onboarding wizard."""

    tour_requested = Signal()
    cockpit_requested = Signal()

    def __init__(
        self,
        settings_repo: SettingsRepository,
        scan_service: ScanService,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._settings = settings_repo
        self._scan_service = scan_service
        self._worker: Optional[WorkerThread] = None
        self._scan_done = False
        self._want_tour = False
        self._want_cockpit = False

        self.setWindowTitle("OH Setup")
        self.setFixedSize(600, 450)
        self.setModal(True)

        self._build_ui()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        main_lo = QVBoxLayout(self)
        main_lo.setContentsMargins(0, 0, 0, 0)
        main_lo.setSpacing(0)

        # Stacked pages
        self._stack = QStackedWidget()
        self._stack.addWidget(self._make_page_welcome())
        self._stack.addWidget(self._make_page_path())
        self._stack.addWidget(self._make_page_scan())
        self._stack.addWidget(self._make_page_done())
        main_lo.addWidget(self._stack, stretch=1)

        # Bottom navigation bar
        main_lo.addWidget(self._make_nav_bar())

        self._go_to_page(0)

    # -- Page 0: Welcome --------------------------------------------------

    def _make_page_welcome(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(40, 30, 40, 20)
        lo.setSpacing(12)

        lo.addStretch()

        # Logo
        if asset_exists("logo.png"):
            logo_lbl = QLabel()
            px = QPixmap(str(asset_path("logo.png")))
            if not px.isNull():
                logo_lbl.setPixmap(
                    px.scaledToHeight(64, Qt.TransformationMode.SmoothTransformation)
                )
                logo_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
                lo.addWidget(logo_lbl)

        title = QLabel("Welcome to OH")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 22px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(title)

        subtitle = QLabel("Operational Hub for managing Onimator campaigns at scale.")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"font-size: 13px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(subtitle)

        desc = QLabel(
            "OH gives you a unified control center for all your devices, accounts,\n"
            "source assignments, FBR analytics, session monitoring, and operational\n"
            "recommendations -- all in one place."
        )
        desc.setAlignment(Qt.AlignmentFlag.AlignCenter)
        desc.setWordWrap(True)
        desc.setStyleSheet(
            f"font-size: 12px; color: {sc('text').name()}; margin-top: 8px;"
        )
        lo.addWidget(desc)

        lo.addStretch()

        # "Don't show again" checkbox
        self._dont_show_check = QCheckBox("Don't show this wizard again")
        self._dont_show_check.setChecked(True)
        self._dont_show_check.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
        )
        lo.addWidget(self._dont_show_check, alignment=Qt.AlignmentFlag.AlignCenter)

        return page

    # -- Page 1: Set Path --------------------------------------------------

    def _make_page_path(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(40, 30, 40, 20)
        lo.setSpacing(12)

        title = QLabel("Connect to Onimator")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(title)

        desc = QLabel(
            "Select the folder where your Onimator installation lives.\n"
            "OH will read device and account data from this folder."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {sc('text').name()};")
        lo.addWidget(desc)

        # Path input row
        row = QHBoxLayout()
        row.setSpacing(6)
        self._path_input = QLineEdit()
        self._path_input.setPlaceholderText(
            "e.g.  C:\\Users\\Admin\\Desktop\\full_igbot_13.9.0"
        )
        saved = self._settings.get_bot_root()
        if saved:
            self._path_input.setText(saved)
        self._path_input.textChanged.connect(self._validate_path)

        browse_btn = QPushButton("Browse...")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse_path)

        row.addWidget(self._path_input, stretch=1)
        row.addWidget(browse_btn)
        lo.addLayout(row)

        # Validation label
        self._path_status = QLabel("")
        self._path_status.setStyleSheet(f"font-size: 11px;")
        lo.addWidget(self._path_status)

        hint = QLabel(
            "Tip: The Onimator folder usually contains subfolders like "
            "'device_01', 'device_02', etc."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()}; margin-top: 8px;"
        )
        lo.addWidget(hint)

        lo.addStretch()
        return page

    # -- Page 2: First Scan ------------------------------------------------

    def _make_page_scan(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(40, 30, 40, 20)
        lo.setSpacing(12)

        title = QLabel("Discover Your Accounts")
        title.setStyleSheet(
            f"font-size: 18px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(title)

        desc = QLabel(
            "OH will scan the Onimator folder to find all devices, accounts, "
            "and their current state. This usually takes a few seconds."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet(f"font-size: 12px; color: {sc('text').name()};")
        lo.addWidget(desc)

        lo.addStretch()

        self._scan_btn = QPushButton("Scan && Sync")
        self._scan_btn.setFixedHeight(40)
        self._scan_btn.setFixedWidth(200)
        self._scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._scan_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; font-size: 14px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
        )
        self._scan_btn.clicked.connect(self._on_scan)
        lo.addWidget(self._scan_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        self._scan_status = QLabel("")
        self._scan_status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._scan_status.setWordWrap(True)
        self._scan_status.setStyleSheet(
            f"font-size: 12px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(self._scan_status)

        lo.addStretch()
        return page

    # -- Page 3: Done ------------------------------------------------------

    def _make_page_done(self) -> QWidget:
        page = QWidget()
        lo = QVBoxLayout(page)
        lo.setContentsMargins(40, 30, 40, 20)
        lo.setSpacing(12)

        title = QLabel("You're All Set!")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(title)

        lo.addSpacing(8)

        tips_title = QLabel("Quick tips to get started:")
        tips_title.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {sc('text').name()};"
        )
        lo.addWidget(tips_title)

        tips = [
            "Open Cockpit at the start of each shift for a daily overview",
            "Run Analyze FBR regularly to track source quality",
            "Check the Sources tab to manage source assignments across accounts",
        ]
        for tip in tips:
            lbl = QLabel(f"  \u2022  {tip}")
            lbl.setWordWrap(True)
            lbl.setStyleSheet(
                f"font-size: 12px; color: {sc('text').name()}; margin-left: 12px;"
            )
            lo.addWidget(lbl)

        lo.addStretch()

        # Action buttons
        actions_lo = QHBoxLayout()
        actions_lo.setSpacing(10)

        tour_btn = QPushButton("Take a Tour")
        tour_btn.setFixedHeight(32)
        tour_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        tour_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {sc('border').name()}; "
            f"border-radius: 4px; padding: 4px 16px; "
            f"color: {sc('text').name()}; background: transparent; }}"
            f"QPushButton:hover {{ background: {sc('bg_note').name()}; }}"
        )
        tour_btn.clicked.connect(self._on_tour)
        actions_lo.addWidget(tour_btn)

        cockpit_btn = QPushButton("Open Cockpit")
        cockpit_btn.setFixedHeight(32)
        cockpit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cockpit_btn.setStyleSheet(
            f"QPushButton {{ border: 1px solid {sc('border').name()}; "
            f"border-radius: 4px; padding: 4px 16px; "
            f"color: {sc('text').name()}; background: transparent; }}"
            f"QPushButton:hover {{ background: {sc('bg_note').name()}; }}"
        )
        cockpit_btn.clicked.connect(self._on_cockpit_click)
        actions_lo.addWidget(cockpit_btn)

        lo.addLayout(actions_lo)

        return page

    # -- Navigation bar ----------------------------------------------------

    def _make_nav_bar(self) -> QFrame:
        bar = QFrame()
        bar.setStyleSheet(
            f"background: {sc('bg_note').name()}; "
            f"border-top: 1px solid {sc('border').name()};"
        )
        lo = QHBoxLayout(bar)
        lo.setContentsMargins(16, 10, 16, 10)
        lo.setSpacing(8)

        # Skip button (always visible)
        self._skip_btn = QPushButton("Skip")
        self._skip_btn.setFixedHeight(30)
        self._skip_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._skip_btn.setStyleSheet(
            f"QPushButton {{ color: {sc('text_secondary').name()}; "
            f"background: transparent; border: none; font-size: 12px; }}"
            f"QPushButton:hover {{ color: {sc('text').name()}; }}"
        )
        self._skip_btn.clicked.connect(self._on_skip)
        lo.addWidget(self._skip_btn)

        lo.addStretch()

        # Page dots
        self._dots: list = []
        dots_lo = QHBoxLayout()
        dots_lo.setSpacing(6)
        for i in range(_NUM_PAGES):
            dot = QLabel("\u25CF")
            dot.setFixedSize(12, 12)
            dot.setAlignment(Qt.AlignmentFlag.AlignCenter)
            dot.setStyleSheet(f"font-size: 8px; color: {sc('muted').name()};")
            self._dots.append(dot)
            dots_lo.addWidget(dot)
        lo.addLayout(dots_lo)

        lo.addStretch()

        # Back button
        self._back_btn = QPushButton("Back")
        self._back_btn.setFixedHeight(30)
        self._back_btn.setFixedWidth(70)
        self._back_btn.clicked.connect(self._on_back)
        lo.addWidget(self._back_btn)

        # Next / Let's Get Started / Finish button
        self._next_btn = QPushButton("Let's Get Started")
        self._next_btn.setFixedHeight(30)
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; padding: 4px 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
        )
        self._next_btn.clicked.connect(self._on_next)
        lo.addWidget(self._next_btn)

        return bar

    # ------------------------------------------------------------------
    # Navigation logic
    # ------------------------------------------------------------------

    def _go_to_page(self, index: int) -> None:
        self._stack.setCurrentIndex(index)
        # Update dots
        for i, dot in enumerate(self._dots):
            if i == index:
                dot.setStyleSheet(f"font-size: 8px; color: {sc('success').name()};")
            else:
                dot.setStyleSheet(f"font-size: 8px; color: {sc('muted').name()};")

        # Update button states
        self._back_btn.setVisible(index > 0)

        if index == _PAGE_WELCOME:
            self._next_btn.setText("Let's Get Started")
        elif index == _PAGE_DONE:
            self._next_btn.setText("Finish")
        else:
            self._next_btn.setText("Next")

    def _on_next(self) -> None:
        current = self._stack.currentIndex()

        if current == _PAGE_WELCOME:
            self._go_to_page(_PAGE_PATH)

        elif current == _PAGE_PATH:
            if self._validate_and_save_path():
                self._go_to_page(_PAGE_SCAN)

        elif current == _PAGE_SCAN:
            self._go_to_page(_PAGE_DONE)

        elif current == _PAGE_DONE:
            self._finish()

    def _on_back(self) -> None:
        current = self._stack.currentIndex()
        if current > 0:
            self._go_to_page(current - 1)

    def _on_skip(self) -> None:
        self._mark_done()
        self.accept()

    def _finish(self) -> None:
        self._mark_done()
        if self._want_tour:
            self.tour_requested.emit()
        if self._want_cockpit:
            self.cockpit_requested.emit()
        self.accept()

    def _mark_done(self) -> None:
        if self._dont_show_check.isChecked():
            self._settings.set("onboarding_done", "1")

    # ------------------------------------------------------------------
    # Page 1: path validation
    # ------------------------------------------------------------------

    def _on_browse_path(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Select Onimator Folder",
            self._path_input.text() or "",
        )
        if folder:
            self._path_input.setText(folder)

    def _validate_path(self) -> None:
        """Live validation feedback as user types."""
        text = self._path_input.text().strip()
        if not text:
            self._path_status.setText("")
            return
        p = Path(text)
        if not p.is_dir():
            self._path_status.setText("Folder does not exist")
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('error').name()};"
            )
            return
        # Check for subfolders that look like bot devices
        has_devices = any(
            (child / "data.db").exists() or (child / "sources.txt").exists()
            for child in p.iterdir()
            if child.is_dir()
        )
        if has_devices:
            self._path_status.setText("\u2705 Looks like a valid Onimator folder")
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('success').name()};"
            )
        else:
            self._path_status.setText(
                "No device subfolders found -- make sure this is the right folder"
            )
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('warning').name()};"
            )

    def _validate_and_save_path(self) -> bool:
        """Validate path and save to settings. Returns True if valid."""
        text = self._path_input.text().strip()
        if not text:
            self._path_status.setText("Please enter a path")
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('error').name()};"
            )
            return False
        p = Path(text)
        if not p.is_dir():
            self._path_status.setText("Folder does not exist")
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('error').name()};"
            )
            return False
        try:
            self._settings.set_bot_root(text)
            return True
        except ValueError as exc:
            self._path_status.setText(str(exc))
            self._path_status.setStyleSheet(
                f"font-size: 11px; color: {sc('error').name()};"
            )
            return False

    # ------------------------------------------------------------------
    # Page 2: scan
    # ------------------------------------------------------------------

    def _on_scan(self) -> None:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            self._scan_status.setText("Set a bot path first (go back to previous page)")
            self._scan_status.setStyleSheet(
                f"font-size: 12px; color: {sc('warning').name()};"
            )
            return

        self._scan_btn.setEnabled(False)
        self._scan_btn.setText("Scanning...")
        self._scan_status.setText("Scanning Onimator folder...")
        self._scan_status.setStyleSheet(
            f"font-size: 12px; color: {sc('text_secondary').name()};"
        )

        def do_scan():
            discovered = self._scan_service.scan(bot_root)
            sync_run = self._scan_service.sync(discovered)
            return sync_run

        self._worker = WorkerThread(do_scan)
        self._worker.result.connect(self._on_scan_done)
        self._worker.error.connect(self._on_scan_error)
        self._worker.start()

    def _on_scan_done(self, sync_run: object) -> None:
        self._scan_done = True
        self._scan_btn.setText("Scan Complete")
        try:
            added = getattr(sync_run, "accounts_added", 0) or 0
            total = getattr(sync_run, "accounts_scanned", 0) or 0
            self._scan_status.setText(
                f"Found {total} accounts (+{added} new)"
            )
        except Exception:
            self._scan_status.setText("Scan completed successfully")
        self._scan_status.setStyleSheet(
            f"font-size: 12px; color: {sc('success').name()};"
        )

    def _on_scan_error(self, error_msg: str) -> None:
        self._scan_btn.setEnabled(True)
        self._scan_btn.setText("Retry Scan")
        self._scan_status.setText(f"Scan failed: {error_msg}")
        self._scan_status.setStyleSheet(
            f"font-size: 12px; color: {sc('error').name()};"
        )

    # ------------------------------------------------------------------
    # Page 3: action buttons
    # ------------------------------------------------------------------

    def _on_tour(self) -> None:
        self._want_tour = True
        # Visual feedback
        sender = self.sender()
        if sender:
            sender.setText("Tour queued!")
            sender.setEnabled(False)

    def _on_cockpit_click(self) -> None:
        self._want_cockpit = True
        sender = self.sender()
        if sender:
            sender.setText("Will open Cockpit")
            sender.setEnabled(False)

    # ------------------------------------------------------------------
    # Escape to close
    # ------------------------------------------------------------------

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self._on_skip()
        else:
            super().keyPressEvent(event)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        super().closeEvent(event)
