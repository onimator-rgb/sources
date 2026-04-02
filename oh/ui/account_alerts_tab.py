"""
AccountAlertsTab — scrollable alerts + review history + contextual cards.

Sits inside the AccountDetailPanel tab widget as the "Alerts" tab.

Signals:
    action_requested(str, int)  -- (action_type, account_id)
"""
import logging
from typing import Optional, List

from PySide6.QtWidgets import (
    QScrollArea, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QFrame, QPushButton, QSizePolicy,
)
from PySide6.QtCore import Qt, Signal

from oh.models.account_detail import AccountDetailData, AccountAlert
from oh.models.operator_action import OperatorActionRecord
from oh.ui.style import sc

logger = logging.getLogger(__name__)

# Severity sort order (lower = shown first)
_SEV_RANK = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}

# Action type -> button label
_ACTION_LABELS = {
    "tb_plus_1":     "TB +1",
    "limits_plus_1": "Limits +1",
    "clear_review":  "Clear Review",
    "set_review":    "Set Review",
}


def _severity_color_name(severity: str) -> str:
    """Return the sc() key for a severity level."""
    return {
        "CRITICAL": "critical",
        "HIGH":     "high",
        "MEDIUM":   "medium",
        "LOW":      "low",
    }.get(severity, "muted")


class AccountAlertsTab(QScrollArea):
    """Scrollable alerts tab for the account detail drawer."""

    action_requested = Signal(str, int)  # (action_type, account_id)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        self._service = None
        self._account_id: Optional[int] = None

        # Inner container
        self._container = QWidget()
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(6, 6, 6, 6)
        self._layout.setSpacing(6)
        self._layout.addStretch()
        self.setWidget(self._container)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def set_service(self, service) -> None:
        """Store reference to AccountDetailService for lazy loading."""
        self._service = service

    def load(self, data: AccountDetailData, service=None) -> None:
        """Populate the tab from an AccountDetailData instance."""
        if service is not None:
            self._service = service

        acc = data.account
        self._account_id = acc.id

        # Clear previous content
        self._clear_layout()

        # 1. Active Alerts
        self._build_alerts_section(data.alerts, acc)

        # 2. Review History
        self._build_review_history_section(data, acc)

        # 3. Contextual Recommendation Cards
        self._build_contextual_cards(data, acc)

        self._layout.addStretch()

    # ------------------------------------------------------------------
    # Section 1: Active Alerts
    # ------------------------------------------------------------------

    def _build_alerts_section(
        self, alerts: List[AccountAlert], acc
    ) -> None:
        sorted_alerts = sorted(
            alerts, key=lambda a: _SEV_RANK.get(a.severity, 9)
        )

        if not sorted_alerts:
            self._layout.addWidget(self._make_all_clear_card())
            return

        for alert in sorted_alerts:
            self._layout.addWidget(self._make_alert_card(alert, acc))

    def _make_alert_card(self, alert: AccountAlert, acc) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        border_color = sc(_severity_color_name(alert.severity)).name()
        card.setStyleSheet(
            "QFrame { border-left: 3px solid %s; border: 1px solid %s; "
            "border-left: 3px solid %s; }"
            % (border_color, sc("border").name(), border_color)
        )

        lo = QVBoxLayout(card)
        lo.setContentsMargins(8, 6, 8, 6)
        lo.setSpacing(3)

        # Top row: severity badge + title
        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        badge = QLabel(alert.severity)
        badge_bg = sc(_severity_color_name(alert.severity)).name()
        badge.setStyleSheet(
            "background: %s; color: #fff; padding: 1px 6px; "
            "border-radius: 2px; font-size: 10px; font-weight: bold;"
            % badge_bg
        )
        badge.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        top_row.addWidget(badge)

        title = QLabel(alert.title)
        title.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: %s; border: none;"
            % sc("text").name()
        )
        title.setWordWrap(True)
        top_row.addWidget(title, stretch=1)
        lo.addLayout(top_row)

        # Detail text
        if alert.detail:
            detail = QLabel(alert.detail)
            detail.setStyleSheet(
                "font-size: 11px; color: %s; border: none;"
                % sc("text_secondary").name()
            )
            detail.setWordWrap(True)
            lo.addWidget(detail)

        # Recommended action
        if alert.recommended_action:
            rec_label = QLabel(alert.recommended_action)
            rec_label.setStyleSheet(
                "font-size: 11px; font-style: italic; color: %s; border: none;"
                % sc("muted").name()
            )
            rec_label.setWordWrap(True)
            lo.addWidget(rec_label)

        # Inline action button
        if alert.action_type and alert.action_type in _ACTION_LABELS:
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 2, 0, 0)
            btn_row.addStretch()
            btn = QPushButton(_ACTION_LABELS[alert.action_type])
            btn.setStyleSheet(
                "min-height: 0px; padding: 3px 10px; font-size: 11px;"
            )
            action_type = alert.action_type
            account_id = acc.id
            btn.clicked.connect(
                lambda checked=False, at=action_type, aid=account_id:
                self._emit_action(at, aid)
            )
            btn_row.addWidget(btn)
            lo.addLayout(btn_row)

        return card

    def _make_all_clear_card(self) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        success_color = sc("success").name()
        card.setStyleSheet(
            "QFrame { border: 1px solid %s; border-left: 3px solid %s; }"
            % (success_color, success_color)
        )
        lo = QVBoxLayout(card)
        lo.setContentsMargins(8, 6, 8, 6)
        lbl = QLabel("All clear -- no issues detected")
        lbl.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: %s; border: none;"
            % success_color
        )
        lo.addWidget(lbl)
        return card

    # ------------------------------------------------------------------
    # Section 2: Review History
    # ------------------------------------------------------------------

    def _build_review_history_section(self, data: AccountDetailData, acc) -> None:
        # Section header
        header = QLabel("Review History")
        header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: %s; margin-top: 6px;"
            % sc("heading").name()
        )
        self._layout.addWidget(header)

        # Current review status
        review_flag = acc.review_flag
        if review_flag:
            note = acc.review_note or ""
            ts = acc.review_set_at or ""
            status_text = "<b>REVIEW</b>"
            if note:
                status_text += " %s" % note
            if ts:
                status_text += "  <span style='color:%s;'>%s</span>" % (
                    sc("muted").name(), ts
                )
            status_label = QLabel(status_text)
            status_label.setTextFormat(Qt.TextFormat.RichText)
            status_label.setStyleSheet(
                "font-size: 11px; color: %s; padding: 2px 0px;"
                % sc("error").name()
            )
            status_label.setWordWrap(True)
            self._layout.addWidget(status_label)
        else:
            no_review = QLabel("No active review")
            no_review.setStyleSheet(
                "font-size: 11px; color: %s; font-style: italic; padding: 2px 0px;"
                % sc("muted").name()
            )
            self._layout.addWidget(no_review)

        # Past review entries from service
        history: List[OperatorActionRecord] = []
        if self._service is not None and acc.id is not None:
            try:
                history = self._service.get_review_history(acc.id)
            except Exception:
                logger.warning(
                    "Failed to load review history for account_id=%s",
                    acc.id, exc_info=True,
                )
                err_label = QLabel("Failed to load review history")
                err_label.setStyleSheet(
                    "font-size: 11px; color: %s; font-style: italic; padding: 2px 0px;"
                    % sc("error").name()
                )
                self._layout.addWidget(err_label)
                return

        if history:
            for rec in history:
                self._layout.addWidget(self._make_review_entry(rec))
        else:
            placeholder = QLabel("No review history")
            placeholder.setStyleSheet(
                "font-size: 11px; color: %s; font-style: italic; padding: 2px 0px;"
                % sc("muted").name()
            )
            self._layout.addWidget(placeholder)

    def _make_review_entry(self, rec: OperatorActionRecord) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { border: 1px solid %s; }" % sc("border").name()
        )

        lo = QHBoxLayout(card)
        lo.setContentsMargins(6, 4, 6, 4)
        lo.setSpacing(8)

        # Timestamp
        ts = rec.performed_at or ""
        ts_label = QLabel(ts)
        ts_label.setStyleSheet(
            "font-size: 10px; color: %s; border: none;" % sc("muted").name()
        )
        ts_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lo.addWidget(ts_label)

        # Action type
        action_text = "Set" if rec.action_type == "set_review" else "Cleared"
        action_label = QLabel(action_text)
        action_label.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: %s; border: none;"
            % sc("text").name()
        )
        action_label.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        lo.addWidget(action_label)

        # Note
        note_text = rec.note or ""
        if note_text:
            note_label = QLabel(note_text)
            note_label.setStyleSheet(
                "font-size: 11px; color: %s; border: none;"
                % sc("text_secondary").name()
            )
            note_label.setWordWrap(True)
            lo.addWidget(note_label, stretch=1)
        else:
            lo.addStretch()

        # Machine
        machine = rec.machine or ""
        if machine:
            machine_label = QLabel(machine)
            machine_label.setStyleSheet(
                "font-size: 10px; color: %s; border: none;" % sc("muted").name()
            )
            machine_label.setSizePolicy(
                QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred
            )
            lo.addWidget(machine_label)

        return card

    # ------------------------------------------------------------------
    # Section 3: Contextual Recommendation Cards
    # ------------------------------------------------------------------

    def _build_contextual_cards(self, data: AccountDetailData, acc) -> None:
        review_note = (acc.review_note or "").lower()
        source_count = data.source_count
        any_card = False

        if "pending" in review_note:
            self._layout.addWidget(
                self._make_context_card(
                    title="Follow is pending",
                    detail=(
                        "This account has a pending follow action. "
                        "The review flag was likely set because a follow "
                        "operation did not complete. Clear the review once "
                        "the follow has been verified or resolved."
                    ),
                    button_action="clear_review",
                    account_id=acc.id,
                )
            )
            any_card = True

        if "try again" in review_note:
            self._layout.addWidget(
                self._make_context_card(
                    title="Try again later",
                    detail=(
                        "The bot flagged this account to try again later, "
                        "typically due to a temporary block or rate limit. "
                        "Increasing the trust-boost level may help the "
                        "account recover faster."
                    ),
                    button_action="tb_plus_1",
                    account_id=acc.id,
                )
            )
            any_card = True

        if source_count == 0:
            self._layout.addWidget(
                self._make_context_card(
                    title="No sources",
                    detail=(
                        "This account has zero active sources. "
                        "Without sources the bot cannot perform follow "
                        "or like actions. Add sources before the next "
                        "automation cycle."
                    ),
                    button_action=None,
                    account_id=acc.id,
                )
            )
            any_card = True

        # Auto-generate contextual cards based on account state
        cards = []
        if hasattr(data, "session") and data.session:
            if data.session.follow_count == 0 and (data.session.follow_limit or 0) > 0:
                cards.append({
                    "title": "Follow is pending",
                    "detail": "Account has follow limit set but 0 follows today",
                    "color_key": "warning",
                })
        if hasattr(data, "source_count") and (data.source_count or 0) < 5:
            cards.append({
                "title": "Low source count",
                "detail": "Only %d active sources" % (data.source_count or 0),
                "color_key": "high",
            })
        if hasattr(data, "account") and getattr(data.account, "review_flag", 0):
            cards.append({
                "title": "Review flag active",
                "detail": getattr(data.account, "review_note", "") or "Check this account",
                "color_key": "medium",
            })
        if cards:
            self.load_contextual_cards(cards)

        if not any_card and not cards:
            return

    def load_contextual_cards(self, cards: list) -> None:
        """Show contextual action cards based on account state.

        cards: list of dicts with 'title', 'detail', 'color_key'
        """
        if not cards:
            return

        header = QLabel("Contextual Insights")
        header.setStyleSheet(
            "font-size: 12px; font-weight: bold; color: %s; margin-top: 6px;"
            % sc("heading").name()
        )
        self._layout.addWidget(header)

        for card_data in cards:
            title = card_data.get("title", "")
            detail = card_data.get("detail", "")
            color_key = card_data.get("color_key", "muted")

            card = QFrame()
            card.setFrameShape(QFrame.Shape.StyledPanel)
            border_color = sc(color_key).name()
            card.setStyleSheet(
                "QFrame { border: 1px solid %s; border-left: 3px solid %s; }"
                % (sc("border").name(), border_color)
            )

            lo = QVBoxLayout(card)
            lo.setContentsMargins(8, 6, 8, 6)
            lo.setSpacing(3)

            title_label = QLabel(title)
            title_label.setStyleSheet(
                "font-size: 11px; font-weight: bold; color: %s; border: none;"
                % sc("text").name()
            )
            title_label.setWordWrap(True)
            lo.addWidget(title_label)

            detail_label = QLabel(detail)
            detail_label.setStyleSheet(
                "font-size: 11px; color: %s; border: none;"
                % sc("text_secondary").name()
            )
            detail_label.setWordWrap(True)
            lo.addWidget(detail_label)

            self._layout.addWidget(card)

    def _make_context_card(
        self,
        title: str,
        detail: str,
        button_action: Optional[str],
        account_id: Optional[int],
    ) -> QFrame:
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: %s; border: 1px solid %s; }"
            % (sc("bg_note").name(), sc("border").name())
        )

        lo = QVBoxLayout(card)
        lo.setContentsMargins(8, 6, 8, 6)
        lo.setSpacing(3)

        title_label = QLabel(title)
        title_label.setStyleSheet(
            "font-size: 11px; font-weight: bold; color: %s; border: none;"
            % sc("heading").name()
        )
        lo.addWidget(title_label)

        detail_label = QLabel(detail)
        detail_label.setStyleSheet(
            "font-size: 11px; color: %s; border: none;" % sc("note_text").name()
        )
        detail_label.setWordWrap(True)
        lo.addWidget(detail_label)

        if button_action and button_action in _ACTION_LABELS:
            btn_row = QHBoxLayout()
            btn_row.setContentsMargins(0, 2, 0, 0)
            btn_row.addStretch()
            btn = QPushButton(_ACTION_LABELS[button_action])
            btn.setStyleSheet(
                "min-height: 0px; padding: 3px 10px; font-size: 11px;"
            )
            btn.clicked.connect(
                lambda checked=False, at=button_action, aid=account_id:
                self._emit_action(at, aid)
            )
            btn_row.addWidget(btn)
            lo.addLayout(btn_row)

        return card

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _emit_action(self, action_type: str, account_id: Optional[int]) -> None:
        if account_id is not None:
            self.action_requested.emit(action_type, account_id)

    def _clear_layout(self) -> None:
        """Remove all widgets and sub-layouts from _layout."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_sub_layout(item.layout())
            else:
                del item

    def _clear_sub_layout(self, layout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
            elif item.layout() is not None:
                self._clear_sub_layout(item.layout())
