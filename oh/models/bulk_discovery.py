"""
Domain models for Bulk Source Discovery.

BulkDiscoveryRun  — one bulk discovery operation across multiple accounts.
BulkDiscoveryItem — one account processed within a bulk run.
"""
from dataclasses import dataclass, field
from typing import List, Optional


# Run status constants
BULK_RUNNING   = "running"
BULK_COMPLETED = "completed"
BULK_FAILED    = "failed"
BULK_CANCELLED = "cancelled"

# Item status constants
ITEM_QUEUED  = "queued"
ITEM_RUNNING = "running"
ITEM_DONE    = "done"
ITEM_FAILED  = "failed"
ITEM_SKIPPED = "skipped"


@dataclass
class BulkDiscoveryItem:
    """One account processed within a bulk discovery run."""
    run_id:                int
    account_id:            int
    username:              str
    device_id:             str
    status:                str = ITEM_QUEUED
    search_id:             Optional[int] = None
    sources_before:        int = 0
    sources_added:         int = 0
    sources_after:         int = 0
    added_sources_json:    Optional[str] = None
    original_sources_json: Optional[str] = None
    error_message:         Optional[str] = None
    id:                    Optional[int] = None


@dataclass
class BulkDiscoveryRun:
    """Header record for one bulk discovery operation."""
    started_at:      str
    status:          str
    min_threshold:   int
    auto_add_top_n:  int
    total_accounts:  int = 0
    accounts_done:   int = 0
    accounts_failed: int = 0
    total_added:     int = 0
    completed_at:    Optional[str] = None
    machine:         Optional[str] = None
    error_message:   Optional[str] = None
    reverted_at:     Optional[str] = None
    revert_status:   Optional[str] = None
    items:           Optional[List[BulkDiscoveryItem]] = None
    id:              Optional[int] = None
