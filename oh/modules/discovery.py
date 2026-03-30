"""
DiscoveryModule — reads the Onimator installation folder structure
and returns a list of DiscoveredAccount objects.

All Onimator files are opened READ-ONLY (sqlite3 URI ?mode=ro).
Nothing is ever written to the Onimator folder.
"""
import contextlib
import sqlite3
import logging
from pathlib import Path
from typing import Optional

from oh.models.account import DiscoveredAccount

logger = logging.getLogger(__name__)

# Folder names inside a device directory that are NOT account folders.
_DEVICE_NON_ACCOUNT_DIRS = frozenset({
    ".stm", ".trash", "crash_log", "logs", "jobs",
    "sources", "scrapers", "template",
    # Common non-account names observed in real installations
    "Camera", "log", "snapshot", "jobtemplate",
})

# Account names in accounts.db that are NOT real Instagram accounts
# (legacy artifacts or metadata rows found in the real installation).
_ACCOUNTS_DB_RESERVED_NAMES = frozenset({
    "settings",
})


class DiscoveryError(Exception):
    """Raised when discovery cannot proceed due to a configuration or I/O problem."""


class DiscoveryModule:
    """
    Reads:
      {bot_root}/devices.db                        → device list
      {bot_root}/{device_id}/accounts.db           → accounts registered on device
      {bot_root}/{device_id}/{username}/            → folder existence check
      {bot_root}/{device_id}/{username}/data.db     → FBR data availability
      {bot_root}/{device_id}/{username}/sources.txt → active sources availability
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_root(self) -> bool:
        """Quick check: does this path look like an Onimator installation?"""
        return self._root.is_dir() and (self._root / "devices.db").exists()

    def discover(self) -> list:
        """
        Perform a full scan and return a list of DiscoveredAccount objects.
        Raises DiscoveryError if the bot root is invalid or devices.db is missing.
        """
        if not self._root.is_dir():
            raise DiscoveryError(
                f"Bot root path does not exist:\n{self._root}\n\n"
                "Update the path in Settings."
            )
        if not (self._root / "devices.db").exists():
            raise DiscoveryError(
                f"devices.db not found at:\n{self._root}\n\n"
                "Verify this is the correct Onimator installation folder."
            )

        devices = self._read_devices_db()
        logger.info(f"Discovery: found {len(devices)} device(s) in devices.db.")

        results: list = []

        for device_id, device_name, device_status in devices:
            device_folder = self._root / device_id
            if not device_folder.is_dir():
                logger.warning(f"Device folder missing on disk: {device_folder} — skipping.")
                continue

            accounts_db = device_folder / "accounts.db"
            if not accounts_db.exists():
                logger.warning(f"accounts.db missing for device {device_id} — skipping.")
                continue

            registered = self._read_accounts_db(accounts_db)
            registered_names = {acc["account"] for acc in registered}

            # --- Accounts registered in accounts.db ---
            for acc in registered:
                if acc["account"] in _ACCOUNTS_DB_RESERVED_NAMES:
                    continue
                username = acc["account"]
                acct_folder = device_folder / username
                folder_exists = acct_folder.is_dir()

                # Read tags and limits from per-account settings.db
                bot_tags_raw = None
                follow_limit_perday = None
                like_limit_perday = None
                if folder_exists:
                    bot_tags_raw, follow_limit_perday, like_limit_perday = (
                        self._read_settings_db(acct_folder / "settings.db")
                    )

                results.append(DiscoveredAccount(
                    device_id=device_id,
                    device_name=device_name,
                    device_status=device_status or "unknown",
                    username=username,
                    folder_exists=folder_exists,
                    data_db_exists=(acct_folder / "data.db").exists() if folder_exists else False,
                    sources_txt_exists=(acct_folder / "sources.txt").exists() if folder_exists else False,
                    follow_enabled=str(acc.get("follow", "")).lower() == "true",
                    unfollow_enabled=str(acc.get("unfollow", "")).lower() == "true",
                    limit_per_day=acc.get("limitperday"),
                    start_time=acc.get("starttime"),
                    end_time=acc.get("endtime"),
                    is_missing_folder=not folder_exists,
                    bot_tags_raw=bot_tags_raw,
                    follow_limit_perday=follow_limit_perday,
                    like_limit_perday=like_limit_perday,
                ))

            # --- Orphan folders: on disk but not in accounts.db ---
            try:
                physical_dirs = {
                    d.name for d in device_folder.iterdir()
                    if d.is_dir()
                    and not d.name.startswith(".")
                    and d.name not in _DEVICE_NON_ACCOUNT_DIRS
                }
                for orphan_name in sorted(physical_dirs - registered_names):
                    orphan_folder = device_folder / orphan_name
                    results.append(DiscoveredAccount(
                        device_id=device_id,
                        device_name=device_name,
                        device_status=device_status or "unknown",
                        username=orphan_name,
                        folder_exists=True,
                        data_db_exists=(orphan_folder / "data.db").exists(),
                        sources_txt_exists=(orphan_folder / "sources.txt").exists(),
                        is_orphan_folder=True,
                    ))
            except PermissionError as e:
                logger.warning(f"Cannot list device folder {device_folder}: {e}")

        logger.info(
            f"Discovery complete: {len(results)} account entries "
            f"across {len(devices)} device(s)."
        )
        return results

    # ------------------------------------------------------------------
    # Internal readers (read-only SQLite connections)
    # ------------------------------------------------------------------

    def _read_devices_db(self) -> list:
        """Returns list of (device_id, device_name, status)."""
        db_path = self._root / "devices.db"
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT deviceid, devicename, status FROM devices"
                ).fetchall()
            return [(r["deviceid"], r["devicename"], r["status"]) for r in rows]
        except sqlite3.OperationalError as e:
            raise DiscoveryError(f"Cannot read devices.db: {e}") from e

    def _read_accounts_db(self, path: Path) -> list:
        """Returns list of account dicts from a device's accounts.db."""
        try:
            uri = f"file:{path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT account, follow, unfollow, limitperday, starttime, endtime "
                    "FROM accounts"
                ).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as e:
            # Non-fatal: log and return empty so the device is not silently skipped
            logger.warning(f"Cannot read accounts from {path}: {e}")
            return []

    def _read_settings_db(
        self, path: Path
    ) -> tuple:
        """
        Read tags and limits from a per-account settings.db.

        Returns (bot_tags_raw, follow_limit_perday, like_limit_perday).
        All values are Optional[str].  Returns (None, None, None) if the
        file is missing, unreadable, or has no settings row.
        """
        if not path.exists():
            return None, None, None
        try:
            import json as _json
            uri = f"file:{path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
                row = conn.execute(
                    "SELECT settings FROM accountsettings LIMIT 1"
                ).fetchone()
            if not row or not row[0]:
                return None, None, None
            settings = _json.loads(row[0])
            tags_raw = settings.get("tags")
            if isinstance(tags_raw, str):
                tags_raw = tags_raw.strip() or None
            else:
                tags_raw = None
            follow_limit = settings.get("default_action_limit_perday")
            like_limit = settings.get("like_limit_perday")
            return (
                tags_raw,
                str(follow_limit) if follow_limit is not None else None,
                str(like_limit) if like_limit is not None else None,
            )
        except (sqlite3.OperationalError, _json.JSONDecodeError, Exception) as e:
            logger.warning(f"Cannot read settings from {path}: {e}")
            return None, None, None
