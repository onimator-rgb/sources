# Plan: Operational Features v2

> Created: 2026-04-02 | Status: IN PROGRESS

## Implementation Waves

### Wave 1 — Daily Operations Core (implement now)
| # | Feature | Complexity | Files |
|---|---------|-----------|-------|
| 1 | Account Health Score | M | model, service, UI column |
| 2 | Source Health Dashboard | L | new tab, leverages source_profiles |
| 3 | Quick Wins (bulk tags, blacklist, notes, CSV export) | M | UI + repo additions |

### Wave 2 — Source Intelligence (next)
| # | Feature | Complexity | Files |
|---|---------|-----------|-------|
| 4 | Source Performance Trends | M | repo queries, UI sparklines |
| 5 | Source Rotation Alerts | M | service + recommendation integration |
| 6 | Cross-Account Source Optimizer | L | new service + dialog |

### Wave 3 — Fleet & Automation (later)
| # | Feature | Complexity | Files |
|---|---------|-----------|-------|
| 7 | Auto-Scan Scheduler | M | QTimer-based scheduler |
| 8 | Device Fleet Dashboard | L | new tab |
| 9 | Campaign Templates | M | new model/repo/UI |
| 10 | Reporting Agent | L | export service + dialog |

---

## Feature 1: Account Health Score

**Problem:** Operator must check 5+ metrics per account to assess health. At 100+ accounts this is impractical.

**Solution:** Composite score 0-100 per account, color-coded in Accounts table.

### Score Formula:
```
health_score = (
    fbr_quality_ratio * 30      # quality_sources / total_sources
  + activity_ratio * 20         # today_follows / follow_limit
  + source_health * 15          # active_sources / min_threshold
  + stability * 15              # inverse of TB+Limits levels (5=0%, 1=100%)
  + session_regularity * 10     # has_activity today? 1.0 or 0.0
  + review_penalty * 10         # no review flag = 10, flagged = 0
)
```

### Implementation:
- **Model:** Add `health_score` property to AccountDetailData or compute in service
- **Service:** `AccountHealthService.compute_score(account, fbr, session, source_count, tags)` → float
- **UI:** New column in Accounts table (COL_HEALTH), color: green >= 70, yellow >= 40, red < 40
- **Sort:** Sortable column, default sort by health ascending (worst first)

### Files:
- `oh/services/account_health_service.py` (new)
- `oh/ui/main_window.py` (add column)

---

## Feature 2: Source Health Dashboard

**Problem:** 9965 sources, no centralized view of source quality and niche distribution.

**Solution:** New "Source Profiles" tab showing source_profiles data with filters.

### Layout:
```
Source Profiles tab
├── Toolbar: [Refresh] [Scan & Index] [Export CSV]
├── Stats bar: "4,521 indexed | 12 niches | avg FBR 8.2%"
├── Filter bar: Niche dropdown | Language | Min FBR | Min followers | Search
└── Table: Source, Niche, Confidence, Language, Location, Followers, FBR%, Quality Accs, Status
    └── Click row → detail pane with per-account breakdown
```

### Files:
- `oh/ui/source_profiles_tab.py` (new)
- `oh/ui/main_window.py` (add tab)

---

## Feature 3: Quick Wins Bundle

### 3a. Bulk Tag Assignment
- Multi-select in Accounts table (Ctrl+click, Shift+click)
- Right-click → "Set TB level" / "Set Limits level" for all selected
- Confirmation dialog showing N accounts affected

### 3b. Source Blacklist
- New table `source_blacklist (source_name TEXT UNIQUE, reason TEXT, added_at TEXT)`
- Migration 011
- Check blacklist before adding sources (in source_finder_service)
- UI: manage blacklist in Settings tab

### 3c. Account Notes
- New column on `oh_accounts`: `operator_notes TEXT`
- Migration 011 (same migration)
- Editable in Account Detail drawer
- Visible in Accounts table tooltip

### 3d. CSV Export
- "Export" button in Accounts tab toolbar
- Exports visible (filtered) rows to CSV
- Opens file dialog for save location

### Files:
- `oh/db/migrations.py` (migration 011)
- `oh/ui/main_window.py` (bulk tags, CSV export)
- `oh/ui/account_detail_panel.py` (notes)
- `oh/ui/settings_tab.py` (blacklist management)
- `oh/repositories/settings_repo.py` or new `blacklist_repo.py`

---

## Feature 4: Source Performance Trends

### Data:
- Query `fbr_source_results` joined with `fbr_snapshots` for last 7/14/30 days
- Compute FBR trend per source: current vs 7-day avg

### UI:
- New column in Sources tab: "Trend" with arrow icon (↑/↓/→)
- Tooltip: "FBR 7d ago: 12.3% → now: 8.1% (↓34%)"

### Alert:
- New recommendation type: `REC_SOURCE_FBR_DECLINING`
- "Source @xyz FBR dropped 50%+ in 7 days"

---

## Feature 5: Source Rotation Alerts

### Logic:
- Source is "exhausted" when usage % > 80% across accounts
- Source is "declining" when FBR trend is negative for 14+ days
- Source is "stale" when no new follows in 30 days

### Integration:
- Add to RecommendationService: `REC_SOURCE_EXHAUSTED`, `REC_SOURCE_DECLINING`
- Show in Cockpit and Recommendations dialog

---

## Feature 6: Cross-Account Source Optimizer

### Analysis:
- For each source, compute FBR by account niche
- Flag sources with >50% FBR variance between niches
- Suggest: "Remove @source from beauty accounts (2% FBR), keep on fitness (18% FBR)"

---

## Feature 7: Auto-Scan Scheduler

### Implementation:
- QTimer in MainWindow, configurable interval (1h, 2h, 6h, 12h, 24h)
- Settings: `auto_scan_enabled` (bool), `auto_scan_interval_hours` (int)
- Runs Scan & Sync + FBR Analysis automatically
- Status bar shows: "Next auto-scan in 2h 15m"
- Notification on completion

---

## Feature 8: Device Fleet Dashboard

### New tab showing:
- Devices table: Name, Status, Accounts, Active %, Avg Health, Last Sync
- Per-device breakdown on click
- Rebalancing suggestions

---

## Feature 9: Campaign Templates

### Schema:
- `campaign_templates (id, name, niche, settings_json, created_at)`
- Settings: min_sources, source_niche, TB level, limits level, follow_limit, like_limit

---

## Feature 10: Reporting Agent

### Automated reports:
- Daily summary PDF per device/account group
- Weekly performance report with trends
- CSV export of all data

---

## Execution Plan

```
Wave 1 (now):
  /coder → Feature 1 (Account Health Score)
  /coder → Feature 2 (Source Health Dashboard)
  /coder → Feature 3 (Quick Wins: migration 011, bulk tags, blacklist, notes, CSV)
  /reviewer → Review Wave 1
  /tester → Test Wave 1

Wave 2 (next session):
  /coder → Features 4-6

Wave 3 (later):
  /coder → Features 7-10
```
