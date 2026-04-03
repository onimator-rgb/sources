"""
Domain model for block/ban detection events.

BlockEvent — one detected Instagram restriction on an account.
BlockSignal — an in-memory detection result (not persisted directly).
"""
from dataclasses import dataclass, field
from typing import Optional, Dict


# Event type constants
BLOCK_ACTION_BLOCK = "action_block"
BLOCK_CHALLENGE    = "challenge"
BLOCK_SHADOW_BAN   = "shadow_ban"
BLOCK_TEMP_BAN     = "temp_ban"
BLOCK_RATE_LIMIT   = "rate_limit"

# Severity mapping
BLOCK_SEVERITY = {
    BLOCK_ACTION_BLOCK: "CRITICAL",
    BLOCK_CHALLENGE:    "CRITICAL",
    BLOCK_SHADOW_BAN:   "HIGH",
    BLOCK_TEMP_BAN:     "HIGH",
    BLOCK_RATE_LIMIT:   "MEDIUM",
}

# Human-readable labels
BLOCK_LABELS = {
    BLOCK_ACTION_BLOCK: "Action Block",
    BLOCK_CHALLENGE:    "Challenge Required",
    BLOCK_SHADOW_BAN:   "Shadow Ban",
    BLOCK_TEMP_BAN:     "Temporary Ban",
    BLOCK_RATE_LIMIT:   "Rate Limited",
}


@dataclass
class BlockEvent:
    """One row in the block_events table."""
    account_id:   int
    event_type:   str                # BLOCK_* constant
    detected_at:  str
    evidence:     Optional[str] = None   # JSON
    resolved_at:  Optional[str] = None
    auto_detected: bool = True
    id:           Optional[int] = None

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None

    @property
    def severity(self) -> str:
        return BLOCK_SEVERITY.get(self.event_type, "MEDIUM")

    @property
    def label(self) -> str:
        return BLOCK_LABELS.get(self.event_type, self.event_type)


@dataclass
class BlockSignal:
    """In-memory detection result from BlockDetector (not persisted)."""
    event_type:  str          # BLOCK_* constant
    confidence:  float        # 0.0 - 1.0
    evidence:    Dict = field(default_factory=dict)


@dataclass
class BlockScanResult:
    """Aggregated result of scanning all accounts for blocks."""
    total_scanned: int = 0
    new_blocks:    int = 0
    resolved:      int = 0
    still_active:  int = 0
    errors:        int = 0
