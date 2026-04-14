"""
Domain models for the Settings Copier feature.

Pure dataclasses — no I/O, no logic.
COPYABLE_SETTINGS is the allowlist of keys safe to copy between accounts.
"""
from dataclasses import dataclass, field
from typing import List, Optional


# Keys in settings.db -> accountsettings.settings JSON that are safe to copy.
# Dict maps internal key name -> human-readable display name.
COPYABLE_SETTINGS = {
    "default_action_limit_perday": "Follow limit / day",
    "like_limit_perday": "Like limit / day",
    "unfollow_limit_perday": "Unfollow limit / day",
    "start_time": "Working hours — start",
    "end_time": "Working hours — end",
    "follow_enabled": "Follow enabled",
    "unfollow_enabled": "Unfollow enabled",
    "like_enabled": "Like enabled",
    "dm_enabled": "DM enabled",
    "dm_limit_perday": "DM limit / day",
    "enable_auto_increment_follow_limit_perday": "Auto-increment follow enabled",
    "enable_auto_increment_like_limit_perday": "Auto-increment like enabled",
    "auto_increment_action_limit_by": "Follow daily increase",
    "auto_increment_like_limit_perday_increase": "Like daily increase",
    "auto_increment_like_limit_perday_increase_limit": "Like auto-increment cap",
    "max_increment_action_limit": "Follow auto-increment cap",
    "enable_follow_joborders": "Follow action enabled",
    "enable_likepost": "Like action enabled",
}


@dataclass
class SettingsSnapshot:
    """All copyable settings for one account, read from settings.db."""
    account_id: int
    username: str
    device_id: str
    device_name: Optional[str]
    values: dict  # key -> value (from COPYABLE_SETTINGS keys)
    raw_json: Optional[dict] = None  # full JSON blob (for reference, never written)
    error: Optional[str] = None


@dataclass
class SettingsDiffEntry:
    """One setting key comparison: source value vs. target value."""
    key: str
    display_name: str
    source_value: object
    target_value: object
    is_different: bool  # True if source != target


@dataclass
class SettingsDiff:
    """Full diff for one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    entries: List[SettingsDiffEntry]
    different_count: int = 0  # how many entries have is_different=True


@dataclass
class SettingsCopyResult:
    """Result of copying settings to one target account."""
    target_account_id: int
    target_username: str
    target_device_name: Optional[str]
    success: bool
    backed_up: bool
    keys_written: List[str]
    error: Optional[str] = None


@dataclass
class SettingsCopyBatchResult:
    """Aggregate result for the entire copy operation."""
    source_username: str
    total_targets: int
    success_count: int
    fail_count: int
    results: List[SettingsCopyResult]
