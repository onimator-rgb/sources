"""
Domain models for FBR (Follow-Back Ratio) analytics.

FBR is computed per source for a single account:
    fbr_percent = (followback_count / follow_count) * 100

A source is "quality" when it meets both configurable thresholds:
    follow_count  >= min_follows   (default 100)
    fbr_percent   >= min_fbr_pct   (default 10.0)
"""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SourceFBRRecord:
    source_name: str
    follow_count: int
    followback_count: int
    fbr_percent: float          # capped at 100 for display; raw value may exceed due to data anomaly
    is_quality: bool            # True when both thresholds are met
    anomaly: Optional[str]      # None | "followback_exceeds_follows" | "fbr_over_100"


@dataclass
class FBRAnalysisResult:
    device_id: str
    username: str

    records: list[SourceFBRRecord] = field(default_factory=list)

    # Schema / connectivity state
    schema_valid: bool = True
    schema_error: Optional[str] = None   # human-readable if schema_valid is False

    # Thresholds that produced this result (stored for display)
    min_follows: int = 100
    min_fbr_pct: float = 10.0

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
        """Sources with fewer follows than the minimum threshold."""
        return sum(1 for r in self.records if r.follow_count < self.min_follows)

    @property
    def anomaly_count(self) -> int:
        return sum(1 for r in self.records if r.anomaly is not None)

    @property
    def best_source_by_fbr(self) -> Optional[SourceFBRRecord]:
        """
        Highest FBR% among sources that meet the minimum follow threshold.
        Returns None if no source meets the volume floor.
        """
        qualifying = [r for r in self.records if r.follow_count >= self.min_follows]
        return max(qualifying, key=lambda r: r.fbr_percent, default=None)

    @property
    def highest_volume_source(self) -> Optional[SourceFBRRecord]:
        """Source with the most total follows."""
        return max(self.records, key=lambda r: r.follow_count, default=None)
