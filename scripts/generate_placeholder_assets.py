"""
Generate placeholder app icon and logo for OH.

Run this ONCE to create:
  oh/assets/oh.ico    — 256×256 app icon (also embedded in the .exe)
  oh/assets/logo.png  — 32×20 brand logo shown in the header bar

These are intentionally simple placeholder images.
Replace them with real brand assets when available.

Usage:
    python scripts/generate_placeholder_assets.py
"""
import sys
from pathlib import Path

# Make sure we can import from the repo root
sys.path.insert(0, str(Path(__file__).parent.parent))

from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPainter, QColor, QFont, QPixmap, QIcon
from PySide6.QtCore import Qt, QSize

ASSETS_DIR = Path(__file__).parent.parent / "oh" / "assets"
ASSETS_DIR.mkdir(parents=True, exist_ok=True)


def _make_icon_pixmap(size: int) -> QPixmap:
    """Dark square with rounded corners and the 'OH' monogram."""
    px = QPixmap(size, size)
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Background
    p.setBrush(QColor("#0d3d6e"))
    p.setPen(Qt.PenStyle.NoPen)
    radius = size // 6
    p.drawRoundedRect(0, 0, size, size, radius, radius)

    # Monogram
    font = QFont("Segoe UI", size // 3, QFont.Weight.Bold)
    p.setFont(font)
    p.setPen(QColor("#d0e8ff"))
    p.drawText(px.rect(), Qt.AlignmentFlag.AlignCenter, "OH")

    p.end()
    return px


def _make_logo_pixmap(width: int = 96, height: int = 24) -> QPixmap:
    """Brand logo: small icon + 'Wizzysocial' text."""
    px = QPixmap(width, height)
    px.fill(Qt.GlobalColor.transparent)

    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    # Small badge
    badge_size = height - 4
    p.setBrush(QColor("#0d3d6e"))
    p.setPen(Qt.PenStyle.NoPen)
    p.drawRoundedRect(0, 2, badge_size, badge_size, 3, 3)

    font_badge = QFont("Segoe UI", badge_size // 2, QFont.Weight.Bold)
    p.setFont(font_badge)
    p.setPen(QColor("#d0e8ff"))
    from PySide6.QtCore import QRect
    p.drawText(QRect(0, 2, badge_size, badge_size), Qt.AlignmentFlag.AlignCenter, "W")

    # Text
    font_text = QFont("Segoe UI", height // 2 - 1)
    p.setFont(font_text)
    p.setPen(QColor("#d0e8ff"))
    p.drawText(badge_size + 4, height - 6, "Wizzysocial")

    p.end()
    return px


def generate_ico(dest: Path) -> None:
    sizes = [16, 32, 48, 64, 128, 256]
    icon = QIcon()
    for s in sizes:
        icon.addPixmap(_make_icon_pixmap(s), QIcon.Mode.Normal, QIcon.State.Off)

    # Save as PNG first, then rename — QPixmap can't write .ico directly on all platforms.
    # For a real .ico, use Pillow: from PIL import Image
    px = _make_icon_pixmap(256)
    png_dest = dest.with_suffix(".png")
    px.save(str(png_dest))
    # Also save an ico-named png so PyInstaller's --icon flag can use it
    # (PyInstaller on Windows converts PNG → ICO automatically when needed)
    import shutil
    shutil.copy(str(png_dest), str(dest))
    print(f"  icon : {dest}  (256×256 PNG, .ico extension)")


def generate_logo(dest: Path) -> None:
    px = _make_logo_pixmap(96, 24)
    px.save(str(dest))
    print(f"  logo : {dest}  (96×24 PNG)")


if __name__ == "__main__":
    app = QApplication.instance() or QApplication(sys.argv)

    print("Generating placeholder assets…")
    generate_ico(ASSETS_DIR / "oh.ico")
    generate_logo(ASSETS_DIR / "logo.png")
    print("Done.")
