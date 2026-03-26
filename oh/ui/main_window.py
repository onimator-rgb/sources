"""
MainWindow — primary application window for OH.

Layout:
  ┌─────────────────────────────────────────────────────┐
  │  [Settings bar: bot root path + Browse + Save]      │
  ├─────────────────────────────────────────────────────┤
  │  [Scan & Sync]  [Refresh]    last sync: ...         │
  ├─────────────────────────────────────────────────────┤
  │  Search: [___]  □ Show removed          N accounts  │
  ├─────────────────────────────────────────────────────┤
  │  Accounts table (sortable, filterable)              │
  │    Username | Device | Status | Follow | Unfollow   │
  │    Limit    | DataDB | Sources| Discovered | Action │
  ├─────────────────────────────────────────────────────┤
  │  Status bar                                         │
  └─────────────────────────────────────────────────────┘
"""
import subprocess
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLineEdit, QLabel, QFileDialog, QStatusBar,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QFrame, QMessageBox, QSizePolicy,
    QToolTip,
)
from PySide6.QtCore import Qt, QSortFilterProxyModel
from PySide6.QtGui import QColor, QFont, QIcon

from oh.models.account import AccountRecord, DiscoveredAccount
from oh.models.sync import SyncRun
from oh.modules.discovery import DiscoveryModule, DiscoveryError
from oh.modules.sync_module import SyncModule
from oh.repositories.account_repo import AccountRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.sync_repo import SyncRepository
from oh.ui.workers import WorkerThread

logger = logging.getLogger(__name__)

# Table column indexes
COL_USERNAME    = 0
COL_DEVICE      = 1
COL_STATUS      = 2
COL_FOLLOW      = 3
COL_UNFOLLOW    = 4
COL_LIMIT       = 5
COL_DATA_DB     = 6
COL_SOURCES_TXT = 7
COL_DISCOVERED  = 8
COL_LAST_SEEN   = 9
COL_ACTIONS     = 10

COLUMN_HEADERS = [
    "Username", "Device", "Status",
    "Follow", "Unfollow", "Limit/Day",
    "Data DB", "Sources.txt",
    "Discovered", "Last Seen", "Actions",
]

# Semantic colors (work on both dark/light themes)
C_ACTIVE   = QColor("#4caf7d")
C_REMOVED  = QColor("#888888")
C_YES      = QColor("#4caf7d")
C_NO       = QColor("#e05555")
C_WARN     = QColor("#e6a817")
C_ORPHAN   = QColor("#cc8800")


class MainWindow(QMainWindow):
    def __init__(self, conn: sqlite3.Connection) -> None:
        super().__init__()
        self._conn = conn
        self._settings  = SettingsRepository(conn)
        self._accounts  = AccountRepository(conn)
        self._devices   = DeviceRepository(conn)
        self._sync_repo = SyncRepository(conn)

        # Active background worker (kept alive while running)
        self._worker: Optional[WorkerThread] = None

        # Latest full account list (unfiltered)
        self._all_accounts: list = []

        # Latest discovery result (needed for orphan display)
        self._last_discovery: list = []

        self.setWindowTitle("OH — Operational Hub")
        self.setMinimumSize(1200, 720)

        self._build_ui()
        self._refresh_table()
        self._update_last_sync_label()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setSpacing(6)
        layout.setContentsMargins(10, 10, 10, 6)

        layout.addWidget(self._make_settings_bar())
        layout.addWidget(self._make_toolbar())
        layout.addWidget(self._make_filter_bar())
        layout.addWidget(self._make_table(), stretch=1)

        self._statusbar = QStatusBar()
        self.setStatusBar(self._statusbar)
        self._set_status("Ready.")

    def _make_settings_bar(self) -> QFrame:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        frame.setObjectName("settingsBar")

        lo = QHBoxLayout(frame)
        lo.setContentsMargins(10, 6, 10, 6)
        lo.setSpacing(8)

        lbl = QLabel("Onimator Path:")
        lbl.setFixedWidth(110)

        self._root_input = QLineEdit()
        self._root_input.setPlaceholderText(
            "e.g.  C:\\Users\\Admin\\Desktop\\full_igbot_13.9.0"
        )
        saved = self._settings.get_bot_root()
        if saved:
            self._root_input.setText(saved)

        browse_btn = QPushButton("Browse…")
        browse_btn.setFixedWidth(80)
        browse_btn.clicked.connect(self._on_browse)

        save_btn = QPushButton("Save")
        save_btn.setFixedWidth(60)
        save_btn.clicked.connect(self._on_save_root)

        lo.addWidget(lbl)
        lo.addWidget(self._root_input, stretch=1)
        lo.addWidget(browse_btn)
        lo.addWidget(save_btn)
        return frame

    def _make_toolbar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(8)

        self._scan_btn = QPushButton("⟳  Scan & Sync")
        self._scan_btn.setFixedHeight(32)
        self._scan_btn.setToolTip(
            "Discover accounts from the Onimator folder and sync with the OH registry"
        )
        self._scan_btn.clicked.connect(self._on_scan_and_sync)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setFixedHeight(32)
        refresh_btn.setToolTip("Reload the account list from the OH database (no scan)")
        refresh_btn.clicked.connect(self._refresh_table)

        self._busy_label = QLabel("")
        self._busy_label.setStyleSheet("font-style: italic; color: #aaa;")

        self._last_sync_label = QLabel("")
        self._last_sync_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self._last_sync_label.setStyleSheet("color: #777; font-size: 11px;")

        lo.addWidget(self._scan_btn)
        lo.addWidget(refresh_btn)
        lo.addSpacing(12)
        lo.addWidget(self._busy_label, stretch=1)
        lo.addWidget(self._last_sync_label)
        return w

    def _make_filter_bar(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 2, 0, 2)
        lo.setSpacing(10)

        lo.addWidget(QLabel("Search:"))

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Filter by username or device name…")
        self._search_box.setFixedWidth(300)
        self._search_box.textChanged.connect(self._apply_filter)
        lo.addWidget(self._search_box)

        self._show_removed_cb = QCheckBox("Show removed accounts")
        self._show_removed_cb.stateChanged.connect(self._apply_filter)
        lo.addWidget(self._show_removed_cb)

        self._show_orphans_cb = QCheckBox("Show orphan folders")
        self._show_orphans_cb.setToolTip(
            "Orphan: folder exists on disk but not registered in accounts.db"
        )
        self._show_orphans_cb.stateChanged.connect(self._apply_filter)
        lo.addWidget(self._show_orphans_cb)

        lo.addStretch()

        self._count_label = QLabel("")
        self._count_label.setStyleSheet("color: #777; font-size: 11px;")
        lo.addWidget(self._count_label)
        return w

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, len(COLUMN_HEADERS))
        t.setHorizontalHeaderLabels(COLUMN_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        # Interactive resize for text-heavy columns
        for col in (COL_USERNAME, COL_DEVICE, COL_DISCOVERED, COL_LAST_SEEN):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        # Fixed-width for boolean/flag columns
        for col in (COL_STATUS, COL_FOLLOW, COL_UNFOLLOW, COL_LIMIT,
                    COL_DATA_DB, COL_SOURCES_TXT, COL_ACTIONS):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(COL_USERNAME,    180)
        t.setColumnWidth(COL_DEVICE,      100)
        t.setColumnWidth(COL_STATUS,       80)
        t.setColumnWidth(COL_FOLLOW,       62)
        t.setColumnWidth(COL_UNFOLLOW,     72)
        t.setColumnWidth(COL_LIMIT,        76)
        t.setColumnWidth(COL_DATA_DB,      68)
        t.setColumnWidth(COL_SOURCES_TXT,  88)
        t.setColumnWidth(COL_DISCOVERED,  105)
        t.setColumnWidth(COL_LAST_SEEN,   105)
        t.setColumnWidth(COL_ACTIONS,     120)

        t.doubleClicked.connect(self._on_row_double_clicked)

        self._table = t
        return t

    # ------------------------------------------------------------------
    # Data loading and display
    # ------------------------------------------------------------------

    def _refresh_table(self) -> None:
        self._all_accounts = self._accounts.get_all()
        self._apply_filter()
        self._update_last_sync_label()

    def _apply_filter(self) -> None:
        query = self._search_box.text().strip().lower()
        show_removed = self._show_removed_cb.isChecked()
        show_orphans = self._show_orphans_cb.isChecked()

        # Build combined list: registry accounts + orphans from last discovery
        rows: list = []

        for acc in self._all_accounts:
            if not show_removed and not acc.is_active:
                continue
            if query:
                name_match = query in acc.username.lower()
                device_match = bool(acc.device_name and query in acc.device_name.lower())
                if not name_match and not device_match:
                    continue
            rows.append(("account", acc))

        if show_orphans:
            for disc in self._last_discovery:
                if disc.is_orphan_folder:
                    if query and query not in disc.username.lower():
                        continue
                    rows.append(("orphan", disc))

        self._populate_table(rows)
        self._count_label.setText(f"{len(rows)} row(s)")

    def _populate_table(self, rows: list) -> None:
        # Disable sorting while populating to avoid index conflicts
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        for kind, obj in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            if kind == "account":
                self._fill_account_row(r, obj)
            else:
                self._fill_orphan_row(r, obj)

        self._table.setSortingEnabled(True)

    def _fill_account_row(self, row: int, acc: AccountRecord) -> None:
        removed = not acc.is_active

        def item(text: str,
                 align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                 color: Optional[QColor] = None) -> QTableWidgetItem:
            i = QTableWidgetItem(text)
            i.setTextAlignment(align)
            if color:
                i.setForeground(color)
            if removed:
                i.setForeground(C_REMOVED)
            return i

        center = Qt.AlignmentFlag.AlignCenter

        def bool_item(val: Optional[bool]) -> QTableWidgetItem:
            if val is None:
                i = QTableWidgetItem("—")
                i.setTextAlignment(center)
                return i
            text = "Yes" if val else "No"
            col = (C_YES if val else C_NO) if not removed else C_REMOVED
            i = QTableWidgetItem(text)
            i.setTextAlignment(center)
            i.setForeground(col)
            return i

        status_color = C_ACTIVE if not removed else C_REMOVED
        status_text  = "Active" if not removed else "Removed"

        disc_date = (acc.discovered_at[:10] if acc.discovered_at else "—")
        seen_date = (acc.last_seen_at[:10]  if acc.last_seen_at  else "—")

        self._table.setItem(row, COL_USERNAME,    item(acc.username))
        self._table.setItem(row, COL_DEVICE,      item(acc.device_name or acc.device_id))
        self._table.setItem(row, COL_STATUS,      item(status_text, center, status_color))
        self._table.setItem(row, COL_FOLLOW,      bool_item(acc.follow_enabled))
        self._table.setItem(row, COL_UNFOLLOW,    bool_item(acc.unfollow_enabled))
        self._table.setItem(row, COL_LIMIT,       item(acc.limit_per_day or "—", center))
        self._table.setItem(row, COL_DATA_DB,     bool_item(acc.data_db_exists))
        self._table.setItem(row, COL_SOURCES_TXT, bool_item(acc.sources_txt_exists))
        self._table.setItem(row, COL_DISCOVERED,  item(disc_date, center))
        self._table.setItem(row, COL_LAST_SEEN,   item(seen_date, center))

        # Store account id for double-click / button action
        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("account", acc.id)
        )

        # Action button
        btn = QPushButton("Open Folder")
        btn.setFixedHeight(24)
        btn.setEnabled(not removed)
        btn.setToolTip("Open this account's folder in Windows Explorer")
        btn.clicked.connect(lambda _, a=acc: self._open_folder(a))
        self._table.setCellWidget(row, COL_ACTIONS, self._wrap_btn(btn))

    def _fill_orphan_row(self, row: int, disc: DiscoveredAccount) -> None:
        center = Qt.AlignmentFlag.AlignCenter

        def item(text: str, align=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                 color: Optional[QColor] = None) -> QTableWidgetItem:
            i = QTableWidgetItem(text)
            i.setTextAlignment(align)
            if color:
                i.setForeground(color)
            return i

        def bool_item(val: bool) -> QTableWidgetItem:
            text = "Yes" if val else "No"
            i = QTableWidgetItem(text)
            i.setTextAlignment(center)
            i.setForeground(C_YES if val else C_NO)
            return i

        self._table.setItem(row, COL_USERNAME,    item(disc.username))
        self._table.setItem(row, COL_DEVICE,      item(disc.device_name))
        self._table.setItem(row, COL_STATUS,      item("Orphan", center, C_ORPHAN))
        self._table.setItem(row, COL_FOLLOW,      item("—", center))
        self._table.setItem(row, COL_UNFOLLOW,    item("—", center))
        self._table.setItem(row, COL_LIMIT,       item("—", center))
        self._table.setItem(row, COL_DATA_DB,     bool_item(disc.data_db_exists))
        self._table.setItem(row, COL_SOURCES_TXT, bool_item(disc.sources_txt_exists))
        self._table.setItem(row, COL_DISCOVERED,  item("—", center))
        self._table.setItem(row, COL_LAST_SEEN,   item("—", center))

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("orphan", disc)
        )

        btn = QPushButton("Open Folder")
        btn.setFixedHeight(24)
        btn.setToolTip("Open orphan folder in Windows Explorer")
        btn.clicked.connect(lambda _, d=disc: self._open_orphan_folder(d))
        self._table.setCellWidget(row, COL_ACTIONS, self._wrap_btn(btn))

    @staticmethod
    def _wrap_btn(btn: QPushButton) -> QWidget:
        wrapper = QWidget()
        lo = QHBoxLayout(wrapper)
        lo.setContentsMargins(4, 2, 4, 2)
        lo.setSpacing(0)
        lo.addWidget(btn)
        return wrapper

    def _update_last_sync_label(self) -> None:
        run = self._sync_repo.get_latest_run()
        if run:
            date = run.completed_at[:16].replace("T", "  ") if run.completed_at else "—"
            self._last_sync_label.setText(f"Last sync: {date}")
        else:
            self._last_sync_label.setText("Last sync: never")

    # ------------------------------------------------------------------
    # User actions
    # ------------------------------------------------------------------

    def _on_browse(self) -> None:
        current = self._root_input.text().strip() or ""
        path = QFileDialog.getExistingDirectory(
            self, "Select Onimator Installation Folder", current
        )
        if path:
            self._root_input.setText(path)
            self._on_save_root()

    def _on_save_root(self) -> None:
        path = self._root_input.text().strip()
        if not path:
            return
        self._settings.set_bot_root(path)
        self._set_status(f"Bot root saved: {path}")

    def _on_scan_and_sync(self) -> None:
        bot_root = self._get_validated_root()
        if not bot_root:
            return

        self._set_busy(True, "Scanning Onimator folder…")

        def do_scan():
            module = DiscoveryModule(bot_root)
            return module.discover()

        self._worker = WorkerThread(do_scan)
        self._worker.result.connect(self._on_scan_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_scan_done(self, discovered: list) -> None:
        self._last_discovery = discovered

        device_count  = len({d.device_id for d in discovered})
        regular_count = sum(1 for d in discovered if not d.is_orphan_folder)
        orphan_count  = sum(1 for d in discovered if d.is_orphan_folder)
        missing_count = sum(1 for d in discovered if d.is_missing_folder)

        notes = []
        if orphan_count:
            notes.append(f"{orphan_count} orphan folder(s)")
        if missing_count:
            notes.append(f"{missing_count} account(s) missing folder")
        note_str = "  ·  " + ",  ".join(notes) if notes else ""

        self._set_status(
            f"Scan done: {regular_count} account(s) on {device_count} device(s){note_str}. "
            "Syncing registry…"
        )
        self._busy_label.setText("Syncing registry…")

        def do_sync():
            mod = SyncModule(
                account_repo=self._accounts,
                device_repo=self._devices,
                sync_repo=self._sync_repo,
            )
            return mod.run(discovered)

        self._worker = WorkerThread(do_sync)
        self._worker.result.connect(self._on_sync_done)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(lambda: self._set_busy(False))
        self._worker.start()

    def _on_sync_done(self, sync_run: SyncRun) -> None:
        msg = (
            f"Sync complete — "
            f"+{sync_run.accounts_added} added,  "
            f"-{sync_run.accounts_removed} removed,  "
            f"~{sync_run.accounts_updated} updated,  "
            f"={sync_run.accounts_unchanged} unchanged"
        )
        self._set_status(msg)
        self._refresh_table()

    def _on_worker_error(self, error_msg: str) -> None:
        self._set_busy(False)
        self._set_status(f"Error: {error_msg}")
        QMessageBox.critical(self, "Operation Failed", error_msg)

    def _open_folder(self, acc: AccountRecord) -> None:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(self, "Bot Root Not Set",
                                "Set the Onimator path before opening folders.")
            return
        folder = Path(bot_root) / acc.device_id / acc.username
        self._launch_explorer(folder, acc.username)

    def _open_orphan_folder(self, disc: DiscoveredAccount) -> None:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(self, "Bot Root Not Set",
                                "Set the Onimator path before opening folders.")
            return
        folder = Path(bot_root) / disc.device_id / disc.username
        self._launch_explorer(folder, disc.username)

    def _launch_explorer(self, folder: Path, label: str) -> None:
        if not folder.exists():
            QMessageBox.warning(
                self, "Folder Not Found",
                f"Folder does not exist on disk:\n{folder}"
            )
            return
        subprocess.Popen(f'explorer "{folder}"', shell=True)
        self._set_status(f"Opened: {folder}")

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data
        if kind == "account":
            acc = self._accounts.get_by_id(payload)
            if acc and acc.is_active:
                self._open_folder(acc)
        elif kind == "orphan":
            self._open_orphan_folder(payload)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_validated_root(self) -> Optional[str]:
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            QMessageBox.warning(
                self, "Bot Root Not Set",
                "Please set the Onimator installation path first.\n\n"
                "Enter it in the path field at the top and click Save.",
            )
            return None
        if not Path(bot_root).is_dir():
            QMessageBox.warning(
                self, "Path Not Found",
                f"The configured path does not exist:\n{bot_root}\n\n"
                "Please update it and click Save.",
            )
            return None
        return bot_root

    def _set_busy(self, busy: bool, message: str = "") -> None:
        self._scan_btn.setEnabled(not busy)
        self._busy_label.setText(message if busy else "")
        if not busy:
            self._set_status("Ready.")

    def _set_status(self, message: str) -> None:
        self._statusbar.showMessage(message)
