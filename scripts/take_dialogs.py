"""Take screenshots of modal dialogs by monkey-patching exec() -> show()."""
import sys
import time
from pathlib import Path
from unittest.mock import patch

PROJECT_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_DIR))

import logging
logging.basicConfig(level=logging.WARNING)

SCREENSHOT_DIR = PROJECT_DIR / "docs" / "screenshots"

_dialogs_to_capture = []  # collect dialogs opened via exec()


def take_screenshot(widget, name: str) -> None:
    from PySide6.QtWidgets import QApplication
    screen = widget.screen() or QApplication.primaryScreen()
    pixmap = screen.grabWindow(widget.winId())
    path = SCREENSHOT_DIR / f"{name}.png"
    pixmap.save(str(path), "PNG")
    print(f"  Saved: {path.name} ({pixmap.width()}x{pixmap.height()})")


def main():
    from PySide6.QtWidgets import QApplication, QDialog
    from PySide6.QtGui import QFont, QIcon
    from PySide6.QtCore import QTimer, Qt

    from oh.db.connection import get_connection
    from oh.db.migrations import run_migrations

    conn = get_connection()
    run_migrations(conn)

    from oh.repositories.settings_repo import SettingsRepository
    settings_repo = SettingsRepository(conn)
    settings_repo.seed_defaults()
    from oh.repositories.sync_repo import SyncRepository
    SyncRepository(conn).recover_stale_runs()

    app = QApplication(sys.argv)
    app.setApplicationName("OH")
    app.setStyle("Fusion")
    app.setFont(QFont("Segoe UI", 11))

    from oh.ui.style import set_current_theme, apply_palette, get_stylesheet
    from oh.resources import asset_path, asset_exists
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

    ar = SourceAssignmentRepository(conn)
    acr = AccountRepository(conn)
    tr = TagRepository(conn)
    sr = SessionRepository(conn)
    spr = SourceProfileRepository(conn)
    fsr = FBRSnapshotRepository(conn)
    oar = OperatorActionRepository(conn)
    dr = DeviceRepository(conn)

    ss = SessionService(session_repo=sr, tag_repo=tr, account_repo=acr)
    scs = ScanService(account_repo=acr, device_repo=dr, sync_repo=SyncRepository(conn), session_service=ss, assignment_repo=ar)
    fs = FBRService(snapshot_repo=fsr, account_repo=acr, settings_repo=settings_repo, assignment_repo=ar, source_profile_repo=spr)
    gs = GlobalSourcesService(account_repo=acr, assignment_repo=ar)
    ds = SourceDeleteService(assignment_repo=ar, history_repo=DeleteHistoryRepository(conn), settings_repo=settings_repo, global_sources_service=gs, fbr_snapshot_repo=fsr)
    os_ = OperatorActionService(account_repo=acr, tag_repo=tr, action_repo=oar)
    sfs = SourceFinderService(search_repo=SourceSearchRepository(conn), account_repo=acr, settings_repo=settings_repo, source_profile_repo=spr)
    bs = BulkDiscoveryService(bulk_repo=BulkDiscoveryRepository(conn), source_finder_service=sfs, account_repo=acr, assignment_repo=ar, settings_repo=settings_repo)
    rs = RecommendationService(global_sources_service=gs, account_repo=acr, tag_repo=tr, settings_repo=settings_repo, source_profile_repo=spr)
    es = ErrorReportService(report_repo=ErrorReportRepository(conn), settings_repo=settings_repo, conn=conn)
    bds = BlockDetectionService(block_repo=BlockEventRepository(conn), session_repo=sr)
    ags = AccountGroupService(group_repo=AccountGroupRepository(conn))
    ts = TrendService(session_repo=sr, fbr_snapshot_repo=fsr)
    ads = None
    if AccountDetailService:
        try:
            ads = AccountDetailService(operator_action_repo=oar, settings_repo=settings_repo)
        except Exception:
            pass

    from oh.ui.main_window import MainWindow
    win = MainWindow(conn, scs, fs, gs, ds, session_service=ss, operator_action_service=os_,
        operator_action_repo=oar, tag_repo=tr, recommendation_service=rs, source_finder_service=sfs,
        bulk_discovery_service=bs, account_detail_service=ads, blacklist_repo=BlacklistRepository(conn),
        error_report_service=es, block_detection_service=bds, account_group_service=ags,
        account_group_repo=AccountGroupRepository(conn), trend_service=ts)
    win.resize(1400, 850)
    win.show()

    # Monkey-patch QDialog.exec to capture dialogs without blocking
    _original_exec = QDialog.exec

    def _patched_exec(dialog_self):
        dialog_self.show()
        app.processEvents()
        time.sleep(0.3)
        app.processEvents()
        _dialogs_to_capture.append(dialog_self)
        return QDialog.DialogCode.Accepted.value

    def capture():
        try:
            print("\nCapturing screenshots...")

            # 1. Account detail drawer
            table = win._table
            if table.rowCount() > 2:
                table.selectRow(2)
                app.processEvents()
                from PySide6.QtGui import QKeyEvent
                from PySide6.QtCore import QEvent
                ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Space, Qt.KeyboardModifier.NoModifier)
                app.sendEvent(table, ev)
                app.processEvents()
                time.sleep(0.3)
                app.processEvents()
                take_screenshot(win, "02_account_detail")

                if hasattr(win, '_detail_panel') and win._detail_panel:
                    dp = win._detail_panel
                    if hasattr(dp, '_tabs'):
                        dp._tabs.setCurrentIndex(1)
                        app.processEvents()
                        time.sleep(0.2)
                        app.processEvents()
                        take_screenshot(win, "03_account_alerts")

                ev2 = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
                app.sendEvent(win, ev2)
                app.processEvents()

            # 2. Cockpit — patch exec temporarily
            QDialog.exec = _patched_exec
            try:
                win._on_cockpit()
                app.processEvents()
                time.sleep(0.5)
                app.processEvents()
                for d in _dialogs_to_capture:
                    if 'cockpit' in type(d).__name__.lower() or 'cockpit' in d.windowTitle().lower():
                        take_screenshot(d, "08_cockpit")
                        d.close()
                        break
                _dialogs_to_capture.clear()
            except Exception as e:
                print(f"  Cockpit: {e}")

            # 3. Session Report
            try:
                win._on_session_report()
                app.processEvents()
                time.sleep(0.5)
                app.processEvents()
                for d in _dialogs_to_capture:
                    take_screenshot(d, "09_session_report")
                    d.close()
                    break
                _dialogs_to_capture.clear()
            except Exception as e:
                print(f"  Session: {e}")

            # 4. Recommendations
            try:
                win._on_recommendations()
                app.processEvents()
                time.sleep(0.5)
                app.processEvents()
                for d in _dialogs_to_capture:
                    take_screenshot(d, "10_recommendations")
                    d.close()
                    break
                _dialogs_to_capture.clear()
            except Exception as e:
                print(f"  Recs: {e}")

            QDialog.exec = _original_exec

            print("\nAll done!")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()
            QDialog.exec = _original_exec
        finally:
            app.quit()

    QTimer.singleShot(2000, capture)
    app.exec()
    from oh.db.connection import close_connection
    close_connection()


if __name__ == "__main__":
    main()
