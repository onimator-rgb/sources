"""
SettingsCopierModule — read and write bot settings.db files.

SAFETY MODEL:
  - settings.db is ALWAYS opened read-only (?mode=ro) for reads
  - Before any write, settings.db is backed up to settings.db.bak (shutil.copy2)
  - Writes use read-modify-write: read full JSON, update only specified keys, write back
  - Only keys in COPYABLE_SETTINGS are accepted for writing
  - Only UPDATE existing rows — never INSERT new rows
  - Per-item errors don't abort batch operations — never raises to caller

The caller (SettingsCopierService) is responsible for:
  - Confirming with the operator before calling write_settings
  - Logging to operator_actions audit trail
"""
import contextlib
import json
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import Optional

from oh.models.settings_copy import (
    COPYABLE_SETTINGS,
    SettingsSnapshot,
    SettingsCopyResult,
)

logger = logging.getLogger(__name__)


class SettingsCopierModule:
    """
    Handles all settings.db file I/O for the Settings Copier feature.
    One instance per bot_root. All methods are stateless and re-read
    the file on every call.
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    def read_settings(
        self,
        device_id: str,
        username: str,
        device_name: Optional[str] = None,
        account_id: int = 0,
    ) -> SettingsSnapshot:
        """
        Read all copyable settings from one account's settings.db (read-only).

        Returns a SettingsSnapshot — never raises.
        """
        db_path = self._root / device_id / username / "settings.db"

        if not db_path.exists():
            return SettingsSnapshot(
                account_id=account_id,
                username=username,
                device_id=device_id,
                device_name=device_name,
                values={},
                error="settings.db not found",
            )

        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with contextlib.closing(
                sqlite3.connect(uri, uri=True, timeout=5)
            ) as conn:
                row = conn.execute(
                    "SELECT settings FROM accountsettings LIMIT 1"
                ).fetchone()
        except sqlite3.OperationalError as e:
            logger.warning(f"Cannot read settings.db for {username}@{device_id[:12]}: {e}")
            return SettingsSnapshot(
                account_id=account_id,
                username=username,
                device_id=device_id,
                device_name=device_name,
                values={},
                error=f"Cannot read: {e}",
            )

        if not row or not row[0]:
            return SettingsSnapshot(
                account_id=account_id,
                username=username,
                device_id=device_id,
                device_name=device_name,
                values={},
                error="accountsettings table is empty",
            )

        try:
            full_json = json.loads(row[0])
        except (json.JSONDecodeError, TypeError) as e:
            logger.warning(f"Bad JSON in settings.db for {username}@{device_id[:12]}: {e}")
            return SettingsSnapshot(
                account_id=account_id,
                username=username,
                device_id=device_id,
                device_name=device_name,
                values={},
                error=f"Bad JSON: {e}",
            )

        # Extract only the copyable keys that exist in the JSON
        values = {}
        for key in COPYABLE_SETTINGS:
            if key in full_json:
                values[key] = full_json[key]

        logger.debug(
            f"Read {len(values)} copyable settings for {username}@{device_id[:12]}"
        )

        return SettingsSnapshot(
            account_id=account_id,
            username=username,
            device_id=device_id,
            device_name=device_name,
            values=values,
            raw_json=full_json,
        )

    def write_settings(
        self,
        device_id: str,
        username: str,
        updates: dict,
        device_name: Optional[str] = None,
        account_id: int = 0,
    ) -> SettingsCopyResult:
        """
        Write specific keys to one account's settings.db.

        SAFETY:
        1. Validate that all keys are in COPYABLE_SETTINGS
        2. Read current JSON blob from accountsettings
        3. Create backup: settings.db.bak (copy the entire file)
        4. Merge only the specified keys into the JSON blob
        5. Write back the full JSON blob in a transaction
        6. Return result with backup/success status

        Never raises — returns SettingsCopyResult with error details.
        """
        db_path = self._root / device_id / username / "settings.db"

        if not db_path.exists():
            return SettingsCopyResult(
                target_account_id=account_id,
                target_username=username,
                target_device_name=device_name,
                success=False,
                backed_up=False,
                keys_written=[],
                error="settings.db not found",
            )

        # Validate keys — reject anything not in the allowlist
        invalid_keys = [k for k in updates if k not in COPYABLE_SETTINGS]
        if invalid_keys:
            return SettingsCopyResult(
                target_account_id=account_id,
                target_username=username,
                target_device_name=device_name,
                success=False,
                backed_up=False,
                keys_written=[],
                error=f"Invalid keys: {', '.join(invalid_keys)}",
            )

        # Step 1: Read current JSON blob (normal connection, not read-only)
        try:
            conn = sqlite3.connect(str(db_path), timeout=10)
        except sqlite3.OperationalError as e:
            logger.error(f"Cannot open settings.db for write {username}@{device_id[:12]}: {e}")
            return SettingsCopyResult(
                target_account_id=account_id,
                target_username=username,
                target_device_name=device_name,
                success=False,
                backed_up=False,
                keys_written=[],
                error=f"Cannot open: {e}",
            )

        try:
            row = conn.execute(
                "SELECT settings FROM accountsettings LIMIT 1"
            ).fetchone()

            if not row or not row[0]:
                conn.close()
                return SettingsCopyResult(
                    target_account_id=account_id,
                    target_username=username,
                    target_device_name=device_name,
                    success=False,
                    backed_up=False,
                    keys_written=[],
                    error="accountsettings table is empty — cannot update",
                )

            try:
                current_json = json.loads(row[0])
            except (json.JSONDecodeError, TypeError) as e:
                conn.close()
                return SettingsCopyResult(
                    target_account_id=account_id,
                    target_username=username,
                    target_device_name=device_name,
                    success=False,
                    backed_up=False,
                    keys_written=[],
                    error=f"Bad JSON in target: {e}",
                )

            # Step 2: Create backup before any write (MANDATORY)
            bak_path = db_path.with_name("settings.db.bak")
            backed_up = False
            try:
                shutil.copy2(str(db_path), str(bak_path))
                backed_up = True
                logger.info(f"Backup created: {bak_path}")
            except OSError as e:
                logger.error(f"Backup failed for {bak_path}: {e} — aborting write")
                conn.close()
                return SettingsCopyResult(
                    target_account_id=account_id,
                    target_username=username,
                    target_device_name=device_name,
                    success=False,
                    backed_up=False,
                    keys_written=[],
                    error=f"Backup failed (write aborted): {e}",
                )

            # Step 3: Merge only the specified keys
            keys_written = []
            for key, value in updates.items():
                current_json[key] = value
                keys_written.append(key)

            # Step 4: Write back the full JSON blob in a transaction
            new_json_str = json.dumps(current_json, ensure_ascii=False)
            try:
                conn.execute("BEGIN")
                conn.execute(
                    "UPDATE accountsettings SET settings = ? "
                    "WHERE rowid = (SELECT rowid FROM accountsettings LIMIT 1)",
                    (new_json_str,),
                )
                conn.execute("COMMIT")
            except sqlite3.OperationalError as e:
                logger.error(
                    f"Write failed for {username}@{device_id[:12]}: {e}"
                )
                try:
                    conn.execute("ROLLBACK")
                except Exception:
                    pass
                conn.close()
                return SettingsCopyResult(
                    target_account_id=account_id,
                    target_username=username,
                    target_device_name=device_name,
                    success=False,
                    backed_up=backed_up,
                    keys_written=[],
                    error=f"Write failed: {e}",
                )

            conn.close()

            logger.info(
                f"Wrote {len(keys_written)} settings to {username}@{device_id[:12]} "
                f"backup={'yes' if backed_up else 'SKIPPED'}"
            )
            return SettingsCopyResult(
                target_account_id=account_id,
                target_username=username,
                target_device_name=device_name,
                success=True,
                backed_up=backed_up,
                keys_written=keys_written,
            )

        except Exception as e:
            logger.exception(
                f"Unexpected error writing settings for {username}@{device_id[:12]}: {e}"
            )
            try:
                conn.close()
            except Exception:
                pass
            return SettingsCopyResult(
                target_account_id=account_id,
                target_username=username,
                target_device_name=device_name,
                success=False,
                backed_up=False,
                keys_written=[],
                error=f"Unexpected error: {e}",
            )
