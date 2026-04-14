"""
License data models for OH offline license system.
"""
import enum
from dataclasses import dataclass
from typing import List, Optional


class LicenseStatus(enum.Enum):
    """Possible states of a license check."""
    VALID = "valid"
    EXPIRED = "expired"
    INVALID_HWID = "invalid_hwid"
    INVALID_SIGNATURE = "invalid_signature"
    MISSING = "missing"
    GRACE_PERIOD = "grace_period"
    CORRUPT = "corrupt"


@dataclass
class LicenseInfo:
    """Parsed license data."""
    client: str
    hwid: str
    issued: str
    expires: str
    features: List[str]
    status: LicenseStatus
    days_remaining: int
    signature_valid: bool
    hwid_match: bool
    raw_payload: Optional[str] = None
