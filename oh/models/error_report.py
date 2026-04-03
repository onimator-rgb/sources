"""
Domain model for remote error reports.

Each ErrorReport captures a crash or user-reported issue with enough
technical context to diagnose remotely — without any client data
(account names, device names, etc.).
"""
from dataclasses import dataclass
from typing import Optional


# Error type constants
ERROR_TYPE_CRASH        = "crash"
ERROR_TYPE_MANUAL       = "manual"
ERROR_TYPE_STARTUP_FAIL = "startup_fail"


@dataclass
class ErrorReport:
    """One row in the error_reports table."""
    report_id:      str                # uuid4
    error_type:     str                # ERROR_TYPE_* constant
    oh_version:     str
    os_version:     str
    python_version: str
    created_at:     str
    error_message:  Optional[str] = None
    traceback:      Optional[str] = None
    db_stats:       Optional[str] = None   # JSON
    log_tail:       Optional[str] = None
    user_note:      Optional[str] = None
    sent_at:        Optional[str] = None
    id:             Optional[int] = None
