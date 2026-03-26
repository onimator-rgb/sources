"""
Domain models for devices and accounts.

AccountRecord    — a persisted account in the OH registry.
DeviceRecord     — a persisted device in the OH registry.
DiscoveredAccount — raw result from a single discovery scan (not yet persisted).
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeviceRecord:
    device_id: str
    device_name: str
    last_known_status: Optional[str]
    first_discovered_at: str
    last_synced_at: str
    is_active: bool
    id: Optional[int] = None


@dataclass
class AccountRecord:
    device_id: str
    username: str
    discovered_at: str
    last_seen_at: str
    data_db_exists: bool
    sources_txt_exists: bool
    id: Optional[int] = None
    device_name: Optional[str] = None          # populated via JOIN with oh_devices
    removed_at: Optional[str] = None
    removal_sync_run_id: Optional[int] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    follow_enabled: Optional[bool] = None
    unfollow_enabled: Optional[bool] = None
    limit_per_day: Optional[str] = None
    last_metadata_updated_at: Optional[str] = None

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def account_folder(self, bot_root: str) -> str:
        """Resolve the full path to this account's Onimator folder."""
        from pathlib import Path
        return str(Path(bot_root) / self.device_id / self.username)


@dataclass
class DiscoveredAccount:
    """
    Raw result from the DiscoveryModule for a single account.
    Not persisted directly — passed to SyncModule for comparison and writing.
    """
    device_id: str
    device_name: str
    device_status: str
    username: str
    folder_exists: bool
    data_db_exists: bool
    sources_txt_exists: bool
    follow_enabled: bool = False
    unfollow_enabled: bool = False
    limit_per_day: Optional[str] = None
    start_time: Optional[str] = None
    end_time: Optional[str] = None
    # Validity flags
    is_orphan_folder: bool = False      # folder exists on disk but not in accounts.db
    is_missing_folder: bool = False     # in accounts.db but no folder on disk
