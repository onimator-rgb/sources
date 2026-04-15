"""
Domain models for LBR (Like-Back Ratio) analytics.

LBR is computed per source for a single account:
    lbr_percent = (followback_count / like_count) * 100

A source is "quality" when it meets both configurable thresholds:
    like_count    >= min_likes    (default 50)
    lbr_percent   >= min_lbr_pct  (default 5.0)
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceLBRRecord:
    source_name: str
    like_count: int
    followback_count: int
    lbr_percent: float          # capped at 100 for display; raw value may exceed due to data anomaly
    is_quality: bool            # True when both thresholds are met
    anomaly: Optional[str]      # None | "followback_exceeds_likes" | "lbr_over_100"


@dataclass
class LBRAnalysisResult:
    device_id: str
    username: str

    records: list[SourceLBRRecord] = field(default_factory=list)

    # Schema / connectivity state
    schema_valid: bool = True
    schema_error: Optional[str] = None   # human-readable if schema_valid is False

    # Thresholds that produced this result (stored for display)
    min_likes: int = 50
    min_lbr_pct: float = 5.0

    # Non-fatal warnings (anomalies, lock warnings, etc.)
    warnings: list[str] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Summary helpers
    # ------------------------------------------------------------------

    @property
    def has_data(self) -> bool:
        return bool(self.records)

    @property
    def quality_count(self) -> int:
        return sum(1 for r in self.records if r.is_quality)

    @property
    def total_count(self) -> int:
        return len(self.records)

    @property
    def below_volume_count(self) -> int:
        """Sources with fewer likes than the minimum threshold."""
        return sum(1 for r in self.records if r.like_count < self.min_likes)

    @property
    def anomaly_count(self) -> int:
        return sum(1 for r in self.records if r.anomaly is not None)

    @property
    def best_source_by_lbr(self) -> Optional[SourceLBRRecord]:
        """
        Highest LBR% among sources that meet the minimum like threshold.
        Returns None if no source meets the volume floor.
        """
        qualifying = [r for r in self.records if r.like_count >= self.min_likes]
        return max(qualifying, key=lambda r: r.lbr_percent, default=None)

    @property
    def highest_volume_source(self) -> Optional[SourceLBRRecord]:
        """Source with the most total likes."""
        return max(self.records, key=lambda r: r.like_count, default=None)
