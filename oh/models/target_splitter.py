"""
Domain models for Target Splitter — distribute sources across accounts.

Pure dataclasses with no I/O or logic beyond computed properties.
"""
from dataclasses import dataclass, field
from typing import Optional, List


@dataclass
class SplitAssignment:
    """One source -> one account mapping in a distribution plan."""
    source_name: str
    account_id: int
    username: str
    device_id: str
    device_name: str
    skipped: bool = False
    skip_reason: Optional[str] = None


@dataclass
class SplitPlan:
    """Complete distribution plan ready for operator review."""
    strategy: str                       # "even_split" | "fill_up"
    sources: List[str]
    target_account_ids: List[int]
    assignments: List[SplitAssignment]
    skipped_count: int = 0

    @property
    def effective_count(self) -> int:
        """Assignments that will actually be written (not skipped)."""
        return sum(1 for a in self.assignments if not a.skipped)


@dataclass
class SplitResult:
    """Outcome after executing a SplitPlan."""
    total_attempted: int = 0
    total_added: int = 0
    total_skipped: int = 0
    total_failed: int = 0
    errors: List[str] = field(default_factory=list)

    @property
    def fully_succeeded(self) -> bool:
        return self.total_failed == 0

    def summary_line(self) -> str:
        parts: List[str] = []
        if self.total_added:
            parts.append(f"{self.total_added} added")
        if self.total_skipped:
            parts.append(f"{self.total_skipped} already present")
        if self.total_failed:
            parts.append(f"{self.total_failed} failed")
        return " / ".join(parts) if parts else "No assignments to apply"
