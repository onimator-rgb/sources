"""
LicenseDialog — shown when OH license is missing, invalid, or expired.

Displays machine HWID (copyable), lets the user load a license.key file,
and shows validation status. There is no bypass — user must load a valid
license or exit.
"""
import logging
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QFileDialog, QApplication, QMessageBox,
    QGroupBox, QFormLayout,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from oh.models.license import LicenseStatus
from oh.services.license_service import LicenseService

logger = logging.getLogger(__name__)

_STATUS_LABELS = {
    LicenseStatus.VALID: ("Valid", "#27ae60"),
    LicenseStatus.GRACE_PERIOD: ("Grace Period", "#e67e22"),
    LicenseStatus.EXPIRED: ("Expired", "#e74c3c"),
    LicenseStatus.INVALID_HWID: ("Invalid — HWID Mismatch", "#e74c3c"),
    LicenseStatus.INVALID_SIGNATURE: ("Invalid — Bad Signature", "#e74c3c"),
    LicenseStatus.MISSING: ("No License Found", "#e74c3c"),
    LicenseStatus.CORRUPT: ("Corrupt License File", "#e74c3c"),
}


class LicenseDialog(QDialog):
    """
    Modal dialog for license activation.

    If the license is valid (or grace), the dialog closes automatically.
    Otherwise it blocks until the user loads a valid license or exits.
    """

    def __init__(
        self,
        license_service: LicenseService,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._license_service = license_service
        self._accepted = False

        self.setWindowTitle("OH — License Activation")
        self.setMinimumSize(520, 340)
        self.setMaximumSize(620, 440)
        self.setModal(True)
        self.setWindowFlags(
            self.windowFlags()
            & ~Qt.WindowContextHelpButtonHint
        )

        self._build_ui()
        self._refresh_status()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        # Title
        title = QLabel("OH — License Activation")
        title.setFont(QFont("Segoe UI", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        layout.addWidget(title)

        # HWID section
        hwid_group = QGroupBox("Machine Identification")
        hwid_layout = QFormLayout(hwid_group)
        hwid_layout.setSpacing(8)

        self._hwid_label = QLabel(self._license_service.get_hwid())
        self._hwid_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._hwid_label.setFont(QFont("Consolas", 10))
        self._hwid_label.setStyleSheet("padding: 4px; background: rgba(255,255,255,0.05); border-radius: 3px;")
        hwid_layout.addRow("HWID:", self._hwid_label)

        copy_btn = QPushButton("Copy HWID")
        copy_btn.setFixedWidth(120)
        copy_btn.clicked.connect(self._copy_hwid)
        hwid_layout.addRow("", copy_btn)

        layout.addWidget(hwid_group)

        # License info section
        info_group = QGroupBox("License Status")
        info_layout = QFormLayout(info_group)
        info_layout.setSpacing(6)

        self._status_label = QLabel("—")
        self._status_label.setFont(QFont("Segoe UI", 11, QFont.Bold))
        info_layout.addRow("Status:", self._status_label)

        self._client_label = QLabel("—")
        info_layout.addRow("Client:", self._client_label)

        self._expiry_label = QLabel("—")
        info_layout.addRow("Expires:", self._expiry_label)

        self._days_label = QLabel("—")
        info_layout.addRow("Days left:", self._days_label)

        layout.addWidget(info_group)

        # Message area
        self._message_label = QLabel("")
        self._message_label.setWordWrap(True)
        self._message_label.setAlignment(Qt.AlignCenter)
        layout.addWidget(self._message_label)

        layout.addStretch()

        # Buttons
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        load_btn = QPushButton("Load License File…")
        load_btn.setMinimumWidth(160)
        load_btn.clicked.connect(self._load_license)
        btn_layout.addWidget(load_btn)

        btn_layout.addStretch()

        exit_btn = QPushButton("Exit")
        exit_btn.setMinimumWidth(100)
        exit_btn.clicked.connect(self._on_exit)
        btn_layout.addWidget(exit_btn)

        layout.addLayout(btn_layout)

    def _refresh_status(self) -> None:
        """Update all labels from current license service state."""
        status = self._license_service.verify()
        label_text, color = _STATUS_LABELS.get(status, ("Unknown", "#999"))

        self._status_label.setText(label_text)
        self._status_label.setStyleSheet(f"color: {color}; font-weight: bold;")

        client = self._license_service.get_client_name()
        expiry = self._license_service.get_expiry_date()
        days = self._license_service.days_remaining()

        self._client_label.setText(client if client else "—")
        self._expiry_label.setText(expiry if expiry else "—")

        if self._license_service.is_valid():
            if days >= 0:
                self._days_label.setText(str(days))
            else:
                grace_left = 7 - abs(days)
                self._days_label.setText(
                    f"Expired — {grace_left} grace day(s) remaining"
                )
                self._days_label.setStyleSheet("color: #e67e22;")
        else:
            self._days_label.setText("—")

        # Message based on status
        if status == LicenseStatus.VALID:
            self._message_label.setText("License is valid.")
            self._message_label.setStyleSheet("color: #27ae60;")
        elif status == LicenseStatus.GRACE_PERIOD:
            grace_left = 7 - abs(days)
            self._message_label.setText(
                f"License has expired but you are in the 7-day grace period.\n"
                f"{grace_left} day(s) remaining. Please renew your license."
            )
            self._message_label.setStyleSheet("color: #e67e22;")
        elif status == LicenseStatus.MISSING:
            self._message_label.setText(
                "No license file found.\n"
                "Copy your HWID above and send it to your provider to receive a license."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")
        elif status == LicenseStatus.INVALID_HWID:
            self._message_label.setText(
                "This license was issued for a different machine.\n"
                "Contact your provider with the HWID shown above."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")
        elif status == LicenseStatus.INVALID_SIGNATURE:
            self._message_label.setText(
                "License file has an invalid signature.\n"
                "The file may be corrupted or tampered with."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")
        elif status == LicenseStatus.EXPIRED:
            self._message_label.setText(
                "License has expired and the grace period is over.\n"
                "Please contact your provider to renew."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")
        else:
            self._message_label.setText(
                "License file is corrupt. Please obtain a new license."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")

    def _copy_hwid(self) -> None:
        """Copy machine HWID to clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(self._license_service.get_hwid())
            self._message_label.setText("HWID copied to clipboard.")
            self._message_label.setStyleSheet("color: #3498db;")

    def _load_license(self) -> None:
        """Open file picker, install selected license file, and re-verify."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select License File",
            "",
            "License Files (*.key);;All Files (*)",
        )
        if not path:
            return

        source = Path(path)
        if not source.exists():
            return

        status = self._license_service.install_license_file(source)
        self._refresh_status()

        if self._license_service.is_valid():
            self._accepted = True
            QMessageBox.information(
                self,
                "License Activated",
                f"License activated for: {self._license_service.get_client_name()}\n"
                f"Expires: {self._license_service.get_expiry_date()}",
            )
            self.accept()

    def _on_exit(self) -> None:
        """Exit without a valid license — this closes the entire application."""
        self._accepted = False
        self.reject()

    def was_accepted(self) -> bool:
        """Return True if the dialog was closed with a valid license."""
        return self._accepted

    def closeEvent(self, event) -> None:
        """Prevent closing via X button if license isn't valid."""
        if not self._license_service.is_valid():
            event.ignore()
            self._message_label.setText(
                "A valid license is required to use OH.\n"
                "Load a license file or click Exit."
            )
            self._message_label.setStyleSheet("color: #e74c3c;")
        else:
            super().closeEvent(event)
