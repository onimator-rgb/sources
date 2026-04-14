"""
Take screenshots of OH for documentation.

Reuses main.py bootstrap, adds screenshot capture after UI loads.
Run: python scripts/take_screenshots.py
"""
import sys
import os
import logging
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

SCREENSHOT_DIR = PROJECT_DIR / "docs" / "screenshots"
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(level=logging.WARNING)


def take_screenshot(widget, name: str) -> None:
    from PySide6.QtWidgets import QApplication
    screen = widget.screen() or QApplication.primaryScreen()
    pixmap = screen.grabWindow(widget.winId())
    path = SCREENSHOT_DIR / f"{name}.png"
    pixmap.save(str(path), "PNG")
    print(f"  Saved: {path.name} ({pixmap.width()}x{pixmap.height()})")


def capture_all(win, app):
    """Capture screenshots of all tabs and dialogs."""
    from PySide6.QtCore import Qt, QEvent
    from PySide6.QtGui import QKeyEvent

    print("\nCapturing OH screenshots...")

    # 1. Accounts tab (main view)
    win._tabs.setCurrentIndex(0)
    app.processEvents()
    take_screenshot(win, "01_accounts_tab")

    # 2. Account detail panel (drawer)
    table = win._table
    if table.rowCount() > 0:
        table.selectRow(2)  # pick a middle row for variety
        app.processEvents()
        ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(table, ev)
        app.processEvents()
        take_screenshot(win, "02_account_detail")

        # Switch to Alerts tab
        if hasattr(win, '_detail_panel') and win._detail_panel and win._detail_panel.isVisible():
            try:
                win._detail_panel._tabs.setCurrentIndex(1)
                app.processEvents()
                take_screenshot(win, "03_account_alerts")
            except Exception:
                pass

        # Close drawer
        ev2 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
        app.sendEvent(win, ev2)
        app.processEvents()

    # 3. Sources tab
    win._tabs.setCurrentIndex(1)
    app.processEvents()
    take_screenshot(win, "04_sources_tab")

    # 4. Source Profiles
    win._tabs.setCurrentIndex(2)
    app.processEvents()
    take_screenshot(win, "05_source_profiles_tab")

    # 5. Fleet
    win._tabs.setCurrentIndex(3)
    app.processEvents()
    take_screenshot(win, "06_fleet_tab")

    # 6. Settings
    win._tabs.setCurrentIndex(4)
    app.processEvents()
    take_screenshot(win, "07_settings_tab")

    # Back to Accounts for dialogs
    win._tabs.setCurrentIndex(0)
    app.processEvents()

    # 7. Cockpit
    try:
        win._on_cockpit()
        app.processEvents()
        for w in app.topLevelWidgets():
            if w != win and w.isVisible():
                take_screenshot(w, "08_cockpit")
                w.close()
                break
    except Exception as e:
        print(f"  Cockpit skipped: {e}")

    # 8. Session Report
    try:
        win._on_session_report()
        app.processEvents()
        for w in app.topLevelWidgets():
            if w != win and w.isVisible():
                take_screenshot(w, "09_session_report")
                w.close()
                break
    except Exception as e:
        print(f"  Session skipped: {e}")

    # 9. Recommendations
    try:
        win._on_recommendations()
        app.processEvents()
        for w in app.topLevelWidgets():
            if w != win and w.isVisible():
                take_screenshot(w, "10_recommendations")
                w.close()
                break
    except Exception as e:
        print(f"  Recs skipped: {e}")

    # 10. History
    try:
        win._on_action_history()
        app.processEvents()
        for w in app.topLevelWidgets():
            if w != win and w.isVisible():
                take_screenshot(w, "11_history")
                w.close()
                break
    except Exception as e:
        print(f"  History skipped: {e}")

    print(f"\nDone! Screenshots in: {SCREENSHOT_DIR}")
    app.quit()


def main():
    from PySide6.QtWidgets import QApplication, QMessageBox
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtCore import QTimer

    from oh.db.connection import get_connection
    from oh.db.migrations import run_migrations
    from oh.resources import asset_path, asset_exists

    conn = get_connection()
    run_migrations(conn)

    from oh.repositories.settings_repo import SettingsRepository
    settings_repo = SettingsRepository(conn)
    settings_repo.seed_defaults()

    from oh.repositories.sync_repo import SyncRepository
    sync_repo = SyncRepository(conn)
    sync_repo.recover_stale_runs()

    app = QApplication(sys.argv)
    app.setApplicationName("OH — Operational Hub")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 11))

    from oh.ui.style import set_current_theme, apply_palette, get_stylesheet
    theme = settings_repo.get("theme") or "dark"
    set_current_theme(theme)
    apply_palette(app, theme)
    app.setStyleSheet(get_stylesheet(theme))

    if asset_exists("oh.ico"):
        app.setWindowIcon(QIcon(str(asset_path("oh.ico"))))

    # Build all services (same as main.py)
    from oh.repositories.account_repo import AccountRepository
    from oh.repositories.source_assignment_repo import SourceAssignmentRepository
    from oh.repositories.tag_repo import TagRepository
    from oh.repositories.source_profile_repo import SourceProfileRepository
    from oh.repositories.fbr_snapshot_repo import FBRSnapshotRepository
    from oh.repositories.delete_history_repo import DeleteHistoryRepository
    from oh.repositories.operator_action_repo import OperatorActionRepository
    from oh.repositories.source_search_repo import SourceSearchRepository
    from oh.repositories.bulk_discovery_repo import BulkDiscoveryRepository
    from oh.repositories.blacklist_repo import BlacklistRepository
    from oh.repositories.error_report_repo import ErrorReportRepository
    from oh.repositories.block_event_repo import BlockEventRepository
    from oh.repositories.session_repo import SessionRepository
    from oh.repositories.account_group_repo import AccountGroupRepository
    from oh.repositories.device_repo import DeviceRepository

    from oh.services.scan_service import ScanService
    from oh.services.fbr_service import FBRService
    from oh.services.global_sources_service import GlobalSourcesService
    from oh.services.source_delete_service import SourceDeleteService
    from oh.services.session_service import SessionService
    from oh.services.operator_action_service import OperatorActionService
    from oh.services.recommendation_service import RecommendationService
    from oh.services.source_finder_service import SourceFinderService
    from oh.services.bulk_discovery_service import BulkDiscoveryService
    from oh.services.error_report_service import ErrorReportService
    from oh.services.block_detection_service import BlockDetectionService
    from oh.services.account_group_service import AccountGroupService
    from oh.services.trend_service import TrendService

    try:
        from oh.services.account_detail_service import AccountDetailService
    except ImportError:
        AccountDetailService = None

    assignment_repo = SourceAssignmentRepository(conn)
    account_repo = AccountRepository(conn)
    tag_repo = TagRepository(conn)
    session_repo = SessionRepository(conn)
    source_profile_repo = SourceProfileRepository(conn)
    fbr_snapshot_repo = FBRSnapshotRepository(conn)
    delete_history_repo = DeleteHistoryRepository(conn)
    operator_action_repo = OperatorActionRepository(conn)
    source_search_repo = SourceSearchRepository(conn)
    bulk_discovery_repo = BulkDiscoveryRepository(conn)
    blacklist_repo = BlacklistRepository(conn)
    error_report_repo = ErrorReportRepository(conn)
    block_event_repo = BlockEventRepository(conn)
    account_group_repo = AccountGroupRepository(conn)
    device_repo = DeviceRepository(conn)

    session_service = SessionService(
        session_repo=session_repo, tag_repo=tag_repo, account_repo=account_repo,
    )
    scan_service = ScanService(
        account_repo=account_repo, device_repo=device_repo,
        sync_repo=sync_repo, session_service=session_service,
        assignment_repo=assignment_repo,
    )
    fbr_service = FBRService(
        snapshot_repo=fbr_snapshot_repo, account_repo=account_repo,
        settings_repo=settings_repo, assignment_repo=assignment_repo,
        source_profile_repo=source_profile_repo,
    )
    global_sources_service = GlobalSourcesService(
        account_repo=account_repo, assignment_repo=assignment_repo,
    )
    source_delete_service = SourceDeleteService(
        assignment_repo=assignment_repo, history_repo=delete_history_repo,
        settings_repo=settings_repo, global_sources_service=global_sources_service,
        fbr_snapshot_repo=fbr_snapshot_repo,
    )
    operator_action_service = OperatorActionService(
        account_repo=account_repo, tag_repo=tag_repo, action_repo=operator_action_repo,
    )
    source_finder_service = SourceFinderService(
        search_repo=source_search_repo, account_repo=account_repo,
        settings_repo=settings_repo, source_profile_repo=source_profile_repo,
    )
    bulk_discovery_service = BulkDiscoveryService(
        bulk_repo=bulk_discovery_repo, source_finder_service=source_finder_service,
        account_repo=account_repo, assignment_repo=assignment_repo,
        settings_repo=settings_repo,
    )
    recommendation_service = RecommendationService(
        global_sources_service=global_sources_service, account_repo=account_repo,
        tag_repo=tag_repo, settings_repo=settings_repo,
        source_profile_repo=source_profile_repo,
    )
    error_report_service = ErrorReportService(
        report_repo=error_report_repo, settings_repo=settings_repo, conn=conn,
    )
    block_detection_service = BlockDetectionService(
        block_repo=block_event_repo, session_repo=session_repo,
    )
    account_group_service = AccountGroupService(group_repo=account_group_repo)
    trend_service = TrendService(
        session_repo=session_repo, fbr_snapshot_repo=fbr_snapshot_repo,
    )

    account_detail_service = None
    if AccountDetailService is not None:
        try:
            account_detail_service = AccountDetailService(
                operator_action_repo=operator_action_repo, settings_repo=settings_repo,
            )
        except Exception:
            pass

    from oh.ui.main_window import MainWindow
    win = MainWindow(
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
    )
    win.resize(1400, 850)
    win.show()

    # Take screenshots after 2 seconds (let UI settle)
    QTimer.singleShot(2000, lambda: capture_all(win, app))
    app.exec()
    from oh.db.connection import close_connection
    close_connection()


if __name__ == "__main__":
    main()
