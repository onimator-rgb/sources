"""
NotificationReader — reads the bot's notificationdatabase.db (read-only).

This module provides structured access to the bot's notification log,
classifying each notification into a type for display and filtering.

All access is READ-ONLY.  Nothing is written to the Onimator folder.
"""
import contextlib
import logging
import sqlite3
from pathlib import Path
from typing import List

from oh.models.notification import NotificationRecord, classify_notification

logger = logging.getLogger(__name__)

# Relative path to the notification database inside the bot root.
_DB_NAME = "notificationdatabase.db"

# Query: pull all notifications, newest first.
_SELECT_ALL_SQL = """
    SELECT deviceid, account, notification, date, time
    FROM notifications
    ORDER BY date DESC, time DESC
"""


class NotificationReader:
    """
    Reads notification records from the bot's notificationdatabase.db.

    Args:
        bot_root: Absolute path to the Onimator installation folder.
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_all(self) -> List[NotificationRecord]:
        """
        Read every notification from the database.

        Returns an empty list (with a warning logged) if the database
        file is missing or unreadable.
        """
        db_path = self._root / _DB_NAME

        if not db_path.exists():
            logger.warning(
                f"NotificationReader: database not found at {db_path}"
            )
            return []

        uri = f"file:{db_path.as_posix()}?mode=ro"
        try:
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(_SELECT_ALL_SQL).fetchall()
        except sqlite3.DatabaseError as e:
            logger.warning(
                f"NotificationReader: cannot read {db_path}: {e}"
            )
            return []

        records: List[NotificationRecord] = []
        for row in rows:
            text = row["notification"] or ""
            records.append(NotificationRecord(
                device_id=row["deviceid"] or "",
                device_name=None,           # enriched later by the service
                account=row["account"] or None,
                notification=text,
                date=row["date"] or "",
                time=row["time"] or "",
                notification_type=classify_notification(text),
            ))

        logger.debug(
            f"NotificationReader: read {len(records)} notifications "
            f"from {db_path.name}"
        )
        return records

    @staticmethod
    def get_distinct_types(records: List[NotificationRecord]) -> List[str]:
        """Return sorted list of unique notification_type values present in *records*."""
        return sorted({r.notification_type for r in records})

    @staticmethod
    def get_distinct_devices(records: List[NotificationRecord]) -> List[str]:
        """Return sorted list of unique device_id values present in *records*."""
        return sorted({r.device_id for r in records if r.device_id})

    @staticmethod
    def get_distinct_accounts(records: List[NotificationRecord]) -> List[str]:
        """Return sorted list of unique account values present in *records*."""
        return sorted({r.account for r in records if r.account})
