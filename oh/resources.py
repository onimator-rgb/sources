"""
Resource path resolver — works in both dev and PyInstaller frozen mode.

Usage:
    from oh.resources import asset_path
    icon = QIcon(str(asset_path("oh.ico")))

In dev mode:  returns  <repo>/oh/assets/<name>
In .exe mode: returns  sys._MEIPASS/assets/<name>
"""
import sys
from pathlib import Path


def _base_dir() -> Path:
    """Return the directory that contains the bundled assets."""
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        # PyInstaller one-file / one-dir bundle
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    # Development: this file is at oh/resources.py → parent is the package dir
    return Path(__file__).parent


def asset_path(filename: str) -> Path:
    """Return the absolute path to an asset file."""
    return _base_dir() / "assets" / filename


def asset_exists(filename: str) -> bool:
    return asset_path(filename).exists()
