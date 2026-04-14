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
from typing import Optional

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QFont, QIcon

from oh.db.connection import get_connection, get_db_path, close_connection
from oh.db.migrations import run_migrations
from oh.repositories.account_repo import AccountRepository
from oh.repositories.delete_history_repo import DeleteHistoryRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_assignment_repo import SourceAssignmentRepository
from oh.repositories.blacklist_repo import BlacklistRepository
from oh.repositories.bulk_discovery_repo import BulkDiscoveryRepository
from oh.repositories.source_profile_repo import SourceProfileRepository
from oh.repositories.source_search_repo import SourceSearchRepository
from oh.repositories.sync_repo import SyncRepository
from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.repositories.session_repo import SessionRepository
from oh.repositories.tag_repo import TagRepository
from oh.repositories.error_report_repo import ErrorReportRepository
from oh.services.fbr_service import FBRService
from oh.services.operator_action_service import OperatorActionService
from oh.services.recommendation_service import RecommendationService
from oh.services.global_sources_service import GlobalSourcesService
from oh.services.scan_service import ScanService
from oh.services.session_service import SessionService
from oh.services.source_delete_service import SourceDeleteService
from oh.services.bulk_discovery_service import BulkDiscoveryService
from oh.services.source_finder_service import SourceFinderService
from oh.services.error_report_service import ErrorReportService
from oh.services.block_detection_service import BlockDetectionService
from oh.services.account_group_service import AccountGroupService
from oh.services.trend_service import TrendService
from oh.services.auto_fix_service import AutoFixService
from oh.services.settings_copier_service import SettingsCopierService
from oh.repositories.warmup_template_repo import WarmupTemplateRepository
from oh.services.warmup_template_service import WarmupTemplateService
from oh.repositories.block_event_repo import BlockEventRepository
from oh.repositories.account_group_repo import AccountGroupRepository
try:
    from oh.services.account_detail_service import AccountDetailService
except ImportError:
    AccountDetailService = None
from oh.resources import asset_path, asset_exists
from oh.ui.main_window import MainWindow
from oh.ui.style import get_stylesheet, apply_palette, set_current_theme


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


def _install_exception_hook(error_report_service=None) -> None:
    """
    Route unhandled exceptions through the logger so they appear in oh.log
    even when no console is attached (e.g. running via pythonw or a shortcut).

    If error_report_service is provided, also captures a crash report and
    optionally sends it to the configured endpoint.
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
        if error_report_service is not None:
            try:
                report = error_report_service.capture_crash(
                    exc_type, exc_value, exc_tb
                )
                if error_report_service.auto_send_enabled():
                    error_report_service.send_report(report)
            except Exception:
                _logger.debug("Failed to capture/send crash report", exc_info=True)

    sys.excepthook = _hook


logger = logging.getLogger(__name__)


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

def _compute_exe_sha256() -> Optional[str]:
    """Compute SHA256 of the running .exe for integrity logging."""
    if not getattr(sys, 'frozen', False):
        return None
    try:
        import hashlib
        h = hashlib.sha256()
        exe_path = Path(sys.executable)
        with open(exe_path, 'rb') as f:
            while True:
                chunk = f.read(1 << 20)  # 1 MB chunks
                if not chunk:
                    break
                h.update(chunk)
        return h.hexdigest()
    except Exception:
        return None


def main() -> None:
    # --- Anti-debug: silently exit if a debugger is attached (frozen only) ---
    if getattr(sys, 'frozen', False):
        try:
            import ctypes
            if ctypes.windll.kernel32.IsDebuggerPresent():
                sys.exit(1)
        except Exception:
            pass

    log_dir = _setup_logging()
    _install_exception_hook()  # basic hook first, upgraded with reporting below

    # Log whether we are running as a frozen .exe or from source
    import sys as _sys
    frozen = getattr(_sys, "frozen", False)
    try:
        from oh.version import BUILD_VERSION
    except ImportError:
        BUILD_VERSION = "dev"
    logger.info("=" * 60)
    logger.info(f"OH — Operational Hub starting up ({'frozen .exe' if frozen else 'dev/source'})  build={BUILD_VERSION}")
    logger.info(f"Log directory: {log_dir}")

    app = QApplication(sys.argv)
    app.setApplicationName("OH — Operational Hub")
    app.setStyle("Fusion")

    # Font
    app.setFont(QFont("Segoe UI", 11))

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

    # Self-integrity check — log SHA256 of the running .exe
    exe_hash = _compute_exe_sha256()
    if exe_hash:
        logger.info(f"EXE integrity SHA256: {exe_hash}")
        try:
            SettingsRepository(conn).set("exe_sha256", exe_hash)
        except Exception:
            logger.debug("Failed to store exe_sha256 in settings", exc_info=True)

    # Error reporting — upgrade exception hook with crash capture
    error_report_repo = ErrorReportRepository(conn)
    error_report_service = ErrorReportService(
        report_repo=error_report_repo,
        settings_repo=SettingsRepository(conn),
        conn=conn,
    )
    _install_exception_hook(error_report_service)
    error_report_service.retry_unsent()

    settings_repo   = SettingsRepository(conn)
    theme = settings_repo.get("theme") or "dark"
    if theme not in ("dark", "light"):
        theme = "dark"
    set_current_theme(theme)
    apply_palette(app, theme)
    app.setStyleSheet(get_stylesheet(theme))
    logger.info(f"Theme: {theme}")

    # App icon (loaded from bundled assets — silently skipped if not yet generated)
    if asset_exists("oh.ico"):
        app.setWindowIcon(QIcon(str(asset_path("oh.ico"))))

    assignment_repo = SourceAssignmentRepository(conn)
    account_repo    = AccountRepository(conn)
    tag_repo        = TagRepository(conn)

    session_service = SessionService(
        session_repo=SessionRepository(conn),
        tag_repo=tag_repo,
        account_repo=account_repo,
    )

    scan_service = ScanService(
        account_repo=account_repo,
        device_repo=DeviceRepository(conn),
        sync_repo=SyncRepository(conn),
        session_service=session_service,
        assignment_repo=assignment_repo,
    )
    source_profile_repo   = SourceProfileRepository(conn)
    fbr_snapshot_repo     = FBRSnapshotRepository(conn)
    fbr_service = FBRService(
        snapshot_repo=fbr_snapshot_repo,
        account_repo=account_repo,
        settings_repo=settings_repo,
        assignment_repo=assignment_repo,
        source_profile_repo=source_profile_repo,
    )
    global_sources_service = GlobalSourcesService(
        account_repo=account_repo,
        assignment_repo=assignment_repo,
    )
    delete_history_repo   = DeleteHistoryRepository(conn)
    source_delete_service = SourceDeleteService(
        assignment_repo=assignment_repo,
        history_repo=delete_history_repo,
        settings_repo=settings_repo,
        global_sources_service=global_sources_service,
        fbr_snapshot_repo=fbr_snapshot_repo,
    )

    logger.info("All services initialised.  Launching main window.")

    operator_action_repo = OperatorActionRepository(conn)

    operator_action_service = OperatorActionService(
        account_repo=account_repo,
        tag_repo=tag_repo,
        action_repo=operator_action_repo,
    )

    source_search_repo = SourceSearchRepository(conn)
    source_finder_service = SourceFinderService(
        search_repo=source_search_repo,
        account_repo=account_repo,
        settings_repo=settings_repo,
        source_profile_repo=source_profile_repo,
    )

    bulk_discovery_repo = BulkDiscoveryRepository(conn)
    bulk_discovery_service = BulkDiscoveryService(
        bulk_repo=bulk_discovery_repo,
        source_finder_service=source_finder_service,
        account_repo=account_repo,
        assignment_repo=assignment_repo,
        settings_repo=settings_repo,
    )

    recommendation_service = RecommendationService(
        global_sources_service=global_sources_service,
        account_repo=account_repo,
        tag_repo=tag_repo,
        settings_repo=settings_repo,
        source_profile_repo=source_profile_repo,
    )

    account_detail_service = None
    if AccountDetailService is not None:
        try:
            account_detail_service = AccountDetailService(
                operator_action_repo=operator_action_repo,
                settings_repo=settings_repo,
            )
            logger.info("AccountDetailService initialised.")
        except Exception:
            logger.warning("AccountDetailService failed to initialise.", exc_info=True)

    blacklist_repo = BlacklistRepository(conn)

    # Block detection
    block_event_repo = BlockEventRepository(conn)
    session_repo = SessionRepository(conn)
    block_detection_service = BlockDetectionService(
        block_repo=block_event_repo,
        session_repo=session_repo,
    )

    # Account groups
    account_group_repo = AccountGroupRepository(conn)
    account_group_service = AccountGroupService(
        group_repo=account_group_repo,
    )

    # Trend service
    trend_service = TrendService(
        session_repo=session_repo,
        fbr_snapshot_repo=fbr_snapshot_repo,
    )

    # Auto-fix (self-healing)
    auto_fix_service = AutoFixService(
        conn=conn,
        settings_repo=settings_repo,
        operator_action_service=operator_action_service,
        source_delete_service=source_delete_service,
        account_repo=account_repo,
        tag_repo=tag_repo,
        assignment_repo=assignment_repo,
    )

    # Warmup templates
    warmup_template_repo = WarmupTemplateRepository(conn)
    warmup_template_service = WarmupTemplateService(
        warmup_repo=warmup_template_repo,
        account_repo=account_repo,
        action_repo=operator_action_repo,
        settings_repo=settings_repo,
    )

    # Settings copier
    settings_copier_service = SettingsCopierService(
        account_repo=account_repo,
        action_repo=operator_action_repo,
        settings_repo=settings_repo,
    )

    window = MainWindow(
        conn,
        scan_service,
        fbr_service,
        global_sources_service,
        source_delete_service,
        session_service=session_service,
        operator_action_service=operator_action_service,
        operator_action_repo=operator_action_repo,
        tag_repo=tag_repo,
        recommendation_service=recommendation_service,
        source_finder_service=source_finder_service,
        bulk_discovery_service=bulk_discovery_service,
        account_detail_service=account_detail_service,
        blacklist_repo=blacklist_repo,
        error_report_service=error_report_service,
        block_detection_service=block_detection_service,
        account_group_service=account_group_service,
        account_group_repo=account_group_repo,
        trend_service=trend_service,
        auto_fix_service=auto_fix_service,
        settings_copier_service=settings_copier_service,
        warmup_template_service=warmup_template_service,
    )
    window.show()

    exit_code = app.exec()
    logger.info(f"OH exiting with code {exit_code}.")
    close_connection()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
