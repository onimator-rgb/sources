"""
AccountsTable — encapsulates the QTableWidget for the accounts list.

Owns the table widget, column constants, cell rendering, context menus,
and action menus.  Emits signals so MainWindow can dispatch actions
without the table needing access to services.
"""
from __future__ import annotations

import logging
from typing import Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QPushButton, QMenu, QApplication,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor

from oh.models.account import AccountRecord, DiscoveredAccount
from oh.models.fbr_snapshot import FBRSnapshotRecord, SNAPSHOT_OK, SNAPSHOT_ERROR
from oh.services.account_health_service import AccountHealthService
from oh.ui.style import sc
from oh.ui.table_utils import SortableItem

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table column indexes
# ---------------------------------------------------------------------------

COL_TIMESLOT    = 0   # slot number 1-4 (derived from working hours)
COL_USERNAME    = 1
COL_DEVICE      = 2
COL_HOURS       = 3   # working hours (start_time - end_time)
COL_STATUS      = 4
COL_TAGS        = 5
COL_FOLLOW      = 6
COL_UNFOLLOW    = 7
COL_LIMIT       = 8
COL_FOLLOW_TODAY = 9
COL_LIKE_TODAY   = 10
COL_FOLLOW_LIM   = 11
COL_LIKE_LIM     = 12
COL_REVIEW       = 13
COL_DATA_DB     = 14
COL_SOURCES_TXT = 15
COL_DISCOVERED  = 16
COL_LAST_SEEN   = 17
COL_SRC_COUNT   = 18   # active source count — from source_assignments
COL_FBR_QUALITY = 19   # "3/12" quality/total — from latest snapshot
COL_FBR_BEST    = 20   # best FBR % — from latest snapshot
COL_FBR_DATE    = 21   # date of last FBR analysis
COL_HEALTH      = 22   # composite health score (0-100)
COL_TREND       = 23   # sparkline trend
COL_BLOCK       = 24   # block/ban indicator
COL_GROUP       = 25   # account group name(s)
COL_ACTIONS     = 26

COLUMN_HEADERS = [
    "Slot", "Username", "Device", "Hours", "Status", "Tags",
    "Fol", "Unf", "Lmt/D",
    "Fol Today", "Like Today", "F.Lmt", "L.Lmt", "Rev",
    "Data D", "Sources.tx",
    "Discovered", "Last Seen",
    "Actve Src",
    "Qlty/Tot", "Best FBR%", "Last FBR",
    "Health", "Trend", "Block", "Group",
    "Actions",
]

# ---------------------------------------------------------------------------
# Semantic palette — resolved at render time via sc()
# ---------------------------------------------------------------------------

def C_ACTIVE():   return sc("success")
def C_REMOVED():  return sc("dimmed")
def C_YES():      return sc("yes")
def C_NO():       return sc("no")
def C_WARN():     return sc("warning")
def C_ORPHAN():   return sc("orphan")
def C_QUALITY():  return sc("success")
def C_LOW_FBR():  return sc("muted")
def C_ERROR():    return sc("error")
def C_NEVER():    return sc("warning")

# Default column widths — wide enough so headers are never truncated
_DEFAULT_COL_WIDTHS = {
    COL_TIMESLOT:    36,
    COL_USERNAME:   160,
    COL_DEVICE:     120,
    COL_HOURS:       60,
    COL_STATUS:      60,
    COL_TAGS:       120,
    COL_FOLLOW:      38,
    COL_UNFOLLOW:    38,
    COL_LIMIT:       50,
    COL_FOLLOW_TODAY: 78,
    COL_LIKE_TODAY:   78,
    COL_FOLLOW_LIM:  46,
    COL_LIKE_LIM:    46,
    COL_REVIEW:      38,
    COL_DATA_DB:     52,
    COL_SOURCES_TXT: 80,
    COL_DISCOVERED:  90,
    COL_LAST_SEEN:   90,
    COL_SRC_COUNT:   76,
    COL_FBR_QUALITY: 72,
    COL_FBR_BEST:    80,
    COL_FBR_DATE:    76,
    COL_HEALTH:      56,
    COL_TREND:       52,
    COL_BLOCK:       48,
    COL_GROUP:       80,
    COL_ACTIONS:     74,
}


class AccountsTable(QWidget):
    """Widget wrapping the accounts QTableWidget.

    Signals are emitted so MainWindow can react without the table
    knowing about services or dialogs.
    """

    # Emitted when user clicks the Actions menu for an account row.
    # (action_type, account_id)  — e.g. ("set_review", 42)
    action_requested = Signal(str, object)

    # Emitted when user clicks "View Sources" for an account row
    view_sources_requested = Signal(str, str, object)  # device_id, username, account_id

    # Emitted when user clicks "Open Folder"
    open_folder_requested = Signal(str, str)  # device_id, username

    # Emitted when user clicks "Find Sources"
    find_sources_requested = Signal(object)  # AccountRecord

    # Emitted when user clicks "Copy Settings From This Account"
    copy_settings_requested = Signal(int)  # account_id

    # Emitted when user wants to apply a warmup
    warmup_requested = Signal(list)  # [account_id, ...]

    # Emitted on double-click on the Trend column
    trend_double_clicked = Signal(int)  # account_id

    # Emitted on double-click on any other column (open detail)
    row_double_clicked = Signal(object)  # QModelIndex

    # Emitted when user right-clicks and copies text
    copy_text_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._table = self._build_table()
        lo.addWidget(self._table)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def table(self) -> QTableWidget:
        """Return the underlying QTableWidget for signal connections."""
        return self._table

    def populate(self, rows: list, data_context: dict) -> None:
        """Fill the table from pre-filtered row data.

        Args:
            rows: list of (kind, obj) tuples — "account" or "orphan"
            data_context: dict with maps needed for rendering:
                - device_status_map
                - op_tags_map
                - session_map
                - source_count_map
                - fbr_map
                - block_map
                - group_map
                - trend_map
                - min_source_count_warning (int)
                - has_operator_action_service (bool)
                - has_source_finder_service (bool)
                - has_settings_copier_service (bool)
                - has_warmup_template_service (bool)
        """
        self._data_context = data_context
        self._table.setSortingEnabled(False)
        self._table.setRowCount(0)

        if not rows:
            self._table.insertRow(0)
            msg = QTableWidgetItem("No accounts match the current filters.")
            msg.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            msg.setForeground(sc("muted"))
            self._table.setItem(0, 0, msg)
            self._table.setSpan(0, 0, 1, len(COLUMN_HEADERS))
            self._table.setSortingEnabled(True)
            return

        # Clear any previous span before adding real rows
        self._table.setSpan(0, 0, 1, 1)

        for kind, obj in rows:
            r = self._table.rowCount()
            self._table.insertRow(r)
            if kind == "account":
                self._fill_account_row(r, obj)
            else:
                self._fill_orphan_row(r, obj)

        self._table.setSortingEnabled(True)

    def get_selected_account_id(self) -> Optional[int]:
        """Return the account_id of the currently selected row, or None."""
        selected = self._table.selectionModel().selectedRows()
        if not selected:
            return None
        item = self._table.item(selected[0].row(), COL_USERNAME)
        if item:
            data = item.data(Qt.ItemDataRole.UserRole)
            if data and data[0] == "account":
                return data[1]
        return None

    def get_selected_account_ids_multi(self) -> list:
        """Return account IDs for all selected rows."""
        ids = []
        for idx in self._table.selectionModel().selectedRows():
            item = self._table.item(idx.row(), COL_USERNAME)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data[0] == "account" and data[1] is not None:
                    ids.append(data[1])
        return ids

    def select_account_by_id(self, account_id: int) -> None:
        """Find and select the row for the given account_id."""
        for row in range(self._table.rowCount()):
            item = self._table.item(row, COL_USERNAME)
            if item:
                data = item.data(Qt.ItemDataRole.UserRole)
                if data and data[0] == "account" and data[1] == account_id:
                    self._table.selectRow(row)
                    self._table.scrollToItem(item)
                    return

    # ------------------------------------------------------------------
    # Table construction
    # ------------------------------------------------------------------

    def _build_table(self) -> QTableWidget:
        t = QTableWidget(0, len(COLUMN_HEADERS))
        t.setObjectName("accountsTable")
        t.setHorizontalHeaderLabels(COLUMN_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(True)
        t.setWordWrap(False)

        # Enable horizontal scrollbar so columns don't squeeze into the viewport
        t.setHorizontalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)

        hdr = t.horizontalHeader()
        hdr.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        hdr.setStretchLastSection(False)   # do NOT stretch — allow h-scroll instead
        hdr_font = hdr.font()
        hdr_font.setPointSize(8)
        hdr.setFont(hdr_font)

        # All columns are Interactive (user can resize by dragging) —
        # none are Stretch so the table can scroll horizontally.
        for col in range(len(COLUMN_HEADERS)):
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)

        for col, w in _DEFAULT_COL_WIDTHS.items():
            t.setColumnWidth(col, w)

        # Column visibility is restored after filter bar is created
        # (see _make_accounts_page)

        # Tooltips on header items so operators see full names on hover
        _HEADER_TOOLTIPS = {
            COL_TIMESLOT: "Timeslot 1-4 (1=0-6h, 2=6-12h, 3=12-18h, 4=18-24h)",
            COL_USERNAME: "Account username",
            COL_DEVICE: "Device name (dot = status: green=running, gray=stop, red=offline)",
            COL_HOURS: "Working hours (start - end)",
            COL_STATUS: "Account status (Active / Removed)",
            COL_TAGS: "Bot tags + operator tags",
            COL_FOLLOW: "Follow enabled", COL_UNFOLLOW: "Unfollow enabled",
            COL_LIMIT: "Limit per day", COL_FOLLOW_TODAY: "Follows today",
            COL_LIKE_TODAY: "Likes today", COL_FOLLOW_LIM: "Follow limit/day",
            COL_LIKE_LIM: "Like limit/day", COL_REVIEW: "Review flag",
            COL_DATA_DB: "Data DB exists", COL_SOURCES_TXT: "Sources.txt exists",
            COL_DISCOVERED: "Date account was discovered",
            COL_LAST_SEEN: "Date account was last seen during sync",
            COL_SRC_COUNT: "Active sources count",
            COL_FBR_QUALITY: "Quality / Total sources",
            COL_FBR_BEST: "Best FBR %", COL_FBR_DATE: "Last FBR analysis date",
            COL_HEALTH: "Health score (0-100, green=70+, yellow=40-69, red=<40)",
            COL_TREND: "Performance trend (14-day)",
            COL_BLOCK: "Block/ban indicator",
            COL_GROUP: "Account group name(s)",
            COL_ACTIONS: "Quick actions menu",
        }
        for col_idx, tip in _HEADER_TOOLTIPS.items():
            header_item = t.horizontalHeaderItem(col_idx)
            if header_item:
                header_item.setToolTip(tip)

        t.doubleClicked.connect(self._on_row_double_clicked)

        # Context menu (right-click)
        t.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        t.customContextMenuRequested.connect(self._on_table_context_menu)

        return t

    # ------------------------------------------------------------------
    # Row rendering
    # ------------------------------------------------------------------

    def _fill_account_row(self, row: int, acc: AccountRecord) -> None:
        removed = not acc.is_active
        center  = Qt.AlignmentFlag.AlignCenter

        status_color = C_ACTIVE() if not removed else C_REMOVED()
        status_text  = "Active" if not removed else "Removed"

        disc_date = acc.discovered_at[:10] if acc.discovered_at else "\u2014"
        seen_date = acc.last_seen_at[:10]  if acc.last_seen_at  else "\u2014"

        ctx = self._data_context
        device_status_map = ctx.get("device_status_map", {})
        op_tags_map = ctx.get("op_tags_map", {})
        session_map = ctx.get("session_map", {})
        source_count_map = ctx.get("source_count_map", {})
        fbr_map = ctx.get("fbr_map", {})
        block_map = ctx.get("block_map", {})
        group_map = ctx.get("group_map", {})
        trend_map = ctx.get("trend_map", {})
        min_warn = ctx.get("min_source_count_warning", 3)

        # Timeslot column (1-4)
        slot_num = self._get_slot_number(acc)
        slot_text = str(slot_num) if slot_num > 0 else "\u2014"
        slot_item = SortableItem(slot_text, slot_num)
        slot_item.setTextAlignment(center)
        if removed:
            slot_item.setForeground(C_REMOVED())
        self._table.setItem(row, COL_TIMESLOT, slot_item)

        self._table.setItem(row, COL_USERNAME,    self._make_item(acc.username, dimmed=removed))

        # Device column with status color dot prefix
        device_name = acc.device_name or acc.device_id
        dev_status = device_status_map.get(acc.device_id)
        if dev_status == "running":
            dot = "\u25cf "  # filled circle
            dot_color = C_YES()    # green
        elif dev_status == "stop":
            dot = "\u25cf "
            dot_color = C_REMOVED()  # gray
        else:
            dot = "\u25cf "
            dot_color = C_NO()     # red — unknown/offline
        device_item = self._make_item(dot + device_name, dimmed=removed)
        if not removed:
            device_item.setForeground(dot_color)
        self._table.setItem(row, COL_DEVICE, device_item)

        self._table.setItem(row, COL_STATUS,      self._make_item(status_text, center, status_color))

        # Tags — combine bot tags + operator tags
        parts = []
        if acc.bot_tags_raw:
            parts.append(acc.bot_tags_raw)
        op_tags = op_tags_map.get(acc.id) if acc.id else None
        if op_tags:
            parts.append("OP:" + op_tags.replace(" | ", " OP:"))
        tags_text = " | ".join(parts) if parts else "\u2014"
        tags_color = C_WARN() if op_tags else None  # amber highlight if operator tags exist
        self._table.setItem(row, COL_TAGS, self._make_item(
            tags_text, color=tags_color, dimmed=removed))

        self._table.setItem(row, COL_FOLLOW,      self._make_bool_item(acc.follow_enabled, dimmed=removed))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_bool_item(acc.unfollow_enabled, dimmed=removed))
        self._table.setItem(row, COL_LIMIT,       self._make_item(acc.limit_per_day or "\u2014", center, dimmed=removed))

        # Session data columns
        sess = session_map.get(acc.id) if acc.id is not None else None
        follow_today = sess.follow_count if sess else 0
        like_today = sess.like_count if sess else 0

        # Follow Today — red if 0 in active slot with follow enabled
        ft_color = None
        if not removed and acc.follow_enabled and follow_today == 0 and sess is not None:
            ft_color = C_NO()
        elif follow_today > 0:
            ft_color = C_YES()
        ft_item = SortableItem(str(follow_today) if sess else "\u2014", follow_today if sess else -1)
        ft_item.setTextAlignment(center)
        if removed:
            ft_item.setForeground(C_REMOVED())
        elif ft_color:
            ft_item.setForeground(ft_color)
        self._table.setItem(row, COL_FOLLOW_TODAY, ft_item)

        # Like Today — neutral rendering (no red for 0 — we can't distinguish
        # accounts without like flow enabled from those that failed)
        lt_color = C_YES() if like_today > 0 else None
        lt_item = SortableItem(str(like_today) if sess else "\u2014", like_today if sess else -1)
        lt_item.setTextAlignment(center)
        if removed:
            lt_item.setForeground(C_REMOVED())
        elif lt_color:
            lt_item.setForeground(lt_color)
        self._table.setItem(row, COL_LIKE_TODAY, lt_item)

        # Follow Limit / Like Limit
        self._table.setItem(row, COL_FOLLOW_LIM, self._make_item(
            acc.follow_limit_perday or "\u2014", center, dimmed=removed))
        self._table.setItem(row, COL_LIKE_LIM, self._make_item(
            acc.like_limit_perday or "\u2014", center, dimmed=removed))

        # Review flag
        review_text = "!" if acc.review_flag else ""
        review_color = C_WARN() if acc.review_flag else None
        self._table.setItem(row, COL_REVIEW, self._make_item(
            review_text, center, review_color, dimmed=removed))

        self._table.setItem(row, COL_DATA_DB,     self._make_bool_item(acc.data_db_exists, dimmed=removed))
        self._table.setItem(row, COL_SOURCES_TXT, self._make_bool_item(acc.sources_txt_exists, dimmed=removed))
        self._table.setItem(row, COL_DISCOVERED,  self._make_item(disc_date, center, dimmed=removed))
        self._table.setItem(row, COL_LAST_SEEN,   self._make_item(seen_date, center, dimmed=removed))

        # Active source count with low-source warning
        if acc.id is not None:
            src_count = source_count_map.get(acc.id, 0)
            if removed:
                src_color = C_REMOVED()
            elif src_count < min_warn:
                src_color = C_WARN()
            else:
                src_color = None
            src_item = SortableItem(str(src_count), src_count)
            src_item.setTextAlignment(center)
            if src_color:
                src_item.setForeground(src_color)
            self._table.setItem(row, COL_SRC_COUNT, src_item)
        else:
            self._table.setItem(row, COL_SRC_COUNT, self._make_item("\u2014", center))

        # FBR summary cells
        snap = fbr_map.get(acc.id) if acc.id is not None else None
        self._fill_fbr_cells(row, snap, dimmed=removed)

        # Working hours
        start_t = getattr(acc, "start_time", None) or ""
        end_t = getattr(acc, "end_time", None) or ""
        if start_t and end_t:
            hours_text = f"{start_t}-{end_t}"
        elif start_t:
            hours_text = f"{start_t}-?"
        else:
            hours_text = "\u2014"
        hours_item = QTableWidgetItem(hours_text)
        hours_item.setTextAlignment(center)
        if not start_t:
            hours_item.setForeground(C_NEVER())
        self._table.setItem(row, COL_HOURS, hours_item)

        # Health score (snap already fetched above for FBR cells)
        src_count_h = source_count_map.get(acc.id, 0) if acc.id is not None else 0
        op_tags_h = op_tags_map.get(acc.id) if acc.id else None
        health = AccountHealthService.compute_score(
            acc, snap, sess, src_count_h, op_tags_h or "", min_warn,
        )
        health_item = SortableItem(f"{health:.0f}", health)
        health_item.setTextAlignment(center)
        if removed:
            health_item.setForeground(C_REMOVED())
        else:
            health_item.setForeground(sc(AccountHealthService.score_color_key(health)))
        self._table.setItem(row, COL_HEALTH, health_item)

        # Trend column — placeholder text, sparklines loaded lazily
        trend_text = ""
        if acc.id is not None and acc.id in trend_map:
            trend_data = trend_map[acc.id]
            arrow = {
                "up": "\u25b2", "down": "\u25bc", "stable": "\u25ac"
            }.get(trend_data.trend_direction, "")
            trend_text = arrow
        trend_item = self._make_item(trend_text, center, dimmed=removed)
        if trend_text == "\u25b2":
            trend_item.setForeground(sc("success"))
        elif trend_text == "\u25bc":
            trend_item.setForeground(sc("error"))
        self._table.setItem(row, COL_TREND, trend_item)

        # Block indicator
        blocks = block_map.get(acc.id, []) if acc.id else []
        if blocks and not removed:
            block_types = ", ".join(b.label for b in blocks)
            block_item = self._make_item("\u26a0", center, C_NO())
            block_item.setToolTip(f"Active: {block_types}")
        else:
            block_item = self._make_item("", center, dimmed=removed)
        self._table.setItem(row, COL_BLOCK, block_item)

        # Group column
        groups = group_map.get(acc.id, []) if acc.id else []
        if groups:
            group_names = ", ".join(g.name for g in groups)
            group_item = self._make_item(group_names, dimmed=removed)
        else:
            group_item = self._make_item("\u2014", center, dimmed=removed)
        self._table.setItem(row, COL_GROUP, group_item)

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("account", acc.id)
        )

        act_btn = QPushButton("Actions \u25be")
        act_btn.setStyleSheet("min-height: 0px; padding: 2px 8px; font-size: 11px;")
        act_btn.setEnabled(not removed)
        act_btn.setToolTip("Open folder, view sources, operator actions")
        act_btn.clicked.connect(lambda _, a=acc, b=act_btn: self._show_action_menu(a, b))

        self._table.setCellWidget(row, COL_ACTIONS, act_btn)

    def _fill_orphan_row(self, row: int, disc: DiscoveredAccount) -> None:
        center = Qt.AlignmentFlag.AlignCenter

        self._table.setItem(row, COL_TIMESLOT,    self._make_item("\u2014", center))
        self._table.setItem(row, COL_USERNAME,    self._make_item(disc.username))
        self._table.setItem(row, COL_DEVICE,      self._make_item(disc.device_name))
        self._table.setItem(row, COL_STATUS,      self._make_item("Orphan", center, C_ORPHAN()))
        self._table.setItem(row, COL_TAGS,        self._make_item(disc.bot_tags_raw or "\u2014", center))
        self._table.setItem(row, COL_FOLLOW,      self._make_item("\u2014", center))
        self._table.setItem(row, COL_UNFOLLOW,    self._make_item("\u2014", center))
        self._table.setItem(row, COL_LIMIT,       self._make_item("\u2014", center))
        self._table.setItem(row, COL_FOLLOW_TODAY, self._make_item("\u2014", center))
        self._table.setItem(row, COL_LIKE_TODAY,   self._make_item("\u2014", center))
        self._table.setItem(row, COL_FOLLOW_LIM,   self._make_item("\u2014", center))
        self._table.setItem(row, COL_LIKE_LIM,     self._make_item("\u2014", center))
        self._table.setItem(row, COL_REVIEW,       self._make_item("", center))
        self._table.setItem(row, COL_DATA_DB,     self._make_bool_item(disc.data_db_exists))
        self._table.setItem(row, COL_SOURCES_TXT, self._make_bool_item(disc.sources_txt_exists))
        self._table.setItem(row, COL_DISCOVERED,  self._make_item("\u2014", center))
        self._table.setItem(row, COL_LAST_SEEN,   self._make_item("\u2014", center))
        self._table.setItem(row, COL_SRC_COUNT,   self._make_item("\u2014", center))

        # Orphans have no OH account_id — no FBR snapshot
        self._fill_fbr_cells(row, snap=None, dimmed=False)

        # Hours — not available for orphans
        self._table.setItem(row, COL_HOURS, self._make_item("\u2014", center))

        # Health — not available for orphans
        self._table.setItem(row, COL_HEALTH, self._make_item("\u2014", center))

        # Trend / Block / Group — not available for orphans
        self._table.setItem(row, COL_TREND, self._make_item("", center))
        self._table.setItem(row, COL_BLOCK, self._make_item("", center))
        self._table.setItem(row, COL_GROUP, self._make_item("\u2014", center))

        self._table.item(row, COL_USERNAME).setData(
            Qt.ItemDataRole.UserRole, ("orphan", disc)
        )

        act_btn = QPushButton("Actions \u25be")
        act_btn.setStyleSheet("min-height: 0px; padding: 2px 8px; font-size: 11px;")
        act_btn.setToolTip("Open folder, view sources")
        act_btn.clicked.connect(lambda _, d=disc, b=act_btn: self._show_orphan_action_menu(d, b))

        self._table.setCellWidget(row, COL_ACTIONS, act_btn)

    def _fill_fbr_cells(
        self,
        row: int,
        snap: Optional[FBRSnapshotRecord],
        dimmed: bool,
    ) -> None:
        """Populate the three FBR summary columns for one row.

        Sort keys:
          COL_FBR_QUALITY  — int: -2=Never, -1=Error, else quality_sources
          COL_FBR_BEST     — float: -2.0=Never, -1.0=Error/empty, else best_fbr_pct
          COL_FBR_DATE     — str: ""=Never (sorts first asc), else ISO date
        """
        center = Qt.AlignmentFlag.AlignCenter

        def _si(text: str, sort_key, color=None, _dimmed=False) -> SortableItem:
            item = SortableItem(text, sort_key)
            item.setTextAlignment(center)
            if _dimmed:
                item.setForeground(C_REMOVED())
            elif color:
                item.setForeground(color)
            return item

        if snap is None:
            # Never analyzed — use amber to draw operator attention
            self._table.setItem(row, COL_FBR_QUALITY, _si("\u2014",     -2,   C_NEVER()))
            self._table.setItem(row, COL_FBR_BEST,    _si("\u2014",     -2.0, C_NEVER()))
            self._table.setItem(row, COL_FBR_DATE,    _si("Never", "",   C_NEVER()))
            return

        date_str  = snap.analyzed_at[:10] if snap.analyzed_at else "\u2014"
        date_sort = snap.analyzed_at[:10] if snap.analyzed_at else ""

        if snap.status == SNAPSHOT_ERROR:
            self._table.setItem(row, COL_FBR_QUALITY, _si("Error", -1,   C_ERROR()))
            self._table.setItem(row, COL_FBR_BEST,    _si("\u2014",     -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        if snap.total_sources == 0:
            # Empty result — data.db exists but no qualifying source rows
            self._table.setItem(row, COL_FBR_QUALITY, _si("0/0", 0,    C_LOW_FBR()))
            self._table.setItem(row, COL_FBR_BEST,    _si("\u2014",   -1.0))
            self._table.setItem(row, COL_FBR_DATE,    _si(date_str, date_sort))
            return

        # Normal case: 'ok' status with data
        quality_text  = f"{snap.quality_sources}/{snap.total_sources}"
        quality_color = C_QUALITY() if snap.quality_sources > 0 else C_LOW_FBR()
        self._table.setItem(
            row, COL_FBR_QUALITY,
            _si(quality_text, snap.quality_sources, quality_color, _dimmed=dimmed),
        )

        if snap.best_fbr_pct is not None:
            fbr_color = C_QUALITY() if snap.quality_sources > 0 else C_LOW_FBR()
            self._table.setItem(
                row, COL_FBR_BEST,
                _si(f"{snap.best_fbr_pct:.1f}%", snap.best_fbr_pct, fbr_color, _dimmed=dimmed),
            )
        else:
            self._table.setItem(row, COL_FBR_BEST, _si("\u2014", -1.0))

        self._table.setItem(
            row, COL_FBR_DATE,
            _si(date_str, date_sort, _dimmed=dimmed),
        )

    # ------------------------------------------------------------------
    # Static cell helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_item(
        text: str,
        align: Qt.AlignmentFlag = Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
        color: Optional[QColor] = None,
        dimmed: bool = False,
    ) -> QTableWidgetItem:
        i = QTableWidgetItem(text)
        i.setTextAlignment(align)
        if dimmed:
            i.setForeground(C_REMOVED())
        elif color:
            i.setForeground(color)
        return i

    @staticmethod
    def _make_bool_item(
        val: Optional[bool], dimmed: bool = False
    ) -> QTableWidgetItem:
        center = Qt.AlignmentFlag.AlignCenter
        if val is None:
            i = QTableWidgetItem("\u2014")
            i.setTextAlignment(center)
            return i
        text = "Yes" if val else "No"
        col  = C_REMOVED() if dimmed else (C_YES() if val else C_NO())
        i = QTableWidgetItem(text)
        i.setTextAlignment(center)
        i.setForeground(col)
        return i

    @staticmethod
    def _get_slot_number(acc: AccountRecord) -> int:
        """Return timeslot 1-4 based on account start_time, or 0 if unknown."""
        start_t = getattr(acc, "start_time", None) or ""
        if not start_t:
            return 0
        try:
            hour = int(start_t.split(":")[0])
        except (ValueError, IndexError):
            return 0
        if hour < 6:
            return 1
        elif hour < 12:
            return 2
        elif hour < 18:
            return 3
        else:
            return 4

    # ------------------------------------------------------------------
    # Context menu (right-click)
    # ------------------------------------------------------------------

    def _on_table_context_menu(self, pos) -> None:
        """Right-click context menu for the accounts table."""
        row = self._table.rowAt(pos.y())
        if row < 0:
            return

        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return

        kind, payload = data

        menu = QMenu(self)

        # Copy Username — always available
        username_text = item.text() or ""
        menu.addAction("Copy Username", lambda: self._copy_text_to_clipboard(username_text))

        ctx = getattr(self, "_data_context", {})
        has_svc = ctx.get("has_operator_action_service", False)

        if kind == "account":
            # We store account_id in payload; emit signals for MainWindow to handle
            account_id = payload
            menu.addSeparator()

            # We need the account record — look it up from data context
            accounts_by_id = ctx.get("accounts_by_id", {})
            acc = accounts_by_id.get(account_id)

            if acc is not None:
                has_sources = acc.data_db_exists or acc.sources_txt_exists
                src_action = menu.addAction(
                    "View Sources",
                    lambda: self.view_sources_requested.emit(acc.device_id, acc.username, acc.id),
                )
                src_action.setEnabled(has_sources)

                if has_svc:
                    menu.addSeparator()
                    if acc.review_flag:
                        menu.addAction("Clear Review", lambda: self.action_requested.emit("clear_review", acc))
                    else:
                        menu.addAction("Set Review", lambda: self.action_requested.emit("set_review", acc))
                    menu.addAction("TB +1", lambda: self.action_requested.emit("tb_plus_1", acc))
                    menu.addAction("Limits +1", lambda: self.action_requested.emit("limits_plus_1", acc))

                menu.addSeparator()
                menu.addAction("Open Folder", lambda: self.open_folder_requested.emit(acc.device_id, acc.username))

        elif kind == "orphan":
            disc = payload
            menu.addSeparator()

            has_sources = disc.data_db_exists or disc.sources_txt_exists
            src_action = menu.addAction(
                "View Sources",
                lambda: self.view_sources_requested.emit(disc.device_id, disc.username, None),
            )
            src_action.setEnabled(has_sources)

            menu.addSeparator()
            menu.addAction("Open Folder", lambda: self.open_folder_requested.emit(disc.device_id, disc.username))

        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _copy_text_to_clipboard(self, text: str) -> None:
        """Copy text to the system clipboard."""
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    # ------------------------------------------------------------------
    # Action menus (button click)
    # ------------------------------------------------------------------

    def _show_action_menu(self, acc: AccountRecord, btn: QPushButton) -> None:
        """Show a popup menu of all actions for this account."""
        ctx = getattr(self, "_data_context", {})
        menu = QMenu(self)

        menu.addAction("Open Folder", lambda: self.open_folder_requested.emit(acc.device_id, acc.username))

        has_sources = acc.data_db_exists or acc.sources_txt_exists
        src_action = menu.addAction(
            "View Sources",
            lambda: self.view_sources_requested.emit(acc.device_id, acc.username, acc.id),
        )
        src_action.setEnabled(has_sources)

        if ctx.get("has_source_finder_service", False):
            menu.addAction("Find Sources", lambda: self.find_sources_requested.emit(acc))

        if ctx.get("has_operator_action_service", False):
            menu.addSeparator()
            if acc.review_flag:
                menu.addAction("Clear Review", lambda: self.action_requested.emit("clear_review", acc))
            else:
                menu.addAction("Set Review", lambda: self.action_requested.emit("set_review", acc))
            menu.addAction("TB +1", lambda: self.action_requested.emit("tb_plus_1", acc))
            menu.addAction("Limits +1", lambda: self.action_requested.emit("limits_plus_1", acc))

        if ctx.get("has_settings_copier_service", False):
            menu.addSeparator()
            menu.addAction(
                "Copy Settings From This Account",
                lambda: self.copy_settings_requested.emit(acc.id),
            )

        if ctx.get("has_warmup_template_service", False):
            menu.addSeparator()
            warmup_sub = menu.addMenu("Apply Warmup")
            # Populate the sub-menu via a callback from MainWindow
            populate_warmup = ctx.get("populate_warmup_submenu")
            if populate_warmup:
                populate_warmup(warmup_sub, [acc.id])

        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _show_orphan_action_menu(self, disc: DiscoveredAccount, btn: QPushButton) -> None:
        """Show a popup menu for an orphan row."""
        menu = QMenu(self)
        menu.addAction("Open Folder", lambda: self.open_folder_requested.emit(disc.device_id, disc.username))

        has_sources = disc.data_db_exists or disc.sources_txt_exists
        src_action = menu.addAction(
            "View Sources",
            lambda: self.view_sources_requested.emit(disc.device_id, disc.username, None),
        )
        src_action.setEnabled(has_sources)

        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    # ------------------------------------------------------------------
    # Double-click
    # ------------------------------------------------------------------

    def _on_row_double_clicked(self, index) -> None:
        row = index.row()
        col = index.column()
        item = self._table.item(row, COL_USERNAME)
        if not item:
            return
        data = item.data(Qt.ItemDataRole.UserRole)
        if not data:
            return
        kind, payload = data

        # Double-click on Trend column -> emit trend signal
        if col == COL_TREND and kind == "account":
            ctx = getattr(self, "_data_context", {})
            if ctx.get("has_trend_service", False):
                self.trend_double_clicked.emit(payload)
            return

        # Double-click on any other column -> emit row_double_clicked
        if kind in ("account", "orphan"):
            self.row_double_clicked.emit(index)
