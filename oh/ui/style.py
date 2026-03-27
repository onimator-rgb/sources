"""
OH application stylesheet — dark theme built on top of the Fusion QPalette.

Call get_stylesheet() once in main() and pass the result to app.setStyleSheet().
"""


def get_stylesheet() -> str:
    return """
/* ------------------------------------------------------------------ */
/* Global                                                               */
/* ------------------------------------------------------------------ */

QWidget {
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: 11px;
}

QMainWindow, QDialog {
    background: #2d2d30;
}

/* ------------------------------------------------------------------ */
/* QTabWidget                                                           */
/* ------------------------------------------------------------------ */

QTabWidget::pane {
    border: 1px solid #3c3c3f;
    border-top: none;
    background: #2d2d30;
}

QTabBar::tab {
    background: #252528;
    color: #aaa;
    padding: 6px 18px;
    border: 1px solid #3c3c3f;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}

QTabBar::tab:selected {
    background: #2d2d30;
    color: #e0e0e0;
    border-bottom: 2px solid #0078d4;
}

QTabBar::tab:hover:!selected {
    background: #2f2f35;
    color: #ccc;
}

/* ------------------------------------------------------------------ */
/* Settings bar / panels                                                */
/* ------------------------------------------------------------------ */

QFrame#settingsBar {
    background: #1e1e21;
    border: 1px solid #3c3c3f;
    border-radius: 4px;
}

QFrame#brandBar {
    background: #141416;
    border-bottom: 1px solid #3c3c3f;
    min-height: 36px;
    max-height: 36px;
}

/* ------------------------------------------------------------------ */
/* Buttons                                                              */
/* ------------------------------------------------------------------ */

QPushButton {
    background: #3c3c42;
    color: #e0e0e0;
    border: 1px solid #55555a;
    border-radius: 4px;
    padding: 4px 12px;
    min-height: 24px;
}

QPushButton:hover {
    background: #4a4a52;
    border-color: #6a6a72;
}

QPushButton:pressed {
    background: #323238;
}

QPushButton:disabled {
    background: #2a2a2e;
    color: #555;
    border-color: #3a3a3e;
}

/* Primary action buttons — Scan & Sync, Analyze FBR */
QPushButton#primaryBtn {
    background: #0d3d6e;
    border-color: #0e5ca0;
    color: #d0e8ff;
}

QPushButton#primaryBtn:hover {
    background: #0e4d8a;
    border-color: #1370c0;
}

/* Destructive buttons — Delete, Bulk Delete */
QPushButton#dangerBtn {
    background: #5a1a1a;
    border-color: #882222;
    color: #ffcccc;
}

QPushButton#dangerBtn:hover {
    background: #6e2020;
    border-color: #aa3333;
}

/* ------------------------------------------------------------------ */
/* Input fields                                                         */
/* ------------------------------------------------------------------ */

QLineEdit, QComboBox {
    background: #1e1e21;
    color: #d4d4d4;
    border: 1px solid #3c3c3f;
    border-radius: 3px;
    padding: 3px 6px;
    selection-background-color: #0078d4;
}

QLineEdit:focus, QComboBox:focus {
    border-color: #0078d4;
}

QComboBox::drop-down {
    border: none;
    width: 20px;
}

QComboBox QAbstractItemView {
    background: #252528;
    border: 1px solid #3c3c3f;
    selection-background-color: #0078d4;
    color: #d4d4d4;
    outline: none;
}

/* ------------------------------------------------------------------ */
/* Table                                                                */
/* ------------------------------------------------------------------ */

QTableWidget {
    background: #1e1e21;
    alternate-background-color: #252528;
    gridline-color: #2e2e32;
    color: #d4d4d4;
    border: 1px solid #3c3c3f;
    selection-background-color: #0d3d6e;
    selection-color: #e0e0e0;
}

QHeaderView::section {
    background: #252528;
    color: #aaaaaa;
    border: none;
    border-right: 1px solid #3c3c3f;
    border-bottom: 2px solid #3c3c3f;
    padding: 4px 6px;
    font-weight: bold;
}

QHeaderView::section:hover {
    background: #2e2e32;
    color: #d4d4d4;
}

/* ------------------------------------------------------------------ */
/* Status bar                                                           */
/* ------------------------------------------------------------------ */

QStatusBar {
    background: #1a1a1d;
    color: #888;
    border-top: 1px solid #3c3c3f;
    font-size: 10px;
}

/* ------------------------------------------------------------------ */
/* Scroll bars                                                          */
/* ------------------------------------------------------------------ */

QScrollBar:vertical {
    background: #1e1e21;
    width: 10px;
    border: none;
}
QScrollBar::handle:vertical {
    background: #3c3c42;
    border-radius: 5px;
    min-height: 20px;
}
QScrollBar::handle:vertical:hover { background: #505058; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }

QScrollBar:horizontal {
    background: #1e1e21;
    height: 10px;
    border: none;
}
QScrollBar::handle:horizontal {
    background: #3c3c42;
    border-radius: 5px;
    min-width: 20px;
}
QScrollBar::handle:horizontal:hover { background: #505058; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }

/* ------------------------------------------------------------------ */
/* Tooltips                                                             */
/* ------------------------------------------------------------------ */

QToolTip {
    background: #1a1a1d;
    color: #d4d4d4;
    border: 1px solid #3c3c3f;
    padding: 4px 8px;
    font-size: 10px;
}

/* ------------------------------------------------------------------ */
/* Dialogs                                                              */
/* ------------------------------------------------------------------ */

QDialog {
    background: #2d2d30;
}

QMessageBox {
    background: #2d2d30;
}
"""
