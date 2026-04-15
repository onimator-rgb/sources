# OH v1.8.0 — Notifications Browser, Like Sources, Enhanced Settings Copier

## Summary

Three new features based on analysis of Onimator Helper Suite:
1. **Notifications Browser** — new main tab reading bot's `notificationdatabase.db` (blocks, suspends, errors, logins)
2. **Like Sources + LBR** — split Sources tab into Follow/Like sub-tabs, with Like-Back Rate analytics mirroring FBR
3. **Enhanced Settings Copier** — expand from 17 to 165+ settings in 9 collapsible categories + text file copying

## Architecture Decisions

| Feature | Layers | DB Changes |
|---------|--------|------------|
| Notifications | Module + Service + UI (new tab) | None — read-only from bot |
| Like Sources | Module + Model + Repo + Service + UI | Migration 017: `lbr_snapshots` + `lbr_source_results` |
| Settings Copier | Model + Module + Service + UI (dialog redesign) | None — writes to bot's `settings.db` |

---

## Task List

### Feature 1: Notifications Browser

#### Task 1.1 — Notification model
**Files**: Create `oh/models/notification.py`
**What**:
```python
@dataclass
class NotificationRecord:
    device_id: str
    account: Optional[str]  # NULL for device-level
    notification: str
    date: str
    time: str
    notification_type: str  # parsed category: Added, Deleted, Login, Block, Suspended, Error, Other

NOTIFICATION_TYPES = {
    "Added": "success",      # green
    "Deleted": "critical",   # red
    "Login": "link",         # blue
    "Block": "high",         # orange
    "Suspended": "warning",  # lighter orange
    "Error": "error",        # pink
}
```
- `notification_type` is derived by keyword matching on the `notification` text
- Map type names to semantic color keys from `oh/ui/style.py`
**Depends on**: Nothing
**Test criteria**: Dataclass instantiates correctly; type classification works for all known types

#### Task 1.2 — Notification reader module
**Files**: Create `oh/modules/notification_reader.py`
**What**:
- Class `NotificationReader(bot_root: str)`
- Method `read_all() -> List[NotificationRecord]`
  - Opens `{bot_root}/notificationdatabase.db` with `?mode=ro`
  - SQL: `SELECT deviceid, account, notification, date, time FROM notifications ORDER BY date DESC, time DESC`
  - Classifies each row's `notification` text into a type using keyword matching:
    - Contains "Added" → Added
    - Contains "Deleted" or "Removed" → Deleted
    - Contains "Login" or "Logged" → Login
    - Contains "Block" → Block
    - Contains "Suspended" → Suspended
    - Contains "Error" or "Exception" or "Failed" → Error
    - Otherwise → Other
  - Returns list of `NotificationRecord`
- Method `get_notification_types() -> List[str]` — returns distinct notification types found
- Method `get_devices() -> List[str]` — returns distinct device IDs
- Handle missing DB gracefully (return empty list + log warning)
**Depends on**: Task 1.1
**Test criteria**: Reads real notificationdatabase.db; returns correct types; handles missing DB

#### Task 1.3 — Notification service
**Files**: Create `oh/services/notification_service.py`
**What**:
- Class `NotificationService(settings_repo)`
- Method `load_notifications(bot_root) -> List[NotificationRecord]`
  - Creates `NotificationReader`, calls `read_all()`
  - Enriches device IDs with device names from `oh_devices` table (if available)
- Method `get_filter_options(bot_root) -> dict` — returns devices list, types list, accounts list
- Method `export_csv(records, path)` — writes filtered records to CSV
**Depends on**: Task 1.2
**Test criteria**: Service loads data; CSV export works; handles empty data

#### Task 1.4 — Notifications tab UI
**Files**: Create `oh/ui/notifications_tab.py`
**What**:
- Class `NotificationsTab(QWidget)` following `DeviceFleetTab` pattern
- Layout: toolbar + filter bar + table
- **Toolbar**: Refresh button, Export CSV button, status label, busy indicator, count label ("Showing X of Y")
- **Filter bar**:
  - Device combo (All + discovered devices)
  - Type combo (All + each notification type)
  - Account search (QLineEdit with placeholder "Search account...")
  - Date From / Date To (QDateEdit with calendar popup)
  - "Show empty accounts" checkbox (include NULL account rows)
  - Clear Filters button
- **Table** (QTableWidget, 5 columns):
  - Device (show device name if available, fallback to ID)
  - Account
  - Notification (text with colored background/foreground based on type)
  - Date
  - Time
- Color coding: use `sc()` from style.py for type-to-color mapping
- Sorting: clickable column headers (use `_SortableItem` pattern)
- Filtering: client-side filter on loaded data (no re-read from DB)
- Load data via `WorkerThread` on first tab activation (lazy load)
- Right-click context menu: Copy row, Filter by this account, Filter by this device, Filter by this type
**Depends on**: Task 1.3
**Test criteria**: Tab renders; filters work; sorting works; CSV export works; lazy loading works; colors visible in both themes

#### Task 1.5 — Wire Notifications tab into MainWindow
**Files**: Modify `oh/ui/main_window.py`
**What**:
- Import `NotificationsTab`
- Create `NotificationService` in `__init__`
- Add tab at index 5 (after Fleet, before Settings): `self._tabs.addTab(notifications_tab, "Notifications")`
- Add lazy-load logic in `_on_tab_changed()` (same pattern as Fleet tab)
- Pass `bot_root` to tab on path change (same pattern as other tabs)
**Depends on**: Task 1.4
**Test criteria**: Tab appears in correct position; loads data when clicked; respects bot path changes

---

### Feature 2: Like Sources + LBR Analytics

#### Task 2.1 — LBR models
**Files**: Create `oh/models/lbr.py`
**What**: Mirror `fbr.py` + `fbr_snapshot.py` structure:
```python
@dataclass
class SourceLBRRecord:
    source_name: str
    like_count: int          # total users liked from this source
    followback_count: int    # users who followed back after being liked
    lbr_percent: float       # (followback_count / like_count) * 100
    is_quality: bool
    anomaly: Optional[str]

@dataclass
class LBRAnalysisResult:
    device_id: str
    username: str
    records: List[SourceLBRRecord]
    schema_valid: bool
    schema_error: Optional[str]
    min_likes: int
    min_lbr_pct: float
    warnings: List[str]
    # Properties: has_data, quality_count, total_count, best_source_by_lbr, highest_volume_source

@dataclass
class LBRSnapshotRecord:
    account_id: int
    device_id: str
    username: str
    analyzed_at: str
    min_likes: int
    min_lbr_pct: float
    total_sources: int
    quality_sources: int
    status: str
    best_lbr_pct: float
    best_lbr_source: Optional[str]
    highest_vol_source: Optional[str]
    highest_vol_count: int
    below_volume_count: int
    anomaly_count: int
    warnings_json: Optional[str]
    schema_error: Optional[str]
    id: Optional[int] = None

@dataclass
class BatchLBRResult:
    total_accounts: int
    analyzed: int
    skipped: int
    errors: int
    snapshots: List[LBRSnapshotRecord]
```
**Depends on**: Nothing
**Test criteria**: All dataclasses instantiate; properties compute correctly

#### Task 2.2 — LBR calculator module
**Files**: Create `oh/modules/lbr_calculator.py`
**What**: Mirror `FBRCalculator` pattern:
- Class `LBRCalculator(bot_root: str, min_likes: int = 50, min_lbr_pct: float = 5.0)`
- Method `calculate(device_id, username) -> LBRAnalysisResult`
  - Opens `{bot_root}/{device_id}/{username}/likes.db` with `?mode=ro`
  - Validates schema: table `likes` with columns `{source, liked, follow_back}`
  - SQL:
    ```sql
    SELECT TRIM(source) AS source_name,
           COUNT(*) AS like_count,
           SUM(CASE WHEN follow_back = 1 THEN 1 ELSE 0 END) AS followback_count
    FROM likes
    WHERE source IS NOT NULL AND LOWER(TRIM(source)) NOT IN ('none', 'null', '')
    GROUP BY TRIM(source)
    ORDER BY like_count DESC, source_name ASC
    ```
  - Compute LBR% per source, apply quality threshold, detect anomalies
  - Return `LBRAnalysisResult`
- Also read `like-source-followers.txt` to know which sources are currently active
**Depends on**: Task 2.1
**Test criteria**: Reads real likes.db; computes correct LBR%; handles missing DB; detects anomalies

#### Task 2.3 — Like source usage reader
**Files**: Create `oh/modules/like_source_usage_reader.py`
**What**: Mirror `source_usage_reader.py` pattern:
- Class `LikeSourceUsageReader(bot_root: str)`
- Method `read_usage(device_id, username, source_name) -> SourceUsageRecord`
  - Opens `{bot_root}/{device_id}/{username}/like_sources/{source_name}.db` with `?mode=ro`
  - Reads `SELECT COUNT(*) FROM like_source_followers` for used count
  - Returns usage record
**Depends on**: Nothing
**Test criteria**: Reads real like_sources/ DB files; handles missing files

#### Task 2.4 — Global like sources model
**Files**: Create `oh/models/global_like_source.py`
**What**: Mirror `global_source.py`:
```python
@dataclass
class LikeSourceAccountDetail:
    account_id: int
    username: str
    device_id: str
    device_name: Optional[str]
    is_active: bool
    like_count: int
    followback_count: int
    lbr_percent: float
    is_quality: bool
    last_analyzed_at: Optional[str]

@dataclass
class GlobalLikeSourceRecord:
    source_name: str
    active_accounts: int
    historical_accounts: int
    total_likes: int
    total_followbacks: int
    avg_lbr_pct: float
    weighted_lbr_pct: float
    quality_account_count: int
    last_analyzed_at: Optional[str]
```
**Depends on**: Nothing
**Test criteria**: Dataclasses instantiate correctly

#### Task 2.5 — DB migration 017: LBR tables
**Files**: Modify `oh/db/migrations.py`
**What**: Add migration 017 `lbr_tables`:
```sql
CREATE TABLE IF NOT EXISTS lbr_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES oh_accounts(id),
    device_id TEXT NOT NULL,
    username TEXT NOT NULL,
    analyzed_at TEXT NOT NULL,
    min_likes INTEGER NOT NULL,
    min_lbr_pct REAL NOT NULL,
    total_sources INTEGER NOT NULL DEFAULT 0,
    quality_sources INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ok',
    best_lbr_pct REAL,
    best_lbr_source TEXT,
    highest_vol_source TEXT,
    highest_vol_count INTEGER DEFAULT 0,
    below_volume_count INTEGER NOT NULL DEFAULT 0,
    anomaly_count INTEGER NOT NULL DEFAULT 0,
    warnings_json TEXT,
    schema_error TEXT
);

CREATE TABLE IF NOT EXISTS lbr_source_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    snapshot_id INTEGER NOT NULL REFERENCES lbr_snapshots(id),
    source_name TEXT NOT NULL,
    like_count INTEGER NOT NULL DEFAULT 0,
    followback_count INTEGER NOT NULL DEFAULT 0,
    lbr_percent REAL NOT NULL DEFAULT 0.0,
    is_quality INTEGER NOT NULL DEFAULT 0,
    anomaly TEXT
);

CREATE TABLE IF NOT EXISTS like_source_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES oh_accounts(id),
    source_name TEXT NOT NULL,
    is_active INTEGER NOT NULL DEFAULT 1,
    snapshot_id INTEGER REFERENCES lbr_snapshots(id),
    updated_at TEXT,
    created_at TEXT,
    UNIQUE(account_id, source_name)
);
```
**Depends on**: Nothing
**Test criteria**: Migration applies cleanly; tables exist after startup

#### Task 2.6 — LBR snapshot repository
**Files**: Create `oh/repositories/lbr_snapshot_repo.py`
**What**: Mirror `fbr_snapshot_repo.py`:
- Class `LBRSnapshotRepository(conn)`
- Methods: `save(snapshot)`, `save_source_results(snapshot_id, records)`, `get_latest_map()`, `get_for_account(account_id)`, `get_source_results(snapshot_id)`
**Depends on**: Task 2.1, Task 2.5
**Test criteria**: Save and retrieve snapshots; latest map returns most recent per account

#### Task 2.7 — Like source assignment repository
**Files**: Create `oh/repositories/like_source_assignment_repo.py`
**What**: Mirror `source_assignment_repo.py`:
- Tracks which like sources are assigned to which accounts
- Methods: `upsert(account_id, source_name, is_active, snapshot_id)`, `get_for_account(account_id)`, `get_all_active()`
**Depends on**: Task 2.5
**Test criteria**: CRUD operations work; unique constraint enforced

#### Task 2.8 — Global like sources service
**Files**: Create `oh/services/global_like_sources_service.py`
**What**: Mirror `global_sources_service.py`:
- Class `GlobalLikeSourcesService(lbr_snapshot_repo, like_assignment_repo, account_repo)`
- Method `get_all() -> List[GlobalLikeSourceRecord]` — aggregates LBR data across all accounts per source
- Method `get_detail(source_name) -> List[LikeSourceAccountDetail]` — per-account breakdown
**Depends on**: Task 2.4, Task 2.6, Task 2.7
**Test criteria**: Aggregation correct; weighted LBR calculated properly

#### Task 2.9 — LBR analysis service
**Files**: Create `oh/services/lbr_service.py`
**What**: Mirror `fbr_service.py`:
- Class `LBRService(lbr_snapshot_repo, account_repo, settings_repo, like_assignment_repo)`
- Method `analyze_and_save(bot_root, device_id, username, account_id) -> (LBRAnalysisResult, LBRSnapshotRecord)`
- Method `analyze_all_active(bot_root) -> BatchLBRResult`
- Method `get_latest_map() -> dict`
- Uses `LBRCalculator` internally
- Reads `like-source-followers.txt` for active source list
- Updates `like_source_assignments` table
**Depends on**: Task 2.2, Task 2.6, Task 2.7
**Test criteria**: Analyzes real accounts; saves snapshots; batch works across fleet

#### Task 2.10 — Like Sources tab UI
**Files**: Create `oh/ui/like_sources_tab.py`
**What**: Mirror `sources_tab.py` structure but for like data:
- Class `LikeSourcesTab(QWidget)`
- Constructor deps: `global_like_sources_service, settings_repo, conn`
- **Toolbar**: Refresh, Analyze LBR, Export CSV, status label, busy indicator
- **Filter bar**: Search, min active accs spinner, min likes spinner, LBR quality combo, Clear, count label
- **Table** (9 columns): Source, Active Accs, Hist. Accs, Total Likes, Followbacks, Avg LBR%, Wtd LBR%, Quality, Last Updated
- **Detail pane** (splitter below): 8 columns: Username, Device, Likes, Followbacks, LBR%, Quality, Used, Used%
- Sorting via `_SortableItem`
- Color coding: quality sources get green tint, anomalies get warning color
- Load via `WorkerThread`
**Depends on**: Task 2.8, Task 2.9
**Test criteria**: Tab renders; data loads; filters work; detail pane updates on selection; both themes correct

#### Task 2.11 — Split Sources tab into sub-tabs
**Files**: Modify `oh/ui/sources_tab.py`, modify `oh/ui/main_window.py`
**What**:
- In `sources_tab.py`: rename class to `FollowSourcesTab` (internal, for clarity)
- Create a new wrapper widget `SourcesTabContainer(QWidget)`:
  - Contains a `QTabWidget` with 2 sub-tabs:
    - "Follow Sources" → existing `FollowSourcesTab` (moved here)
    - "Like Sources" → new `LikeSourcesTab`
  - Exposes `load_data()` that delegates to both sub-tabs
  - Exposes `set_bot_root()` that delegates to both sub-tabs
- In `main_window.py`:
  - Replace `SourcesTab` instantiation with `SourcesTabContainer`
  - Create LBR-related repos and services in `__init__`
  - Wire "Analyze LBR" into the existing scan flow (option to run after FBR)
  - Add "Analyze LBR" button to accounts tab toolbar (next to "Analyze FBR")
**Depends on**: Task 2.10
**Test criteria**: Sources tab shows two sub-tabs; Follow Sources behaves exactly as before; Like Sources loads data; switching sub-tabs is smooth

---

### Feature 3: Enhanced Settings Copier

#### Task 3.1 — Expanded settings model
**Files**: Modify `oh/models/settings_copy.py`
**What**:
- Keep existing dataclasses unchanged
- Replace flat `COPYABLE_SETTINGS` dict with categorized structure:
```python
@dataclass
class SettingDef:
    key: str           # JSON path (dot notation for nested, e.g. "follow_method.follow_followers")
    display_name: str
    value_type: str    # "bool", "int", "float", "str"

@dataclass
class SettingsCategory:
    name: str          # e.g. "Follow"
    key: str           # e.g. "follow"
    settings: List[SettingDef]

SETTINGS_CATEGORIES: List[SettingsCategory] = [...]
```
- Define all 9 categories with ~165 settings (exact keys from Helper Suite research):
  1. **Follow** (~45): follow_method.*, min/max_user_follow, follow delays, filters.*, weekday scheduling, story interactions, mute_after_follow, etc.
  2. **Unfollow** (~25): unfollow_method.*, min/max_user_unfollow, delays, unfollowdelayday, dont_unfollow_followers, close_friend, weekday scheduling
  3. **Like** (~30): likepost_method.*, min/max_likepost_action, delays, like_limit_perday, filters_like.*, story interactions, post counts
  4. **Story** (~15): view_method.*, story_viewer_min/max, story_view_peraccount, daily limits, highlight options
  5. **Reels** (~6): enable_watch_reels, min/max_reels_to_watch, watch duration, like_reel, save
  6. **DM** (~14): enable_directmessage, directmessage_method.*, min/max counts, delays, daily limit, auto-increment, OpenAI
  7. **Share** (~12): enable_shared_post, share_to_story, repost, link, mention, limits
  8. **Post** (1): enable_scheduled_post
  9. **Human Behavior** (~18): home feed stories, scroll home feed, scroll explore, all with min/max and delays
- Keep a flat `ALL_COPYABLE_KEYS` set for backward compatibility with validation
- Add `COPYABLE_TEXT_FILES` list:
  ```python
  COPYABLE_TEXT_FILES = [
      ("name_must_include.txt", "Follow name filter (include)"),
      ("name_must_not_include.txt", "Follow name filter (exclude)"),
      ("name_must_include_likes.txt", "Like name filter (include)"),
      ("name_must_not_include_likes.txt", "Like name filter (exclude)"),
  ]
  ```
**Depends on**: Nothing
**Test criteria**: All 165+ keys defined; categories cover all Helper Suite settings; backward compatibility maintained

#### Task 3.2 — Enhanced settings copier module
**Files**: Modify `oh/modules/settings_copier.py`
**What**:
- `read_settings()` — expand to read ALL keys from `SETTINGS_CATEGORIES`, including nested JSON paths:
  - For dot-notation keys like `follow_method.follow_followers`: traverse JSON dict (`settings["follow_method"]["follow_followers"]`)
  - Return full `SettingsSnapshot` with all readable values
- `write_settings()` — expand to write nested JSON paths:
  - For dot-notation: create intermediate dicts if missing, set leaf value
  - Validate against `ALL_COPYABLE_KEYS`
  - Backup still mandatory
- New method `read_text_files(device_id, username) -> dict[str, Optional[str]]`:
  - Reads each file from `COPYABLE_TEXT_FILES` in account folder
  - Returns filename → content mapping (None if file doesn't exist)
- New method `write_text_files(device_id, username, files: dict[str, str])`:
  - Backs up existing file as `.bak`
  - Writes new content
  - Only writes files that differ from current content
**Depends on**: Task 3.1
**Test criteria**: Nested JSON paths read/write correctly; text files copied; backups created; missing keys handled gracefully

#### Task 3.3 — Enhanced settings copier service
**Files**: Modify `oh/services/settings_copier_service.py`
**What**:
- `read_source_settings()` — now reads all categories + text files
- Add `text_files` field to `SettingsSnapshot` (dict of filename → content)
- `preview_diff()` — include text file diffs (show "differs" / "same" / "missing")
- `apply_copy()` — copy selected settings keys + selected text files
- Audit trail: log category-level summary in `operator_actions` (e.g. "Copied Follow (12 keys), Like (8 keys), 2 text files")
**Depends on**: Task 3.2
**Test criteria**: Full category read works; diff shows correct changes; text files included; audit trail logged

#### Task 3.4 — Redesigned settings copier dialog
**Files**: Modify `oh/ui/settings_copier_dialog.py`
**What**: Keep 3-step wizard structure, redesign Step 1:
- **Step 1 (Source + Settings Selection)**:
  - Source account combo (unchanged)
  - Replace flat checkbox list with **collapsible category sections**:
    - Each category is a `QGroupBox` with a checkbox in the title (select/deselect all in category)
    - Inside: grid of checkboxes for individual settings, showing current value
    - Collapsed by default, click to expand
    - "Select All" / "Deselect All" buttons at the top (across all categories)
  - **Text Files section** at the bottom:
    - Separate `QGroupBox` "Text Files"
    - Checkboxes for each copyable text file with display name
    - Show "(exists)" or "(missing)" next to each
  - Implementation: use `QToolButton` with arrow icon for collapse/expand, or a custom `CollapsibleSection` widget:
    ```python
    class CollapsibleSection(QWidget):
        def __init__(self, title, parent=None):
            # QToolButton (arrow + title + select-all checkbox)
            # QScrollArea with content widget (hidden by default)
            # Toggle animation or instant show/hide
    ```
- **Step 2 (Targets + Preview)**: unchanged structure, but diff table now groups by category with category headers (gray separator rows)
- **Step 3 (Results)**: add text file copy results to summary
**Depends on**: Task 3.3
**Test criteria**: Categories render correctly; collapse/expand smooth; select all/none works per category and globally; text file section shows correctly; diff preview groups by category; both themes look good

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| `notificationdatabase.db` schema varies across bot versions | Notifications tab shows no data | Schema validation like FBR calculator; graceful fallback with user message |
| `likes.db` may not have `source` or `follow_back` columns on older bots | LBR analysis fails | Schema validation before query; show "unsupported" status |
| Nested JSON write in settings copier corrupts settings.db | Bot accounts break | Mandatory backup; read-after-write validation; only modify known keys |
| Sources tab split breaks existing functionality | Regression | Keep `FollowSourcesTab` code changes minimal (rename only); wrapper is additive |
| 165+ settings checkboxes make dialog too tall | Poor UX | Collapsible sections; collapsed by default; scroll area |
| Performance: loading all notifications for large fleets | UI freeze | WorkerThread; consider LIMIT/pagination if >10k rows |

## Complexity

| Feature | Estimate | Rationale |
|---------|----------|-----------|
| Notifications Browser | **M** | New module/service/tab but straightforward read-only pattern |
| Like Sources + LBR | **L** | Full FBR parallel: module, model, repo, service, UI + migration + tab restructuring |
| Enhanced Settings Copier | **M** | Model + module expansion is data-heavy but structurally simple; UI redesign is moderate |
| **Total** | **L-XL** | Three features touching many layers, but each follows established patterns |

## Implementation Order

```
Phase A (foundation):
  Task 1.1 + 1.2 + 1.3          Notification model/module/service
  Task 2.1 + 2.2 + 2.3 + 2.4   LBR models + calculator + usage reader
  Task 2.5                       DB migration
  Task 3.1                       Expanded settings model

Phase B (persistence + services):
  Task 2.6 + 2.7                 LBR repos
  Task 2.8 + 2.9                 LBR services
  Task 3.2 + 3.3                 Settings copier module/service expansion

Phase C (UI):
  Task 1.4 + 1.5                 Notifications tab + wiring
  Task 2.10 + 2.11               Like Sources tab + Sources split
  Task 3.4                       Settings copier dialog redesign
```

Phases A and B can be parallelized across features (no cross-dependencies).

## Handoff

Once approved, run `/coder` to begin implementation following Phase A → B → C order.
