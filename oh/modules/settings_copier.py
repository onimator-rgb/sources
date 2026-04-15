"""
SettingsCopierModule — read and write bot settings.db files.

SAFETY MODEL:
  - settings.db is ALWAYS opened read-only (?mode=ro) for reads
  - Before any write, settings.db is backed up to settings.db.bak (shutil.copy2)
  - Writes use read-modify-write: read full JSON, update only specified keys, write back
  - Only keys in ALL_COPYABLE_KEYS are accepted for writing
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
from typing import List, Optional

from oh.models.settings_copy import (
    ALL_COPYABLE_KEYS,
    COPYABLE_SETTINGS,
    COPYABLE_TEXT_FILES,
    SettingsSnapshot,
    SettingsCopyResult,
)

logger = logging.getLogger(__name__)


def _get_nested(json_dict: dict, dot_path: str):
    """Traverse a dict using a dot-separated key path. Returns None if any segment is missing."""
    parts = dot_path.split(".")
    current = json_dict
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _set_nested(json_dict: dict, dot_path: str, value) -> None:
    """Set a value in a dict using a dot-separated key path, creating intermediate dicts if needed."""
    parts = dot_path.split(".")
    current = json_dict
    for part in parts[:-1]:
        if part not in current or not isinstance(current[part], dict):
            current[part] = {}
        current = current[part]
    current[parts[-1]] = value


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

        # Extract all copyable keys (both legacy flat and new nested paths)
        values = {}
        for key in ALL_COPYABLE_KEYS:
            val = _get_nested(full_json, key)
            if val is not None:
                values[key] = val

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
        invalid_keys = [k for k in updates if k not in ALL_COPYABLE_KEYS]
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

            # Step 3: Merge only the specified keys (supports nested dot paths)
            keys_written = []
            for key, value in updates.items():
                _set_nested(current_json, key, value)
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

    def read_text_files(
        self,
        device_id: str,
        username: str,
    ) -> dict:
        """
        Read all copyable text files from an account folder.

        Returns dict: filename -> content (None if the file does not exist).
        Never raises.
        """
        account_dir = self._root / device_id / username
        result = {}
        for filename, _display_name in COPYABLE_TEXT_FILES:
            file_path = account_dir / filename
            if file_path.exists():
                try:
                    result[filename] = file_path.read_text(encoding="utf-8")
                except OSError as e:
                    logger.warning(f"Cannot read {file_path}: {e}")
                    result[filename] = None
            else:
                result[filename] = None
        return result

    def write_text_files(
        self,
        device_id: str,
        username: str,
        files: dict,
    ) -> List[str]:
        """
        Write text files to an account folder.

        For each filename -> content in *files*:
          1. Skip if content is None
          2. Skip if current content is identical (no-op)
          3. Back up existing file as {filename}.bak
          4. Write new content

        Returns list of filenames actually written. Never raises.
        """
        account_dir = self._root / device_id / username
        # Validate: only write files that are in the allowlist
        allowed = {fn for fn, _dn in COPYABLE_TEXT_FILES}
        written = []

        for filename, content in files.items():
            if filename not in allowed:
                logger.warning(f"Skipping non-copyable text file: {filename}")
                continue
            if content is None:
                continue

            file_path = account_dir / filename
            # Skip if content is identical to current
            if file_path.exists():
                try:
                    current = file_path.read_text(encoding="utf-8")
                    if current == content:
                        logger.debug(f"Text file unchanged, skipping: {file_path}")
                        continue
                except OSError:
                    pass  # proceed to write

                # Backup existing file
                bak_path = file_path.with_name(f"{filename}.bak")
                try:
                    shutil.copy2(str(file_path), str(bak_path))
                    logger.info(f"Text file backup created: {bak_path}")
                except OSError as e:
                    logger.error(f"Text file backup failed for {bak_path}: {e}")
                    continue  # skip this file if backup fails

            try:
                file_path.write_text(content, encoding="utf-8")
                written.append(filename)
                logger.info(f"Wrote text file: {file_path}")
            except OSError as e:
                logger.error(f"Failed to write text file {file_path}: {e}")

        return written
