# OH — Installation Guide (Fresh Windows PC)

## Prompt for Claude Code on a new machine

Copy the entire block below and paste it as a prompt to Claude Code on the new PC.
Claude will install everything needed and build the OH application.

---

```
I need you to set up the OH (Operational Hub) application on this fresh Windows PC.
The PC has only Windows installed — no Python, no Git, no development tools.

Follow these steps exactly, in order. Run each command and verify it succeeds before moving to the next.

## STEP 1: Install Git

Run this in PowerShell (not bash):
```powershell
winget install Git.Git --accept-package-agreements --accept-source-agreements
```

After install, verify:
```bash
git --version
```

If `winget` is not available, download Git from https://git-scm.com/download/win and install manually.

## STEP 2: Install Python 3.9+

Run in PowerShell:
```powershell
winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
```

After install, close and reopen terminal, then verify:
```bash
python --version
pip --version
```

Python must be 3.9 or higher. If `python` is not found, check PATH or try `python3`.

## STEP 3: Clone the repository

```bash
cd ~/Desktop
git clone https://github.com/onimator-rgb/sources.git OH
cd OH
```

Verify:
```bash
ls main.py
```

## STEP 4: Create virtual environment and install dependencies

```bash
python -m venv venv
venv\Scripts\activate
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller
```

Verify:
```bash
python -c "import PySide6; print(PySide6.__version__)"
python -m PyInstaller --version
```

## STEP 5: Generate assets

```bash
python scripts/generate_placeholder_assets.py
```

Verify:
```bash
ls oh/assets/oh.ico
```

## STEP 6: Test that the app runs from source

```bash
python main.py
```

The OH window should open. Close it after verifying.

## STEP 7: Build the .exe

```bash
python scripts/build.py
```

This will:
1. Update `oh/version.py` with current commit hash
2. Clean `build/` and `dist/`
3. Run PyInstaller

Verify:
```bash
ls dist/OH.exe
```

The file should be ~45 MB.

## STEP 8: Create Desktop shortcut (optional)

```powershell
powershell -ExecutionPolicy Bypass -File scripts/create_shortcut.ps1
```

## STEP 9: First launch configuration

1. Run `dist/OH.exe` (or the Desktop shortcut)
2. In the top bar, set the **Onimator path** to the bot installation folder
   (e.g., `C:\Users\Admin\Desktop\full_igbot_13.9.0`)
3. Click **Save**
4. Click **Scan & Sync** to discover accounts
5. Click **Cockpit** to see the operations overview

## VERIFICATION CHECKLIST

After completing all steps, verify:
- [ ] `git --version` works
- [ ] `python --version` shows 3.9+
- [ ] `dist/OH.exe` exists and is ~45 MB
- [ ] OH.exe opens without errors
- [ ] Brand bar shows build version (e.g., `build 2026-03-31_abc1234`)
- [ ] Scan & Sync discovers devices and accounts
- [ ] Cockpit shows operational sections

## TROUBLESHOOTING

If `python` command is not found after install:
- Close all terminals and open a new one
- Try `py` instead of `python`
- Check Windows Settings > Apps > App Execution Aliases

If PyInstaller build fails with missing DLLs:
- Make sure you activated the venv: `venv\Scripts\activate`
- Try: `pip install --force-reinstall pyinstaller`

If OH.exe won't start (no window appears):
- Check `%APPDATA%\OH\logs\oh.log` for errors
- Try running from source first: `python main.py`

If Scan & Sync shows "Bot root not set":
- Set the Onimator path in the top settings bar and click Save
```

---

## Quick reference (for manual setup)

| Step | Command |
|------|---------|
| Install Git | `winget install Git.Git` |
| Install Python | `winget install Python.Python.3.12` |
| Clone repo | `git clone https://github.com/onimator-rgb/sources.git OH` |
| Setup venv | `python -m venv venv && venv\Scripts\activate` |
| Install deps | `pip install -r requirements.txt pyinstaller` |
| Generate assets | `python scripts/generate_placeholder_assets.py` |
| Build .exe | `python scripts/build.py` |
| Run | `dist\OH.exe` |

## System requirements

- Windows 10/11
- ~500 MB disk space (Python + PySide6 + build artifacts)
- No admin rights required (user-level Python install works)
- Internet connection for initial setup only
