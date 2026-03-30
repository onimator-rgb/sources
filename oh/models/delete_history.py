"""
Domain models for source deletion history.

Two-table design:
  DeleteAction — one row per delete operation (the header)
  DeleteItem   — one row per source deleted within an action

For single deletes:  1 action + 1 item
For bulk deletes:    1 action + N items

This grouping makes it easy to query "what happened in this run?" while
still being able to search for a specific source across all history.
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class DeleteItem:
    """One source deleted within a single delete action."""
    source_name: str
    affected_accounts: list[str]   # usernames that were modified
    files_removed: int = 0         # file successfully rewritten
    files_not_found: int = 0       # source was already absent
    files_failed: int = 0          # write error
    errors: list[str] = field(default_factory=list)
    affected_details: list[dict] = field(default_factory=list)  # [{account_id, device_id, username, device_name}]
    id: Optional[int] = None
    action_id: Optional[int] = None


@dataclass
class DeleteAction:
    """Header record for one delete operation (single or bulk)."""
    deleted_at: str
    delete_type: str              # 'single' | 'bulk' | 'revert'
    scope: str                    # 'global' | 'account'
    total_sources: int = 0
    total_accounts_affected: int = 0
    threshold_pct: Optional[float] = None   # bulk only
    machine: Optional[str] = None
    notes: Optional[str] = None
    status: str = "completed"                              # 'completed' | 'reverted'
    reverted_at: Optional[str] = None
    revert_of_action_id: Optional[int] = None
    id: Optional[int] = None
    items: list[DeleteItem] = field(default_factory=list)


@dataclass
class SourceDeleteResult:
    """
    Returned to the UI after a delete operation completes.
    Summarises across all sources and accounts attempted.
    """
    sources_attempted: list[str]
    accounts_attempted: int = 0
    accounts_removed: int = 0     # sources.txt was rewritten
    accounts_not_found: int = 0   # source was already absent
    accounts_failed: int = 0      # write error
    action_id: Optional[int] = None
    errors: list[str] = field(default_factory=list)

    @property
    def fully_succeeded(self) -> bool:
        return self.accounts_failed == 0

    def summary_line(self, is_revert: bool = False) -> str:
        parts = []
        if is_revert:
            if self.accounts_removed:
                parts.append(f"✓ {self.accounts_removed} restored")
            if self.accounts_not_found:
                parts.append(f"↷ {self.accounts_not_found} already present")
        else:
            if self.accounts_removed:
                parts.append(f"✓ {self.accounts_removed} removed")
            if self.accounts_not_found:
                parts.append(f"↷ {self.accounts_not_found} already absent")
        if self.accounts_failed:
            parts.append(f"✗ {self.accounts_failed} failed")
        n = len(self.sources_attempted)
        label = f"{n} source{'s' if n != 1 else ''}"
        return (label + " — " + "  ·  ".join(parts)) if parts else f"{label} — no active assignments found"
