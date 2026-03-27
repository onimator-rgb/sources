"""
Domain models for source inspection results.

A "source" is an Instagram account name used as a follow/unfollow source
by the Onimator bot.  Each source can appear in two places:
  - sources.txt  → currently active (the bot is using it right now)
  - data.db      → historically used (any row exists for it in the sources table)

Classification:
  active_with_activity  — in sources.txt AND in data.db
  active_no_activity    — in sources.txt but NOT yet in data.db (just added)
  historical_only       — NOT in sources.txt but present in data.db (was removed)
"""
from dataclasses import dataclass, field
from typing import Optional

STATUS_ACTIVE_WITH_ACTIVITY = "active_with_activity"
STATUS_ACTIVE_NO_ACTIVITY   = "active_no_activity"
STATUS_HISTORICAL_ONLY      = "historical_only"

_STATUS_LABELS = {
    STATUS_ACTIVE_WITH_ACTIVITY: "Active + history",
    STATUS_ACTIVE_NO_ACTIVITY:   "Active (new)",
    STATUS_HISTORICAL_ONLY:      "Historical",
}


@dataclass
class SourceRecord:
    source_name: str
    is_active: bool      # present in sources.txt
    is_historical: bool  # present in data.db

    @property
    def status(self) -> str:
        if self.is_active and self.is_historical:
            return STATUS_ACTIVE_WITH_ACTIVITY
        if self.is_active:
            return STATUS_ACTIVE_NO_ACTIVITY
        return STATUS_HISTORICAL_ONLY

    @property
    def status_label(self) -> str:
        return _STATUS_LABELS[self.status]


@dataclass
class SourceInspectionResult:
    device_id: str
    username: str
    sources: list[SourceRecord] = field(default_factory=list)

    # Which files were found (controls empty-state messaging)
    sources_txt_found: bool = False
    data_db_found: bool = False

    # Non-fatal warnings (e.g., one file unreadable while the other succeeded)
    warnings: list[str] = field(default_factory=list)

    @property
    def active_count(self) -> int:
        return sum(1 for s in self.sources if s.is_active)

    @property
    def historical_count(self) -> int:
        return sum(1 for s in self.sources if s.is_historical)

    @property
    def total_count(self) -> int:
        return len(self.sources)

    @property
    def has_data(self) -> bool:
        return bool(self.sources)
