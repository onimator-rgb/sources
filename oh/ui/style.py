"""
OH application stylesheets — dark and light themes.

Call get_stylesheet(theme) in main() and pass the result to app.setStyleSheet().
Call apply_palette(app, theme) to set the QPalette for Fusion style.
Import semantic_colors(theme) to get theme-aware QColor values for Python-side rendering.
"""
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPalette, QColor


# ---------------------------------------------------------------------------
# Font size bump: 13px base (up from 11px) for readability
# ---------------------------------------------------------------------------

_FONT_SIZE = "13px"
_FONT_SIZE_SMALL = "11px"
_FONT_SIZE_TOOLTIP = "12px"
_BTN_MIN_HEIGHT = "32px"
_TAB_PADDING = "9px 22px"
_CELL_PADDING = "6px 10px"
_INPUT_PADDING = "6px 10px"


# ---------------------------------------------------------------------------
# Semantic color palette — used by Python UI code for foreground colors
# ---------------------------------------------------------------------------

_DARK_COLORS = {
    "critical":       QColor("#f06060"),   # bright red on dark
    "high":           QColor("#f0b830"),   # bright amber on dark
    "medium":         QColor("#70b0e0"),   # soft blue on dark
    "low":            QColor("#909090"),   # light gray on dark
    "success":        QColor("#50c080"),   # green on dark
    "warning":        QColor("#f0b830"),   # amber (same as high)
    "error":          QColor("#f06060"),   # red (same as critical)
    "muted":          QColor("#777777"),   # dim text on dark
    "dimmed":         QColor("#666666"),   # very dim (removed/disabled)
    "yes":            QColor("#50c080"),   # boolean true
    "no":             QColor("#f06060"),   # boolean false
    "orphan":         QColor("#d09020"),   # orphan status
    "text":           QColor("#e8e8e8"),   # primary text
    "text_secondary":  QColor("#aaaaaa"),  # secondary/label text
    "heading":        QColor("#d0e0f0"),   # section headings
    "heading_urgent": QColor("#f06060"),   # urgent section heading
    "border":         QColor("#3e3e44"),   # frame borders
    "border_urgent":  QColor("#664444"),   # urgent section border
    "bg_note":        QColor("#2a2a2e"),   # note/info box background
    "note_text":      QColor("#bbbbbb"),   # note/info text
    "link":           QColor("#70b0e0"),   # clickable link text
    "status_ok":      QColor("#50c080"),   # status feedback
}

_LIGHT_COLORS = {
    "critical":       QColor("#cc2020"),   # strong red on light
    "high":           QColor("#b07800"),   # dark amber on light
    "medium":         QColor("#2060a0"),   # strong blue on light
    "low":            QColor("#707070"),   # medium gray on light
    "success":        QColor("#1a8a4a"),   # dark green on light
    "warning":        QColor("#b07800"),   # amber
    "error":          QColor("#cc2020"),   # red
    "muted":          QColor("#888888"),   # dim text on light
    "dimmed":         QColor("#aaaaaa"),   # very dim
    "yes":            QColor("#1a8a4a"),   # boolean true
    "no":             QColor("#cc2020"),   # boolean false
    "orphan":         QColor("#a06000"),   # orphan status
    "text":           QColor("#1a1a1a"),   # primary text
    "text_secondary":  QColor("#555555"),  # secondary/label text
    "heading":        QColor("#1a3050"),   # section headings
    "heading_urgent": QColor("#cc2020"),   # urgent section heading
    "border":         QColor("#cccccc"),   # frame borders
    "border_urgent":  QColor("#e0a0a0"),   # urgent section border
    "bg_note":        QColor("#f0f0f4"),   # note/info box background
    "note_text":      QColor("#555555"),   # note/info text
    "link":           QColor("#2060a0"),   # clickable link text
    "status_ok":      QColor("#1a8a4a"),   # status feedback
}

_CURRENT_THEME = "dark"


def set_current_theme(theme: str) -> None:
    """Set the current theme name. Called once at startup."""
    global _CURRENT_THEME
    _CURRENT_THEME = theme


def semantic_colors(theme: str = None) -> dict:
    """Return the semantic color dict for the given (or current) theme."""
    t = theme or _CURRENT_THEME
    return _LIGHT_COLORS if t == "light" else _DARK_COLORS


def sc(name: str, theme: str = None) -> QColor:
    """Shorthand: get one semantic color by name."""
    return semantic_colors(theme)[name]


# ---------------------------------------------------------------------------
# Palette
# ---------------------------------------------------------------------------

def apply_palette(app: QApplication, theme: str = "dark") -> None:
    """Apply a QPalette matching the given theme to the Fusion style."""
    p = QPalette()
    if theme == "light":
        p.setColor(QPalette.ColorRole.Window,          QColor(243, 243, 243))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(30, 30, 30))
        p.setColor(QPalette.ColorRole.Base,            QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(245, 245, 248))
        p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(255, 255, 220))
        p.setColor(QPalette.ColorRole.ToolTipText,     QColor(30, 30, 30))
        p.setColor(QPalette.ColorRole.Text,            QColor(30, 30, 30))
        p.setColor(QPalette.ColorRole.Button,          QColor(230, 230, 234))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(30, 30, 30))
        p.setColor(QPalette.ColorRole.BrightText,      QColor(200, 40, 40))
        p.setColor(QPalette.ColorRole.Link,            QColor(0, 100, 200))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(0, 120, 212))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Mid,             QColor(200, 200, 205))
        p.setColor(QPalette.ColorRole.Dark,            QColor(180, 180, 185))
    else:  # dark
        p.setColor(QPalette.ColorRole.Window,          QColor(40, 40, 43))
        p.setColor(QPalette.ColorRole.WindowText,      QColor(230, 230, 230))
        p.setColor(QPalette.ColorRole.Base,            QColor(28, 28, 30))
        p.setColor(QPalette.ColorRole.AlternateBase,   QColor(36, 36, 40))
        p.setColor(QPalette.ColorRole.ToolTipBase,     QColor(25, 25, 25))
        p.setColor(QPalette.ColorRole.ToolTipText,     QColor(230, 230, 230))
        p.setColor(QPalette.ColorRole.Text,            QColor(230, 230, 230))
        p.setColor(QPalette.ColorRole.Button,          QColor(55, 55, 60))
        p.setColor(QPalette.ColorRole.ButtonText,      QColor(230, 230, 230))
        p.setColor(QPalette.ColorRole.BrightText,      QColor(255, 80, 80))
        p.setColor(QPalette.ColorRole.Link,            QColor(86, 156, 214))
        p.setColor(QPalette.ColorRole.Highlight,       QColor(0, 120, 212))
        p.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
        p.setColor(QPalette.ColorRole.Mid,             QColor(60, 60, 65))
        p.setColor(QPalette.ColorRole.Dark,            QColor(35, 35, 38))
    app.setPalette(p)


# ---------------------------------------------------------------------------
# Stylesheet
# ---------------------------------------------------------------------------

def get_stylesheet(theme: str = "dark") -> str:
    """Return the full QSS stylesheet for the given theme."""
    if theme == "light":
        return _LIGHT_QSS
    return _DARK_QSS


# ===================================================================
# DARK THEME
# ===================================================================

_DARK_QSS = f"""
/* Global */
QWidget {{
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: {_FONT_SIZE};
}}

QMainWindow, QDialog {{
    background: #282830;
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid #3e3e44;
    border-top: none;
    background: #282830;
}}
QTabBar::tab {{
    background: #222226;
    color: #bbb;
    padding: {_TAB_PADDING};
    border: 1px solid #3e3e44;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: #282830;
    color: #eee;
    border-bottom: 2px solid #0078d4;
}}
QTabBar::tab:hover:!selected {{
    background: #2e2e34;
    color: #ddd;
}}

/* Brand / Settings bars */
QFrame#settingsBar {{
    background: #1c1c20;
    border: 1px solid #3e3e44;
    border-radius: 4px;
}}
QFrame#brandBar {{
    background: #141418;
    border-bottom: 1px solid #3e3e44;
    min-height: 40px;
    max-height: 40px;
}}

/* Buttons */
QPushButton {{
    background: #3e3e46;
    color: #eee;
    border: 1px solid #5a5a62;
    border-radius: 4px;
    padding: 5px 14px;
    min-height: {_BTN_MIN_HEIGHT};
}}
QPushButton:hover {{
    background: #4c4c56;
    border-color: #707078;
}}
QPushButton:pressed {{
    background: #333338;
}}
QPushButton:disabled {{
    background: #2a2a2e;
    color: #555;
    border-color: #3a3a3e;
}}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #1c1c20;
    color: #e8e8e8;
    border: 1px solid #4a4a50;
    border-radius: 3px;
    padding: {_INPUT_PADDING};
    selection-background-color: #0078d4;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: #0078d4;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: #222226;
    border: 1px solid #4a4a50;
    selection-background-color: #0078d4;
    color: #e8e8e8;
    outline: none;
}}

/* Tables */
QTableWidget {{
    background: #1c1c20;
    alternate-background-color: #222228;
    gridline-color: #333338;
    color: #e8e8e8;
    border: 1px solid #3e3e44;
    selection-background-color: #0d4070;
    selection-color: #f0f0f0;
}}
QHeaderView::section {{
    background: #222228;
    color: #ccc;
    border: none;
    border-right: 1px solid #3e3e44;
    border-bottom: 2px solid #3e3e44;
    padding: {_CELL_PADDING};
    font-weight: bold;
    font-size: {_FONT_SIZE_SMALL};
}}
QHeaderView::section:hover {{
    background: #2c2c34;
    color: #eee;
}}

/* Checkboxes */
QCheckBox {{
    spacing: 6px;
    color: #e0e0e0;
}}

/* Group boxes */
QGroupBox {{
    border: 1px solid #3e3e44;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
    color: #ccc;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* Status bar */
QStatusBar {{
    background: #1a1a1e;
    color: #aaa;
    border-top: 1px solid #3e3e44;
    font-size: {_FONT_SIZE_SMALL};
}}

/* Scroll bars */
QScrollBar:vertical {{
    background: #1c1c20;
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: #444450;
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #555562; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: #1c1c20;
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: #444450;
    border-radius: 6px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: #555562; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Tooltips */
QToolTip {{
    background: #1a1a1e;
    color: #e8e8e8;
    border: 1px solid #4a4a50;
    padding: 6px 10px;
    font-size: {_FONT_SIZE_TOOLTIP};
}}

/* Dialogs */
QDialog {{
    background: #282830;
}}
QMessageBox {{
    background: #282830;
}}
"""


# ===================================================================
# LIGHT THEME
# ===================================================================

_LIGHT_QSS = f"""
/* Global */
QWidget {{
    font-family: "Segoe UI", Arial, sans-serif;
    font-size: {_FONT_SIZE};
}}

QMainWindow, QDialog {{
    background: #f3f3f3;
}}

/* Tabs */
QTabWidget::pane {{
    border: 1px solid #ccc;
    border-top: none;
    background: #f3f3f3;
}}
QTabBar::tab {{
    background: #e8e8ec;
    color: #444;
    padding: {_TAB_PADDING};
    border: 1px solid #ccc;
    border-bottom: none;
    border-top-left-radius: 4px;
    border-top-right-radius: 4px;
    margin-right: 2px;
}}
QTabBar::tab:selected {{
    background: #f3f3f3;
    color: #111;
    border-bottom: 2px solid #0078d4;
}}
QTabBar::tab:hover:!selected {{
    background: #eee;
    color: #222;
}}

/* Brand / Settings bars */
QFrame#settingsBar {{
    background: #e8e8ec;
    border: 1px solid #ccc;
    border-radius: 4px;
}}
QFrame#brandBar {{
    background: #dde4ec;
    border-bottom: 1px solid #bcc;
    min-height: 40px;
    max-height: 40px;
}}

/* Buttons */
QPushButton {{
    background: #e4e4e8;
    color: #1a1a1a;
    border: 1px solid #bbb;
    border-radius: 4px;
    padding: 5px 14px;
    min-height: {_BTN_MIN_HEIGHT};
}}
QPushButton:hover {{
    background: #d4d4da;
    border-color: #999;
}}
QPushButton:pressed {{
    background: #c4c4ca;
}}
QPushButton:disabled {{
    background: #eee;
    color: #aaa;
    border-color: #ccc;
}}

/* Inputs */
QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox {{
    background: #fff;
    color: #1a1a1a;
    border: 1px solid #bbb;
    border-radius: 3px;
    padding: {_INPUT_PADDING};
    selection-background-color: #0078d4;
    selection-color: #fff;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus {{
    border-color: #0078d4;
}}
QComboBox::drop-down {{
    border: none;
    width: 22px;
}}
QComboBox QAbstractItemView {{
    background: #fff;
    border: 1px solid #bbb;
    selection-background-color: #0078d4;
    selection-color: #fff;
    color: #1a1a1a;
    outline: none;
}}

/* Tables */
QTableWidget {{
    background: #fff;
    alternate-background-color: #f7f7fa;
    gridline-color: #ddd;
    color: #1a1a1a;
    border: 1px solid #ccc;
    selection-background-color: #cce4ff;
    selection-color: #111;
}}
QHeaderView::section {{
    background: #e8e8ec;
    color: #333;
    border: none;
    border-right: 1px solid #ccc;
    border-bottom: 2px solid #ccc;
    padding: {_CELL_PADDING};
    font-weight: bold;
    font-size: {_FONT_SIZE_SMALL};
}}
QHeaderView::section:hover {{
    background: #ddd;
    color: #111;
}}

/* Checkboxes */
QCheckBox {{
    spacing: 6px;
    color: #1a1a1a;
}}

/* Group boxes */
QGroupBox {{
    border: 1px solid #ccc;
    border-radius: 4px;
    margin-top: 8px;
    padding-top: 16px;
    color: #333;
    font-weight: bold;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
}}

/* Status bar */
QStatusBar {{
    background: #e8e8ec;
    color: #555;
    border-top: 1px solid #ccc;
    font-size: {_FONT_SIZE_SMALL};
}}

/* Scroll bars */
QScrollBar:vertical {{
    background: #f0f0f0;
    width: 12px;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: #c0c0c8;
    border-radius: 6px;
    min-height: 24px;
}}
QScrollBar::handle:vertical:hover {{ background: #a0a0a8; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}

QScrollBar:horizontal {{
    background: #f0f0f0;
    height: 12px;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: #c0c0c8;
    border-radius: 6px;
    min-width: 24px;
}}
QScrollBar::handle:horizontal:hover {{ background: #a0a0a8; }}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0; }}

/* Tooltips */
QToolTip {{
    background: #fffde0;
    color: #222;
    border: 1px solid #ccc;
    padding: 6px 10px;
    font-size: {_FONT_SIZE_TOOLTIP};
}}

/* Dialogs */
QDialog {{
    background: #f3f3f3;
}}
QMessageBox {{
    background: #f3f3f3;
}}
"""
