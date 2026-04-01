"""
Domain models for the Account Detail View.

AccountAlert       — one auto-generated alert for an account (not persisted).
AccountDetailData  — aggregated data bundle for rendering the detail drawer.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from oh.models.account import AccountRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.operator_action import OperatorActionRecord
from oh.models.session import AccountSessionRecord


@dataclass
class AccountAlert:
    """
    One auto-generated alert for an account.

    Alerts are computed on demand (never persisted).  Each alert describes
    a condition the operator should inspect, ranked by severity.
    """
    severity: str                          # CRITICAL / HIGH / MEDIUM / LOW
    title: str                             # short one-line description
    detail: str                            # longer explanation
    recommended_action: str                # what the operator should do
    action_type: Optional[str] = None      # links to inline action button
                                           # e.g. "tb_plus_1", "clear_review"


@dataclass
class AccountDetailData:
    """
    All data needed to render the Summary + Alerts tabs of the
    Account Detail drawer.

    Assembled by AccountDetailService.get_summary_data() from maps
    that MainWindow already holds in memory — no extra DB queries.
    """
    account: AccountRecord

    # Session (today)
    session: Optional[AccountSessionRecord] = None

    # FBR (latest snapshot)
    fbr_snapshot: Optional[FBRSnapshotRecord] = None

    # Source count (active sources for this account)
    source_count: int = 0

    # Tags — raw concatenated strings for display
    bot_tags: str = ""
    operator_tags: str = ""

    # Device status (e.g. "running", "stop", "offline")
    device_status: Optional[str] = None

    # Review history (operator set_review / clear_review actions)
    review_actions: List[OperatorActionRecord] = field(default_factory=list)

    # Auto-generated alerts (populated by compute_alerts)
    alerts: List[AccountAlert] = field(default_factory=list)
