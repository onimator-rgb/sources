"""
Domain models for session snapshot data and account tags.

AccountSessionRecord — one row in session_snapshots: daily counters for one
                       account (follows, likes, DMs, unfollows) collected
                       during a scan.  One record per (account, date).

AccountTag           — one row in account_tags: a single parsed tag for an
                       account, originating from the bot's settings.db or
                       set manually by an operator in OH.

SessionCollectionResult — in-memory result returned after collecting session
                          data for all active accounts; not persisted (the
                          individual snapshots carry the data).
"""
from dataclasses import dataclass, field
from typing import Optional


# ---------------------------------------------------------------------------
# Slot constants (matching Onimator's 6-hour time windows)
# ---------------------------------------------------------------------------

SLOT_00_06 = "00-06"
SLOT_06_12 = "06-12"
SLOT_12_18 = "12-18"
SLOT_18_24 = "18-24"

ALL_SLOTS = (SLOT_00_06, SLOT_06_12, SLOT_12_18, SLOT_18_24)

# Tag sources
TAG_SOURCE_BOT      = "bot"
TAG_SOURCE_OPERATOR  = "operator"

# Tag categories
TAG_CAT_LIMITS = "limits"
TAG_CAT_TB     = "TB"
TAG_CAT_ROLE   = "role"
TAG_CAT_STATUS = "status"
TAG_CAT_CUSTOM = "custom"


def slot_for_times(start_time: Optional[str], end_time: Optional[str]) -> str:
    """
    Map an account's start_time/end_time to a slot constant.

    Onimator stores start/end as hour strings: "0", "6", "12", "18".
    Accounts with start=0 end=0 are treated as unscheduled → first slot.
    """
    try:
        start = int(start_time or 0)
    except (ValueError, TypeError):
        start = 0

    if start < 6:
        return SLOT_00_06
    elif start < 12:
        return SLOT_06_12
    elif start < 18:
        return SLOT_12_18
    else:
        return SLOT_18_24


# ---------------------------------------------------------------------------
# Session snapshot
# ---------------------------------------------------------------------------

@dataclass
class AccountSessionRecord:
    """
    Daily session counters for one account.
    Matches the session_snapshots table schema.
    """
    account_id:     int
    device_id:      str
    username:       str
    snapshot_date:  str             # "YYYY-MM-DD"
    slot:           str             # one of ALL_SLOTS

    follow_count:   int = 0
    like_count:     int = 0
    dm_count:       int = 0
    unfollow_count: int = 0
    follow_limit:   Optional[int] = None
    like_limit:     Optional[int] = None
    has_activity:   bool = False
    collected_at:   Optional[str] = None
    id:             Optional[int] = None

    @property
    def total_actions(self) -> int:
        return self.follow_count + self.like_count + self.dm_count


# ---------------------------------------------------------------------------
# Account tag
# ---------------------------------------------------------------------------

@dataclass
class AccountTag:
    """
    A single parsed tag for an account.
    Matches the account_tags table schema.
    """
    account_id:   int
    tag_source:   str               # TAG_SOURCE_BOT | TAG_SOURCE_OPERATOR
    tag_category: str               # TAG_CAT_*
    tag_value:    str               # e.g. "limits 4", "TB3", "SLAVE"
    tag_level:    Optional[int] = None
    updated_at:   Optional[str] = None
    id:           Optional[int] = None


# ---------------------------------------------------------------------------
# Collection result (in-memory, not persisted)
# ---------------------------------------------------------------------------

@dataclass
class SessionCollectionResult:
    """
    Aggregated outcome of a session-data collection run.
    Returned to the UI; not persisted (individual snapshots carry the data).
    """
    total:     int = 0              # active accounts attempted
    collected: int = 0              # snapshots successfully written
    skipped:   int = 0              # accounts with no data_db / sources_txt
    failed:    int = 0              # unexpected errors during read
    errors:    list[str] = field(default_factory=list)

    def status_line(self) -> str:
        parts = [f"✓ {self.collected} collected"]
        if self.skipped:
            parts.append(f"↷ {self.skipped} skipped")
        if self.failed:
            parts.append(f"✗ {self.failed} failed")
        return "  ·  ".join(parts) + f"  (of {self.total} active accounts)"
