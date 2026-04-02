# Plan: Bulk Source Discovery

> Created: 2026-04-02 | Complexity: XL (Extra Large) | Status: PLANNED

## Feature Summary

Automatically discover and add similar Instagram profiles **in bulk** for all accounts that have fewer than a configurable minimum number of sources. The operator triggers a "Bulk Find Sources" operation which:

1. Identifies all accounts with `active_sources < min_source_threshold` (configurable in Settings)
2. For each qualifying account, runs the existing Source Finder pipeline (HikerAPI + optional Gemini)
3. Auto-adds the top N results to each account's `sources.txt`
4. Stores ALL discovered data (candidates, results) in the database — even profiles not selected
5. Provides a dedicated UI to review what was added where
6. Supports full **revert** — remove newly added sources and restore the original `sources.txt`

## Architecture Decisions

### Reusing existing infrastructure
- **HikerAPI client** (`oh/modules/source_finder.py`) — unchanged
- **SourceFinderService** (`oh/services/source_finder_service.py`) — reuse `run_search()` per account
- **SourceSearchRepository** — reuse for storing candidates/results
- **Source Restorer/Deleter** — reuse backup-first pattern for revert

### New components
- **Migration 009** — `bulk_discovery_runs` + `bulk_discovery_items` tables (audit trail + revert)
- **Models** — `BulkDiscoveryRun`, `BulkDiscoveryItem` dataclasses
- **Repository** — `BulkDiscoveryRepository` for run/item CRUD
- **Service** — `BulkDiscoveryService` orchestrates the bulk pipeline
- **Settings** — `min_source_for_bulk_discovery` (default: 10), `bulk_auto_add_top_n` (default: 5)
- **UI** — `BulkDiscoveryDialog` (progress + results + revert)

### Revert strategy
Each bulk run creates a snapshot:
- For each account touched, we record the original `sources.txt` content (as JSON array)
- On revert: remove all added sources from `sources.txt`, restore originals if missing
- Revert uses the proven `SourceDeleter` + `SourceRestorer` modules

### UI/UX Design

**Trigger:** New "Bulk Find Sources" button in Sources tab toolbar.

**Dialog flow:**
```
Step 1: Preview
┌──────────────────────────────────────────────────┐
│ Bulk Source Discovery                        [X] │
│                                                  │
│ Settings:                                        │
│   Min sources threshold: [10 ▼]                  │
│   Auto-add top N results: [5 ▼]                  │
│                                                  │
│ Qualifying accounts: 23 / 150 (below threshold)  │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ ☑ Username    │ Device   │ Sources │ Deficit │ │
│ │ ☑ @john_doe   │ pixel_1  │ 3       │ 7       │ │
│ │ ☑ @jane_smith │ pixel_2  │ 8       │ 2       │ │
│ │ ☐ @bob_test   │ pixel_1  │ 6       │ 4       │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ [Select All] [Deselect All]                      │
│                                                  │
│              [Cancel]  [Start Discovery ▶]       │
└──────────────────────────────────────────────────┘

Step 2: Progress
┌──────────────────────────────────────────────────┐
│ Bulk Source Discovery — Running              [X] │
│                                                  │
│ Overall: ████████░░░░░░░░░░ 8/23 accounts        │
│ Current: @john_doe — Step 4/7: Enriching...      │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ Username     │ Status    │ Found │ Added     │ │
│ │ @john_doe    │ ✓ Done    │ 10    │ 5         │ │
│ │ @jane_smith  │ ✓ Done    │ 8     │ 5         │ │
│ │ @alice_w     │ ⟳ Running │ —     │ —         │ │
│ │ @bob_test    │ ⏳ Queued  │ —     │ —         │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ Errors: 0  |  Rate limit pauses: 2              │
│                                                  │
│              [Cancel]                             │
└──────────────────────────────────────────────────┘

Step 3: Results
┌──────────────────────────────────────────────────┐
│ Bulk Source Discovery — Complete              [X] │
│                                                  │
│ Summary: 23 accounts processed, 115 sources added│
│ Errors: 2 (hover for details)                    │
│                                                  │
│ ┌──────────────────────────────────────────────┐ │
│ │ Account      │ Device  │ Before│ Added│ After│ │
│ │ @john_doe    │ pixel_1 │ 3     │ 5    │ 8    │ │
│ │ @jane_smith  │ pixel_2 │ 8     │ 2    │ 10   │ │
│ │ @bob_test    │ pixel_1 │ 6     │ 4    │ 10   │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│ Select account to see added sources:             │
│ ┌──────────────────────────────────────────────┐ │
│ │ Source Added │ Followers │ ER%  │ AI Score   │ │
│ │ @fit_coach1  │ 15,230    │ 3.2% │ 8.5       │ │
│ │ @gym_pro     │ 8,400     │ 4.1% │ 7.2       │ │
│ └──────────────────────────────────────────────┘ │
│                                                  │
│       [Revert All]  [Revert Selected]  [Close]   │
└──────────────────────────────────────────────────┘
```

**Bulk Discovery History:** Accessible from Sources tab toolbar ("Discovery History" button).
- Shows past bulk runs with date, accounts processed, sources added, status
- Click to expand details (same as Step 3 Results view)
- Revert button per run

---

## Database Schema

### Migration 009 — Bulk Discovery Tables

```sql
CREATE TABLE IF NOT EXISTS bulk_discovery_runs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at       TEXT    NOT NULL,
    completed_at     TEXT,
    status           TEXT    NOT NULL DEFAULT 'running',
    min_threshold    INTEGER NOT NULL,
    auto_add_top_n   INTEGER NOT NULL,
    total_accounts   INTEGER NOT NULL DEFAULT 0,
    accounts_done    INTEGER NOT NULL DEFAULT 0,
    accounts_failed  INTEGER NOT NULL DEFAULT 0,
    total_added      INTEGER NOT NULL DEFAULT 0,
    machine          TEXT,
    error_message    TEXT,
    reverted_at      TEXT,
    revert_status    TEXT
);

CREATE INDEX IF NOT EXISTS idx_bulk_runs_status
    ON bulk_discovery_runs(status, started_at DESC);

CREATE TABLE IF NOT EXISTS bulk_discovery_items (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL REFERENCES bulk_discovery_runs(id),
    account_id          INTEGER NOT NULL REFERENCES oh_accounts(id),
    username            TEXT    NOT NULL,
    device_id           TEXT    NOT NULL,
    search_id           INTEGER REFERENCES source_searches(id),
    sources_before      INTEGER NOT NULL DEFAULT 0,
    sources_added       INTEGER NOT NULL DEFAULT 0,
    sources_after       INTEGER NOT NULL DEFAULT 0,
    status              TEXT    NOT NULL DEFAULT 'queued',
    added_sources_json  TEXT,
    original_sources_json TEXT,
    error_message       TEXT
);

CREATE INDEX IF NOT EXISTS idx_bulk_items_run
    ON bulk_discovery_items(run_id);

CREATE INDEX IF NOT EXISTS idx_bulk_items_account
    ON bulk_discovery_items(account_id);
```

**Key fields:**
- `added_sources_json` — JSON array of usernames added (for revert: we know exactly what to remove)
- `original_sources_json` — JSON array of original sources.txt content (for revert: we can fully restore)
- `search_id` — links to `source_searches` for full candidate/result drill-down
- `revert_status` on run level: NULL | 'reverted' | 'partial_revert'

---

## Implementation Order

```
Task 1 (Migration 009)
    ↓
Tasks 2-3 (Models + Repository) — parallel
    ↓
Task 4 (Settings additions)
    ↓
Task 5 (BulkDiscoveryService)
    ↓
Tasks 6-7 (UI Dialog + History Dialog) — parallel
    ↓
Task 8 (Main Window integration)
    ↓
Task 9 (Error handling + polish)
    ↓
Task 10 (Tests)
```

---

## Task 1 — Migration 009: Bulk Discovery Tables

**Agent:** Coder
**Files:** `oh/db/migrations.py`

**Changes:**
- Add `_MIGRATION_009_SQL` with `bulk_discovery_runs` and `bulk_discovery_items` tables
- Register as `(9, "bulk_discovery", _MIGRATION_009_SQL)` in `_MIGRATIONS`

**Acceptance:** OH starts, `SELECT * FROM schema_migrations WHERE version=9` returns a row.

---

## Task 2 — Models: Bulk Discovery Dataclasses

**Agent:** Coder
**Files:** `oh/models/bulk_discovery.py` (new)

**Dataclasses:**
```python
# Run status constants
BULK_RUNNING   = "running"
BULK_COMPLETED = "completed"
BULK_FAILED    = "failed"
BULK_CANCELLED = "cancelled"

# Item status constants
ITEM_QUEUED    = "queued"
ITEM_RUNNING   = "running"
ITEM_DONE      = "done"
ITEM_FAILED    = "failed"
ITEM_SKIPPED   = "skipped"

@dataclass
class BulkDiscoveryRun:
    started_at:      str
    status:          str
    min_threshold:   int
    auto_add_top_n:  int
    total_accounts:  int  = 0
    accounts_done:   int  = 0
    accounts_failed: int  = 0
    total_added:     int  = 0
    completed_at:    Optional[str] = None
    machine:         Optional[str] = None
    error_message:   Optional[str] = None
    reverted_at:     Optional[str] = None
    revert_status:   Optional[str] = None
    items:           Optional[List["BulkDiscoveryItem"]] = None
    id:              Optional[int] = None

@dataclass
class BulkDiscoveryItem:
    run_id:                int
    account_id:            int
    username:              str
    device_id:             str
    status:                str  = ITEM_QUEUED
    search_id:             Optional[int] = None
    sources_before:        int  = 0
    sources_added:         int  = 0
    sources_after:         int  = 0
    added_sources_json:    Optional[str] = None
    original_sources_json: Optional[str] = None
    error_message:         Optional[str] = None
    id:                    Optional[int] = None
```

**Acceptance:** Dataclasses instantiate correctly with defaults.

---

## Task 3 — Repository: Bulk Discovery CRUD

**Agent:** Coder
**Files:** `oh/repositories/bulk_discovery_repo.py` (new)

**Class:** `BulkDiscoveryRepository(conn)`

**Methods:**
- `create_run(min_threshold, auto_add_top_n, total_accounts, machine) -> BulkDiscoveryRun`
- `update_run_progress(run_id, accounts_done, accounts_failed, total_added)`
- `complete_run(run_id, status, error_message=None)`
- `create_item(run_id, account_id, username, device_id, sources_before) -> BulkDiscoveryItem`
- `update_item(item_id, status, search_id, sources_added, sources_after, added_sources_json, original_sources_json, error_message)`
- `get_run(run_id) -> Optional[BulkDiscoveryRun]`
- `get_run_with_items(run_id) -> Optional[BulkDiscoveryRun]`
- `get_recent_runs(limit=20) -> List[BulkDiscoveryRun]`
- `get_items_for_run(run_id) -> List[BulkDiscoveryItem]`
- `mark_run_reverted(run_id, revert_status)`
- `recover_stale_runs(max_age_hours=24) -> int`

**Acceptance:** Full CRUD round-trip on in-memory DB.

---

## Task 4 — Settings: Bulk Discovery Configuration

**Agent:** Coder
**Files:** `oh/repositories/settings_repo.py`, `oh/ui/settings_tab.py`

**Changes to settings_repo:**
- Add to `_CONFIG_DEFAULTS`:
  - `"min_source_for_bulk_discovery": "10"` — minimum sources threshold
  - `"bulk_auto_add_top_n": "5"` — how many top results to auto-add per account

**Changes to settings_tab:**
- Add new "Source Discovery" QGroupBox between "Source Cleanup" and "Appearance":
  - `Min sources for bulk discovery` — QSpinBox (1-50, default 10)
  - `Auto-add top N results` — QSpinBox (1-10, default 5)
  - Hint: "Accounts with fewer active sources than the threshold will be included in bulk discovery."

**Acceptance:** Settings visible, persist across restart.

---

## Task 5 — Service: Bulk Discovery Pipeline

**Agent:** Coder
**Files:** `oh/services/bulk_discovery_service.py` (new)

**Class:** `BulkDiscoveryService(bulk_repo, source_finder_service, account_repo, source_assignment_repo, settings_repo, source_delete_service)`

**Methods:**

### `get_qualifying_accounts(min_threshold) -> List[Tuple[AccountRecord, int]]`
- Query all active accounts
- Get source count from `source_assignment_repo`
- Return accounts with `source_count < min_threshold`, paired with current count
- Sorted by source count ascending (most needy first)

### `run_bulk_discovery(accounts, min_threshold, auto_add_top_n, bot_root, progress_callback, cancel_check) -> BulkDiscoveryRun`
Pipeline per account:
1. Snapshot original `sources.txt` content → `original_sources_json`
2. Run `source_finder_service.run_search(account_id)` → get results
3. Take top `auto_add_top_n` results
4. For each: call `source_finder_service.add_to_sources(result_id, account_id, bot_root)`
5. Record added sources → `added_sources_json`
6. Update item status + run progress
7. On error: log, mark item failed, continue to next account
8. Inter-account delay (2s) to respect rate limits

**Rate limit handling:**
- If HikerAPIError with "rate limit", pause 60s, then retry current account
- Max 3 retries per account before marking failed
- Progress callback reports pauses to UI

### `revert_run(run_id, bot_root) -> Tuple[int, int, List[str]]`
Returns (reverted_count, failed_count, errors).
For each item in the run:
1. Read `added_sources_json` — list of sources to remove
2. Use `SourceDeleter.remove_source()` for each added source
3. Read `original_sources_json` — if any original sources are now missing, restore them via `SourceRestorer`
4. Mark item as reverted
5. Update `source_assignments` to reflect changes

### `revert_item(item_id, bot_root) -> bool`
Same as above but for a single account within a run.

### `get_run_details(run_id) -> BulkDiscoveryRun`
Load run with items + join search results for each item's `search_id`.

**Acceptance:** Full bulk pipeline runs for 3+ accounts. Revert restores original state.

---

## Task 6 — UI: Bulk Discovery Dialog

**Agent:** Coder + UI/UX
**Files:** `oh/ui/bulk_discovery_dialog.py` (new)

**Layout:** 3-step wizard dialog (QStackedWidget):

### Page 1: Preview
- Settings override: min threshold spinner, auto-add top N spinner
- Account table with checkboxes: Username, Device, Current Sources, Deficit
- Select All / Deselect All buttons
- Summary: "X accounts qualify (below Y sources)"
- [Cancel] [Start Discovery ▶]

### Page 2: Progress
- Overall progress bar (accounts done / total)
- Current account label + step progress
- Results table (live updating): Username, Status icon, Found, Added, Error
- Stats line: "Errors: N | Rate limit pauses: N"
- [Cancel] button (sets cancel flag, finishes current account)

### Page 3: Results
- Summary header: "N accounts processed, M sources added, E errors"
- Main table: Account, Device, Before, Added, After, Status
- Detail pane (below, appears on account selection): shows added sources with candidate data
- [Revert All] [Revert Selected] [Close]

**Worker:** `BulkDiscoveryWorker(QThread)` with signals:
- `account_started(int, str)` — (index, username)
- `account_done(int, str, int, int)` — (index, username, found, added)
- `account_error(int, str, str)` — (index, username, error_message)
- `overall_progress(int, int)` — (done, total)
- `step_progress(int, str)` — (percent, step_message) for current account
- `finished(BulkDiscoveryRun)` — final result
- `rate_limit_pause(int)` — seconds to wait

**Size:** 900×650 min, resizable.

**Acceptance:** Dialog opens, shows qualifying accounts, runs pipeline with live progress, shows results, revert works.

---

## Task 7 — UI: Bulk Discovery History Dialog

**Agent:** Coder + UI/UX
**Files:** `oh/ui/bulk_discovery_history_dialog.py` (new)

**Layout:** QSplitter vertical:

### Top: Runs table
- Columns: Date, Status, Threshold, Accounts, Sources Added, Machine
- Status colors: running=blue, completed=green, reverted=gray, failed=red
- Row selection loads items in bottom pane

### Bottom: Items detail
- Columns: Account, Device, Before, Added, After, Status, Error
- Double-click: navigate to account in main window
- Context menu: "Revert this account"

### Footer
- [Revert Selected Run] [Close]

**Size:** 900×550 min, resizable.

**Acceptance:** History shows past runs, drill-down works, revert per run works.

---

## Task 8 — Main Window Integration

**Agent:** Coder
**Files:** `oh/ui/main_window.py`, `oh/ui/sources_tab.py`, `main.py`

**Changes to main.py:**
- Bootstrap `BulkDiscoveryRepository`
- Bootstrap `BulkDiscoveryService`
- Pass to `MainWindow`

**Changes to sources_tab.py:**
- Add "Bulk Find Sources" button to toolbar (icon: magnifying glass + list)
- Add "Discovery History" button to toolbar
- Wire button clicks to MainWindow signals

**Changes to main_window.py:**
- Handle "Bulk Find Sources" → validate bot_root + hiker_api_key → open `BulkDiscoveryDialog`
- Handle "Discovery History" → open `BulkDiscoveryHistoryDialog`
- After bulk discovery completes → refresh Sources tab + Accounts table

**Acceptance:** Buttons visible in Sources tab. Full flow works end-to-end.

---

## Task 9 — Error Handling & Polish

**Agent:** Coder + Reviewer
**Files:** All new files from tasks above

**Hardening:**
1. Cancel handling — clean stop after current account finishes
2. Rate limit backoff — 60s pause with countdown in UI
3. HikerAPI key validation — warn before starting if not configured
4. Empty qualifying accounts — friendly message "All accounts have enough sources"
5. Partial failure — continue to next account, report at end
6. Revert safety — verify file exists before modifying
7. Stale run recovery — mark running runs > 24h as failed on startup
8. Memory — don't hold all candidate data in memory; load per-account
9. Duplicate source prevention — case-insensitive check before adding
10. Bot root validation — ensure path exists and has expected structure

**Acceptance:** All edge cases handled gracefully.

---

## Task 10 — Tests

**Agent:** Tester
**Files:** `tests/test_bulk_discovery_*.py`

**Test suites:**
1. `test_bulk_discovery_models.py` — dataclass creation, defaults
2. `test_bulk_discovery_repo.py` — CRUD on in-memory DB
3. `test_bulk_discovery_service.py` — qualifying accounts logic, revert logic (mocked API)
4. `test_bulk_discovery_integration.py` — end-to-end with mock HikerAPI responses

**Acceptance:** All tests pass with `python -m unittest discover tests/`.

---

## Agent Pipeline

```
/architect  → ✅ Done (this document is the feature proposal)

/planner    → ✅ Done (this document contains the plan)

/coder      → Tasks 1-5, 8 (backend: migration, models, repo, settings, service, wiring)
              Tasks 6-7 (UI dialogs)

/reviewer   → After Tasks 1-5: review backend code
              After Tasks 6-8: review UI code + integration

/uiux       → After Tasks 6-7: review dialog design, layout, colors, UX flow

/tester     → Task 10: write tests, validate full pipeline
```

### Recommended execution order:

```
Step 1: /coder  → Task 1 (Migration 009)
Step 2: /coder  → Tasks 2+3 (Models + Repository)
Step 3: /coder  → Task 4 (Settings)
Step 4: /coder  → Task 5 (BulkDiscoveryService)
Step 5: /reviewer → Review Tasks 1-5 backend
Step 6: /coder  → Tasks 6+7 (UI Dialogs)
Step 7: /coder  → Task 8 (Main Window integration)
Step 8: /reviewer → Review Tasks 6-8 UI + integration
Step 9: /uiux  → Review UI design
Step 10: /coder → Task 9 (Error handling fixes from reviews)
Step 11: /tester → Task 10 (Tests)
Step 12: /reviewer → Final review
```

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| HikerAPI rate limits (30-40 calls/account × N accounts) | Bulk runs hit limits fast | Inter-account delay (2s), rate limit pause (60s), max 3 retries |
| Long runtime (5-10 min per account × 20+ accounts) | 2+ hours for large fleets | Cancel support, resume not needed (re-run is fine), progress updates |
| Concurrent bulk runs | Data corruption | Check for running run before starting new one |
| Revert after bot has processed new sources | Followbacks already happened | UI warning: "Revert only removes sources from sources.txt, existing interactions remain" |
| Gemini API cost at scale | Money | Optional — works without it |
| sources.txt write during bot runtime | File conflict | Backup-first pattern (proven) |
| Large number of qualifying accounts | Memory / API cost | Checkbox selection in preview, operator controls scope |

---

## Settings Summary

| Setting Key | Default | UI Control | Description |
|-------------|---------|------------|-------------|
| `min_source_for_bulk_discovery` | 10 | QSpinBox (1-50) | Accounts below this threshold qualify for bulk discovery |
| `bulk_auto_add_top_n` | 5 | QSpinBox (1-10) | How many top results to auto-add per account |
| `hiker_api_key` | "" | QLineEdit (masked) | Required for any source discovery |
| `gemini_api_key` | "" | QLineEdit (masked) | Optional AI scoring |
