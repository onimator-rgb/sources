"""
UpdateService — checks for updates and downloads new versions.

The update server hosts a JSON file at a configurable URL:
{
    "version": "1.1.0",
    "download_url": "https://example.com/releases/OH_v1.1.0.exe",
    "changelog": "- Fixed bug X\n- Added feature Y",
    "min_version": "1.0.0",
    "release_date": "2026-04-03"
}

Update flow:
1. Fetch update.json from server
2. Compare version with local BUILD_VERSION
3. If newer -> show dialog
4. Download .exe to temp location
5. Generate updater.bat that swaps files after OH closes
6. Launch updater.bat and exit OH
"""
import hashlib
import json
import logging
import os
import sys
from typing import Callable, Optional
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)


@dataclass
class UpdateInfo:
    version: str
    download_url: str
    changelog: str
    release_date: str
    min_version: str = ""
    sha256: str = ""

    @property
    def is_valid(self) -> bool:
        return bool(self.version and self.download_url)


class UpdateService:
    """Checks for and applies OH updates."""

    def __init__(self, update_url: str = "") -> None:
        self._update_url = update_url
        self._current_version = self._get_current_version()

    @staticmethod
    def _get_current_version() -> str:
        try:
            from oh.version import BUILD_VERSION
            return BUILD_VERSION
        except ImportError:
            return "0.0.0"

    @property
    def current_version(self) -> str:
        return self._current_version

    @property
    def update_url(self) -> str:
        return self._update_url

    @update_url.setter
    def update_url(self, url: str) -> None:
        self._update_url = url

    def check_for_update(self) -> Optional[UpdateInfo]:
        """Check remote server for a newer version.
        Returns UpdateInfo if update available, None otherwise.
        """
        if not self._update_url:
            logger.debug("Update URL not configured, skipping check")
            return None

        try:
            resp = requests.get(self._update_url, timeout=10)
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as exc:
            logger.warning("Update check failed: %s", exc)
            return None
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("Invalid update response: %s", exc)
            return None

        info = UpdateInfo(
            version=data.get("version", ""),
            download_url=data.get("download_url", ""),
            changelog=data.get("changelog", ""),
            release_date=data.get("release_date", ""),
            min_version=data.get("min_version", ""),
            sha256=data.get("sha256", ""),
        )

        if not info.is_valid:
            logger.warning("Invalid update info: missing version or download_url")
            return None

        # Compare versions
        if self._version_compare(info.version, self._current_version) > 0:
            logger.info(
                "Update available: %s -> %s",
                self._current_version, info.version,
            )
            return info

        logger.debug("No update available (current=%s, remote=%s)",
                     self._current_version, info.version)
        return None

    def download_update(
        self,
        download_url: str,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        expected_sha256: str = "",
    ) -> Optional[str]:
        """Download the update .exe to a temp location.

        Args:
            download_url: URL to download from
            progress_callback: optional (downloaded_bytes, total_bytes) callback
            expected_sha256: if provided, verify downloaded file hash

        Returns path to downloaded file, or None on failure.
        """
        exe_dir = self._get_exe_dir()
        temp_path = os.path.join(exe_dir, "OH_update.exe")
        try:
            resp = requests.get(download_url, stream=True, timeout=300)
            resp.raise_for_status()

            total = int(resp.headers.get("content-length", 0))

            downloaded = 0
            with open(temp_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=65536):
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_callback and total > 0:
                        progress_callback(downloaded, total)

            # Verify SHA256 hash if provided
            if expected_sha256:
                h = hashlib.sha256()
                with open(temp_path, "rb") as f:
                    for chunk in iter(lambda: f.read(65536), b""):
                        h.update(chunk)
                computed = h.hexdigest()
                if computed != expected_sha256:
                    os.remove(temp_path)
                    logger.error(
                        "Update hash mismatch: expected %s, got %s",
                        expected_sha256, computed,
                    )
                    return None

            logger.info("Update downloaded to: %s (%d bytes)", temp_path, downloaded)
            return temp_path

        except requests.RequestException as exc:
            logger.error("Download failed: %s", exc)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None
        except OSError as exc:
            logger.error("Failed to save update: %s", exc)
            if os.path.exists(temp_path):
                os.remove(temp_path)
            return None

    def apply_update(self, update_path: str) -> bool:
        """Create updater.bat and launch it to swap .exe files.

        The batch script:
        1. Waits for OH.exe to close (polls every second)
        2. Copies OH_update.exe over OH.exe
        3. Deletes OH_update.exe
        4. Restarts OH.exe
        5. Deletes itself

        Returns True if updater was launched successfully.
        """
        exe_dir = self._get_exe_dir()
        current_exe = os.path.join(exe_dir, "OH.exe")
        updater_path = os.path.join(exe_dir, "oh_updater.bat")

        # Validate paths don't contain batch-special characters
        _BAD_CHARS = set('&|><^%"')
        for path_str in (update_path, current_exe):
            if _BAD_CHARS.intersection(path_str):
                logger.error("Unsafe characters in update path: %s", path_str)
                return False

        bat_content = f'''@echo off
echo OH Updater - Please wait...
echo Waiting for OH to close...

:wait_loop
tasklist /FI "IMAGENAME eq OH.exe" 2>NUL | find /I "OH.exe" >NUL
if %ERRORLEVEL% == 0 (
    timeout /t 1 /nobreak >NUL
    goto wait_loop
)

echo Applying update...
timeout /t 1 /nobreak >NUL

copy /Y "{update_path}" "{current_exe}" >NUL
if %ERRORLEVEL% NEQ 0 (
    echo ERROR: Failed to apply update!
    echo Press any key to exit...
    pause >NUL
    exit /b 1
)

del /F "{update_path}" >NUL 2>&1

echo Update complete! Starting OH...
start "" "{current_exe}"

timeout /t 2 /nobreak >NUL
del /F "%~f0" >NUL 2>&1
'''

        try:
            with open(updater_path, "w", encoding="utf-8") as f:
                f.write(bat_content)

            # Launch updater in background
            import subprocess
            subprocess.Popen(
                ["cmd.exe", "/c", updater_path],
                creationflags=subprocess.CREATE_NO_WINDOW,
                close_fds=True,
            )

            logger.info("Updater launched: %s", updater_path)
            return True

        except Exception as exc:
            logger.error("Failed to launch updater: %s", exc)
            return False

    @staticmethod
    def _get_exe_dir() -> str:
        """Get the directory of the running .exe (or script dir in dev)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(sys.argv[0]))

    @staticmethod
    def _version_compare(v1: str, v2: str) -> int:
        """Compare two version strings. Returns >0 if v1>v2, 0 if equal, <0 if v1<v2."""
        def parse(v: str) -> list:
            parts = []
            for p in v.replace("-", ".").replace("_", ".").split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(0)
            return parts

        p1 = parse(v1)
        p2 = parse(v2)

        # Pad shorter list
        max_len = max(len(p1), len(p2))
        p1.extend([0] * (max_len - len(p1)))
        p2.extend([0] * (max_len - len(p2)))

        for a, b in zip(p1, p2):
            if a > b:
                return 1
            if a < b:
                return -1
        return 0
