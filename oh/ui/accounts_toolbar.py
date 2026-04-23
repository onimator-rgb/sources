"""
AccountsToolbar — action buttons row for the Accounts tab.

Emits signals so MainWindow can wire each action to its handler
without the toolbar needing access to services or workers.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QLabel, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from oh.ui.help_button import HelpButton
from oh.ui.style import sc


class AccountsToolbar(QWidget):
    """Horizontal toolbar with all Accounts-tab action buttons."""

    # Button signals
    cockpit_requested = Signal()
    scan_requested = Signal()
    fbr_requested = Signal()
    lbr_requested = Signal()
    refresh_requested = Signal()
    session_requested = Signal()
    recs_requested = Signal()
    history_requested = Signal()
    export_csv_requested = Signal()
    groups_requested = Signal()
    report_problem_requested = Signal()
    cancel_requested = Signal()

    def __init__(self, show_help_tips: bool = True, parent: QWidget = None) -> None:
        super().__init__(parent)
        self._show_help_tips = show_help_tips
        self._build_ui()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_busy(self, busy: bool, message: str = "") -> None:
        """Toggle busy state — disable action buttons, show/hide cancel."""
        self._scan_btn.setEnabled(not busy)
        self._fbr_btn.setEnabled(not busy)
        self._busy_label.setText(message if busy else "")
        self._cancel_btn.setVisible(busy)
        self._cancel_btn.setEnabled(busy)

    def set_busy_message(self, message: str) -> None:
        """Update the busy label text without changing button states."""
        self._busy_label.setText(message)

    def set_cancel_enabled(self, enabled: bool) -> None:
        """Enable or disable the cancel button independently."""
        self._cancel_btn.setEnabled(enabled)

    def update_last_sync(self, text: str) -> None:
        """Update the last-sync label text."""
        self._last_sync_label.setText(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QHBoxLayout(self)
        lo.setContentsMargins(0, 4, 0, 4)
        lo.setSpacing(6)

        _btn_policy = QSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)

        self._cockpit_btn = QPushButton("Cockpit")
        self._cockpit_btn.setObjectName("cockpitBtn")
        self._cockpit_btn.setFixedHeight(34)
        self._cockpit_btn.setSizePolicy(_btn_policy)
        self._cockpit_btn.setToolTip("Daily operations overview")
        self._cockpit_btn.clicked.connect(self.cockpit_requested)

        self._scan_btn = QPushButton("Scan && Sync")
        self._scan_btn.setObjectName("scanBtn")
        self._scan_btn.setFixedHeight(34)
        self._scan_btn.setSizePolicy(_btn_policy)
        self._scan_btn.setToolTip(
            "Discover accounts from the Onimator folder and sync with the OH registry"
        )
        self._scan_btn.clicked.connect(self.scan_requested)

        self._fbr_btn = QPushButton("Analyze FBR")
        self._fbr_btn.setFixedHeight(34)
        self._fbr_btn.setSizePolicy(_btn_policy)
        self._fbr_btn.setToolTip(
            "Run FBR analysis for all active accounts that have data.db\n"
            "and save results to the OH database"
        )
        self._fbr_btn.clicked.connect(self.fbr_requested)

        self._lbr_btn = QPushButton("Analyze LBR")
        self._lbr_btn.setFixedHeight(34)
        self._lbr_btn.setSizePolicy(_btn_policy)
        self._lbr_btn.setToolTip(
            "Run LBR (Like-Back Rate) analysis for all active accounts\n"
            "that have likes.db and save results to the OH database"
        )
        self._lbr_btn.clicked.connect(self.lbr_requested)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(34)
        refresh_btn.setSizePolicy(_btn_policy)
        refresh_btn.setToolTip("Reload the account list from the OH database (no scan)")
        refresh_btn.clicked.connect(self.refresh_requested)

        self._report_btn = QPushButton("Session")
        self._report_btn.setFixedHeight(34)
        self._report_btn.setSizePolicy(_btn_policy)
        self._report_btn.setToolTip("Open session report for today")
        self._report_btn.clicked.connect(self.session_requested)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet(
            f"font-style: italic; color: {sc('text_secondary').name()};"
        )

        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedHeight(28)
        self._cancel_btn.setFixedWidth(60)
        self._cancel_btn.setToolTip("Cancel the running operation")
        self._cancel_btn.clicked.connect(self.cancel_requested)
        self._cancel_btn.setVisible(False)

        self._last_sync_label = QLabel("")
        self._last_sync_label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )
        self._last_sync_label.setStyleSheet(
            f"color: {sc('muted').name()}; font-size: 11px;"
        )

        self._history_btn = QPushButton("History")
        self._history_btn.setFixedHeight(34)
        self._history_btn.setSizePolicy(_btn_policy)
        self._history_btn.setToolTip("Show recent operator actions")
        self._history_btn.clicked.connect(self.history_requested)

        self._recs_btn = QPushButton("Recs")
        self._recs_btn.setFixedHeight(34)
        self._recs_btn.setSizePolicy(_btn_policy)
        self._recs_btn.setToolTip("Generate and view operational recommendations")
        self._recs_btn.clicked.connect(self.recs_requested)

        self._export_btn = QPushButton("Export CSV")
        self._export_btn.setFixedHeight(34)
        self._export_btn.setSizePolicy(_btn_policy)
        self._export_btn.setToolTip("Export visible accounts to CSV file")
        self._export_btn.clicked.connect(self.export_csv_requested)

        self._groups_btn = QPushButton("Groups")
        self._groups_btn.setFixedHeight(34)
        self._groups_btn.setSizePolicy(_btn_policy)
        self._groups_btn.setToolTip("Manage account groups (clients, campaigns)")
        self._groups_btn.clicked.connect(self.groups_requested)

        self._report_problem_btn = QPushButton("Report Problem")
        self._report_problem_btn.setFixedHeight(34)
        self._report_problem_btn.setSizePolicy(_btn_policy)
        self._report_problem_btn.setToolTip(
            "Send an anonymous problem report to the developer"
        )
        self._report_problem_btn.clicked.connect(self.report_problem_requested)

        # Layout
        lo.addWidget(self._cockpit_btn)
        lo.addWidget(HelpButton(
            "Daily operations overview. Open at the start of each shift "
            "to see what needs attention.",
        ))
        lo.addWidget(self._scan_btn)
        lo.addWidget(self._fbr_btn)
        lo.addWidget(self._lbr_btn)
        lo.addWidget(HelpButton(
            "FBR = Follow-Back Rate (from follow sources).\n"
            "LBR = Like-Back Rate (from like sources).\n"
            "Shows which sources bring followers back.",
        ))
        lo.addWidget(refresh_btn)
        lo.addWidget(self._report_btn)
        lo.addWidget(HelpButton(
            "Detailed analysis of today's bot activity across all accounts.",
        ))
        lo.addWidget(self._recs_btn)
        lo.addWidget(HelpButton(
            "Automated recommendations sorted by priority. Reviews weak "
            "sources, inactive accounts, and more.",
        ))
        lo.addWidget(self._history_btn)
        lo.addWidget(self._export_btn)
        lo.addWidget(self._groups_btn)
        lo.addSpacing(12)
        lo.addWidget(self._busy_label, stretch=1)
        lo.addWidget(self._cancel_btn)
        lo.addWidget(self._report_problem_btn)
        lo.addWidget(self._last_sync_label)

        # Apply initial help button visibility
        if not self._show_help_tips:
            HelpButton.set_all_visible(False)
