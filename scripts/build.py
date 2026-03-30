"""
Clean build script for OH.

Usage:
    python scripts/build.py

Steps:
  1. Updates oh/version.py with current commit hash and date
  2. Cleans build/ and dist/ directories
  3. Generates placeholder assets if missing
  4. Runs PyInstaller with OH.spec
"""
import os
import shutil
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).parent.parent


def get_commit_hash() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        return result.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


def update_version():
    commit = get_commit_hash()
    today = date.today().isoformat()
    version = f"{today}_{commit}"

    version_file = ROOT / "oh" / "version.py"
    version_file.write_text(
        '"""\nBuild version info for OH.\n\n'
        "Updated before each PyInstaller build.  The UI reads BUILD_VERSION\n"
        "to display which build is running — so operators can verify they\n"
        'have the latest .exe.\n"""\n\n'
        f'BUILD_VERSION = "{version}"\n'
        f'BUILD_DATE = "{today}"\n'
        f'BUILD_COMMIT = "{commit}"\n',
        encoding="utf-8",
    )
    print(f"Version: {version}")
    return version


def clean():
    for d in ["build", "dist"]:
        p = ROOT / d
        if p.exists():
            print(f"Cleaning {p}...")
            shutil.rmtree(p)


def generate_assets():
    script = ROOT / "scripts" / "generate_placeholder_assets.py"
    ico = ROOT / "oh" / "assets" / "oh.ico"
    if not ico.exists():
        print("Generating placeholder assets...")
        subprocess.run([sys.executable, str(script)], cwd=str(ROOT))
    else:
        print("Assets already exist.")


def build():
    print("Running PyInstaller...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", "OH.spec"],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("BUILD FAILED")
        sys.exit(1)

    exe = ROOT / "dist" / "OH.exe"
    if exe.exists():
        size_mb = exe.stat().st_size / (1024 * 1024)
        print(f"\nBuild successful: {exe}  ({size_mb:.1f} MB)")
    else:
        print("ERROR: dist/OH.exe not found after build")
        sys.exit(1)


def main():
    print("=" * 50)
    print("OH — Clean Build")
    print("=" * 50)

    version = update_version()
    clean()
    generate_assets()
    build()

    print(f"\nDone. Build version: {version}")


if __name__ == "__main__":
    main()
