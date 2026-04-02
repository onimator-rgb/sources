"""
UpdateDialog — shows available update with changelog and download progress.
"""
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTextEdit, QMessageBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from oh.services.update_service import UpdateInfo
from oh.ui.style import sc

logger = logging.getLogger(__name__)


class DownloadWorker(QThread):
    """Downloads update in background thread."""
    progress = Signal(int, int)  # downloaded, total
    finished = Signal(str)       # file path
    error = Signal(str)          # error message

    def __init__(self, service, download_url: str) -> None:
        super().__init__()
        self._service = service
        self._url = download_url

    def run(self) -> None:
        try:
            path = self._service.download_update(
                self._url,
                progress_callback=lambda d, t: self.progress.emit(d, t),
            )
            if path:
                self.finished.emit(path)
            else:
                self.error.emit("Download failed")
        except Exception as e:
            self.error.emit(str(e))


class UpdateDialog(QDialog):
    """Dialog showing available update with changelog and install button."""

    update_accepted = Signal()  # emitted when user applies update

    def __init__(self, parent, update_service, update_info: UpdateInfo) -> None:
        super().__init__(parent)
        self._service = update_service
        self._info = update_info
        self._worker: Optional[DownloadWorker] = None
        self._download_path: Optional[str] = None

        self.setWindowTitle("Update Available")
        self.setMinimumSize(500, 400)
        self.setModal(True)

        self._build_ui()
        QShortcut(QKeySequence("Escape"), self, self.close)

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(12)
        lo.setContentsMargins(16, 16, 16, 16)

        # Header
        header = QLabel(f"OH v{self._info.version} is available!")
        header.setStyleSheet(
            f"font-size: 16px; font-weight: bold; color: {sc('heading').name()};"
        )
        lo.addWidget(header)

        current = self._service.current_version
        version_label = QLabel(
            f"Your version: {current}  |  "
            f"New version: {self._info.version}  |  "
            f"Released: {self._info.release_date or 'N/A'}"
        )
        version_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        lo.addWidget(version_label)

        # Changelog
        changelog_header = QLabel("What's new:")
        changelog_header.setStyleSheet(
            f"font-size: 13px; font-weight: bold; color: {sc('text').name()}; "
            f"margin-top: 8px;"
        )
        lo.addWidget(changelog_header)

        self._changelog = QTextEdit()
        self._changelog.setReadOnly(True)
        self._changelog.setPlainText(self._info.changelog or "No changelog available.")
        self._changelog.setMaximumHeight(200)
        self._changelog.setStyleSheet(
            f"background: {sc('bg_note').name()}; "
            f"color: {sc('text').name()}; "
            f"border: 1px solid {sc('border').name()}; "
            f"border-radius: 4px; padding: 8px;"
        )
        lo.addWidget(self._changelog)

        # Progress (hidden initially)
        self._progress_frame = QLabel("")
        self._progress_frame.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        self._progress_frame.setVisible(False)
        lo.addWidget(self._progress_frame)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setFixedHeight(20)
        self._progress_bar.setVisible(False)
        lo.addWidget(self._progress_bar)

        lo.addStretch()

        # Footer buttons
        footer = QHBoxLayout()

        self._skip_btn = QPushButton("Skip This Version")
        self._skip_btn.setFixedHeight(32)
        self._skip_btn.clicked.connect(self._on_skip)
        footer.addWidget(self._skip_btn)

        self._later_btn = QPushButton("Remind Me Later")
        self._later_btn.setFixedHeight(32)
        self._later_btn.clicked.connect(self.reject)
        footer.addWidget(self._later_btn)

        footer.addStretch()

        self._install_btn = QPushButton("Download && Install")
        self._install_btn.setFixedHeight(32)
        self._install_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; padding: 5px 16px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
        )
        self._install_btn.clicked.connect(self._on_install)
        footer.addWidget(self._install_btn)

        lo.addLayout(footer)

    def _on_skip(self) -> None:
        """Skip this version -- don't show again for this version."""
        self.done(2)  # custom result code for "skip"

    def _on_install(self) -> None:
        """Start downloading the update."""
        self._install_btn.setEnabled(False)
        self._install_btn.setText("Downloading...")
        self._skip_btn.setEnabled(False)
        self._later_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._progress_frame.setVisible(True)
        self._progress_frame.setText("Downloading update...")

        self._worker = DownloadWorker(self._service, self._info.download_url)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_download_done)
        self._worker.error.connect(self._on_download_error)
        self._worker.start()

    def _on_progress(self, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(downloaded / total * 100)
            self._progress_bar.setValue(pct)
            mb_done = downloaded / 1024 / 1024
            mb_total = total / 1024 / 1024
            self._progress_frame.setText(
                f"Downloading... {mb_done:.1f} / {mb_total:.1f} MB ({pct}%)"
            )

    def _on_download_done(self, path: str) -> None:
        self._download_path = path
        self._progress_frame.setText("Download complete! Ready to install.")
        self._progress_bar.setValue(100)

        self._install_btn.setText("Install && Restart")
        self._install_btn.setEnabled(True)
        self._install_btn.clicked.disconnect()
        self._install_btn.clicked.connect(self._on_apply)

    def _on_apply(self) -> None:
        """Apply the update -- swap exe and restart."""
        reply = QMessageBox.question(
            self,
            "Apply Update",
            "OH will close and restart with the new version.\n\nContinue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        success = self._service.apply_update(self._download_path)
        if success:
            self.update_accepted.emit()
            # Close the entire application
            from PySide6.QtWidgets import QApplication
            QApplication.instance().quit()
        else:
            QMessageBox.critical(
                self, "Update Failed",
                "Failed to start the updater. Please update manually.",
            )
            self._install_btn.setText("Download && Install")
            self._install_btn.setEnabled(True)

    def _on_download_error(self, error: str) -> None:
        self._progress_frame.setText(f"Download failed: {error}")
        self._progress_bar.setVisible(False)
        self._install_btn.setText("Retry Download")
        self._install_btn.setEnabled(True)
        self._skip_btn.setEnabled(True)
        self._later_btn.setEnabled(True)
        self._install_btn.clicked.disconnect()
        self._install_btn.clicked.connect(self._on_install)

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.quit()
            self._worker.wait(3000)
        super().closeEvent(event)
