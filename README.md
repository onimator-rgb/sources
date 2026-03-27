# OH — Operational Hub

Internal desktop tool for monitoring and managing Onimator bot operations at scale.

OH connects to the Onimator bot directory, discovers all devices and accounts, and provides a unified view of account state, source assignments, FBR (Follow-Back Rate) analytics, and source consumption metrics — without touching the bot's runtime behaviour.

## Why OH exists

Operating Onimator across many devices and accounts creates operational challenges:

- **Visibility** — Which accounts are active? Which sources are performing? Which are consuming resources with no return?
- **Analytics** — FBR data exists inside per-account `data.db` files, but comparing it across 100+ accounts manually is impractical.
- **Source management** — Removing underperforming sources from `sources.txt` for dozens of accounts by hand is error-prone and slow.
- **Usage tracking** — Understanding how much of a source's audience has already been processed requires reading per-source SQLite databases across many accounts.

OH solves these by aggregating data from the bot's file structure into a single, searchable desktop interface.

## Features

### Account discovery and sync
- Scans the Onimator bot root for device folders and account directories
- Detects active accounts, orphan folders, and removed accounts
- Reads per-account configuration (follow/unfollow limits, status, last seen)
- Persists account state in OH's internal database for fast access

### Source inspection
- Reads `sources.txt` (active sources) and `data.db` (historical sources) per account
- Merges and deduplicates with case-insensitive normalization
- Shows file presence, assignment status, and source history

### FBR analytics
- Computes Follow-Back Rate per source per account from `data.db`
- Configurable quality thresholds (min follows, min FBR %)
- Anomaly detection (followback count > follow count)
- Persisted snapshots for historical comparison
- Batch analysis across all active accounts

### Source usage metrics
- **Used count** — reads `sources/{name}.db` for each account to count processed users
- **Used %** — derives total source followers from `.stm/{name}-total-followed-percent.txt` to calculate consumption percentage
- Shown per-account in the Sources dialog and in the global Sources detail pane

### Global source aggregation
- Cross-account view of every known source
- Average FBR, weighted FBR, quality counts, assignment counts
- Filterable by name, minimum active accounts, minimum follows, FBR status
- Drill-down detail pane showing per-account metrics for any selected source

### Source deletion
- Remove underperforming sources from `sources.txt` across all assigned accounts
- Single-source delete or bulk delete (by FBR threshold)
- Confirmation dialog with affected account list
- Full deletion history with timestamps

### Settings and configuration
- Bot root path — the Onimator installation directory
- FBR quality thresholds (minimum follows, minimum FBR %)
- Delete threshold for bulk source cleanup
- Theme selection
- All settings persisted in OH's internal database

### Logging
- Rotating log file at `%APPDATA%\OH\logs\oh.log`
- 2 MB per file, 5 backups (10 MB max)
- DEBUG level to file, INFO level to console
- Structured `[SourceUsage]`, `[UsedPct]`, `[Sources]` prefixes for traceability
- Unhandled exception logging

## UI Layout

| Tab | Purpose |
|---|---|
| **Accounts** | Master account list with status, FBR summary, source counts, and per-account actions |
| **Sources** | Global source aggregation table with filters, detail pane, delete actions, and history |
| **Settings** | Bot root path, FBR thresholds, theme, and delete configuration |

### Per-account Sources dialog

Opened from the Accounts tab via the "Sources" button on any account row. Shows a merged table of all sources for that account with columns:

`Source | Status | sources.txt | data.db | Follows | Follow-backs | FBR % | Quality | Used | Used %`

## Requirements

- Python 3.9+
- Windows 10/11 (tested on Windows 11 Pro)

### Python dependencies

```
PySide6>=6.6.0
```

No other external dependencies. OH uses only the Python standard library (`sqlite3`, `logging`, `pathlib`, etc.) beyond PySide6.

## Setup

```bash
# Clone the repository
git clone https://github.com/onimator-rgb/sources.git
cd sources

# Create a virtual environment (recommended)
python -m venv venv
venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## Running in development mode

```bash
python main.py
```

On first launch:
1. Set the **Onimator path** in the settings bar at the top of the window (e.g. `C:\Users\Admin\Desktop\full_igbot_13.9.0`)
2. Click **Save** to persist the path
3. Click **Scan & Sync** to discover accounts

## Configuration

All configuration is stored in OH's internal SQLite database at `%APPDATA%\OH\oh.db`.

| Setting | Description | Default |
|---|---|---|
| `bot_root` | Path to the Onimator bot installation directory | *(must be set manually)* |
| `min_follows` | Minimum follow count for a source to be considered "quality" | 100 |
| `min_fbr_pct` | Minimum FBR % for a source to be considered "quality" | 10.0 |
| `delete_threshold` | Weighted FBR % at or below which sources are eligible for bulk delete | 5.0 |
| `theme` | UI theme (`dark`) | `dark` |

## Logs

Log location: `%APPDATA%\OH\logs\oh.log`

To open the log directory:
```
explorer %APPDATA%\OH\logs
```

Log entries use the format:
```
2026-03-27 14:30:00  INFO      oh.ui.main_window — [Sources] Inspection done: username — 25 total ...
```

Key log prefixes:
- `[Sources]` — source inspection and FBR computation
- `[SourceUsage]` — source usage (Used count) reading
- `[UsedPct]` — Used % derivation and calculation

## Smoke test

After setup:

1. Launch the app: `python main.py`
2. Set bot root path and click Save
3. Click **Scan & Sync** — account table should populate
4. Click **Sources** on any account row — the Sources dialog should show source names, status, and FBR data
5. Switch to the **Sources** tab — click **Refresh Sources** — the global table should populate
6. Click any source row — the detail pane should show per-account data including Used and Used %
7. Check `%APPDATA%\OH\logs\oh.log` — confirm log entries appear

## Packaging to .exe

OH includes a PyInstaller spec file for single-file Windows packaging:

```bash
# Generate placeholder assets (icon + logo) if not already present
python scripts/generate_placeholder_assets.py

# Build the executable
python -m PyInstaller OH.spec

# Output: dist/OH.exe
```

To create a Desktop shortcut after building:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/create_shortcut.ps1
```

## Project structure

```
OH/
├── main.py                          # Entry point — bootstrap, logging, app launch
├── OH.spec                          # PyInstaller build configuration
├── requirements.txt                 # Python dependencies
├── oh/
│   ├── resources.py                 # Asset path resolver (dev vs frozen mode)
│   ├── assets/                      # Bundled icons and logos
│   ├── db/
│   │   ├── connection.py            # SQLite connection management
│   │   └── migrations.py            # Schema migrations
│   ├── models/                      # Domain dataclasses
│   │   ├── account.py               # AccountRecord, DiscoveredAccount
│   │   ├── fbr.py                   # SourceFBRRecord, FBRAnalysisResult
│   │   ├── fbr_snapshot.py          # FBRSnapshotRecord, BatchFBRResult
│   │   ├── global_source.py         # GlobalSourceRecord, SourceAccountDetail
│   │   ├── source.py                # SourceRecord, SourceInspectionResult
│   │   ├── source_usage.py          # SourceUsageRecord, SourceUsageResult
│   │   ├── sync.py                  # SyncRun
│   │   └── delete_history.py        # DeleteHistoryRecord
│   ├── modules/                     # Read-only business logic (reads bot files)
│   │   ├── discovery.py             # Account/device discovery from bot root
│   │   ├── fbr_calculator.py        # FBR computation from data.db
│   │   ├── source_inspector.py      # Source file reader (sources.txt + data.db)
│   │   ├── source_usage_reader.py   # Source consumption reader (sources/*.db + .stm)
│   │   ├── source_deleter.py        # Removes sources from sources.txt
│   │   └── sync_module.py           # Account config reader
│   ├── repositories/                # OH database access layer
│   │   ├── account_repo.py
│   │   ├── settings_repo.py
│   │   ├── sync_repo.py
│   │   ├── source_assignment_repo.py
│   │   ├── fbr_snapshot_repo.py
│   │   └── delete_history_repo.py
│   ├── services/                    # High-level orchestrators
│   │   ├── scan_service.py          # Scan & sync coordination
│   │   ├── fbr_service.py           # FBR analysis + persistence
│   │   ├── global_sources_service.py# Source refresh + global reads
│   │   └── source_delete_service.py # Delete workflow orchestration
│   └── ui/                          # PySide6 interface
│       ├── main_window.py           # Main application window
│       ├── sources_tab.py           # Global Sources tab
│       ├── settings_tab.py          # Settings tab
│       ├── source_dialog.py         # Per-account Sources dialog
│       ├── delete_confirm_dialog.py # Delete confirmation
│       ├── delete_history_dialog.py # Deletion history viewer
│       ├── style.py                 # QSS dark stylesheet
│       └── workers.py               # Background thread helper
└── scripts/
    ├── generate_placeholder_assets.py  # Creates oh.ico + logo.png
    └── create_shortcut.ps1             # Creates Desktop shortcut to dist/OH.exe
```

## Architecture notes

OH is strictly **read-only with respect to bot state**, except for one intentional operation: deleting sources from `sources.txt` files. It never modifies `data.db`, source databases, `.stm` files, or any other bot runtime data.

The application uses a layered architecture:

- **modules/** — pure functions and classes that read bot files from disk. No database writes. No UI dependencies.
- **repositories/** — CRUD operations on OH's own SQLite database. No disk I/O to bot files.
- **services/** — orchestrate modules and repositories. Called by the UI layer.
- **ui/** — PySide6 widgets. Calls services, never touches bot files directly.

OH's internal database (`%APPDATA%\OH\oh.db`) stores account registry, sync history, source assignments, FBR snapshots, settings, and deletion history. It is created automatically on first launch and migrated on subsequent launches if the schema has changed.

## Safety notes

- **Source deletion is destructive** — it modifies `sources.txt` files inside the bot directory. Always review the confirmation dialog before proceeding.
- **Bulk delete** removes all sources at or below the configured FBR threshold across all active accounts. Use with caution.
- **OH does not run the bot** — it is a monitoring and management tool only.
- All deletions are logged in the deletion history (viewable from the Sources tab).

## License

Internal use only. Property of Wizzysocial.
