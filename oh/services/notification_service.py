"""
NotificationService — orchestrates notification loading, enrichment, and export.

Responsibilities:
  - Load notifications from the bot's notificationdatabase.db via NotificationReader
  - Enrich device IDs with human-readable device names from oh_devices
  - Provide filter option lists for the UI
  - Export filtered records to CSV

UI layers call this service; they never call NotificationReader directly.
"""
import csv
import logging
import sqlite3
from typing import Dict, List, Optional

from oh.models.notification import NotificationRecord
from oh.modules.notification_reader import NotificationReader

logger = logging.getLogger(__name__)

# CSV column headers
_CSV_HEADERS = ["Device", "Account", "Notification", "Type", "Date", "Time"]


class NotificationService:
    """
    Orchestrates notification data flow between the reader module,
    the OH database (for device name enrichment), and the UI.

    Args:
        conn: sqlite3.Connection to the OH database (oh.db).
    """

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Loading
    # ------------------------------------------------------------------

    def load_notifications(self, bot_root: str) -> List[NotificationRecord]:
        """
        Read all notifications and enrich device IDs with names.

        Returns an empty list if the notification database is missing.
        """
        reader = NotificationReader(bot_root)
        records = reader.read_all()

        if records:
            name_map = self._build_device_name_map()
            if name_map:
                for rec in records:
                    rec.device_name = name_map.get(rec.device_id)

        logger.info(
            f"NotificationService: loaded {len(records)} notifications"
        )
        return records

    # ------------------------------------------------------------------
    # Filter helpers
    # ------------------------------------------------------------------

    def get_filter_options(
        self, records: List[NotificationRecord]
    ) -> Dict[str, List[str]]:
        """
        Return filter option lists derived from the loaded records.

        Returns a dict with keys: devices, types, accounts.
        """
        return {
            "devices":  NotificationReader.get_distinct_devices(records),
            "types":    NotificationReader.get_distinct_types(records),
            "accounts": NotificationReader.get_distinct_accounts(records),
        }

    # ------------------------------------------------------------------
    # Export
    # ------------------------------------------------------------------

    def export_csv(
        self, records: List[NotificationRecord], path: str
    ) -> None:
        """
        Write *records* to a CSV file at *path*.

        Columns: Device, Account, Notification, Type, Date, Time.
        The Device column shows the device name if available, falling
        back to the raw device_id.

        Raises OSError if the file cannot be written.
        """
        try:
            with open(path, "w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(_CSV_HEADERS)
                for rec in records:
                    writer.writerow([
                        rec.device_name or rec.device_id,
                        rec.account or "",
                        rec.notification,
                        rec.notification_type,
                        rec.date,
                        rec.time,
                    ])

            logger.info(
                f"NotificationService: exported {len(records)} records to {path}"
            )
        except OSError as exc:
            logger.error("Failed to export CSV to %s: %s", path, exc)
            raise

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_device_name_map(self) -> Dict[str, str]:
        """
        Query oh_devices for a {device_id: device_name} mapping.

        Returns an empty dict on failure (logged, never raised).
        """
        try:
            rows = self._conn.execute(
                "SELECT device_id, device_name FROM oh_devices"
            ).fetchall()
            return {
                r[0]: r[1]
                for r in rows
                if r[0] and r[1]
            }
        except Exception as e:
            logger.warning(
                f"NotificationService: could not load device names: {e}"
            )
            return {}
