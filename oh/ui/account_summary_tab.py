"""
AccountSummaryTab -- scrollable Summary tab for the Account Detail drawer.

Blocks:
  1. Identity   -- username, device, status, tags, review
  2. Performance cards -- Today's Activity, FBR Status, Source Health, Account Health
  3. Configuration -- settings grid
  4. FBR Snapshot  -- latest analysis summary

Public API:
  load(data: AccountDetailData) -- populate all labels/cards
"""
import logging
from typing import Optional

from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QGridLayout, QSizePolicy,
)
from PySide6.QtCore import Qt

from oh.models.account_detail import AccountDetailData
from oh.models.fbr_snapshot import SNAPSHOT_OK, SNAPSHOT_EMPTY, SNAPSHOT_ERROR
from oh.ui.style import sc

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _label(text: str = "", bold: bool = False, size: int = 11,
           color_key: Optional[str] = None) -> QLabel:
    """Create a styled QLabel."""
    lbl = QLabel(text)
    parts = ["font-size: %dpx;" % size]
    if bold:
        parts.append("font-weight: bold;")
    if color_key:
        parts.append("color: %s;" % sc(color_key).name())
    lbl.setStyleSheet(" ".join(parts))
    lbl.setTextFormat(Qt.TextFormat.RichText)
    lbl.setWordWrap(True)
    return lbl


def _card_frame(border_color_key: str) -> QFrame:
    """Create a performance card QFrame with a colored 3px left border."""
    frame = QFrame()
    frame.setFrameShape(QFrame.Shape.NoFrame)
    frame.setStyleSheet(
        "QFrame { border-left: 3px solid %s; padding: 8px; }" % sc(border_color_key).name()
    )
    frame.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
    return frame


# ---------------------------------------------------------------------------
# AccountSummaryTab
# ---------------------------------------------------------------------------

class AccountSummaryTab(QScrollArea):
    """Scrollable summary tab for the account detail panel."""

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)

        self._container = QWidget()
        self._root = QVBoxLayout(self._container)
        self._root.setContentsMargins(6, 6, 6, 6)
        self._root.setSpacing(6)

        self._build_identity_block()
        self._build_performance_cards()
        self._build_configuration_block()
        self._build_fbr_snapshot_block()
        self._root.addStretch()

        self.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def load(self, data: AccountDetailData) -> None:
        """Populate all labels and cards from an AccountDetailData instance."""
        self._load_identity(data)
        self._load_performance_cards(data)
        self._load_configuration(data)
        self._load_fbr_snapshot(data)
        logger.debug("AccountSummaryTab loaded for %s", data.account.username)

    # ------------------------------------------------------------------
    # 1. Identity block
    # ------------------------------------------------------------------

    def _build_identity_block(self) -> None:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        lo = QVBoxLayout(frame)
        lo.setContentsMargins(8, 6, 8, 6)
        lo.setSpacing(4)

        # Username
        self._id_username = _label(bold=True, size=14)
        lo.addWidget(self._id_username)

        # Device + status row
        row = QHBoxLayout()
        row.setSpacing(8)
        self._id_device = _label(size=11, color_key="text_secondary")
        row.addWidget(self._id_device)
        self._id_status = _label(size=11)
        row.addWidget(self._id_status)
        row.addStretch()
        lo.addLayout(row)

        # Tags row
        self._id_tags = _label(size=11)
        self._id_tags.setVisible(False)
        lo.addWidget(self._id_tags)

        # Review row
        self._id_review_frame = QFrame()
        self._id_review_frame.setVisible(False)
        review_lo = QHBoxLayout(self._id_review_frame)
        review_lo.setContentsMargins(0, 2, 0, 0)
        review_lo.setSpacing(6)
        self._id_review_badge = _label(size=11)
        review_lo.addWidget(self._id_review_badge)
        self._id_review_note = _label(size=11, color_key="text_secondary")
        review_lo.addWidget(self._id_review_note)
        self._id_review_ts = _label(size=10, color_key="muted")
        review_lo.addWidget(self._id_review_ts)
        review_lo.addStretch()
        lo.addWidget(self._id_review_frame)

        self._root.addWidget(frame)

    def _load_identity(self, data: AccountDetailData) -> None:
        acct = data.account

        self._id_username.setText(acct.username)
        self._id_device.setText(acct.device_name or acct.device_id or "")

        if acct.is_active:
            self._id_status.setText(
                "<span style='color:%s; font-weight:bold;'>Active</span>"
                % sc("success").name()
            )
        else:
            self._id_status.setText(
                "<span style='color:%s; font-weight:bold;'>Removed</span>"
                % sc("error").name()
            )

        # Tags
        tags_parts = []
        if data.bot_tags:
            for t in data.bot_tags.split(","):
                t = t.strip()
                if t:
                    tags_parts.append(
                        "<span style='color:%s;'>%s</span>" % (sc("text").name(), t)
                    )
        if data.operator_tags:
            for t in data.operator_tags.split(","):
                t = t.strip()
                if t:
                    tags_parts.append(
                        "<span style='color:%s; font-weight:bold;'>OP: %s</span>"
                        % (sc("warning").name(), t)
                    )
        if tags_parts:
            self._id_tags.setText("  ".join(tags_parts))
            self._id_tags.setVisible(True)
        else:
            self._id_tags.setVisible(False)

        # Review
        if acct.review_flag:
            self._id_review_frame.setVisible(True)
            self._id_review_badge.setText(
                "<span style='background:%s; color:#fff; padding:1px 6px; "
                "border-radius:3px; font-weight:bold;'>REVIEW</span>"
                % sc("error").name()
            )
            self._id_review_note.setText(acct.review_note or "")
            self._id_review_ts.setText(acct.review_set_at or "")
        else:
            self._id_review_frame.setVisible(False)

    # ------------------------------------------------------------------
    # 2. Performance cards
    # ------------------------------------------------------------------

    def _build_performance_cards(self) -> None:
        row = QHBoxLayout()
        row.setSpacing(6)

        # Card 1: Today's Activity
        self._card_activity_frame = _card_frame("muted")
        c1_lo = QVBoxLayout(self._card_activity_frame)
        c1_lo.setContentsMargins(6, 4, 6, 4)
        c1_lo.setSpacing(2)
        self._card_activity_title = _label("Today's Activity", bold=True, size=11)
        c1_lo.addWidget(self._card_activity_title)
        self._card_activity_body = _label(size=11)
        c1_lo.addWidget(self._card_activity_body)
        row.addWidget(self._card_activity_frame)

        # Card 2: FBR Status
        self._card_fbr_frame = _card_frame("muted")
        c2_lo = QVBoxLayout(self._card_fbr_frame)
        c2_lo.setContentsMargins(6, 4, 6, 4)
        c2_lo.setSpacing(2)
        self._card_fbr_title = _label("FBR Status", bold=True, size=11)
        c2_lo.addWidget(self._card_fbr_title)
        self._card_fbr_body = _label(size=11)
        c2_lo.addWidget(self._card_fbr_body)
        row.addWidget(self._card_fbr_frame)

        # Card 3: Source Health
        self._card_source_frame = _card_frame("muted")
        c3_lo = QVBoxLayout(self._card_source_frame)
        c3_lo.setContentsMargins(6, 4, 6, 4)
        c3_lo.setSpacing(2)
        self._card_source_title = _label("Source Health", bold=True, size=11)
        c3_lo.addWidget(self._card_source_title)
        self._card_source_body = _label(size=11)
        c3_lo.addWidget(self._card_source_body)
        row.addWidget(self._card_source_frame)

        # Card 4: Account Health
        self._card_health_frame = _card_frame("muted")
        c4_lo = QVBoxLayout(self._card_health_frame)
        c4_lo.setContentsMargins(6, 4, 6, 4)
        c4_lo.setSpacing(2)
        self._card_health_title = _label("Account Health", bold=True, size=11)
        c4_lo.addWidget(self._card_health_title)
        self._card_health_body = _label(size=11)
        c4_lo.addWidget(self._card_health_body)
        row.addWidget(self._card_health_frame)

        self._root.addLayout(row)

    def _set_card_border(self, frame: QFrame, color_key: str) -> None:
        """Update the left-border color of a performance card."""
        frame.setStyleSheet(
            "QFrame { border-left: 3px solid %s; padding: 8px; }" % sc(color_key).name()
        )

    def _load_performance_cards(self, data: AccountDetailData) -> None:
        self._load_card_activity(data)
        self._load_card_fbr(data)
        self._load_card_source(data)
        self._load_card_health(data)

    def _load_card_activity(self, data: AccountDetailData) -> None:
        sess = data.session
        if sess is None:
            self._card_activity_body.setText(
                "<span style='color:%s;'>No session data</span>" % sc("muted").name()
            )
            self._set_card_border(self._card_activity_frame, "muted")
            return

        follow_lim = str(sess.follow_limit) if sess.follow_limit is not None else "?"
        like_lim = str(sess.like_limit) if sess.like_limit is not None else "?"

        lines = [
            "Follow: %d / %s" % (sess.follow_count, follow_lim),
            "Like: %d / %s" % (sess.like_count, like_lim),
            "DM: %d" % sess.dm_count,
        ]
        self._card_activity_body.setText("<br>".join(lines))

        if sess.total_actions > 0:
            self._set_card_border(self._card_activity_frame, "success")
        else:
            self._set_card_border(self._card_activity_frame, "error")

    def _load_card_fbr(self, data: AccountDetailData) -> None:
        snap = data.fbr_snapshot
        if snap is None:
            self._card_fbr_body.setText(
                "<span style='color:%s;'>Never analyzed</span>" % sc("muted").name()
            )
            self._set_card_border(self._card_fbr_frame, "muted")
            return

        best_str = ""
        if snap.best_fbr_pct is not None:
            src_name = snap.best_fbr_source or "?"
            best_str = "Best: %.1f%% (%s)" % (snap.best_fbr_pct, src_name)

        lines = [
            "Quality: %d / %d" % (snap.quality_sources, snap.total_sources),
        ]
        if best_str:
            lines.append(best_str)

        self._card_fbr_body.setText("<br>".join(lines))

        if snap.quality_sources > 0:
            self._set_card_border(self._card_fbr_frame, "success")
        else:
            self._set_card_border(self._card_fbr_frame, "warning")

    def _load_card_source(self, data: AccountDetailData) -> None:
        count = data.source_count
        self._card_source_body.setText("Active: %d sources" % count)

        min_warn = 5
        if count == 0:
            self._set_card_border(self._card_source_frame, "error")
        elif count < min_warn:
            self._set_card_border(self._card_source_frame, "warning")
        else:
            self._set_card_border(self._card_source_frame, "success")

    def _load_card_health(self, data: AccountDetailData) -> None:
        acct = data.account
        # Parse TB and Limits levels from tags
        tb_level = self._parse_tag_level(data.bot_tags, data.operator_tags, "TB")
        limits_level = self._parse_tag_level(data.bot_tags, data.operator_tags, "limits")

        tb_str = str(tb_level) if tb_level is not None else "n/a"
        lim_str = str(limits_level) if limits_level is not None else "n/a"

        self._card_health_body.setText(
            "TB: %s<br>Limits: %s" % (tb_str, lim_str)
        )

        tb_val = tb_level or 0
        lim_val = limits_level or 0
        if tb_val >= 4 or lim_val >= 4:
            self._set_card_border(self._card_health_frame, "error")
        else:
            self._set_card_border(self._card_health_frame, "success")

    @staticmethod
    def _parse_tag_level(bot_tags: str, operator_tags: str, prefix: str) -> Optional[int]:
        """Extract numeric level from tags like 'TB3', 'limits 4'."""
        combined = (bot_tags or "") + "," + (operator_tags or "")
        for raw in combined.split(","):
            t = raw.strip()
            low = t.lower()
            plow = prefix.lower()
            if low.startswith(plow):
                rest = low[len(plow):].strip()
                if rest.isdigit():
                    return int(rest)
        return None

    # ------------------------------------------------------------------
    # 3. Configuration block
    # ------------------------------------------------------------------

    def _build_configuration_block(self) -> None:
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.StyledPanel)
        grid = QGridLayout(frame)
        grid.setContentsMargins(8, 6, 8, 6)
        grid.setSpacing(4)

        row = 0
        self._cfg_follow_enabled = self._add_config_row(grid, row, "Follow enabled", "")
        self._cfg_unfollow_enabled = self._add_config_row(grid, row, "Unfollow enabled", "", col_offset=2)
        row += 1
        self._cfg_follow_limit = self._add_config_row(grid, row, "Follow limit/day", "")
        self._cfg_like_limit = self._add_config_row(grid, row, "Like limit/day", "", col_offset=2)
        row += 1
        self._cfg_time_slot = self._add_config_row(grid, row, "Time slot", "")
        self._cfg_limit_per_day = self._add_config_row(grid, row, "Limit/day", "", col_offset=2)
        row += 1
        self._cfg_last_seen = self._add_config_row(grid, row, "Last seen", "")
        self._cfg_discovered = self._add_config_row(grid, row, "Discovered", "", col_offset=2)
        row += 1
        self._cfg_data_db = self._add_config_row(grid, row, "data.db exists", "")
        self._cfg_sources_txt = self._add_config_row(grid, row, "sources.txt exists", "", col_offset=2)

        self._root.addWidget(frame)

    def _add_config_row(self, grid: QGridLayout, row: int, label_text: str,
                        default: str, col_offset: int = 0) -> QLabel:
        """Add a label+value pair to the config grid. Returns the value label."""
        lbl = _label(label_text, size=11, color_key="muted")
        val = _label(default, size=11)
        grid.addWidget(lbl, row, 0 + col_offset)
        grid.addWidget(val, row, 1 + col_offset)
        return val

    def _load_configuration(self, data: AccountDetailData) -> None:
        acct = data.account

        self._cfg_follow_enabled.setText(self._bool_html(acct.follow_enabled))
        self._cfg_unfollow_enabled.setText(self._bool_html(acct.unfollow_enabled))

        self._cfg_follow_limit.setText(acct.follow_limit_perday or "n/a")
        self._cfg_like_limit.setText(acct.like_limit_perday or "n/a")

        start = acct.start_time or "?"
        end = acct.end_time or "?"
        self._cfg_time_slot.setText("%s - %s" % (start, end))
        self._cfg_limit_per_day.setText(acct.limit_per_day or "n/a")

        self._cfg_last_seen.setText(acct.last_seen_at or "n/a")
        self._cfg_discovered.setText(acct.discovered_at or "n/a")

        self._cfg_data_db.setText(self._bool_html(acct.data_db_exists))
        self._cfg_sources_txt.setText(self._bool_html(acct.sources_txt_exists))

    @staticmethod
    def _bool_html(val: Optional[bool]) -> str:
        if val is None:
            return "<span style='color:%s;'>n/a</span>" % sc("muted").name()
        if val:
            return "<span style='color:%s;'>Yes</span>" % sc("yes").name()
        return "<span style='color:%s;'>No</span>" % sc("no").name()

    # ------------------------------------------------------------------
    # 4. FBR Snapshot block
    # ------------------------------------------------------------------

    def _build_fbr_snapshot_block(self) -> None:
        self._fbr_frame = QFrame()
        self._fbr_frame.setFrameShape(QFrame.Shape.StyledPanel)
        self._fbr_lo = QVBoxLayout(self._fbr_frame)
        self._fbr_lo.setContentsMargins(8, 6, 8, 6)
        self._fbr_lo.setSpacing(4)

        self._fbr_title = _label("FBR Snapshot", bold=True, size=11, color_key="heading")
        self._fbr_lo.addWidget(self._fbr_title)

        self._fbr_body = _label(size=11)
        self._fbr_lo.addWidget(self._fbr_body)

        self._fbr_schema_error = _label(size=11)
        self._fbr_schema_error.setVisible(False)
        self._fbr_lo.addWidget(self._fbr_schema_error)

        self._root.addWidget(self._fbr_frame)

    def _load_fbr_snapshot(self, data: AccountDetailData) -> None:
        snap = data.fbr_snapshot

        if snap is None:
            self._fbr_body.setText(
                "<span style='color:%s;'>Never analyzed</span>" % sc("muted").name()
            )
            self._fbr_schema_error.setVisible(False)
            return

        lines = []

        # Quality / Total
        lines.append("Quality: %d / %d" % (snap.quality_sources, snap.total_sources))

        # Best FBR
        if snap.best_fbr_pct is not None:
            src = snap.best_fbr_source or "?"
            lines.append("Best FBR: %.1f%% (%s)" % (snap.best_fbr_pct, src))

        # Highest volume
        if snap.highest_vol_source is not None:
            vol_count = snap.highest_vol_count or 0
            lines.append("Highest volume: %s (%d)" % (snap.highest_vol_source, vol_count))

            # Below volume count
            lines.append("Below volume: %d" % snap.below_volume_count)

        # Anomaly count
        if snap.anomaly_count > 0:
            lines.append(
                "<span style='color:%s;'>Anomalies: %d</span>"
                % (sc("error").name(), snap.anomaly_count)
            )
        else:
            lines.append("Anomalies: 0")

        # Last analyzed
        lines.append(
            "<span style='color:%s;'>Analyzed: %s</span>"
            % (sc("muted").name(), snap.analyzed_at)
        )

        self._fbr_body.setText("<br>".join(lines))

        # Schema error badge
        if snap.schema_error:
            self._fbr_schema_error.setText(
                "<span style='background:%s; color:#fff; padding:1px 6px; "
                "border-radius:3px; font-weight:bold;'>SCHEMA ERROR: %s</span>"
                % (sc("error").name(), snap.schema_error)
            )
            self._fbr_schema_error.setVisible(True)
        else:
            self._fbr_schema_error.setVisible(False)
