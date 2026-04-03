# Phase 10 — Operations v3: Error Reporting, Block Detection, Groups, Bulk Ops, Trends

> Created: 2026-04-03 | Complexity: XL | Migrations: 013, 014
> 5 features, ~30 tasks, builds on all existing infrastructure

---

## Feature Overview

| # | Feature | Priority | New Tables | New Files | Modified Files |
|---|---------|----------|------------|-----------|----------------|
| A | Remote Error Reporting | CRITICAL | `error_reports` | 3 | 3 |
| B | Block/Ban Detection | HIGH | `block_events` | 2 | 4 |
| C | Account Groups | HIGH | `account_groups`, `account_group_members` | 4 | 4 |
| D | Bulk Account Operations | HIGH | — | 1 | 1 |
| E | Performance Trends | MEDIUM | — | 2 | 3 |

---

## Architecture Decisions

1. **Migration 013** — covers features A+B+C (new tables: `error_reports`, `block_events`, `account_groups`, `account_group_members`)
2. **No migration for D+E** — Bulk Ops uses existing data; Trends reads existing `session_snapshots` + `fbr_snapshots`
3. **Error reporting uses HTTP POST** — `urllib.request` (stdlib) to avoid new dependency
4. **Block detection reads .stm files** — new module `block_detector.py`, stateless file reader
5. **Groups are OH-only** — stored in oh.db, no bot file changes
6. **Sparklines use QPainter** — custom QWidget, no chart library dependency
7. **Bulk ops extend existing selection model** — QTableWidget multi-select mode

---

## A. Remote Error Reporting

### Problem
After distributing OH.exe to clients, we have no visibility into crashes, errors, or bugs. Clients report issues verbally with no context.

### Solution
Automatic crash report collection + manual "Report Problem" button. Reports sent via HTTP POST to a configurable endpoint (Discord webhook or custom server).

### A1. Migration — `error_reports` table
**Files:** `oh/db/migrations.py`
**What:**
```sql
CREATE TABLE IF NOT EXISTS error_reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id    TEXT    NOT NULL UNIQUE,  -- UUID
    error_type   TEXT    NOT NULL,         -- crash | manual | startup_fail
    error_message TEXT,
    traceback    TEXT,
    oh_version   TEXT,
    os_version   TEXT,
    python_version TEXT,
    db_stats     TEXT,                     -- JSON: {devices: N, accounts: N, ...}
    log_tail     TEXT,                     -- last 100 lines of oh.log
    user_note    TEXT,                     -- optional user description
    sent_at      TEXT,                     -- NULL if not yet sent
    created_at   TEXT    NOT NULL
);
```
**Depends on:** nothing
**Test:** Migration applies cleanly, table exists

### A2. Model — `ErrorReport`
**Files:** `oh/models/error_report.py` (NEW)
**What:**
```python
@dataclass
class ErrorReport:
    id: Optional[int]
    report_id: str           # uuid4
    error_type: str          # crash | manual | startup_fail
    error_message: Optional[str]
    traceback: Optional[str]
    oh_version: str
    os_version: str
    python_version: str
    db_stats: Optional[str]  # JSON
    log_tail: Optional[str]
    user_note: Optional[str]
    sent_at: Optional[str]
    created_at: str
```
**Depends on:** nothing
**Test:** Dataclass instantiation

### A3. Repository — `ErrorReportRepository`
**Files:** `oh/repositories/error_report_repo.py` (NEW)
**What:**
- `save(report) -> ErrorReport` — insert new report
- `mark_sent(report_id, sent_at)` — mark as sent
- `get_unsent() -> List[ErrorReport]` — queue of failed sends
- `get_recent(limit=20) -> List[ErrorReport]` — for history
**Depends on:** A1, A2
**Test:** CRUD operations on error_reports table

### A4. Service — `ErrorReportService`
**Files:** `oh/services/error_report_service.py` (NEW)
**What:**
- `capture_crash(exc_type, exc_value, exc_tb) -> ErrorReport` — captures unhandled exception
- `capture_manual(user_note: str) -> ErrorReport` — user-initiated report
- `send_report(report: ErrorReport) -> bool` — HTTP POST to endpoint
- `retry_unsent()` — retry failed sends on startup
- `_collect_context() -> dict` — gathers: OH version, OS, Python, DB stats, log tail
- `_read_log_tail(lines=100) -> str` — reads last N lines from oh.log
- `_build_payload(report) -> dict` — formats for webhook

**HTTP payload format (Discord webhook compatible):**
```json
{
    "content": "OH Error Report",
    "embeds": [{
        "title": "crash | v1.0.1 | report_id",
        "description": "error_message",
        "fields": [
            {"name": "Traceback", "value": "```...```"},
            {"name": "Version", "value": "1.0.1"},
            {"name": "OS", "value": "Windows 11"},
            {"name": "DB Stats", "value": "12 devices, 234 accounts"},
            {"name": "User Note", "value": "..."}
        ],
        "color": 15158332
    }]
}
```

**Privacy:** Never sends account usernames, device names, or client data. Only technical info.

**Depends on:** A3
**Test:** Mock HTTP, verify payload structure, verify log tail reading

### A5. Exception Hook Integration
**Files:** `main.py`
**What:**
- Modify `_install_exception_hook()` to call `error_report_service.capture_crash()`
- After capture, show QMessageBox: "OH encountered an error. Send anonymous crash report?" [Yes/No]
- On startup, call `error_report_service.retry_unsent()` for any queued reports
- Add `error_report_service` to bootstrap chain
**Depends on:** A4
**Test:** Simulate exception → verify report created, dialog shown

### A6. UI — Report Problem Button
**Files:** `oh/ui/settings_tab.py`, `oh/ui/main_window.py`
**What:**
- Settings tab: new group "Error Reporting"
  - `report_endpoint` text field (Discord webhook URL or custom endpoint)
  - `auto_send_crashes` checkbox (default: True)
  - `[Report Problem]` button → opens dialog with text area for description
  - `[View Report History]` button → shows recent reports table
- Main window toolbar: small "Report Problem" button (or menu item)
- Report dialog: QDialog with QTextEdit for user note + [Send] [Cancel]
**Depends on:** A4, A5
**Test:** Button visible, dialog opens, report sent on click

---

## B. Block/Ban Detection

### Problem
Accounts get Instagram action blocks → bot stops following → operator sees "0 actions" but doesn't know WHY. Must check each account folder manually. Critical time wasted.

### Solution
New `BlockDetector` module reads bot .stm files and data.db patterns to detect action blocks, challenges, and shadow bans. Integrates with Recommendations and Cockpit.

### B1. Migration — `block_events` table
**Files:** `oh/db/migrations.py` (append to migration 013)
**What:**
```sql
CREATE TABLE IF NOT EXISTS block_events (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id      INTEGER NOT NULL REFERENCES oh_accounts(id),
    event_type      TEXT    NOT NULL,  -- action_block | challenge | shadow_ban | temp_ban | rate_limit
    detected_at     TEXT    NOT NULL,
    evidence        TEXT,              -- JSON: what signals triggered detection
    resolved_at     TEXT,              -- NULL if still active
    auto_detected   INTEGER DEFAULT 1, -- 1=auto, 0=manual flag
    FOREIGN KEY (account_id) REFERENCES oh_accounts(id)
);

CREATE INDEX IF NOT EXISTS idx_block_events_account
    ON block_events(account_id, detected_at DESC);
```
**Depends on:** nothing
**Test:** Migration applies, table exists

### B2. Model — `BlockEvent`
**Files:** `oh/models/block_event.py` (NEW)
**What:**
```python
@dataclass
class BlockEvent:
    id: Optional[int]
    account_id: int
    event_type: str        # action_block | challenge | shadow_ban | temp_ban | rate_limit
    detected_at: str
    evidence: Optional[str]  # JSON
    resolved_at: Optional[str]
    auto_detected: bool

    @property
    def is_active(self) -> bool:
        return self.resolved_at is None

    @property
    def severity(self) -> str:
        return {"action_block": "CRITICAL", "challenge": "CRITICAL",
                "shadow_ban": "HIGH", "temp_ban": "HIGH",
                "rate_limit": "MEDIUM"}.get(self.event_type, "MEDIUM")
```
**Depends on:** nothing
**Test:** Dataclass, properties

### B3. Repository — `BlockEventRepository`
**Files:** `oh/repositories/block_event_repo.py` (NEW)
**What:**
- `save(event) -> BlockEvent`
- `get_active_for_account(account_id) -> List[BlockEvent]`
- `get_active_all() -> List[BlockEvent]`
- `resolve(event_id, resolved_at)`
- `get_active_map() -> Dict[int, List[BlockEvent]]` — for main table display
**Depends on:** B1, B2
**Test:** CRUD, resolve, active map

### B4. Module — `BlockDetector`
**Files:** `oh/modules/block_detector.py` (NEW)
**What:** Stateless reader that scans bot files for block/ban signals.

**Detection strategies:**
1. **Zero follows on running device in active slot** (already exists as REC_ZERO_ACTION, but now we classify WHY)
2. **Effective limit drop** — read `.stm/follow-action-limit-per-day-{date}.txt`, compare with `settings.db` configured limit. If effective < 50% of configured → `rate_limit`
3. **Sudden activity drop** — compare today's follow_count with average of last 3 days from session_snapshots. If < 30% of average → `shadow_ban` suspect
4. **Challenge detection** — check for `.stm/challenge-required*` or similar marker files
5. **Consecutive zero days** — 2+ days of zero activity on running device → `action_block`

**Interface:**
```python
class BlockDetector:
    def __init__(self, bot_root: str) -> None: ...

    def detect_for_account(self, device_id: str, username: str,
                           session_history: List[AccountSessionRecord],
                           configured_limit: int) -> List[BlockSignal]:
        """Returns list of detected block signals with evidence."""

@dataclass
class BlockSignal:
    event_type: str      # action_block | challenge | shadow_ban | rate_limit
    confidence: float    # 0.0 - 1.0
    evidence: dict       # {"reason": "...", "details": {...}}
```

**Depends on:** B2
**Test:** Mock .stm files, verify detection logic per strategy

### B5. Service — `BlockDetectionService`
**Files:** `oh/services/block_detection_service.py` (NEW)
**What:**
- `scan_all_accounts(bot_root, accounts, session_map) -> BlockScanResult`
  - Runs `BlockDetector` for each active account
  - Compares with existing active block_events
  - Creates new events for new detections
  - Auto-resolves events when block signals disappear
- `get_active_blocks() -> Dict[int, List[BlockEvent]]` — for UI
- `resolve_manually(event_id)` — operator marks as resolved
- `get_block_summary() -> BlockSummary` — counts by type for Cockpit

**Integrates with Scan & Sync:** Called after session collection.

**Depends on:** B3, B4
**Test:** End-to-end detection → persistence → resolution

### B6. UI Integration — Block indicators
**Files:** `oh/ui/main_window.py`, `oh/ui/account_detail_panel.py`, `oh/services/recommendation_service.py`
**What:**
- Main table: new column "Block" with colored indicator (red dot = active block, empty = ok)
- Account detail Summary tab: block status card with event type, detected time, evidence
- Account detail Alerts tab: block events as CRITICAL alerts with "Mark Resolved" action
- Cockpit: new section "Blocked Accounts" at top (before existing critical actions)
- Recommendation engine: new type `REC_ACTION_BLOCK` with CRITICAL severity
- Filter bar: add "Blocked" option to Activity filter
**Depends on:** B5
**Test:** Block indicator visible, filter works, Cockpit shows blocked accounts

---

## C. Account Groups / Campaigns

### Problem
Operator manages 200+ accounts for different clients. Can't quickly filter "all accounts for client X" or see campaign-level performance.

### Solution
Account groups with labels, color coding, and aggregated metrics. Groups appear as a filter + optional tab.

### C1. Migration — `account_groups` + `account_group_members`
**Files:** `oh/db/migrations.py` (append to migration 013)
**What:**
```sql
CREATE TABLE IF NOT EXISTS account_groups (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT    NOT NULL UNIQUE,
    color       TEXT    DEFAULT '#5B8DEF',  -- hex color for UI
    description TEXT,
    created_at  TEXT    NOT NULL,
    updated_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS account_group_members (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    group_id    INTEGER NOT NULL REFERENCES account_groups(id) ON DELETE CASCADE,
    account_id  INTEGER NOT NULL REFERENCES oh_accounts(id),
    added_at    TEXT    NOT NULL,
    UNIQUE(group_id, account_id)
);

CREATE INDEX IF NOT EXISTS idx_group_members_group
    ON account_group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_account
    ON account_group_members(account_id);
```
**Depends on:** nothing
**Test:** Migration applies, foreign keys work, unique constraint works

### C2. Model — `AccountGroup`
**Files:** `oh/models/account_group.py` (NEW)
**What:**
```python
@dataclass
class AccountGroup:
    id: Optional[int]
    name: str
    color: str             # hex
    description: Optional[str]
    created_at: str
    updated_at: str
    member_count: int = 0  # computed, not stored

@dataclass
class GroupMembership:
    group_id: int
    account_id: int
    added_at: str

@dataclass
class GroupSummary:
    group: AccountGroup
    total_accounts: int
    active_accounts: int
    avg_health: float
    avg_fbr: float
    total_follows_today: int
    blocked_count: int
    review_count: int
```
**Depends on:** nothing
**Test:** Dataclass instantiation

### C3. Repository — `AccountGroupRepository`
**Files:** `oh/repositories/account_group_repo.py` (NEW)
**What:**
- `create_group(name, color, description) -> AccountGroup`
- `update_group(group_id, name, color, description)`
- `delete_group(group_id)` — CASCADE deletes members
- `get_all_groups() -> List[AccountGroup]` — with member_count
- `get_group(group_id) -> AccountGroup`
- `add_members(group_id, account_ids: List[int])`
- `remove_members(group_id, account_ids: List[int])`
- `get_members(group_id) -> List[int]` — account IDs
- `get_groups_for_account(account_id) -> List[AccountGroup]`
- `get_membership_map() -> Dict[int, List[AccountGroup]]` — for main table
**Depends on:** C1, C2
**Test:** CRUD, member management, cascade delete

### C4. Service — `AccountGroupService`
**Files:** `oh/services/account_group_service.py` (NEW)
**What:**
- `create_group(name, color, description) -> AccountGroup`
- `update_group(...)`
- `delete_group(group_id)`
- `assign_accounts(group_id, account_ids)` — add to group
- `unassign_accounts(group_id, account_ids)` — remove from group
- `get_group_summary(group_id, accounts, session_map, health_map, block_map) -> GroupSummary`
- `get_all_summaries(...) -> List[GroupSummary]`
**Depends on:** C3
**Test:** CRUD + summary computation

### C5. UI — Group Management Dialog
**Files:** `oh/ui/group_management_dialog.py` (NEW)
**What:**
- QDialog with split view:
  - Left: group list (name, color dot, member count)
  - Right: editor form (name, color picker, description) + member list with add/remove
- [New Group] [Delete Group] buttons
- Member list: shows account username + device, searchable
- [Add Accounts] opens picker dialog with checkbox list of all accounts
- [Remove Selected] removes from group
**Depends on:** C4
**Test:** Create/edit/delete groups, add/remove members

### C6. UI — Group Filter + Table Column
**Files:** `oh/ui/main_window.py`
**What:**
- Filter bar: new "Group" combo box (All groups + each group name)
- Table: new "Group" column showing group name(s) with color dot
- Toolbar: [Groups] button opens Group Management Dialog
- _apply_filter: filter by group membership
- _populate_row: show group badges
**Depends on:** C5
**Test:** Filter works, column shows groups, dialog opens

---

## D. Bulk Account Operations

### Problem
Operator wants to set Review on 20 accounts, or TB+1 on all accounts of a device. Currently must click one by one.

### Solution
Enable multi-select in accounts table + bulk action toolbar.

### D1. Multi-Select + Bulk Actions
**Files:** `oh/ui/main_window.py`, `oh/ui/bulk_action_dialog.py` (NEW)
**What:**

**Table changes:**
- Change selection mode: `QAbstractItemView.SelectionMode.ExtendedSelection` (Ctrl+click, Shift+click)
- Selection count label in toolbar: "N selected"
- When multi-selected, detail panel shows aggregate info instead of single account

**Bulk action toolbar (appears when N > 1 selected):**
- [Set Review] — sets review flag on all selected accounts
- [Clear Review] — clears review flag
- [TB +1] — increments TB on all selected
- [Limits +1] — increments limits on all selected
- [Assign Group] — opens group picker, adds all selected to group
- [Remove Group] — removes all selected from a group

**Bulk Action Dialog:**
- Shows count of affected accounts
- Confirmation: "Set Review on 15 accounts?" [Confirm] [Cancel]
- Optional note field for review actions
- Progress indicator for large batches
- Results summary: "14 ok, 1 failed"

**Implementation:**
- `_get_selected_account_ids() -> List[int]` — reads all selected rows
- Each bulk action calls existing `OperatorActionService` methods in a loop
- Audit trail: each action logged individually (same as single-click)
- Detail panel: when multi-select, show "N accounts selected" summary card

**Depends on:** existing OperatorActionService, C4 (for group assignment)
**Test:** Multi-select works, bulk actions apply to all selected, audit trail has N entries

---

## E. Performance Trends

### Problem
Operator sees current metrics but can't tell if an account is improving or degrading over time. Health Score 65 — is it going up or down?

### Solution
Sparkline mini-charts in the main table + trend dialog with larger charts, using existing session_snapshots and fbr_snapshots data.

### E1. Sparkline Widget
**Files:** `oh/ui/sparkline_widget.py` (NEW)
**What:**
- Custom QWidget that draws a mini line chart using QPainter
- Input: `List[float]` values, width, height, color
- Features:
  - Draws polyline through data points
  - Fill gradient below line (subtle)
  - Last-point dot (current value)
  - Trend arrow: up (green) / down (red) / stable (gray)
  - Fixed size: ~80x24 pixels (fits in table cell)
- No external dependencies — pure QPainter

**Usage:** `SparklineWidget(values=[45, 52, 48, 65, 70], color="#4CAF50")`

**Depends on:** nothing
**Test:** Widget renders without crash, correct trend arrow

### E2. Trend Data Service
**Files:** `oh/services/trend_service.py` (NEW — or extend existing `source_trend_service.py`)
**What:**
- `get_health_trend(account_id, days=14) -> List[float]` — daily health scores
  - Computed from stored session + FBR data per day
- `get_follow_trend(account_id, days=14) -> List[int]` — daily follow counts from session_snapshots
- `get_fbr_trend(account_id, days=14) -> List[float]` — FBR% over time from fbr_snapshots
- `get_source_count_trend(account_id, days=14) -> List[int]` — active source count over time
- `get_trends_map(account_ids, days=14) -> Dict[int, AccountTrends]` — batch for table rendering

```python
@dataclass
class AccountTrends:
    follow_trend: List[int]       # daily follows, last N days
    health_trend: List[float]     # daily health, last N days
    fbr_trend: List[float]        # FBR% snapshots
    trend_direction: str          # up | down | stable
```

**Depends on:** existing session_repo, fbr_snapshot_repo
**Test:** Returns correct data from snapshots, handles missing days

### E3. UI — Sparklines in Main Table + Trend Dialog
**Files:** `oh/ui/main_window.py`, `oh/ui/trend_dialog.py` (NEW)
**What:**

**Main table changes:**
- New column "Trend" (after Health) — shows SparklineWidget with follow_trend
- Tooltip on hover shows: "Last 14 days: avg X follows/day, trend: up/down/stable"
- Sparklines loaded lazily (after table render, in background worker)

**Trend Dialog** (double-click Trend column or button):
- 4 sections with larger sparklines (400x100 pixels):
  1. Daily Follows (bar chart style)
  2. Health Score trend
  3. FBR% trend
  4. Active Sources trend
- Date range selector: 7d / 14d / 30d
- Account name + device header
- [Copy] button for text summary

**Depends on:** E1, E2
**Test:** Sparklines visible in table, dialog shows larger charts

---

## Migration 013 — Combined SQL

All new tables (features A, B, C) go into a single migration:

```python
_MIGRATION_013_SQL = """
-- Error Reporting
CREATE TABLE IF NOT EXISTS error_reports (...);

-- Block Detection
CREATE TABLE IF NOT EXISTS block_events (...);
CREATE INDEX IF NOT EXISTS idx_block_events_account ON block_events(...);

-- Account Groups
CREATE TABLE IF NOT EXISTS account_groups (...);
CREATE TABLE IF NOT EXISTS account_group_members (...);
CREATE INDEX IF NOT EXISTS idx_group_members_group ON account_group_members(group_id);
CREATE INDEX IF NOT EXISTS idx_group_members_account ON account_group_members(account_id);
"""
```

---

## Implementation Order

```
Migration 013 ──────────────────────────────────────────┐
                                                        │
┌── A. Error Reporting ─────────────────────────────┐   │
│   A1 migration ← A2 model ← A3 repo ← A4 service│   │
│   ← A5 exception hook ← A6 UI                    │   │
└───────────────────────────────────────────────────┘   │
                                                        │
┌── B. Block Detection ─────────────────────────────┐   │
│   B1 migration ← B2 model ← B3 repo ← B4 module │   │
│   ← B5 service ← B6 UI integration               │   │
└───────────────────────────────────────────────────┘   │
                                                        │
┌── C. Account Groups ─────────────────────────────┐    │
│   C1 migration ← C2 model ← C3 repo ← C4 service│   │
│   ← C5 dialog ← C6 filter + column               │   │
└───────────────────────────────────────────────────┘   │
                                                        │
┌── D. Bulk Operations ────────────────────────────┐    │
│   D1 multi-select + bulk dialog (depends on C4)  │    │
└──────────────────────────────────────────────────┘    │
                                                        │
┌── E. Performance Trends ─────────────────────────┐    │
│   E1 sparkline widget ← E2 trend service         │    │
│   ← E3 table column + dialog                     │    │
└──────────────────────────────────────────────────┘    │
```

**Parallel tracks:** A, B, C can be implemented in parallel (independent). D depends on C. E is fully independent.

---

## Risk Assessment

| Risk | Mitigation |
|------|-----------|
| Discord webhook rate limits | Queue reports, retry with backoff, cap at 10/hour |
| .stm file format varies by bot version | Graceful fallback — missing files = no detection, not crash |
| Block detection false positives | Confidence scoring + "Resolved" workflow, not auto-action |
| Multi-select breaks detail panel | When >1 selected, show aggregate summary instead |
| Sparkline performance with 200+ rows | Lazy render — load trend data in background after table paint |
| Group filter + other filters interaction | Groups are ANDed with other filters (same as existing pattern) |
| Privacy in error reports | Strip all account/device names, only send technical context |

---

## Test Plan

Each feature should have:
- **Unit tests** for models, repos, services (mock DB)
- **Integration test** for migration apply + CRUD cycle
- **Manual test** for UI interaction

Estimated: ~80 new tests across all features.

---

## Handoff

Plan is ready. Run `/coder` to start implementation. Recommended order:
1. Start with **Migration 013** (unlocks A, B, C in parallel)
2. Implement **A (Error Reporting)** first — CRITICAL for distribution
3. Then **B (Block Detection)** + **C (Groups)** in parallel
4. Then **D (Bulk Ops)** after C is done
5. Finally **E (Trends)** — independent, can be last
