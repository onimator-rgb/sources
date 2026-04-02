"""
Domain models for source profile metadata and FBR statistics.
"""
from dataclasses import dataclass
from typing import Optional


@dataclass
class SourceProfile:
    source_name:      str
    niche_category:   Optional[str] = None
    niche_confidence: Optional[float] = None
    language:         Optional[str] = None
    location:         Optional[str] = None
    follower_count:   Optional[int] = None
    bio:              Optional[str] = None
    avg_er:           Optional[float] = None
    is_active_source: int = 1
    first_seen_at:    Optional[str] = None
    updated_at:       Optional[str] = None
    profile_json:     Optional[str] = None
    id:               Optional[int] = None


@dataclass
class SourceFBRStats:
    source_name:           str
    total_accounts_used:   int = 0
    total_follows:         int = 0
    total_followbacks:     int = 0
    avg_fbr_pct:           float = 0.0
    weighted_fbr_pct:      float = 0.0
    quality_account_count: int = 0
    last_analyzed_at:      Optional[str] = None
    updated_at:            Optional[str] = None
    id:                    Optional[int] = None
