"""Domain model for campaign templates."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class CampaignTemplate:
    name:           str
    niche:          Optional[str] = None
    description:    Optional[str] = None
    language:       str = "pl"
    min_sources:    int = 10
    source_niche:   Optional[str] = None
    follow_limit:   int = 200
    like_limit:     int = 100
    tb_level:       int = 1
    limits_level:   int = 1
    settings_json:  Optional[str] = None
    created_at:     Optional[str] = None
    updated_at:     Optional[str] = None
    id:             Optional[int] = None
