"""
Single SQLite connection for the OH local database.
Stored in %APPDATA%\\OH\\oh.db on Windows.
"""
import os
import shutil
import sqlite3
import logging
import threading
from contextlib import contextmanager
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


_BACKUP_COUNT = 3


def backup_database() -> None:
    """Rotate and create a backup of oh.db before migrations.

    Maintains up to 3 rolling backups:
      oh.db.bak.1  (newest)
      oh.db.bak.2
      oh.db.bak.3  (oldest)

    Skips silently if oh.db does not exist yet (fresh install).
    Errors are logged as warnings but never crash the application.
    """
    try:
        db_path = Path(get_db_path())
        if not db_path.exists():
            logger.debug("No existing database to back up (fresh install).")
            return

        # Rotate: .bak.3 is dropped, .bak.2→.bak.3, .bak.1→.bak.2
        for i in range(_BACKUP_COUNT, 1, -1):
            older = db_path.with_suffix(f".db.bak.{i}")
            newer = db_path.with_suffix(f".db.bak.{i - 1}")
            if newer.exists():
                if older.exists():
                    older.unlink()
                newer.rename(older)

        # Copy current db → .bak.1 (preserves metadata)
        bak1 = db_path.with_suffix(".db.bak.1")
        shutil.copy2(str(db_path), str(bak1))
        logger.info(f"Database backed up: {bak1}")
    except Exception as exc:
        logger.warning(f"Database backup failed (non-fatal): {exc}", exc_info=True)


def close_connection() -> None:
    global _connection
    if _connection is not None:
        _connection.close()
        _connection = None
        logger.info("OH database connection closed.")


# ------------------------------------------------------------------
# Transaction helper
# ------------------------------------------------------------------

_tx_depth: threading.local = threading.local()


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Nestable transaction context manager for SQLite.

    Usage::

        with transaction(conn):
            conn.execute("INSERT ...")
            conn.execute("UPDATE ...")
            # both are committed atomically on exit

    Nesting is safe: the outermost ``transaction()`` controls the real
    COMMIT/ROLLBACK.  Inner calls are no-ops (depth counter).

    While a transaction is active, ``conn.commit()`` calls from
    repository methods are suppressed (monkey-patched to no-op) so
    that intermediate writes do not break atomicity.  The outermost
    context manager restores the original ``commit`` and calls it on
    successful exit.

    Uses SAVEPOINT internally so it works even when an implicit
    transaction is already open (which is normal with Python sqlite3's
    default ``isolation_level``).
    """
    depth = getattr(_tx_depth, "depth", 0)
    _tx_depth.depth = depth + 1

    if depth == 0:
        # Outermost — suppress individual commits and use a savepoint
        original_commit = conn.commit
        conn.commit = lambda: None  # type: ignore[assignment]
        conn.execute("SAVEPOINT oh_tx")

    try:
        yield conn
    except BaseException:
        _tx_depth.depth -= 1
        if _tx_depth.depth == 0:
            conn.commit = original_commit  # type: ignore[possibly-undefined]
            conn.execute("ROLLBACK TO oh_tx")
            conn.execute("RELEASE oh_tx")
        raise
    else:
        _tx_depth.depth -= 1
        if _tx_depth.depth == 0:
            conn.commit = original_commit  # type: ignore[possibly-undefined]
            conn.execute("RELEASE oh_tx")
            conn.commit()
