"""
Domain models for per-account source usage data.

USED count:
  COUNT(*) from {bot_root}/{device_id}/{username}/sources/{source_name}.db
  Table: source_followers(id, username, date_checked)
  Every row = one user processed (checked/filtered/acted on) by the bot.

USED %:
  Derived from the bot's .stm cache file:
    {bot_root}/{device_id}/{username}/.stm/{source_name}-total-followed-percent.txt

  That file stores: follows / total_source_followers * 100
  So: total_source_followers = follows / (percent / 100)
      used_pct               = used_count / total_source_followers * 100
                             = used_count * percent / follows   (equivalent)

  If the percent file is missing, malformed, or produces an inconsistent
  result, used_pct is left as None and the UI shows "—".
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceUsageRecord:
    """Usage data for one source, for one account."""
    source_name: str

    # --- USED count (from sources/{name}.db) ---
    used_count: int = 0
    db_found: bool = False          # True if source .db file exists on disk
    db_error: Optional[str] = None  # non-None if DB exists but could not be read

    # --- USED % (derived from .stm percent file + follows) ---
    used_pct: Optional[float] = None              # used_count / total * 100
    total_followers_derived: Optional[int] = None # round(follows / (percent/100))
    pct_file_found: bool = False                  # .stm percent file existed
    pct_file_error: Optional[str] = None          # set if file found but parse failed

    @property
    def has_data(self) -> bool:
        """True when the source DB was found and read successfully."""
        return self.db_found and self.db_error is None


@dataclass
class SourceUsageResult:
    """All source usage records for one account."""
    account_username: str
    device_id: str
    records: list[SourceUsageRecord] = field(default_factory=list)
    sources_dir_found: bool = False
    db_count_found: int = 0     # source DBs successfully read
    db_count_missing: int = 0   # source DBs not found or errored
    pct_count_derived: int = 0  # sources with valid used_pct

    def as_map(self) -> dict[str, SourceUsageRecord]:
        """Return {normalized_source_name: record} for O(1) lookup."""
        return {r.source_name.strip().lower(): r for r in self.records}
