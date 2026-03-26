"""
Single SQLite connection for the OH local database.
Stored in %APPDATA%\\OH\\oh.db on Windows.
"""
import os
import sqlite3
import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_connection: Optional[sqlite3.Connection] = None


def get_db_path() -> str:
    app_data = os.environ.get("APPDATA")
    if app_data:
        db_dir = Path(app_data) / "OH"
    else:
        db_dir = Path.home() / ".oh"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "oh.db")


def get_connection() -> sqlite3.Connection:
    global _connection
    if _connection is None:
        db_path = get_db_path()
        logger.info(f"Opening OH database: {db_path}")
        _connection = sqlite3.connect(db_path, check_same_thread=False)
        _connection.row_factory = sqlite3.Row
        # WAL mode: allows reads while writes are in progress (important
        # for background workers reading while UI renders).
        _connection.execute("PRAGMA journal_mode=WAL")
        _connection.execute("PRAGMA foreign_keys=ON")
    return _connection


def close_connection() -> None:
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        logger.info("OH database connection closed.")
