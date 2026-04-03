"""
Domain models for account grouping / campaigns.

AccountGroup      — a named group with color label.
GroupMembership   — links an account to a group.
GroupSummary      — aggregated metrics for a group (in-memory).
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class AccountGroup:
    """One row in the account_groups table."""
    name:         str
    color:        str = "#5B8DEF"
    description:  Optional[str] = None
    created_at:   Optional[str] = None
    updated_at:   Optional[str] = None
    member_count: int = 0          # computed, not stored
    id:           Optional[int] = None


@dataclass
class GroupMembership:
    """One row in the account_group_members table."""
    group_id:   int
    account_id: int
    added_at:   str
    id:         Optional[int] = None


@dataclass
class GroupSummary:
    """Aggregated group metrics (in-memory, not persisted)."""
    group:              AccountGroup
    total_accounts:     int = 0
    active_accounts:    int = 0
    avg_health:         float = 0.0
    avg_fbr:            float = 0.0
    total_follows_today: int = 0
    blocked_count:      int = 0
    review_count:       int = 0
