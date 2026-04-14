"""
AccountDetailPanel -- right-side drawer that shows detail for the
currently selected account in the Accounts table.

Layout:
  +------------------------------------------+
  |  username (bold 16px)              [X]   |
  |  device_name  *status_dot*               |
  |  [Active] badge   [REVIEW: note] badge   |
  +------------------------------------------+
  |  [ Summary ]  [ Alerts ]   (tabs)        |
  |  (placeholder content -- Tasks 3-4)      |
  +------------------------------------------+
  |  [Set Review] [TB +1] [Limits +1]        |
  |  [Open Folder] [Copy Diagnostic]         |
  +------------------------------------------+

Signals:
  action_requested(str, int) -- (action_type, account_id)
  close_requested()

Public API:
  load_account(data)  -- update header + tabs
  clear()             -- reset to empty
  current_account_id() -> Optional[int]
"""
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QTabWidget, QFrame, QSizePolicy,
    QApplication,
)
from PySide6.QtCore import Qt, Signal, QTimer

from oh.ui.style import sc
from oh.ui.account_summary_tab import AccountSummaryTab
from oh.ui.account_alerts_tab import AccountAlertsTab
from oh.ui.account_sources_tab import AccountSourcesTab
from oh.ui.account_history_tab import AccountHistoryTab

logger = logging.getLogger(__name__)


class AccountDetailPanel(QWidget):
    """Drawer panel showing account detail; lives on the right side of a QSplitter."""

    action_requested = Signal(str, int)   # (action_type, account_id)
    close_requested = Signal()

    def __init__(self, service=None, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(520)

        self._service = service
        self._current_account_id: Optional[int] = None
        self._current_data = None  # AccountDetailData or None

        self._build_ui()
        self.clear()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_service(self, service) -> None:
        """Store reference to AccountDetailService for diagnostic and alerts."""
        self._service = service
        self._alerts_tab.set_service(service)

    def load_account(self, data) -> None:
        """Update the panel with an AccountDetailData instance.

        *data* is expected to have at least:
          .account_id, .username, .device_name, .device_status,
          .is_active, .review_flag, .review_note
        """
        self._current_data = data
        # Support both AccountDetailData (has .account.id) and SimpleNamespace
        # fallback (has .account_id directly).
        if hasattr(data, "account") and hasattr(data.account, "id"):
            self._current_account_id = data.account.id
        else:
            self._current_account_id = data.account_id
        self._update_header(data)

        # Only load tabs that require AccountDetailData when the real model
        # is provided (not a SimpleNamespace fallback).
        has_account_attr = hasattr(data, "account")
        if has_account_attr:
            self._summary_tab.load(data)
            self._alerts_tab.load(data, service=self._service)

        self._update_footer(data)
        username = data.account.username if hasattr(data, "account") else data.username
        logger.debug("AccountDetailPanel loaded account_id=%s (%s)", self._current_account_id, username)

    def clear(self) -> None:
        """Reset the panel to an empty / no-selection state."""
        self._current_account_id = None
        self._current_data = None
        self._username_label.setText("")
        self._device_label.setText("")
        self._status_badge.setText("")
        self._status_badge.setVisible(False)
        self._review_badge.setText("")
        self._review_badge.setVisible(False)
        self._set_review_btn.setText("Set Review")
        self._sources_tab.clear()
        self._history_tab.clear()
        self._related_frame.setVisible(False)
        self._related_list.setText("")

    def current_account_id(self) -> Optional[int]:
        return self._current_account_id

    def switch_tab(self, delta: int) -> None:
        idx = self._tab_widget.currentIndex() + delta
        count = self._tab_widget.count()
        if 0 <= idx < count:
            self._tab_widget.setCurrentIndex(idx)

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(10, 8, 10, 8)
        root.setSpacing(6)

        root.addWidget(self._make_header())

        # Subtle separator between header and tabs
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: %s;" % sc("border").name())
        root.addWidget(sep)

        root.addWidget(self._make_tabs(), stretch=1)
        root.addWidget(self._make_related_accounts())
        root.addWidget(self._make_footer())

    # -- Header --------------------------------------------------------

    def _make_header(self) -> QWidget:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(8, 8, 8, 8)
        lo.setSpacing(4)

        # Row 1: username + close button
        row1 = QHBoxLayout()
        row1.setSpacing(6)

        self._username_label = QLabel("")
        self._username_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        row1.addWidget(self._username_label)
        row1.addStretch()

        close_btn = QPushButton("X")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "min-height: 0px; padding: 0px; font-size: 12px; font-weight: bold;"
        )
        close_btn.setToolTip("Close detail panel")
        close_btn.clicked.connect(self.close_requested.emit)
        row1.addWidget(close_btn)

        lo.addLayout(row1)

        # Row 2: device name with status dot
        self._device_label = QLabel("")
        self._device_label.setStyleSheet("font-size: 12px;")
        lo.addWidget(self._device_label)

        # Row 3: badges
        badge_row = QHBoxLayout()
        badge_row.setSpacing(8)

        self._status_badge = QLabel("")
        self._status_badge.setVisible(False)
        badge_row.addWidget(self._status_badge)

        self._review_badge = QLabel("")
        self._review_badge.setWordWrap(True)
        self._review_badge.setVisible(False)
        badge_row.addWidget(self._review_badge)

        badge_row.addStretch()
        lo.addLayout(badge_row)

        return frame

    # -- Tabs ----------------------------------------------------------

    def _make_tabs(self) -> QTabWidget:
        self._tab_widget = QTabWidget()

        self._summary_tab = AccountSummaryTab()

        self._alerts_tab = AccountAlertsTab()
        if self._service is not None:
            self._alerts_tab.set_service(self._service)
        # Bubble up action_requested from alerts tab to panel signal
        self._alerts_tab.action_requested.connect(self.action_requested.emit)

        self._sources_tab = AccountSourcesTab()
        self._history_tab = AccountHistoryTab()

        self._tab_widget.addTab(self._summary_tab, "Summary")
        self._tab_widget.addTab(self._alerts_tab, "Alerts")
        self._tab_widget.addTab(self._sources_tab, "Sources")
        self._tab_widget.addTab(self._history_tab, "History")

        return self._tab_widget

    # -- Related Accounts ----------------------------------------------

    def _make_related_accounts(self) -> QFrame:
        self._related_frame = QFrame()
        related_lo = QVBoxLayout(self._related_frame)
        related_lo.setContentsMargins(8, 4, 8, 4)
        related_lo.setSpacing(2)

        self._related_header = QLabel("Related Accounts")
        self._related_header.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: %s;" % sc("heading").name()
        )
        related_lo.addWidget(self._related_header)

        self._related_list = QLabel("")
        self._related_list.setWordWrap(True)
        self._related_list.setStyleSheet(
            "font-size: 11px; color: %s;" % sc("text_secondary").name()
        )
        related_lo.addWidget(self._related_list)

        self._related_frame.setVisible(False)
        return self._related_frame

    def load_related_accounts(self, accounts: list) -> None:
        """Show other accounts on the same device.

        accounts: list of dicts with 'username', 'health_score' keys.
        """
        if not accounts:
            self._related_frame.setVisible(False)
            return

        lines = []
        for acc in accounts[:8]:  # max 8
            score = acc.get("health_score", 0)
            lines.append("@%s (%.0f)" % (acc["username"], score))

        self._related_header.setText(
            "Related Accounts (%d on same device)" % len(accounts)
        )
        self._related_list.setText("  |  ".join(lines))
        self._related_frame.setVisible(True)

    # -- Footer --------------------------------------------------------

    def _make_footer(self) -> QWidget:
        w = QWidget()
        from PySide6.QtWidgets import QGridLayout
        lo = QGridLayout(w)
        lo.setContentsMargins(0, 4, 0, 0)
        lo.setSpacing(4)

        btn_style = "min-height: 0px; padding: 4px 10px; font-size: 11px;"

        self._set_review_btn = QPushButton("Set Review")
        self._set_review_btn.setStyleSheet(btn_style)
        self._set_review_btn.clicked.connect(self._on_review_clicked)

        tb_btn = QPushButton("TB +1")
        tb_btn.setStyleSheet(btn_style)
        tb_btn.clicked.connect(self._on_tb_clicked)

        limits_btn = QPushButton("Limits +1")
        limits_btn.setStyleSheet(btn_style)
        limits_btn.clicked.connect(self._on_limits_clicked)

        open_btn = QPushButton("Open Folder")
        open_btn.setStyleSheet(btn_style)
        open_btn.clicked.connect(self._on_open_folder_clicked)

        self._copy_btn = QPushButton("Copy Diagnostic")
        self._copy_btn.setStyleSheet(btn_style)
        self._copy_btn.clicked.connect(self._on_copy_diagnostic_clicked)

        export_btn = QPushButton("Export Profile")
        export_btn.setFixedHeight(28)
        export_btn.setStyleSheet(btn_style)
        export_btn.setToolTip("Export account profile to text file")
        export_btn.clicked.connect(self._on_export_profile)

        warmup_btn = QPushButton("Apply Warmup")
        warmup_btn.setFixedHeight(28)
        warmup_btn.setStyleSheet(btn_style)
        warmup_btn.setToolTip("Apply a warmup template to this account")
        warmup_btn.clicked.connect(self._on_warmup_clicked)

        sources_btn = QPushButton("Open Sources")
        sources_btn.setFixedHeight(28)
        sources_btn.setStyleSheet(btn_style)
        sources_btn.setToolTip("Open full Sources & FBR dialog for this account")
        sources_btn.clicked.connect(self._on_open_sources_clicked)

        # Row 1: operational actions
        lo.addWidget(self._set_review_btn, 0, 0)
        lo.addWidget(tb_btn, 0, 1)
        lo.addWidget(limits_btn, 0, 2)

        # Row 2: utility actions
        lo.addWidget(open_btn, 1, 0)
        lo.addWidget(sources_btn, 1, 1)
        lo.addWidget(self._copy_btn, 1, 2)

        # Row 3: export + templates
        lo.addWidget(export_btn, 2, 0)
        lo.addWidget(warmup_btn, 2, 1, 1, 2)

        return w

    # ------------------------------------------------------------------
    # Header update helpers
    # ------------------------------------------------------------------

    def _update_header(self, data) -> None:
        # Support both AccountDetailData (.account.username) and SimpleNamespace
        if hasattr(data, "account") and hasattr(data.account, "username"):
            acct = data.account
            username = acct.username
            device_name = acct.device_name or getattr(acct, "device_id", "") or ""
            dev_status = getattr(data, "device_status", None) or ""
            is_active = acct.is_active
            review_flag = acct.review_flag
            review_note = acct.review_note
        else:
            username = data.username
            device_name = data.device_name or ""
            dev_status = getattr(data, "device_status", None) or ""
            is_active = getattr(data, "is_active", True)
            review_flag = getattr(data, "review_flag", False)
            review_note = getattr(data, "review_note", None)

        self._username_label.setText(username)
        if dev_status == "running":
            dot_color = sc("yes").name()
        elif dev_status == "stop":
            dot_color = sc("dimmed").name()
        else:
            dot_color = sc("no").name()

        self._device_label.setText(
            "<span style='color:%s;'>\u25cf</span> %s" % (dot_color, device_name)
        )
        self._device_label.setTextFormat(Qt.TextFormat.RichText)

        # Status badge
        if is_active:
            self._status_badge.setText("Active")
            self._status_badge.setStyleSheet(
                "background: %s; color: #fff; padding: 2px 8px; "
                "border-radius: 3px; font-size: 11px; font-weight: bold;"
                % sc("success").name()
            )
        else:
            self._status_badge.setText("Removed")
            self._status_badge.setStyleSheet(
                "background: %s; color: #fff; padding: 2px 8px; "
                "border-radius: 3px; font-size: 11px; font-weight: bold;"
                % sc("error").name()
            )
        self._status_badge.setVisible(True)

        # Review badge
        if review_flag:
            note = review_note or ""
            review_text = "REVIEW"
            if note:
                review_text = "REVIEW: %s" % note
            self._review_badge.setText(review_text)
            self._review_badge.setStyleSheet(
                "background: %s; color: #fff; padding: 2px 8px; "
                "border-radius: 3px; font-size: 11px; font-weight: bold;"
                % sc("error").name()
            )
            self._review_badge.setVisible(True)
        else:
            self._review_badge.setVisible(False)

    def _update_footer(self, data) -> None:
        if hasattr(data, "account") and hasattr(data.account, "review_flag"):
            review_flag = data.account.review_flag
        else:
            review_flag = getattr(data, "review_flag", False)
        if review_flag:
            self._set_review_btn.setText("Clear Review")
        else:
            self._set_review_btn.setText("Set Review")

    # ------------------------------------------------------------------
    # Footer button handlers
    # ------------------------------------------------------------------

    def _on_review_clicked(self) -> None:
        if self._current_account_id is None:
            return
        data = self._current_data
        if data is not None and hasattr(data, "account") and hasattr(data.account, "review_flag"):
            review_flag = data.account.review_flag
        else:
            review_flag = getattr(data, "review_flag", False) if data else False
        action = "clear_review" if review_flag else "set_review"
        self.action_requested.emit(action, self._current_account_id)

    def _on_tb_clicked(self) -> None:
        if self._current_account_id is None:
            return
        self.action_requested.emit("tb_plus_1", self._current_account_id)

    def _on_limits_clicked(self) -> None:
        if self._current_account_id is None:
            return
        self.action_requested.emit("limits_plus_1", self._current_account_id)

    def _on_open_folder_clicked(self) -> None:
        if self._current_account_id is None:
            return
        self.action_requested.emit("open_folder", self._current_account_id)

    def _on_open_sources_clicked(self) -> None:
        if self._current_account_id is None:
            return
        self.action_requested.emit("open_sources", self._current_account_id)

    def _on_warmup_clicked(self) -> None:
        if self._current_account_id is None:
            return
        self.action_requested.emit("apply_warmup", self._current_account_id)

    def _on_copy_diagnostic_clicked(self) -> None:
        if self._current_account_id is None:
            return
        # If the service is available and we have full data, use the rich
        # format_diagnostic output directly instead of round-tripping via signal.
        if self._service is not None and self._current_data is not None:
            try:
                text = self._service.format_diagnostic(self._current_data)
                QApplication.clipboard().setText(text)
                self._show_copy_feedback()
                logger.info(
                    "Diagnostic copied (rich) for account_id=%s",
                    self._current_account_id,
                )
                return
            except Exception:
                logger.debug(
                    "format_diagnostic failed, falling back to signal",
                    exc_info=True,
                )
        # Fallback: let the main window handle it
        self.action_requested.emit("copy_diagnostic", self._current_account_id)

    def _on_export_profile(self) -> None:
        """Export current account profile to a text file."""
        if self._current_data is None or self._service is None:
            return

        from PySide6.QtWidgets import QFileDialog

        username = ""
        if hasattr(self._current_data, "account"):
            username = self._current_data.account.username
        elif hasattr(self._current_data, "username"):
            username = self._current_data.username

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Account Profile",
            "oh_profile_%s.txt" % username,
            "Text Files (*.txt);;All Files (*)",
        )
        if not path:
            return

        try:
            diagnostic = self._service.format_diagnostic(self._current_data)
            with open(path, "w", encoding="utf-8") as f:
                f.write(diagnostic)
        except Exception as exc:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Export Failed", "Failed to export:\n\n%s" % exc)

    def _show_copy_feedback(self) -> None:
        """Briefly change the Copy Diagnostic button text to confirm the copy."""
        self._copy_btn.setText("Copied!")
        QTimer.singleShot(2000, lambda: self._copy_btn.setText("Copy Diagnostic"))
