# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for OH — Operational Hub.

Build command (run from repo root):
    pyinstaller OH.spec

Output:
    dist/OH.exe   (single-file Windows executable)

Prerequisites:
  1. Install deps:    pip install -r requirements.txt pyinstaller
  2. Generate assets: python scripts/generate_placeholder_assets.py
     (creates oh/assets/oh.ico and oh/assets/logo.png)

Notes:
  - The app stores its database at %APPDATA%\\OH\\oh.db  (not bundled).
  - Log files go to %APPDATA%\\OH\\logs\\oh.log.
  - The 'oh/assets' folder is bundled so resources work in frozen mode.
"""
import sys
from pathlib import Path

ROOT = Path(SPECPATH)

# ---------------------------------------------------------------------------
# Icon — use real .ico if present, else skip (exe will have default icon)
# ---------------------------------------------------------------------------

_ico = ROOT / "oh" / "assets" / "oh.ico"
_icon_arg = [str(_ico)] if _ico.exists() else []

# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

block_cipher = None

a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[
        # Bundle the entire assets folder so asset_path() works when frozen
        (str(ROOT / "oh" / "assets"), "oh/assets"),
    ],
    hiddenimports=[
        # PySide6 plugins sometimes need explicit listing
        "PySide6.QtCore",
        "PySide6.QtGui",
        "PySide6.QtWidgets",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # Trim unused large packages from the bundle
        "matplotlib",
        "numpy",
        "pandas",
        "PIL",
        "tkinter",
        "unittest",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ---------------------------------------------------------------------------
# Single-file EXE
# ---------------------------------------------------------------------------

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="OH",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,          # UPX can cause false-positive AV detections — keep off
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # No console window (windowed app)
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=_icon_arg if _icon_arg else None,
    version=None,
)
