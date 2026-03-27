"""
OH — Operational Hub
Entry point: bootstraps DB, applies migrations, launches the desktop UI.

Logs are written to:  %APPDATA%\\OH\\logs\\oh.log
  - Rotating at 2 MB, keeping 5 backups (10 MB max).
  - Console output at INFO level; file output at DEBUG level.
"""
import os
import sys
import logging
import logging.handlers
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QPalette, QColor, QFont, QIcon

from oh.db.connection import get_connection, get_db_path, close_connection
from oh.db.migrations import run_migrations
from oh.repositories.account_repo import AccountRepository
from oh.repositories.delete_history_repo import DeleteHistoryRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.repositories.sync_repo import SyncRepository
from oh.services.fbr_service import FBRService
from oh.services.global_sources_service import GlobalSourcesService
from oh.services.scan_service import ScanService
from oh.services.source_delete_service import SourceDeleteService
from oh.resources import asset_path, asset_exists
from oh.ui.main_window import MainWindow
from oh.ui.style import get_stylesheet


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

def _get_log_dir() -> Path:
    app_data = os.environ.get("APPDATA") or str(Path.home())
    log_dir = Path(app_data) / "OH" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def _setup_logging() -> Path:
    """
    Configure root logger with:
      - RotatingFileHandler  (DEBUG+, 2 MB × 5 files) → %APPDATA%\\OH\\logs\\oh.log
      - StreamHandler        (INFO+)                   → stdout
    Returns the log directory path.
    """
    log_dir  = _get_log_dir()
    log_file = log_dir / "oh.log"

    fmt = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    # File handler — rotates at 2 MB, keeps 5 backups
    fh = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=2 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    root.addHandler(fh)

    # Console handler — INFO+ only (less noise during testing)
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.INFO)
    ch.setFormatter(fmt)
    root.addHandler(ch)

    return log_dir


def _install_exception_hook() -> None:
    """
    Route unhandled exceptions through the logger so they appear in oh.log
    even when no console is attached (e.g. running via pythonw or a shortcut).
    """
    _logger = logging.getLogger("oh.uncaught")

    def _hook(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        _logger.critical(
            "Unhandled exception — OH will attempt to continue",
            exc_info=(exc_type, exc_value, exc_tb),
        )

    sys.excepthook = _hook


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def apply_dark_palette(app: QApplication) -> None:
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window,          QColor(45, 45, 48))
    palette.setColor(QPalette.ColorRole.WindowText,      QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Base,            QColor(30, 30, 30))
    palette.setColor(QPalette.ColorRole.AlternateBase,   QColor(40, 40, 43))
    palette.setColor(QPalette.ColorRole.ToolTipBase,     QColor(25, 25, 25))
    palette.setColor(QPalette.ColorRole.ToolTipText,     QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Text,            QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.Button,          QColor(55, 55, 60))
    palette.setColor(QPalette.ColorRole.ButtonText,      QColor(220, 220, 220))
    palette.setColor(QPalette.ColorRole.BrightText,      QColor(255, 80, 80))
    palette.setColor(QPalette.ColorRole.Link,            QColor(86, 156, 214))
    palette.setColor(QPalette.ColorRole.Highlight,       QColor(0, 120, 212))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    palette.setColor(QPalette.ColorRole.Mid,             QColor(60, 60, 65))
    palette.setColor(QPalette.ColorRole.Dark,            QColor(35, 35, 38))
    app.setPalette(palette)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap(conn) -> None:
    """Apply migrations, seed config defaults, recover interrupted sync runs."""
    logger.info("Running database migrations…")
    run_migrations(conn)

    settings_repo = SettingsRepository(conn)
    settings_repo.seed_defaults()
    logger.info(f"Config defaults seeded.  DB: {get_db_path()}")

    sync_repo = SyncRepository(conn)
    recovered = sync_repo.recover_stale_runs()
    if recovered:
        logger.warning(f"Recovered {recovered} stale sync run(s) from previous session.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    log_dir = _setup_logging()
    _install_exception_hook()

    # Log whether we are running as a frozen .exe or from source
    import sys as _sys
    frozen = getattr(_sys, "frozen", False)
    logger.info("=" * 60)
    logger.info(f"OH — Operational Hub starting up ({'frozen .exe' if frozen else 'dev/source'})")
    logger.info(f"Log directory: {log_dir}")

    app = QApplication(sys.argv)
    app.setApplicationName("OH — Operational Hub")
    app.setStyle("Fusion")

    # Font
    app.setFont(QFont("Segoe UI", 10))

    try:
        conn = get_connection()
        bootstrap(conn)
    except Exception as e:
        logger.critical(f"Startup failed during DB bootstrap: {e}", exc_info=True)
        QMessageBox.critical(
            None,
            "OH — Startup Error",
            f"Failed to initialise the database:\n\n{e}\n\n"
            f"Check the log file for details:\n{log_dir / 'oh.log'}",
        )
        sys.exit(1)

    settings_repo   = SettingsRepository(conn)
    theme = settings_repo.get("theme") or "dark"
    if theme == "dark":
        apply_dark_palette(app)
    app.setStyleSheet(get_stylesheet())
    logger.info(f"Theme: {theme}")

    # App icon (loaded from bundled assets — silently skipped if not yet generated)
    if asset_exists("oh.ico"):
        app.setWindowIcon(QIcon(str(asset_path("oh.ico"))))

    assignment_repo = SourceAssignmentRepository(conn)

    scan_service = ScanService(
        account_repo=AccountRepository(conn),
        device_repo=DeviceRepository(conn),
        sync_repo=SyncRepository(conn),
    )
    fbr_service = FBRService(
        snapshot_repo=FBRSnapshotRepository(conn),
        account_repo=AccountRepository(conn),
        settings_repo=settings_repo,
        assignment_repo=assignment_repo,
    )
    global_sources_service = GlobalSourcesService(
        account_repo=AccountRepository(conn),
        assignment_repo=assignment_repo,
    )
    delete_history_repo   = DeleteHistoryRepository(conn)
    source_delete_service = SourceDeleteService(
        assignment_repo=assignment_repo,
        history_repo=delete_history_repo,
        settings_repo=settings_repo,
        global_sources_service=global_sources_service,
    )

    logger.info("All services initialised.  Launching main window.")

    window = MainWindow(
        conn,
        scan_service,
        fbr_service,
        global_sources_service,
        source_delete_service,
    )
    window.show()

    exit_code = app.exec()
    logger.info(f"OH exiting with code {exit_code}.")
    close_connection()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
