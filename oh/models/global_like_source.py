"""
Domain models for the global Like Sources tab.

GlobalLikeSourceRecord  — aggregated cross-account view of one like source name.
LikeSourceAccountDetail — one account's relationship to a specific like source,
                          used in the detail pane when a source row is selected.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class LikeSourceAccountDetail:
    """Per-account details for a single like source — shown in the detail pane."""
    account_id: int
    username: str
    device_id: str            # raw device folder name — used to locate source DB files
    device_name: str
    is_active: bool           # True = in like-source-followers.txt; False = historical only
    like_count: int = 0
    followback_count: int = 0
    lbr_percent: Optional[float] = None
    is_quality: bool = False
    last_analyzed_at: Optional[str] = None


@dataclass
class GlobalLikeSourceRecord:
    """
    Aggregated view of one like source across all accounts.

    Assignment types:
      active_accounts     — accounts whose like-source-followers.txt currently
                            lists this source
      historical_accounts — accounts where source appeared in likes.db but is NOT
                            in like-source-followers.txt (was used in the past,
                            now removed)

    LBR metrics are derived from each account's latest persisted snapshot:

      avg_lbr_pct      — arithmetic mean of lbr_percent across accounts that have
                         LBR data for this source.  Treats every account equally
                         regardless of like volume.

      weighted_lbr_pct — total_followbacks / total_likes x 100 across all accounts.
                         High-volume accounts have proportionally more influence.

    Both are useful:
      avg_lbr_pct      → how consistently this source performs across accounts
      weighted_lbr_pct → overall conversion rate when volume is considered
    """
    source_name: str
    active_accounts: int = 0
    historical_accounts: int = 0
    total_likes: int = 0
    total_followbacks: int = 0
    avg_lbr_pct: Optional[float] = None
    weighted_lbr_pct: Optional[float] = None
    quality_account_count: int = 0
    last_analyzed_at: Optional[str] = None

    @property
    def total_accounts(self) -> int:
        return self.active_accounts + self.historical_accounts

    @property
    def low_quality_account_count(self) -> int:
        return self.total_accounts - self.quality_account_count
