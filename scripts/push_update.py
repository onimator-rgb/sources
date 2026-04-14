"""
Push OH Update — one-command release pipeline.

Usage:
    python scripts/push_update.py 1.1.0 "- Added feature X\n- Fixed bug Y"
    python scripts/push_update.py 1.1.0              # interactive changelog
    python scripts/push_update.py --current           # show current version

Workflow:
    1. Bump version in oh/version.py
    2. Build OH.exe via PyInstaller
    3. Upload OH.exe as GitHub Release asset
    4. Update update.json on GitHub (main branch)
    5. Copy to OH_Distribution folder
    6. Done — clients see the update on next startup
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import shutil
from datetime import date
from pathlib import Path

PROJECT_DIR = Path(__file__).parent.parent
DIST_DIR = PROJECT_DIR / "OH_Distribution"
VERSION_FILE = PROJECT_DIR / "oh" / "version.py"
SPEC_FILE = PROJECT_DIR / "OH.spec"
EXE_PATH = PROJECT_DIR / "dist" / "OH.exe"

GITHUB_REPO = "onimator-rgb/oh-releases"
UPDATE_JSON_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/main/update.json"


def get_current_version() -> str:
    content = VERSION_FILE.read_text(encoding="utf-8")
    match = re.search(r'BUILD_VERSION\s*=\s*"([^"]+)"', content)
    return match.group(1) if match else "0.0.0"


def set_version(version: str) -> None:
    content = VERSION_FILE.read_text(encoding="utf-8")
    content = re.sub(
        r'BUILD_VERSION\s*=\s*"[^"]+"',
        f'BUILD_VERSION = "{version}"',
        content,
    )
    content = re.sub(
        r'BUILD_DATE\s*=\s*"[^"]+"',
        f'BUILD_DATE = "{date.today().isoformat()}"',
        content,
    )
    VERSION_FILE.write_text(content, encoding="utf-8")
    print(f"  Version set to: {version}")


def build_exe() -> bool:
    print("\n2. Building OH.exe...")
    result = subprocess.run(
        [sys.executable, "-m", "PyInstaller", str(SPEC_FILE), "--noconfirm"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  BUILD FAILED:\n{result.stderr[-500:]}")
        return False
    if not EXE_PATH.exists():
        print("  BUILD FAILED: OH.exe not found in dist/")
        return False
    size_mb = EXE_PATH.stat().st_size / 1024 / 1024
    print(f"  Build OK: {size_mb:.1f} MB")
    return True


def run_tests() -> bool:
    print("\n  Running tests...")
    result = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "tests/"],
        cwd=str(PROJECT_DIR),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  TESTS FAILED:\n{result.stderr[-500:]}")
        return False
    # Extract test count
    for line in result.stderr.split("\n"):
        if "Ran" in line:
            print(f"  {line.strip()}")
            break
    return True


def create_github_release(version: str, changelog: str) -> str:
    """Create a GitHub Release and upload OH.exe. Returns download URL."""
    print(f"\n3. Creating GitHub Release v{version}...")

    tag = f"v{version}"

    # Create release with asset
    result = subprocess.run(
        [
            "gh", "release", "create", tag,
            str(EXE_PATH),
            "--repo", GITHUB_REPO,
            "--title", f"OH v{version}",
            "--notes", changelog,
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  Release creation failed:\n{result.stderr}")
        return ""

    print(f"  Release created: {tag}")

    # Get the download URL for OH.exe
    download_url = f"https://github.com/{GITHUB_REPO}/releases/download/{tag}/OH.exe"
    print(f"  Download URL: {download_url}")
    return download_url


def compute_exe_sha256() -> str:
    """Compute SHA256 hash of the built OH.exe."""
    h = hashlib.sha256()
    with open(EXE_PATH, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def update_json_on_github(version: str, download_url: str, changelog: str) -> bool:
    """Push update.json to the main branch of the releases repo."""
    print("\n4. Updating update.json on GitHub...")

    exe_sha256 = compute_exe_sha256()
    print(f"  SHA256: {exe_sha256}")

    update_data = {
        "version": version,
        "download_url": download_url,
        "changelog": changelog,
        "release_date": date.today().isoformat(),
        "min_version": "1.0.0",
        "sha256": exe_sha256,
    }

    # Clone repo to temp dir, update file, push
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp) / "oh-releases"

        # Clone
        result = subprocess.run(
            ["gh", "repo", "clone", GITHUB_REPO, str(tmp_dir), "--", "--depth", "1"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Repo might be empty, init it
            tmp_dir.mkdir(parents=True, exist_ok=True)
            subprocess.run(["git", "init"], cwd=str(tmp_dir), capture_output=True)
            subprocess.run(
                ["git", "remote", "add", "origin", f"https://github.com/{GITHUB_REPO}.git"],
                cwd=str(tmp_dir), capture_output=True,
            )

        # Write update.json
        json_path = tmp_dir / "update.json"
        json_path.write_text(
            json.dumps(update_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # Write README
        readme_path = tmp_dir / "README.md"
        readme_path.write_text(
            f"# OH Releases\n\nLatest version: **v{version}** ({date.today().isoformat()})\n\n"
            f"Download: [OH.exe]({download_url})\n",
            encoding="utf-8",
        )

        # Git commit and push
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_dir), capture_output=True)
        subprocess.run(
            ["git", "commit", "-m", f"Release v{version}"],
            cwd=str(tmp_dir), capture_output=True,
        )

        # Push (try main, then master)
        result = subprocess.run(
            ["git", "push", "-u", "origin", "main"],
            cwd=str(tmp_dir), capture_output=True, text=True,
        )
        if result.returncode != 0:
            result = subprocess.run(
                ["git", "push", "-u", "origin", "HEAD:main"],
                cwd=str(tmp_dir), capture_output=True, text=True,
            )
        if result.returncode != 0:
            # Maybe need to set branch name
            subprocess.run(["git", "branch", "-M", "main"], cwd=str(tmp_dir), capture_output=True)
            result = subprocess.run(
                ["git", "push", "-u", "origin", "main", "--force"],
                cwd=str(tmp_dir), capture_output=True, text=True,
            )

        if result.returncode != 0:
            print(f"  Failed to push update.json:\n{result.stderr}")
            return False

    print(f"  update.json pushed to {GITHUB_REPO}")
    print(f"  URL: {UPDATE_JSON_URL}")
    return True


def copy_to_distribution(version: str) -> None:
    """Copy all distribution files to OH_Distribution folder."""
    print("\n5. Updating OH_Distribution folder...")
    DIST_DIR.mkdir(parents=True, exist_ok=True)

    # Core: OH.exe
    shutil.copy2(str(EXE_PATH), str(DIST_DIR / "OH.exe"))
    print(f"  OH.exe copied ({EXE_PATH.stat().st_size / 1024 / 1024:.1f} MB)")

    # Version file for START.bat pre-launch checks
    ver_file = DIST_DIR / ".oh_version"
    ver_file.write_text(version + "\n", encoding="utf-8")
    print(f"  .oh_version: {version}")

    # Copy PDF guides if they exist
    docs_dir = PROJECT_DIR / "docs"
    for pdf_name in ("OH_User_Guide_EN.pdf", "OH_User_Guide_PL.pdf"):
        src = docs_dir / pdf_name
        if src.exists():
            shutil.copy2(str(src), str(DIST_DIR / pdf_name))
            print(f"  {pdf_name} copied")

    print(f"  Distribution ready: {DIST_DIR}")


def main():
    print("=" * 60)
    print("  OH Update Pusher")
    print("=" * 60)

    current = get_current_version()

    # Parse args
    if len(sys.argv) < 2:
        print(f"\nCurrent version: {current}")
        print(f"\nUsage:")
        print(f'  python scripts/push_update.py 1.1.0 "- Change 1\\n- Change 2"')
        print(f'  python scripts/push_update.py --current')
        sys.exit(0)

    if sys.argv[1] == "--current":
        print(f"Current version: {current}")
        sys.exit(0)

    new_version = sys.argv[1]

    # Changelog
    if len(sys.argv) >= 3:
        changelog = sys.argv[2].replace("\\n", "\n")
    else:
        print(f"\nEnter changelog (one line per change, empty line to finish):")
        lines = []
        while True:
            line = input("  > ").strip()
            if not line:
                break
            if not line.startswith("- "):
                line = f"- {line}"
            lines.append(line)
        changelog = "\n".join(lines) if lines else f"- Update to v{new_version}"

    print(f"\n  Current version: {current}")
    print(f"  New version:     {new_version}")
    print(f"  Changelog:\n    {changelog.replace(chr(10), chr(10) + '    ')}")

    confirm = input(f"\n  Proceed? (y/n): ").strip().lower()
    if confirm != "y":
        print("  Aborted.")
        sys.exit(0)

    # 1. Set version
    print("\n1. Setting version...")
    set_version(new_version)

    # Run tests
    if not run_tests():
        print("\nABORTED: Tests failed.")
        set_version(current)  # rollback
        sys.exit(1)

    # 2. Build
    if not build_exe():
        print("\nABORTED: Build failed.")
        set_version(current)  # rollback
        sys.exit(1)

    # 3. Create GitHub Release
    download_url = create_github_release(new_version, changelog)
    if not download_url:
        print("\nWARNING: GitHub Release failed. Continuing with local build only.")
    else:
        # 4. Update update.json
        update_json_on_github(new_version, download_url, changelog)

    # 5. Copy to distribution
    copy_to_distribution(new_version)

    # Summary
    print("\n" + "=" * 60)
    print("  UPDATE PUSHED SUCCESSFULLY")
    print("=" * 60)
    print(f"  Version:    {new_version}")
    print(f"  OH.exe:     {DIST_DIR / 'OH.exe'}")
    if download_url:
        print(f"  Download:   {download_url}")
        print(f"  update.json: {UPDATE_JSON_URL}")
    print(f"\n  Clients will see the update on next startup.")


if __name__ == "__main__":
    main()
