# OH — Operational Hub

> Desktop monitoring & management dashboard for Onimator bot operations at scale.

OH connects to the Onimator bot directory and provides a unified view of all devices, accounts, source assignments, FBR analytics, and consumption metrics — **without modifying the bot's runtime behaviour**.

Built with **Python** and **PySide6 (Qt 6)** for Windows. Single-file `.exe` distribution via PyInstaller.

---

## Problem

Operating Onimator across many devices and accounts creates challenges that grow with scale:

| Challenge | Manual approach | OH solution |
|-----------|----------------|-------------|
| **Visibility** | Open each device folder, check each account | Single table with all accounts, statuses, and configs |
| **FBR Analytics** | Read `data.db` per account, compute manually | One-click batch analysis with quality thresholds |
| **Source Management** | Edit `sources.txt` in dozens of folders | Global source view with single/bulk delete and revert |
| **Usage Tracking** | Read per-source SQLite DBs across accounts | Aggregated Used count & Used % with drill-down |

---

## Features

### Account Discovery & Sync
- Auto-discovers devices and accounts from bot folder structure
- Tracks active, removed, and orphan accounts
- Reads per-account configuration (follow/unfollow limits, status)
- Persistent account registry with sync history

### FBR Analytics
- Computes Follow-Back Rate per source per account from `data.db`
- Configurable quality thresholds (min follows, min FBR %)
- Anomaly detection (followback > follow count)
- Persisted snapshots for historical comparison
- Batch analysis across all active accounts

### Global Source Aggregation
- Cross-account view of every known source
- Average FBR, weighted FBR (by follow volume), quality counts
- Filterable by name, active accounts, follows, FBR status
- Drill-down detail pane with per-account metrics

### Source Usage Metrics
- **Used count** — processed users per source (from `sources/{name}.db`)
- **Used %** — consumption percentage (derived from `.stm` files)
- Shown per-account and in global detail pane

### Source Deletion & Revert
- Remove underperforming sources from `sources.txt` across accounts
- Single-source, per-account, or bulk delete (by FBR threshold)
- Confirmation dialog with affected account list
- Full deletion history with audit trail
- **Revert** — restore previously deleted sources with one click

### Per-Account Source Dialog
- Merged view combining `sources.txt`, `data.db`, FBR, and usage data
- 10-column table: Source, Status, sources.txt, data.db, Follows, Followbacks, FBR %, Quality, Used, Used %
- Delete sources from individual accounts

---

## UI Overview

| Tab | Purpose |
|-----|---------|
| **Accounts** | Master account list — status, FBR summary, source counts, per-account actions |
| **Sources** | Global source aggregation — filters, detail pane, delete/revert, history |
| **Settings** | Bot root path, FBR thresholds, delete config, theme |

---

## Quick Start

### Requirements
- Python 3.9+
- Windows 10/11

### Setup

```bash
git clone https://github.com/onimator-rgb/sources.git
cd sources

python -m venv venv
venv\Scripts\activate

pip install -r requirements.txt
```

### Run

```bash
python main.py
```

On first launch:
1. Set the **Onimator path** in the top bar (e.g. `C:\Users\Admin\Desktop\full_igbot_13.9.0`)
2. Click **Save**
3. Click **Scan & Sync** to discover accounts

### Build `.exe`

```bash
python scripts/generate_placeholder_assets.py
python -m PyInstaller OH.spec
# Output: dist/OH.exe
```

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌───────────────┐     ┌──────────┐
│   UI Layer   │────▶│   Services   │────▶│   Modules     │────▶│ Bot Files│
│  (PySide6)   │     │ (orchestrate)│     │ (read-only*)  │     │ (on disk)│
└─────────────┘     └──────┬───────┘     └───────────────┘     └──────────┘
                           │
                    ┌──────▼───────┐     ┌───────────────┐
                    │ Repositories │────▶│   oh.db        │
                    │ (CRUD)       │     │ (SQLite/WAL)   │
                    └──────────────┘     └───────────────┘
```

\* _Modules are strictly read-only except `SourceDeleter` and `SourceRestorer` which modify `sources.txt` with backup._

| Layer | Location | Responsibility |
|-------|----------|---------------|
| **modules/** | `oh/modules/` | Stateless readers of bot files — discovery, FBR, inspection, usage |
| **repositories/** | `oh/repositories/` | CRUD on OH's internal database — never touches bot files |
| **services/** | `oh/services/` | Orchestrators combining modules + repositories |
| **ui/** | `oh/ui/` | PySide6 widgets — calls services, never accesses bot files directly |

---

## Project Structure

```
OH/
├── main.py                             # Entry point
├── OH.spec                             # PyInstaller config
├── requirements.txt                    # PySide6>=6.6.0
│
├── oh/
│   ├── db/
│   │   ├── connection.py               # SQLite connection (WAL, FK)
│   │   └── migrations.py               # Schema migrations (5 versions)
│   │
│   ├── models/                         # Pure dataclasses
│   │   ├── account.py                  # AccountRecord, DiscoveredAccount, DeviceRecord
│   │   ├── fbr.py                      # SourceFBRRecord, FBRAnalysisResult
│   │   ├── fbr_snapshot.py             # FBRSnapshotRecord, BatchFBRResult
│   │   ├── global_source.py            # GlobalSourceRecord, SourceAccountDetail
│   │   ├── source.py                   # SourceRecord, SourceInspectionResult
│   │   ├── source_usage.py             # SourceUsageRecord, SourceUsageResult
│   │   ├── sync.py                     # SyncRun
│   │   └── delete_history.py           # DeleteAction, DeleteItem
│   │
│   ├── modules/                        # Bot file readers
│   │   ├── discovery.py                # Account & device discovery
│   │   ├── fbr_calculator.py           # FBR computation from data.db
│   │   ├── source_inspector.py         # sources.txt + data.db reader
│   │   ├── source_usage_reader.py      # sources/*.db + .stm reader
│   │   ├── source_deleter.py           # Remove sources (destructive)
│   │   ├── source_restorer.py          # Restore sources (revert)
│   │   └── sync_module.py              # Account config reader
│   │
│   ├── repositories/                   # OH database layer
│   │   ├── account_repo.py
│   │   ├── device_repo.py
│   │   ├── settings_repo.py
│   │   ├── sync_repo.py
│   │   ├── source_assignment_repo.py
│   │   ├── fbr_snapshot_repo.py
│   │   └── delete_history_repo.py
│   │
│   ├── services/                       # Business logic
│   │   ├── scan_service.py             # Scan & sync coordination
│   │   ├── fbr_service.py              # FBR analysis + snapshots
│   │   ├── global_sources_service.py   # Cross-account aggregation
│   │   └── source_delete_service.py    # Delete & revert orchestration
│   │
│   └── ui/                             # Desktop interface
│       ├── main_window.py              # Main window + Accounts tab
│       ├── sources_tab.py              # Global Sources tab
│       ├── settings_tab.py             # Settings tab
│       ├── source_dialog.py            # Per-account Sources dialog
│       ├── delete_confirm_dialog.py    # Delete confirmation
│       ├── delete_history_dialog.py    # History viewer + revert
│       ├── style.py                    # Dark theme QSS
│       └── workers.py                  # QThread helpers
│
├── scripts/
│   ├── generate_placeholder_assets.py  # Create oh.ico + logo.png
│   └── create_shortcut.ps1             # Desktop shortcut
│
└── docs/
    └── FEATURES.md                     # Operator-facing feature guide
```

---

## Configuration

All settings stored in `%APPDATA%\OH\oh.db`:

| Setting | Description | Default |
|---------|-------------|---------|
| `bot_root` | Onimator installation directory | _(must be set)_ |
| `min_follows` | Min follow count for "quality" source | `100` |
| `min_fbr_pct` | Min FBR % for "quality" source | `10.0` |
| `delete_threshold` | Weighted FBR % for bulk delete eligibility | `5.0` |
| `theme` | UI theme | `dark` |

---

## Logs

Location: `%APPDATA%\OH\logs\oh.log`

- Rotating: 2 MB per file, 5 backups (10 MB max)
- DEBUG to file, INFO to console
- Prefixes: `[Sources]`, `[SourceUsage]`, `[UsedPct]`, `[Delete]`, `[Revert]`

---

## Safety

- **Read-only** — OH never modifies `data.db`, source databases, `.stm` files, or any bot runtime data
- **Backup** — `sources.txt.bak` created before every delete/restore operation
- **Confirmation** — detailed dialog before any destructive action
- **Audit trail** — all deletions logged with timestamps, machine name, affected accounts
- **Revert** — completed deletions can be reversed from the history dialog

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9+ |
| GUI | PySide6 6.6+ (Qt 6) |
| Database | SQLite 3 (WAL mode) |
| Packaging | PyInstaller |
| Platform | Windows 10/11 |
| Dependencies | PySide6 only — everything else is stdlib |

---

## License

Internal use only. Property of Wizzysocial.
