"""
Domain models for Source Finder — profile discovery and scoring.

SourceSearchRecord  — one search run for one account.
SourceCandidate     — a candidate profile found during search.
SourceSearchResult  — a ranked top-10 result linking to a candidate.
"""
from dataclasses import dataclass
from typing import Optional


# Search status constants
SEARCH_RUNNING   = "running"
SEARCH_COMPLETED = "completed"
SEARCH_FAILED    = "failed"


@dataclass
class SourceSearchRecord:
    """One source-finder search run for one account."""
    account_id:    int
    username:      str
    started_at:    str
    status:        str             # SEARCH_RUNNING | SEARCH_COMPLETED | SEARCH_FAILED
    step_reached:  int   = 0
    completed_at:  Optional[str] = None
    query_used:    Optional[str] = None
    error_message: Optional[str] = None
    id:            Optional[int] = None


@dataclass
class SourceCandidate:
    """A candidate profile discovered during a source search."""
    search_id:       int
    username:        str
    full_name:       Optional[str]   = None
    follower_count:  int             = 0
    bio:             Optional[str]   = None
    source_type:     str             = "suggested"
    is_private:      bool            = False
    is_verified:     bool            = False
    is_enriched:     bool            = False
    avg_er:          Optional[float] = None
    ai_score:        Optional[float] = None
    ai_category:     Optional[str]   = None
    profile_pic_url: Optional[str]   = None
    id:              Optional[int]   = None


@dataclass
class SourceSearchResult:
    """A ranked result (top-10) linking a search to a candidate."""
    search_id:        int
    candidate_id:     int
    rank:             int
    added_to_sources: bool                       = False
    added_at:         Optional[str]              = None
    candidate:        Optional[SourceCandidate]  = None
    id:               Optional[int]              = None
