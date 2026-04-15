"""
Domain models for persisted LBR snapshot data.

LBRSnapshotRecord  — one row in lbr_snapshots: per-account summary of one
                     analysis run.  Pre-aggregated for fast main-table reads.
BatchLBRResult     — in-memory result returned by a batch analysis run;
                     not persisted (the individual snapshots are).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Optional


# Snapshot status values
SNAPSHOT_OK    = "ok"     # schema valid, sources found and aggregated
SNAPSHOT_EMPTY = "empty"  # schema valid, likes.db had no qualifying source rows
SNAPSHOT_ERROR = "error"  # schema invalid or file unreadable


@dataclass
class LBRSnapshotRecord:
    """
    One LBR analysis run for one account.
    Matches the lbr_snapshots table schema.
    """
    account_id:         int
    device_id:          str
    username:           str
    analyzed_at:        str
    min_likes:          int
    min_lbr_pct:        float
    total_sources:      int
    quality_sources:    int
    status:             str                 # SNAPSHOT_OK | SNAPSHOT_EMPTY | SNAPSHOT_ERROR

    best_lbr_pct:       Optional[float] = None
    best_lbr_source:    Optional[str]   = None
    highest_vol_source: Optional[str]   = None
    highest_vol_count:  Optional[int]   = None
    below_volume_count: int             = 0
    anomaly_count:      int             = 0
    warnings_json:      Optional[str]   = None  # JSON array
    schema_error:       Optional[str]   = None
    id:                 Optional[int]   = None

    @property
    def warnings(self) -> list[str]:
        return json.loads(self.warnings_json) if self.warnings_json else []

    @property
    def has_quality_data(self) -> bool:
        return self.status == SNAPSHOT_OK and self.total_sources > 0


@dataclass
class BatchLBRResult:
    """
    Aggregated outcome of an Analyze All LBR run.
    Returned to the UI; not persisted (individual snapshots carry the data).
    """
    total_accounts: int = 0
    analyzed:       int = 0   # schema valid, analysis completed (ok or empty)
    skipped:        int = 0   # account had likes_db_exists=False — not attempted
    errors:         int = 0   # schema error or unexpected exception
    snapshots:      list[LBRSnapshotRecord] = field(default_factory=list)

    def status_line(self) -> str:
        parts = [f"✓ {self.analyzed} analyzed"]
        if self.skipped:
            parts.append(f"↷ {self.skipped} skipped")
        if self.errors:
            parts.append(f"✗ {self.errors} failed")
        return "  ·  ".join(parts) + f"  (of {self.total_accounts} active accounts)"
