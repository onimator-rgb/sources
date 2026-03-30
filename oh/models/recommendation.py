"""
Domain model for operational recommendations.

Recommendations are generated on demand from current data — they are
never persisted.  Each Recommendation describes one actionable finding
with a severity, target, reason, and suggested operator action.
"""
from dataclasses import dataclass
from typing import Optional


# Recommendation type constants
REC_LOW_FBR_SOURCE   = "LOW_FBR_SOURCE"
REC_SOURCE_EXHAUSTION = "SOURCE_EXHAUSTION"
REC_LOW_LIKE         = "LOW_LIKE"
REC_LIMITS_MAX       = "LIMITS_MAX"
REC_TB_MAX           = "TB_MAX"
REC_ZERO_ACTION      = "ZERO_ACTION"

# Severity constants (reused from session report pattern)
SEV_CRITICAL = "CRITICAL"
SEV_HIGH     = "HIGH"
SEV_MEDIUM   = "MEDIUM"
SEV_LOW      = "LOW"

# Sort rank: lower = more urgent
SEV_RANK = {
    SEV_CRITICAL: 0,
    SEV_HIGH: 1,
    SEV_MEDIUM: 2,
    SEV_LOW: 3,
}

# Target types
TARGET_SOURCE  = "source"
TARGET_ACCOUNT = "account"
TARGET_DEVICE  = "device"

# Human-readable type labels
REC_TYPE_LABELS = {
    REC_LOW_FBR_SOURCE:   "Weak Source",
    REC_SOURCE_EXHAUSTION: "Source Refresh",
    REC_LOW_LIKE:         "Low Like",
    REC_LIMITS_MAX:       "Limits Max",
    REC_TB_MAX:           "TB Max",
    REC_ZERO_ACTION:      "Zero Actions",
}


@dataclass
class Recommendation:
    """One actionable recommendation for the operator."""
    rec_type:         str           # REC_* constant
    severity:         str           # SEV_* constant
    target_type:      str           # TARGET_* constant
    target_id:        str           # source_name | username | device_id
    target_label:     str           # display name
    reason:           str           # one-line explanation
    suggested_action: str           # what operator should do
    account_id:       Optional[int] = None   # for account-level recs
    metadata:         Optional[dict] = None  # extra data for UI

    @property
    def sort_key(self):
        """Sort by severity rank, then type, then target label."""
        return (SEV_RANK.get(self.severity, 9), self.rec_type, self.target_label)
