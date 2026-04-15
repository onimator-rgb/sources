"""
Domain models for Notifications Browser.

NotificationRecord represents a single notification from the bot's
notificationdatabase.db.  Each record is classified into a type
(Added, Deleted, Login, Block, Suspended, Error, Other) by keyword
matching on the notification text.

NOTIFICATION_TYPES maps each type name to a semantic color key
from oh/ui/style.py so the UI can render type-appropriate colors.
"""
from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Type → semantic color key (from oh/ui/style.py)
# ---------------------------------------------------------------------------

NOTIFICATION_TYPES = {
    "Added":     "success",    # green
    "Deleted":   "critical",   # red
    "Login":     "link",       # blue
    "Block":     "high",       # orange
    "Suspended": "warning",    # lighter orange
    "Error":     "error",      # pink
    "Other":     "muted",      # dim
}

# ---------------------------------------------------------------------------
# Keyword → type mapping (order matters — first match wins)
# ---------------------------------------------------------------------------

_CLASSIFICATION_RULES = [
    (("Added",),                          "Added"),
    (("Deleted", "Removed"),              "Deleted"),
    (("Login", "Logged"),                 "Login"),
    (("Block",),                          "Block"),
    (("Suspended",),                      "Suspended"),
    (("Error", "Exception", "Failed"),    "Error"),
]


def classify_notification(text: str) -> str:
    """
    Classify a notification text into one of the known types by
    keyword matching (case-insensitive).  Returns 'Other' if no
    keyword matches.
    """
    if not text:
        return "Other"
    lower = text.lower()
    for keywords, ntype in _CLASSIFICATION_RULES:
        for kw in keywords:
            if kw.lower() in lower:
                return ntype
    return "Other"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class NotificationRecord:
    device_id: str
    device_name: Optional[str]       # enriched from oh_devices; None if unknown
    account: Optional[str]           # NULL for device-level notifications
    notification: str
    date: str
    time: str
    notification_type: str           # one of NOTIFICATION_TYPES keys
