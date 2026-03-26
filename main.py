"""
OH — Operational Hub
Entry point: bootstraps DB, applies migrations, launches the desktop UI.
"""
import sys
import logging
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor

from oh.db.connection import get_connection, close_connection
from oh.db.migrations import run_migrations
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.sync_repo import SyncRepository
from oh.ui.main_window import MainWindow

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


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


def bootstrap(conn) -> None:
    """Apply migrations, seed config defaults, recover interrupted sync runs."""
    run_migrations(conn)
    settings_repo = SettingsRepository(conn)
    settings_repo.seed_defaults()
    sync_repo = SyncRepository(conn)
    recovered = sync_repo.recover_stale_runs()
    if recovered:
        logger.warning(f"Recovered {recovered} stale sync run(s) from previous session.")


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("OH — Operational Hub")
    app.setStyle("Fusion")

    conn = get_connection()
    bootstrap(conn)

    theme = SettingsRepository(conn).get("theme") or "dark"
    if theme == "dark":
        apply_dark_palette(app)

    window = MainWindow(conn)
    window.show()

    exit_code = app.exec()
    close_connection()
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
