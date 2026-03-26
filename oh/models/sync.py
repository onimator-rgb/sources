"""Domain models for sync runs and events."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SyncRun:
    started_at: str
    triggered_by: str = "manual"
    status: str = "running"
    id: Optional[int] = None
    completed_at: Optional[str] = None
    devices_scanned: int = 0
    accounts_scanned: int = 0
    accounts_added: int = 0
    accounts_removed: int = 0
    accounts_updated: int = 0
    accounts_unchanged: int = 0
    error_message: Optional[str] = None


@dataclass
class SyncEvent:
    sync_run_id: int
    event_type: str     # 'added' | 'removed' | 'metadata_changed'
    device_id: str
    username: str
    created_at: str
    id: Optional[int] = None
    account_id: Optional[int] = None
    changed_fields: Optional[str] = None   # JSON string, only for 'metadata_changed'


@dataclass
class SyncSummary:
    """Mutable accumulator used during a sync run, then written to sync_runs."""
    devices_scanned: int = 0
    accounts_scanned: int = 0
    accounts_added: int = 0
    accounts_removed: int = 0
    accounts_updated: int = 0
    accounts_unchanged: int = 0
