"""CRUD access to the oh_devices table."""
import sqlite3
import logging
from typing import Optional

from oh.models.account import DeviceRecord

logger = logging.getLogger(__name__)


class DeviceRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def upsert(self, device: DeviceRecord) -> DeviceRecord:
        existing = self._conn.execute(
            "SELECT id FROM oh_devices WHERE device_id=?", (device.device_id,)
        ).fetchone()

        if existing is None:
            cursor = self._conn.execute(
                """
                INSERT INTO oh_devices
                    (device_id, device_name, last_known_status,
                     first_discovered_at, last_synced_at, is_active)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    device.device_id, device.device_name, device.last_known_status,
                    device.first_discovered_at, device.last_synced_at,
                    1 if device.is_active else 0,
                ),
            )
            device.id = cursor.lastrowid
        else:
            self._conn.execute(
                """
                UPDATE oh_devices
                SET device_name=?, last_known_status=?, last_synced_at=?, is_active=?
                WHERE device_id=?
                """,
                (
                    device.device_name, device.last_known_status,
                    device.last_synced_at, 1 if device.is_active else 0,
                    device.device_id,
                ),
            )
            device.id = existing["id"]

        self._conn.commit()
        return device

    def get_all_active(self) -> list:
        rows = self._conn.execute(
            "SELECT * FROM oh_devices WHERE is_active=1 ORDER BY device_name"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_by_device_id(self, device_id: str) -> Optional[DeviceRecord]:
        row = self._conn.execute(
            "SELECT * FROM oh_devices WHERE device_id=?", (device_id,)
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> DeviceRecord:
        return DeviceRecord(
            id=row["id"],
            device_id=row["device_id"],
            device_name=row["device_name"],
            last_known_status=row["last_known_status"],
            first_discovered_at=row["first_discovered_at"],
            last_synced_at=row["last_synced_at"],
            is_active=bool(row["is_active"]),
        )
