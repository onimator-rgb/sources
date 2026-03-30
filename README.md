# OH — Operational Hub

> Desktop operations dashboard for Onimator bot management at scale.

OH connects to the Onimator bot directory and gives operators a unified control center for all devices, accounts, source assignments, FBR analytics, session monitoring, and operational recommendations — **without modifying the bot's runtime behaviour**.

Built with **Python** and **PySide6 (Qt 6)** for Windows. Single-file `.exe` distribution via PyInstaller.

---

## Problem

Operating Onimator across many devices and accounts creates challenges that grow with scale:

| Challenge | Manual approach | OH solution |
|-----------|----------------|-------------|
| **Visibility** | Open each device folder, check each account | Single table with all accounts, statuses, configs, and session data |
| **FBR Analytics** | Read `data.db` per account, compute manually | One-click batch analysis with quality thresholds |
| **Source Management** | Edit `sources.txt` in dozens of folders | Global source view with single/bulk delete, account cleanup, and revert |
| **Session Monitoring** | No way to see daily follow/like/DM counts | Per-session counters with slot awareness and activity detection |
| **Operational Decisions** | Manually check 100+ accounts for issues | Automated recommendations with severity and suggested actions |
| **Usage Tracking** | Read per-source SQLite DBs across accounts | Aggregated Used count & Used % with drill-down |

---

## Features

### Daily Operations Cockpit
- One-click overview of the entire fleet at shift start
- 5 sections: urgent items, accounts to review, top recommendations, recent source actions, today's activity
- Quick actions: set/clear review, navigate to accounts/sources
- Drilldown to full reports and history

### Session Monitoring
- Daily follow, like, DM, and unfollow counts per account
- Slot-aware activity detection (00-06, 06-12, 12-18, 18-24)
- Automatic collection during Scan & Sync
- Session Report with 8 analysis sections and operator action checklist

### Operator Actions & Tags
- Review flag with notes per account
- TB level tracking (TB1-TB5) with warmup recommendations
- Limits level tracking (1-5) with source refresh guidance
- Full audit trail of all operator actions
- Bot tags parsed from `settings.db` + separate operator tags

### Operational Recommendations
- 6 recommendation types: Weak Source, Source Exhaustion, Low Like, Limits Max, TB Max, Zero Actions
- Severity-based prioritization (CRITICAL / HIGH / MEDIUM / LOW)
- Quick filters: All, Critical+High, Accounts only, Sources only
- Apply recommendations (set review), navigate to targets, copy to clipboard
- Source-level actions: delete weak source, account cleanup

### Account Discovery & Sync
- Auto-discovers devices and accounts from bot folder structure
- Reads per-account configuration, tags, and limits from `settings.db`
- Tracks active, removed, and orphan accounts
- Persistent account registry with sync history
- Device status visualization (running / stop / offline)

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

### Source Management
- Remove underperforming sources from `sources.txt` across accounts
- Single-source, per-account, bulk delete (by FBR threshold), or account cleanup (non-quality sources)
- Preview with checkboxes before any destructive operation
- Full deletion history with audit trail
- **Revert** — restore previously deleted sources with one click
- Revert awareness: every delete message shows how to undo

### Source Usage Metrics
- **Used count** — processed users per source (from `sources/{name}.db`)
- **Used %** — consumption percentage (derived from `.stm` files)
- Shown per-account and in global detail pane

---

## UI Overview

| Element | Purpose |
|---------|---------|
| **Cockpit** | Daily operations overview — priorities, review queue, recommendations, recent activity |
| **Accounts tab** | Master account list — status, tags, session data, FBR summary, per-account actions |
| **Sources tab** | Global source aggregation — filters, detail pane, delete/revert, history |
| **Settings tab** | Bot root path, FBR thresholds, delete config, theme |
| **Session Report** | 8-section analysis: zero actions, devices, review, low follow/like, TB, limits, operator checklist |
| **Recommendations** | Severity-sorted actionable findings with quick filters, apply, and navigation |
| **Action History** | Chronological audit trail of all operator actions |

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
1. Set the **Onimator path** in the top bar
2. Click **Save**
3. Click **Scan & Sync** to discover accounts and collect session data
4. Click **Cockpit** to see the operations overview

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
│   UI Layer   │────>│   Services   │────>│   Modules     │────>│ Bot Files│
│  (PySide6)   │     │ (orchestrate)│     │ (read-only*)  │     │ (on disk)│
└─────────────┘     └──────┬───────┘     └───────────────┘     └──────────┘
                           │
                    ┌──────▼───────┐     ┌───────────────┐
                    │ Repositories │────>│   oh.db        │
                    │ (CRUD)       │     │ (SQLite/WAL)   │
                    └──────────────┘     └───────────────┘
```

\* _Modules are strictly read-only except `SourceDeleter` and `SourceRestorer` which modify `sources.txt` with backup._

| Layer | Location | Responsibility |
|-------|----------|---------------|
| **modules/** | `oh/modules/` | Stateless readers of bot files — discovery, FBR, inspection, usage, session data |
| **repositories/** | `oh/repositories/` | CRUD on OH's internal database — never touches bot files |
| **services/** | `oh/services/` | Orchestrators: scan, FBR, session, recommendations, operator actions, source delete |
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
│   │   └── migrations.py               # Schema migrations (7 versions)
│   │
│   ├── models/                         # Pure dataclasses
│   │   ├── account.py                  # AccountRecord, DiscoveredAccount, DeviceRecord
│   │   ├── fbr.py                      # SourceFBRRecord, FBRAnalysisResult
│   │   ├── fbr_snapshot.py             # FBRSnapshotRecord, BatchFBRResult
│   │   ├── global_source.py            # GlobalSourceRecord, SourceAccountDetail
│   │   ├── source.py                   # SourceRecord, SourceInspectionResult
│   │   ├── source_usage.py             # SourceUsageRecord, SourceUsageResult
│   │   ├── sync.py                     # SyncRun
│   │   ├── delete_history.py           # DeleteAction, DeleteItem
│   │   ├── session.py                  # AccountSessionRecord, AccountTag
│   │   ├── operator_action.py          # OperatorActionRecord
│   │   └── recommendation.py           # Recommendation
│   │
│   ├── modules/                        # Bot file readers
│   │   ├── discovery.py                # Account & device discovery + settings.db
│   │   ├── fbr_calculator.py           # FBR computation from data.db
│   │   ├── source_inspector.py         # sources.txt + data.db reader
│   │   ├── source_usage_reader.py      # sources/*.db + .stm reader
│   │   ├── source_deleter.py           # Remove sources (destructive)
│   │   ├── source_restorer.py          # Restore sources (revert)
│   │   ├── session_reader.py           # Session data + tags from bot files
│   │   └── sync_module.py              # Account config sync
│   │
│   ├── repositories/                   # OH database layer
│   │   ├── account_repo.py             # Accounts + review flags
│   │   ├── device_repo.py              # Device registry
│   │   ├── settings_repo.py            # Configuration key-value store
│   │   ├── sync_repo.py                # Sync run history
│   │   ├── source_assignment_repo.py   # Source-account relationships
│   │   ├── fbr_snapshot_repo.py        # FBR analysis snapshots
│   │   ├── delete_history_repo.py      # Source deletion audit trail
│   │   ├── session_repo.py             # Session snapshots
│   │   ├── tag_repo.py                 # Account tags (bot + operator)
│   │   └── operator_action_repo.py     # Operator action audit trail
│   │
│   ├── services/                       # Business logic
│   │   ├── scan_service.py             # Scan & sync + session collection
│   │   ├── fbr_service.py              # FBR analysis + snapshots
│   │   ├── global_sources_service.py   # Cross-account aggregation
│   │   ├── source_delete_service.py    # Delete, revert, account cleanup
│   │   ├── session_service.py          # Session data collection
│   │   ├── operator_action_service.py  # Review, TB, limits actions + audit
│   │   └── recommendation_service.py   # Operational recommendations engine
│   │
│   └── ui/                             # Desktop interface
│       ├── main_window.py              # Main window + Accounts tab + toolbar
│       ├── cockpit_dialog.py           # Daily Operations Cockpit
│       ├── session_report_dialog.py    # Session Report (8 sections)
│       ├── recommendations_dialog.py   # Recommendations viewer + actions
│       ├── sources_tab.py              # Global Sources tab
│       ├── settings_tab.py             # Settings tab
│       ├── source_dialog.py            # Per-account Sources dialog + cleanup
│       ├── delete_confirm_dialog.py    # Delete/cleanup confirmation
│       ├── delete_history_dialog.py    # Deletion history + revert
│       ├── operator_action_history_dialog.py  # Operator action history
│       ├── style.py                    # Dark theme QSS
│       └── workers.py                  # QThread helpers
│
├── scripts/
│   ├── generate_placeholder_assets.py
│   └── create_shortcut.ps1
│
└── docs/
    └── FEATURES.md
```

---

## Database Schema

OH uses SQLite with WAL mode. 7 migrations applied automatically on startup.

| Table | Purpose |
|-------|---------|
| `oh_config` | Configuration key-value store |
| `oh_devices` | Device registry with status |
| `oh_accounts` | Account registry with review flags, tags, limits |
| `sync_runs` / `sync_events` | Scan & sync audit trail |
| `fbr_snapshots` / `fbr_source_results` | FBR analysis history |
| `source_assignments` | Source-account relationships |
| `source_delete_actions` / `source_delete_items` | Deletion audit trail |
| `session_snapshots` | Daily session counters per account |
| `account_tags` | Bot + operator tags with levels |
| `operator_actions` | Operator action audit trail |

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

## Safety

- **Read-only** — OH never modifies `data.db`, source databases, `.stm` files, or any bot runtime data
- **Backup** — `sources.txt.bak` created before every delete/restore operation
- **Preview** — detailed preview dialog before any destructive action, with checkboxes for account cleanup
- **Audit trail** — all deletions and operator actions logged with timestamps, machine name, affected accounts
- **Revert** — completed deletions can be reversed from the history dialog
- **Operator tags isolated** — bot tags and operator tags stored separately, never conflict

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Language | Python 3.9+ |
| GUI | PySide6 6.6+ (Qt 6) |
| Database | SQLite 3 (WAL mode, 7 migrations) |
| Packaging | PyInstaller |
| Platform | Windows 10/11 |
| Dependencies | PySide6 only — everything else is stdlib |

---

## License

Internal use only. Property of Wizzysocial.
