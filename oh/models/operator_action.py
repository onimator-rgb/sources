"""
Domain model for operator action audit trail.

Each row in operator_actions records one operator-initiated change
to an account's review flag or tags.  The audit trail is append-only;
rows are never updated or deleted.
"""
from dataclasses import dataclass
from typing import Optional


# Action type constants
ACTION_SET_REVIEW       = "set_review"
ACTION_CLEAR_REVIEW     = "clear_review"
ACTION_ADD_TAG          = "add_tag"
ACTION_REMOVE_TAG       = "remove_tag"
ACTION_INCREMENT_TB     = "increment_tb"
ACTION_INCREMENT_LIMITS = "increment_limits"


@dataclass
class OperatorActionRecord:
    """One row in the operator_actions table."""
    account_id:   int
    username:     str
    device_id:    str
    action_type:  str               # ACTION_* constant
    old_value:    Optional[str] = None
    new_value:    Optional[str] = None
    note:         Optional[str] = None
    performed_at: Optional[str] = None
    machine:      Optional[str] = None
    id:           Optional[int] = None
