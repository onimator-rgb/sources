"""
Thread-safe SQLite connections for the OH local database.
Stored in %APPDATA%\\OH\\oh.db on Windows.

Each thread gets its own connection via threading.local().
SQLite WAL mode allows concurrent readers + one writer,
so per-thread connections work well for our use case.
"""
import os
import shutil
import sqlite3
import logging
import threading
from contextlib import contextmanager
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger(__name__)

_local = threading.local()
_all_connections_lock = threading.Lock()
_all_connections: List[sqlite3.Connection] = []


def get_db_path() -> str:
    app_data = os.environ.get("APPDATA")
    if app_data:
        db_dir = Path(app_data) / "OH"
    else:
        db_dir = Path.home() / ".oh"
    db_dir.mkdir(parents=True, exist_ok=True)
    return str(db_dir / "oh.db")


def _create_connection() -> sqlite3.Connection:
    """Create a new connection with standard OH settings."""
    db_path = get_db_path()
    thread_name = threading.current_thread().name
    logger.info(f"Opening OH database for thread '{thread_name}': {db_path}")
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # WAL mode: allows reads while writes are in progress (important
    # for background workers reading while UI renders).
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    with _all_connections_lock:
        _all_connections.append(conn)
    return conn


def get_connection() -> sqlite3.Connection:
    """Return the connection for the current thread, creating one if needed."""
    conn = getattr(_local, "connection", None)
    if conn is None:
        conn = _create_connection()
        _local.connection = conn
    return conn


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
    """Close the current thread's connection."""
    conn = getattr(_local, "connection", None)
    if conn is not None:
        with _all_connections_lock:
            if conn in _all_connections:
                _all_connections.remove(conn)
        conn.close()
        _local.connection = None
        thread_name = threading.current_thread().name
        logger.info(f"OH database connection closed for thread '{thread_name}'.")


def close_all_connections() -> None:
    """Close all tracked connections (call during shutdown)."""
    with _all_connections_lock:
        for conn in _all_connections:
            try:
                conn.close()
            except Exception:
                pass
        count = len(_all_connections)
        _all_connections.clear()
    _local.connection = None
    logger.info(f"All OH database connections closed ({count} total).")


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
