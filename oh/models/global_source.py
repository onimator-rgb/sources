"""
Domain models for the global Sources tab.

GlobalSourceRecord  — aggregated cross-account view of one source name.
SourceAccountDetail — one account's relationship to a specific source,
                      used in the detail pane when a source row is selected.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SourceAccountDetail:
    """Per-account details for a single source — shown in the detail pane."""
    account_id: int
    username: str
    device_id: str            # raw device folder name — used to locate source DB files
    device_name: str
    is_active: bool           # True = in sources.txt; False = historical only
    follow_count: int = 0
    followback_count: int = 0
    fbr_percent: Optional[float] = None
    is_quality: bool = False
    last_analyzed_at: Optional[str] = None


@dataclass
class GlobalSourceRecord:
    """
    Aggregated view of one source across all accounts.

    Assignment types:
      active_accounts     — accounts whose sources.txt currently lists this source
      historical_accounts — accounts where source appeared in data.db but is NOT
                            in sources.txt (was used in the past, now removed)

    FBR metrics are derived from each account's latest persisted snapshot:

      avg_fbr_pct      — arithmetic mean of fbr_percent across accounts that have
                         FBR data for this source.  Treats every account equally
                         regardless of follow volume.

      weighted_fbr_pct — total_followbacks / total_follows × 100 across all accounts.
                         High-volume accounts have proportionally more influence.

    Both are useful:
      avg_fbr_pct   → how consistently this source performs across accounts
      weighted_fbr_ → overall conversion rate when volume is considered
    """
    source_name: str
    active_accounts: int = 0
    historical_accounts: int = 0
    total_follows: int = 0
    total_followbacks: int = 0
    avg_fbr_pct: Optional[float] = None
    weighted_fbr_pct: Optional[float] = None
    quality_account_count: int = 0
    last_analyzed_at: Optional[str] = None

    @property
    def total_accounts(self) -> int:
        return self.active_accounts + self.historical_accounts

    @property
    def low_quality_account_count(self) -> int:
        return self.total_accounts - self.quality_account_count
