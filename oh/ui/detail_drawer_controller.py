"""
DetailDrawerController — manages the account detail drawer lifecycle.

Handles opening/closing the drawer, loading data into it, debounced
arrow-key navigation, and keyboard shortcuts (Space/Escape/Left/Right).
Emits signals so MainWindow can dispatch actions without managing
drawer internals.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QApplication, QLineEdit, QComboBox, QInputDialog,
)
from PySide6.QtCore import Qt, QObject, QTimer, Signal
from PySide6.QtGui import QKeyEvent

from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.session import AccountSessionRecord
from oh.repositories.account_repo import AccountRepository
from oh.services.account_health_service import AccountHealthService
from oh.ui.account_detail_panel import AccountDetailPanel
from oh.ui.accounts_table import COL_USERNAME

logger = logging.getLogger(__name__)


class DetailDrawerController(QObject):
    """Controller for the account detail drawer (right-side panel).

    This is a QObject (not a QWidget).  It owns the AccountDetailPanel
    widget and manages its visibility inside the parent QSplitter.
    """

    # Signals
    action_requested = Signal(str, int)   # (action_type, account_id)
    drawer_opened = Signal()
    drawer_closed = Signal()

    def __init__(
        self,
        table,               # QTableWidget
        panel: AccountDetailPanel,
        conn,                # sqlite3.Connection
        accounts_repo: AccountRepository,
        account_detail_service=None,
        operator_action_repo=None,
        settings_repo=None,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self._table = table
        self._panel = panel
        self._conn = conn
        self._accounts = accounts_repo
        self._account_detail_service = account_detail_service
        self._operator_action_repo = operator_action_repo
        self._settings_repo = settings_repo

        # Debounce timer for arrow-key navigation
        self._detail_debounce_timer: Optional[QTimer] = None

        # Data-context maps — updated by MainWindow after refresh
        self._fbr_map: dict[int, FBRSnapshotRecord] = {}
        self._lbr_map: dict = {}
        self._source_count_map: dict[int, int] = {}
        self._session_map: dict[int, AccountSessionRecord] = {}
        self._device_status_map: dict[str, str] = {}
        self._op_tags_map: dict[int, str] = {}
        self._all_accounts: list = []

        # Wire panel signals
        self._panel.close_requested.connect(self.close_drawer)
        self._panel.action_requested.connect(self.action_requested)

        # Wire table selection for debounced loading
        self._table.clicked.connect(self._on_account_selected)
        self._table.selectionModel().currentRowChanged.connect(
            self._on_table_row_changed
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_data_context(
        self,
        all_accounts: list,
        fbr_map: dict,
        lbr_map: dict,
        source_count_map: dict,
        session_map: dict,
        device_status_map: dict,
        op_tags_map: dict,
    ) -> None:
        """Update the data maps used for detail panel rendering."""
        self._all_accounts = all_accounts
        self._fbr_map = fbr_map
        self._lbr_map = lbr_map
        self._source_count_map = source_count_map
        self._session_map = session_map
        self._device_status_map = device_status_map
        self._op_tags_map = op_tags_map

    def open_for_account(self, account_id: int) -> None:
        """Open the drawer and load data for the given account."""
        self._load_detail_for_account(account_id)
        if not self._panel.isVisible():
            self._panel.setVisible(True)
            self.drawer_opened.emit()

    def close_drawer(self) -> None:
        """Hide the detail panel and give full width back to the table."""
        self._panel.setVisible(False)
        self._panel.clear()
        self.drawer_closed.emit()

    def is_open(self) -> bool:
        """Return True if the drawer is currently visible."""
        return self._panel.isVisible()

    def reload_current(self) -> None:
        """Reload the drawer for the currently displayed account (if any)."""
        if (self._panel.isVisible()
                and self._panel.current_account_id() is not None):
            self._load_detail_for_account(self._panel.current_account_id())

    def handle_key_press(self, event: QKeyEvent) -> bool:
        """Process keyboard shortcuts for the drawer.

        Returns True if the event was consumed, False otherwise.

        Space  -- toggle drawer for selected row (only when table has focus)
        Escape -- close drawer if open
        Left/Right arrows -- switch drawer tabs
        """
        focus = QApplication.focusWidget()
        focus_is_input = isinstance(focus, (QLineEdit, QComboBox, QInputDialog))

        key = event.key()

        # Escape: close drawer regardless of focus
        if key == Qt.Key.Key_Escape:
            if self._panel.isVisible():
                self.close_drawer()
                return True
            return False

        # The following shortcuts only apply when focus is NOT on an input
        if focus_is_input:
            return False

        # Space: toggle drawer open/close for selected row
        if key == Qt.Key.Key_Space:
            if self._panel.isVisible():
                self.close_drawer()
            else:
                current = self._table.currentIndex()
                if current.isValid():
                    self._on_account_selected(current)
            return True

        # Left/Right arrows: switch drawer tabs when drawer is visible
        if self._panel.isVisible():
            if key == Qt.Key.Key_Left:
                self._panel.switch_tab(-1)
                return True
            elif key == Qt.Key.Key_Right:
                self._panel.switch_tab(1)
                return True

        return False

    @property
    def panel(self) -> AccountDetailPanel:
        """Return the underlying AccountDetailPanel widget."""
        return self._panel

    # ------------------------------------------------------------------
    # Selection handlers
    # ------------------------------------------------------------------

    def _on_account_selected(self, index) -> None:
        """Handle single-click on a table row: open detail panel."""
        row = index.row()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind != "account":
            return
        account_id = payload
        if account_id is None:
            return
        self.open_for_account(account_id)

    def _on_table_row_changed(self, current, previous) -> None:
        """Debounce row changes (arrow keys) to avoid loading every row."""
        if not self._panel.isVisible():
            return

        if self._detail_debounce_timer is not None:
            self._detail_debounce_timer.stop()
            self._detail_debounce_timer.deleteLater()

        self._detail_debounce_timer = QTimer(self)
        self._detail_debounce_timer.setSingleShot(True)
        self._detail_debounce_timer.setInterval(150)
        self._detail_debounce_timer.timeout.connect(
            lambda: self._debounced_load_row(current.row())
        )
        self._detail_debounce_timer.start()

    def _debounced_load_row(self, row: int) -> None:
        """Load the detail panel for the given table row after debounce."""
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind != "account":
            return
        account_id = payload
        if account_id is None:
            return
        self._load_detail_for_account(account_id)

    # ------------------------------------------------------------------
    # Data loading
    # ------------------------------------------------------------------

    def _load_detail_for_account(self, account_id: int) -> None:
        """Fetch account data and populate the detail panel."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            self._panel.clear()
            return

        if self._account_detail_service is not None:
            try:
                detail_data = self._account_detail_service.get_summary_data(
                    account=acc,
                    fbr_map=self._fbr_map,
                    source_count_map=self._source_count_map,
                    session_map=self._session_map,
                    device_status_map=self._device_status_map,
                    op_tags_map=self._op_tags_map,
                )
                self._panel.load_account(detail_data)
                self._load_peer_and_related(detail_data, acc)
                self._load_detail_sources_and_history(account_id)
                return
            except Exception:
                logger.debug(
                    "account_detail_service.get_summary_data failed for %s, "
                    "falling back to minimal data",
                    account_id,
                    exc_info=True,
                )

        # Fallback: build a minimal data object from the AccountRecord
        from types import SimpleNamespace
        dev_status = self._device_status_map.get(acc.device_id)
        fallback = SimpleNamespace(
            account_id=acc.id,
            username=acc.username,
            device_name=acc.device_name or acc.device_id,
            device_status=dev_status,
            is_active=acc.is_active,
            review_flag=acc.review_flag,
            review_note=acc.review_note,
        )
        self._panel.load_account(fallback)
        self._load_detail_sources_and_history(account_id)

    def _load_detail_sources_and_history(self, account_id: int) -> None:
        """Load Sources and History tab data for the detail drawer."""
        # --- Sources tab ---
        try:
            snap = self._fbr_map.get(account_id)
            if snap is not None and snap.id is not None:
                from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
                fbr_repo = FBRSnapshotRepository(self._conn)
                source_results = fbr_repo.get_source_results(snap.id)
                sources_data = []
                for sr in source_results:
                    sources_data.append({
                        "source_name": sr.source_name,
                        "is_active": True,
                        "follow_count": sr.follow_count,
                        "followback_count": sr.followback_count,
                        "fbr_percent": sr.fbr_percent,
                        "is_quality": sr.is_quality,
                    })
                self._panel._sources_tab.load_sources(sources_data)
            else:
                self._panel._sources_tab.load_sources([])
        except Exception as exc:
            logger.debug("Failed to load sources for drawer: %s", exc)

        # --- Like Sources (LBR) ---
        try:
            lbr_snap = self._lbr_map.get(account_id)
            if lbr_snap is not None and lbr_snap.id is not None:
                from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
                lbr_repo = LBRSnapshotRepository(self._conn)
                lbr_results = lbr_repo.get_source_results(lbr_snap.id)
                like_data = []
                for lr in lbr_results:
                    like_data.append({
                        "source_name": lr.source_name,
                        "is_active": True,
                        "like_count": lr.like_count,
                        "followback_count": lr.followback_count,
                        "lbr_percent": lr.lbr_percent,
                        "is_quality": lr.is_quality,
                    })
                self._panel._sources_tab.load_like_sources(like_data)
            else:
                self._panel._sources_tab.load_like_sources([])
        except Exception as exc:
            logger.debug("Failed to load like sources for drawer: %s", exc)

        # --- History tab ---
        try:
            actions = []
            if self._operator_action_repo is not None:
                actions = self._operator_action_repo.get_for_account(account_id)

            fbr_snapshots = []
            try:
                from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
                fbr_repo = FBRSnapshotRepository(self._conn)
                fbr_snapshots = fbr_repo.get_for_account(account_id)
            except Exception:
                pass

            self._panel._history_tab.load_history(
                actions=actions,
                fbr_snapshots=fbr_snapshots,
                sessions=[],
            )
        except Exception as exc:
            logger.debug("Failed to load history for drawer: %s", exc)

    def _load_peer_and_related(self, data, acc) -> None:
        """Compute peer comparison and related accounts for the detail panel."""
        device_accounts = []  # type: list
        acc_id = None
        settings_repo = self._settings_repo
        # Peer comparison
        try:
            acc_id = data.account.id if hasattr(data, "account") else getattr(data, "account_id", None)
            device_id = data.account.device_id if hasattr(data, "account") else getattr(data, "device_id", "")
            min_src_th = settings_repo.get_min_source_count_warning() if settings_repo else 3

            # This account's health
            acc_health = AccountHealthService.compute_score(
                data.account, data.fbr_snapshot, data.session,
                data.source_count or 0, data.operator_tags or "",
                min_src_th,
            )

            # Device avg — accounts on same device
            device_accounts = [
                a for a in self._all_accounts
                if a.device_id == device_id and a.removed_at is None
            ]
            device_healths = []
            for da in device_accounts:
                dh = AccountHealthService.compute_score(
                    da, self._fbr_map.get(da.id), self._session_map.get(da.id),
                    self._source_count_map.get(da.id, 0),
                    self._op_tags_map.get(da.id, "") or "",
                    min_src_th,
                )
                device_healths.append(dh)
            device_avg = sum(device_healths) / len(device_healths) if device_healths else 0

            # Fleet avg — all active accounts
            fleet_healths = []
            for fa in self._all_accounts:
                if fa.removed_at is not None:
                    continue
                fh = AccountHealthService.compute_score(
                    fa, self._fbr_map.get(fa.id), self._session_map.get(fa.id),
                    self._source_count_map.get(fa.id, 0),
                    self._op_tags_map.get(fa.id, "") or "",
                    min_src_th,
                )
                fleet_healths.append(fh)
            fleet_avg = sum(fleet_healths) / len(fleet_healths) if fleet_healths else 0

            peer_data = {
                "account_health": acc_health,
                "device_avg_health": round(device_avg, 1),
                "fleet_avg_health": round(fleet_avg, 1),
            }
            self._panel._summary_tab.load_peer_data(peer_data)
        except Exception:
            logger.debug("Failed to compute peer comparison", exc_info=True)

        # Related accounts
        try:
            if not device_accounts:
                device_id = acc.device_id if acc else ""
                device_accounts = [
                    a for a in self._all_accounts
                    if a.device_id == device_id and a.removed_at is None
                ]
            if acc_id is None:
                acc_id = data.account.id if hasattr(data, "account") else getattr(data, "account_id", None)

            related = []
            for ra in device_accounts:
                if ra.id == acc_id:
                    continue
                rh = AccountHealthService.compute_score(
                    ra, self._fbr_map.get(ra.id), self._session_map.get(ra.id),
                    self._source_count_map.get(ra.id, 0),
                    self._op_tags_map.get(ra.id, "") or "",
                    settings_repo.get_min_source_count_warning() if settings_repo else 3,
                )
                related.append({"username": ra.username, "health_score": rh})
            related.sort(key=lambda x: x["health_score"])
            self._panel.load_related_accounts(related)
        except Exception:
            logger.debug("Failed to compute related accounts", exc_info=True)

    def copy_diagnostic(self, acc) -> None:
        """Copy a diagnostic summary for the account to the clipboard."""
        # Try the rich format from the service first
        if self._account_detail_service is not None:
            try:
                detail_data = self._account_detail_service.get_summary_data(
                    account=acc,
                    fbr_map=self._fbr_map,
                    source_count_map=self._source_count_map,
                    session_map=self._session_map,
                    device_status_map=self._device_status_map,
                    op_tags_map=self._op_tags_map,
                )
                text = self._account_detail_service.format_diagnostic(detail_data)
                QApplication.clipboard().setText(text)
                logger.info("Diagnostic copied (rich) for %s", acc.username)
                return
            except Exception:
                logger.debug(
                    "format_diagnostic via service failed, using fallback",
                    exc_info=True,
                )

        # Fallback: simple text summary
        snap = self._fbr_map.get(acc.id) if acc.id is not None else None
        src_count = self._source_count_map.get(acc.id, 0) if acc.id is not None else 0
        sess = self._session_map.get(acc.id) if acc.id is not None else None
        dev_status = self._device_status_map.get(acc.device_id, "unknown")

        lines = [
            "Account: %s" % acc.username,
            "Device: %s (%s)" % (acc.device_name or acc.device_id, dev_status),
            "Status: %s" % ("Active" if acc.is_active else "Removed"),
            "Follow: %s  Unfollow: %s  Limit: %s" % (
                acc.follow_enabled, acc.unfollow_enabled, acc.limit_per_day or "-"),
            "Active sources: %s" % src_count,
        ]
        if snap:
            lines.append("FBR: %s/%s quality  best=%.1f%%  date=%s" % (
                snap.quality_sources, snap.total_sources,
                snap.best_fbr_pct if snap.best_fbr_pct is not None else 0,
                (snap.analyzed_at[:10] if snap.analyzed_at else "-"),
            ))
        if sess:
            lines.append("Today: follow=%s  like=%s" % (sess.follow_count, sess.like_count))
        if acc.review_flag:
            lines.append("Review: %s" % (acc.review_note or "(no note)"))

        clipboard = QApplication.clipboard()
        clipboard.setText("\n".join(lines))
        logger.info("Diagnostic copied for %s", acc.username)
