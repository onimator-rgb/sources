# Account Detail View — Feature Proposal

> **Phase 5 feature** | Priority: **CRITICAL** | Author: Architect agent | Date: 2026-04-01

---

## Problem

Operators managing 100+ Instagram accounts must currently jump between 5+ different views to review a single account:

1. **Accounts tab** — username, device, status, tags, session counters, FBR summary
2. **Sources dialog** — per-account sources with FBR and usage data
3. **Session Report** — session data across all accounts (not per-account)
4. **Recommendations dialog** — account-level findings mixed with source-level
5. **Action History** — global audit trail (not filtered per-account)
6. **Phone Preview** / Explorer — manual folder inspection

This fragmentation means each account review takes 2-5 minutes of clicking and mental context-switching. At 100+ accounts, daily reviews become impractical. The operator cannot answer "what is the full picture of this account?" from any single screen.

## Solution

A unified **Account Detail View** (drawer panel) that opens when clicking an account row. It consolidates every piece of data OH knows about an account into one scrollable, tabbed interface with inline actions.

---

## 1. UX Proposal

### Layout: Right-side Drawer (recommended)

| Option | Pros | Cons | Verdict |
|--------|------|------|---------|
| **Right drawer** | No navigation away from table; see account list alongside detail; fast open/close | Horizontal space pressure on smaller monitors | **Recommended** |
| Full-page dialog | Maximum space for content | Loses table context; slower workflow | Phase 2 fallback for deep analysis |
| Modal dialog | Familiar pattern in OH | Blocks table interaction; feels heavy for quick reviews | Reject |
| Split view (horizontal) | Table + detail side by side | Too cramped vertically for both | Reject |

**Drawer behavior:**
- Opens to the right of the Accounts table, taking ~45% of window width (min 520px)
- Table columns compress automatically (hide low-priority columns like Discovered, Last Seen, Data DB, Sources.txt)
- Single-click on a row opens the drawer for that account (replaces current double-click = open folder)
- Double-click on a row still opens the folder (backward compatible)
- `Escape` or close button collapses the drawer
- Arrow keys navigate accounts while drawer stays open (live update)
- Drawer remembers open/closed state and last active tab within session

**Internal layout: Tabbed sections within the drawer**

```
+---------------------------------------------------+
| [x] username@device_name                    [Close]|
|     Status: Active  |  Slot: 06-12  |  Review: !  |
+---------------------------------------------------+
| [Summary] [Sources] [History] [Alerts] [Actions]   |
|                                                     |
|  (tab content area — scrollable)                    |
|                                                     |
+---------------------------------------------------+
| [Copy Diagnostic] [Open Folder] [Phone Preview]    |
+---------------------------------------------------+
```

### What is visible immediately (no clicks):

The **Summary tab** is the default and shows the most critical information at a glance. The operator should be able to assess "is this account OK?" within 3 seconds of opening.

### What requires one click (tabs):

- Sources detail (tab 2)
- Full history/audit log (tab 3)
- Alerts and issues (tab 4)
- Quick actions (tab 5)

---

## 2. Data Sections and Fields

### Tab 1: Summary (default, always visible first)

#### Identity Block (top, always shown)

| Field | Source | Priority | Visual treatment |
|-------|--------|----------|-----------------|
| Username | `AccountRecord.username` | CRITICAL | Large bold text |
| Device | `AccountRecord.device_name` + status dot | CRITICAL | Green/gray/red dot prefix |
| Status | `AccountRecord.is_active` | CRITICAL | Active=green, Removed=gray |
| Tags | `bot_tags_raw` + operator tags | CRITICAL | Bot tags normal, OP: tags amber |
| Review flag | `review_flag` + `review_note` | CRITICAL | Red badge if flagged, note text below |
| Account ID | `AccountRecord.id` | LOW | Small muted text |

#### Performance Cards (horizontal row of 4 cards)

| Card | Data | Visual |
|------|------|--------|
| **Today's Activity** | Follow: N / Limit | Like: N / Limit | DM: N | Green if active, red if zero in active slot |
| **FBR Status** | Quality/Total sources, Best FBR% | Green if quality > 0, amber if 0, red if never analyzed |
| **Source Health** | Active sources count, quality count | Red if 0 sources, amber if < 3 |
| **Account Health** | TB level, Limits level, days since last activity | Red if TB>=4 or limits>=4 |

#### Configuration Block

| Field | Source | Priority |
|-------|--------|----------|
| Follow enabled | `follow_enabled` | HIGH |
| Unfollow enabled | `unfollow_enabled` | HIGH |
| Follow limit/day | `follow_limit_perday` | HIGH |
| Like limit/day | `like_limit_perday` | HIGH |
| Limit per day (old) | `limit_per_day` | MEDIUM |
| Time slot | `start_time` - `end_time` | HIGH |
| Last seen | `last_seen_at` | MEDIUM |
| Discovered | `discovered_at` | LOW |
| Last FBR analysis | `FBRSnapshotRecord.analyzed_at` | MEDIUM |
| data.db exists | `data_db_exists` | LOW |
| sources.txt exists | `sources_txt_exists` | LOW |

#### FBR Snapshot Summary

| Field | Source | Visual |
|-------|--------|--------|
| Quality / Total | `FBRSnapshotRecord.quality_sources` / `total_sources` | Green ratio or "Never analyzed" |
| Best FBR % | `best_fbr_pct` + `best_fbr_source` | Bold green number |
| Highest volume | `highest_vol_source` + `highest_vol_count` | Normal |
| Below volume floor | `below_volume_count` | Amber if > half of total |
| Anomalies | `anomaly_count` | Red if > 0 |
| Schema status | `status` / `schema_error` | Red badge if error |

### Tab 2: Sources

Reuses data from the existing `SourceDialog` but embedded inline (not as a separate modal).

| Column | Source | Notes |
|--------|--------|-------|
| Source name | `SourceInspectionResult` | Link to global sources tab |
| Status | active+history / active(new) / historical | Color coded |
| Follows | `SourceFBRRecord.follow_count` | Right-aligned |
| Follow-backs | `SourceFBRRecord.followback_count` | Right-aligned |
| FBR % | `SourceFBRRecord.fbr_percent` | Green if quality, gray otherwise |
| Quality | is_quality | Checkmark or X |
| Used | `SourceUsageRecord.used_count` | Right-aligned |
| Used % | `SourceUsageRecord.used_pct` | Right-aligned |

**Additional elements:**
- Summary bar: "12 active, 3 quality, 9 need attention"
- Quick-add source: text input + "Add" button (writes to sources.txt)
- "Remove Non-Quality" button (reuses `on_cleanup` callback)
- Per-source right-click: Remove, Replace (remove + add), View in Global
- **System suggestion**: if active sources < 3, show amber banner: "Account has fewer than 3 active sources. Consider adding more via Find Sources."

### Tab 3: History (Timeline / Audit Log)

A unified chronological timeline combining ALL events for this account. This is the key differentiator -- no other view in OH shows per-account history.

| Event type | Source | Icon/Color |
|------------|--------|-----------|
| Tag change (bot) | Compare `bot_tags_raw` across syncs | Blue |
| Tag change (operator) | `OperatorActionRecord` where `action_type` = add_tag/remove_tag | Amber |
| Review set/cleared | `OperatorActionRecord` where `action_type` = set_review/clear_review | Purple |
| TB increment | `OperatorActionRecord` where `action_type` = increment_tb | Red |
| Limits increment | `OperatorActionRecord` where `action_type` = increment_limits | Orange |
| Source added | `source_delete_actions` where `delete_type` = revert + account match | Green |
| Source removed | `source_delete_items` where account in affected_accounts | Red |
| FBR analysis | `fbr_snapshots` for this account_id | Blue |
| Session snapshots | `session_snapshots` for this account_id (daily records) | Gray |
| Device transfer | Detect `device_id` change across syncs | Amber |
| Account discovered | `discovered_at` | Green |
| Account removed | `removed_at` | Red |
| Operator note | `OperatorActionRecord.note` field | Gray italic |

**Timeline display:**
```
2026-04-01 14:32  [TB]     TB2 -> TB3          by DESKTOP-ABC
2026-04-01 10:15  [REVIEW] Set: "follow is pending"  by DESKTOP-ABC
2026-03-31 18:00  [SESSION] Follow: 87, Like: 120, DM: 5
2026-03-31 12:00  [SOURCE] Removed: fitness_daily (wFBR 3.2%)
2026-03-30 09:00  [FBR]    Analyzed: 4/12 quality, best 18.3%
2026-03-29 15:22  [TAG]    Bot tags: [3] SLAVE TB2 -> [3] SLAVE TB2 START
```

**Controls:**
- Filter by event type (checkboxes)
- Date range selector
- "Load more" pagination (show last 50 events initially)

### Tab 4: Alerts and Issues

Consolidated view of everything that needs operator attention for THIS account.

#### Active Alerts (auto-generated)

| Alert condition | Severity | Trigger | Recommended action |
|-----------------|----------|---------|-------------------|
| Zero actions in active slot | CRITICAL | `has_activity=False` AND device running AND current hour in slot | Check popup/2FA/block |
| Device offline | CRITICAL | `device_status != running` | Check cable/WiFi/power |
| TB >= 4 | CRITICAL | Operator tag TB4/TB5 | Move to another device |
| Follow is pending | HIGH | `review_note` contains "pending" | Disable follow 48h, monitor |
| No sources for DM | HIGH | 0 active sources AND DM configured | Add sources or mark as read |
| Try again later | HIGH | `review_note` contains "try again" | Increase TB level |
| Limits >= 4 | HIGH | Operator tag limits 4/5 | Replace exhausted sources |
| Follow = 0 but other actions active | HIGH | `follow_count=0` AND `like_count>0` | Check sources/popup |
| Low follow (< 40) | MEDIUM | `follow_count < 40` | Check throttle/block |
| Like = 0 despite limit | MEDIUM | `like_count=0` AND `like_limit > 0` | Check like sources |
| Few active sources (< 3) | MEDIUM | `active_source_count < 3` | Add sources |
| No quality sources | MEDIUM | `quality_sources = 0` | Replace sources, check FBR |
| Below 50% follow limit | LOW | `follow_count < follow_limit * 0.5` | Monitor |
| Never analyzed FBR | LOW | No FBR snapshot | Run Analyze FBR |

#### Review History

| Field | Source |
|-------|--------|
| Current review status | `review_flag` + `review_note` + `review_set_at` |
| Past reviews | `OperatorActionRecord` filtered to set_review/clear_review |
| Review count (all time) | COUNT of review actions |

#### Specific Case Handling (inline recommendation cards)

When the account matches a known pattern, show a highlighted card with the recommended workflow:

**"follow is pending" detected:**
```
[!] Follow action is pending on this account.
    Recommended: Disable follow for 48h, then re-enable and monitor.
    [Disable Follow 48h]  [Dismiss]
```

**"no sources for DM" detected:**
```
[!] Account has no sources for DM delivery.
    Recommended: Mark DM queue as read, add fresh sources.
    [Open Sources]  [Dismiss]
```

**"try again later" detected:**
```
[!] Account is getting "try again later" responses.
    Recommended: Increase TB level and apply warmup procedure.
    [TB +1]  [View Warmup Guide]  [Dismiss]
```

### Tab 5: Quick Actions

All operator actions available for this account, organized by risk level.

#### Basic Actions (no confirmation needed)

| Action | Effect | Shortcut |
|--------|--------|----------|
| Edit tags | Open tag editor inline | `T` |
| Mark review read | Clear review flag | `R` |
| Add note | Set review with note | `N` |
| Copy diagnostic summary | Copy account summary to clipboard | `Ctrl+C` |

#### Standard Actions (confirmation dialog)

| Action | Effect | Condition |
|--------|--------|-----------|
| Open sources | Switch to Sources tab | Always |
| Add source | Write to sources.txt | Always |
| Replace sources | Remove non-quality + add suggestions | Has FBR data |
| Restart warmup | Set TB to 1, apply warmup limits | TB > 0 |
| TB +1 | Increment TB level | TB < 5 |
| Limits +1 | Increment limits level | Limits < 5 |
| Adjust follow limit | Write new follow_limit_perday | Has settings.db |
| Adjust like limit | Write new like_limit_perday | Has settings.db |
| Find sources (AI) | Open Source Finder dialog | HikerAPI key set |

#### Dangerous Actions (require explicit confirmation with consequences shown)

| Action | Effect | Warning |
|--------|--------|---------|
| Disable follow 48h | Set follow_enabled=False, schedule re-enable | "Account will not follow for 48 hours" |
| Move account to device | Change device_id, update folder refs | "This moves the account folder reference" |
| Remove all sources | Clear sources.txt | "Account will have 0 sources" |
| Delete account | Mark as removed | "Account will be soft-deleted from OH" |

#### Contextual Actions (shown only when relevant)

| Condition | Action shown |
|-----------|-------------|
| TB >= 3 | "Apply warmup procedure" with TB-specific limits |
| Limits >= 4 | "Replace exhausted sources" |
| Review flagged | "Clear review" (prominent) |
| Zero activity + device running | "Check on device" link |
| No FBR data | "Run FBR Analysis" |
| < 3 active sources | "Find Sources" |

---

## 3. Additional Sections, Buttons, Shortcuts, and Indicators (beyond operator request)

### Additional sections proposed by Architect:

#### A. Performance Trends (mini-charts)

| Metric | Visualization | Time range |
|--------|--------------|------------|
| Daily follow count | Sparkline (7-day) | Last 7 days from session_snapshots |
| Daily like count | Sparkline (7-day) | Last 7 days |
| FBR quality ratio | Sparkline per analysis | Last 5 FBR snapshots |
| Source count over time | Sparkline | From source_assignments timestamps |

Implementation: Simple text-based sparklines using Unicode block characters (no charting library needed). Example: `Follow 7d: _..--^^` or numeric: `12 → 45 → 87 → 92 → 88 → 91 → 95`.

#### B. Peer Comparison

Show how this account compares to others on the same device and fleet-wide:

| Metric | This account | Device avg | Fleet avg |
|--------|-------------|-----------|-----------|
| Follow today | 87 | 72 | 68 |
| Quality sources | 4/12 | 3/10 | 5/14 |
| FBR best % | 18.3 | 14.1 | 15.7 |

This helps operators immediately spot if an account is underperforming relative to peers.

#### C. Related Accounts Panel

Show other accounts on the same device (compact list):

```
Same device (Pixel_7_Pro):
  account_a  Follow: 92  FBR: 4/12  [Active]
  account_b  Follow: 0   FBR: 0/8   [Review!]
  account_c  Follow: 45  FBR: 2/6   [TB3]
```

Clicking any of these switches the drawer to that account. Helps with device-level diagnosis.

#### D. Session History Table

Show the last 14 days of session snapshots for this account:

| Date | Slot | Follow | Like | DM | Unfollow | Activity |
|------|------|--------|------|-----|----------|----------|
| 2026-04-01 | 06-12 | 87 | 120 | 5 | 12 | Yes |
| 2026-03-31 | 06-12 | 92 | 115 | 3 | 8 | Yes |
| 2026-03-30 | 06-12 | 0 | 0 | 0 | 0 | No |

#### E. Source Change Log

Compact view of source additions and removals for this account:

```
2026-04-01  -fitness_daily (wFBR 3.2%, cleanup)
2026-03-29  +travel_world (added by operator)
2026-03-28  -old_source_1 (bulk delete, wFBR 1.8%)
```

### Additional buttons:

| Button | Location | Function |
|--------|----------|----------|
| **Pin account** | Header | Keep this drawer open even when clicking other rows (compare mode) |
| **Previous / Next** | Header arrows | Navigate to prev/next account in current filtered list |
| **Expand to full page** | Header | Open drawer content as a full-screen dialog for deep review |
| **Print / Export** | Footer | Export account profile as text/PDF for handoff |
| **Open on device** | Footer | If phone preview URL is configured, open in browser |

### Additional keyboard shortcuts:

| Shortcut | Action |
|----------|--------|
| `Space` | Toggle drawer for selected account |
| `Left/Right arrows` | Switch tabs in drawer |
| `Ctrl+Shift+C` | Copy full diagnostic summary |
| `Ctrl+R` | Toggle review flag |
| `Ctrl+T` | TB +1 |
| `Ctrl+L` | Limits +1 |
| `Ctrl+S` | Open sources tab for this account |
| `Ctrl+F` | Find sources (if API key set) |

### Additional indicators:

| Indicator | Location | Meaning |
|-----------|----------|---------|
| **Flame icon** | Next to username | Account has CRITICAL alerts |
| **Clock icon** | Next to slot | Currently in active time slot |
| **Trend arrow** | Next to Follow Today | Up/down vs yesterday |
| **Stale badge** | Next to Last FBR | FBR data older than 3 days |
| **New badge** | Next to Discovered | Account discovered in last 24h |
| **Source health dot** | Next to Active Sources | Green (>= 5 quality), amber (1-4 quality), red (0 quality) |

---

## 4. Conditional Logic

### TB Accounts (TB1-TB5)

| TB Level | Shown elements |
|----------|---------------|
| TB1-TB2 | Warmup card with specific limits (Follow=10, Added=10, Till=80/60) |
| TB3-TB4 | Warmup card (stricter limits) + "Consider device move" warning |
| TB5 | CRITICAL alert banner: "Must move to another device" + Move button |

### Limits Accounts (limits 1-5)

| Level | Shown elements |
|-------|---------------|
| 1-2 | Informational note |
| 3-4 | "Replace exhausted sources" recommendation card |
| 5 | HIGH alert: "Maximum limits reached. Source replacement urgent." |

### Review Flagged

- Summary tab shows red "REVIEW" badge in header
- Alerts tab auto-focuses on review section
- "Clear Review" button is prominent (green, top of actions)
- Review note is displayed prominently

### No Sources

- Sources tab shows "No active sources" banner
- Alerts tab shows MEDIUM/HIGH alert
- "Find Sources" and "Add Source" buttons highlighted
- System suggestion: "This account has 0 active sources. Add sources to resume operation."

### Low Follow/Like

- Performance cards show red/amber coloring
- Alerts tab shows relevant alert with recommendation
- Peer comparison emphasizes the gap

### Auto-generated alerts

Alerts are computed on drawer open (not persisted). Logic:

```python
def compute_alerts(account, session, fbr_snapshot, source_count, device_status):
    alerts = []

    # Zero activity in active slot
    if is_active_slot(account) and device_status == "running":
        if not session or not session.has_activity:
            alerts.append(Alert("CRITICAL", "Zero actions in active slot"))

    # Device offline
    if device_status not in ("running",):
        alerts.append(Alert("CRITICAL", f"Device {device_status}"))

    # TB level
    tb = extract_tb_level(account.bot_tags_raw)
    if tb and tb >= 4:
        alerts.append(Alert("CRITICAL", f"TB{tb} — needs device transfer"))
    elif tb and tb >= 2:
        alerts.append(Alert("HIGH", f"TB{tb} — warmup required"))

    # Source health
    if source_count == 0:
        alerts.append(Alert("HIGH", "No active sources"))
    elif fbr_snapshot and fbr_snapshot.quality_sources == 0:
        alerts.append(Alert("MEDIUM", "No quality sources"))

    # ... etc for all conditions listed in Tab 4

    return sorted(alerts, key=lambda a: SEV_RANK[a.severity])
```

---

## 5. Implementation Recommendation

### Approach: QSplitter-based drawer in Accounts tab

The drawer should NOT be a separate dialog. It should be a `QSplitter` child within the Accounts tab, allowing the operator to resize the split between table and detail.

#### Component structure:

```
AccountsPage (QWidget)
  └── QSplitter (horizontal)
       ├── Left: existing table + toolbar + filter bar
       └── Right: AccountDetailPanel (QWidget, initially hidden)
            ├── HeaderWidget (username, device, status, review badge)
            ├── QTabWidget
            │    ├── SummaryTab
            │    ├── SourcesTab (embedded, not dialog)
            │    ├── HistoryTab
            │    ├── AlertsTab
            │    └── ActionsTab
            └── FooterWidget (Copy, Open Folder, Phone Preview)
```

#### New files to create:

| File | Contents |
|------|----------|
| `oh/ui/account_detail_panel.py` | Main drawer container, tab management, data loading |
| `oh/ui/account_summary_widget.py` | Summary tab: identity, performance cards, config, FBR summary |
| `oh/ui/account_sources_widget.py` | Embedded sources table (reuse SourceDialog logic, not as dialog) |
| `oh/ui/account_history_widget.py` | Timeline widget with filtering |
| `oh/ui/account_alerts_widget.py` | Auto-generated alerts + review history + recommendation cards |
| `oh/ui/account_actions_widget.py` | Action buttons organized by risk level |
| `oh/services/account_detail_service.py` | Aggregation service: fetches all data for one account in one call |

#### Files to modify:

| File | Change |
|------|--------|
| `oh/ui/main_window.py` | Replace `_make_accounts_page` to use QSplitter; add `_on_row_single_clicked` handler; wire drawer open/close |
| `oh/repositories/session_repo.py` | Add `get_history_for_account(account_id, limit)` for multi-day history |
| `oh/repositories/operator_action_repo.py` | Already has `get_for_account()` — no change needed |
| `oh/repositories/fbr_snapshot_repo.py` | Already has `get_for_account()` — no change needed |
| `oh/repositories/delete_history_repo.py` | Add `get_for_account(account_id)` to filter delete items by account |

#### Avoiding UI overload:

1. **Lazy tab loading** — only fetch data when a tab is first selected. Summary tab loads immediately; Sources/History/Alerts load on tab switch.
2. **Cached data** — reuse `_session_map`, `_fbr_map`, `_source_count_map` from MainWindow. Only fetch additional data (history, per-source detail) when tabs are opened.
3. **Pagination** — History tab shows last 50 events with "Load more" button.
4. **Debounced account switching** — when navigating with arrow keys, delay data loading by 150ms to avoid rapid fire queries.
5. **Minimal new queries** — Summary tab needs zero new queries (all data is in MainWindow's existing maps). Sources tab reuses existing SourceInspector + FBRCalculator + SourceUsageReader. Only History tab requires new queries.

---

## 6. Technical Structure

### Data model for the view

```python
@dataclass
class AccountDetailData:
    """All data needed to render the Account Detail View."""
    # Core
    account: AccountRecord

    # Session (today)
    session: Optional[AccountSessionRecord]

    # Session history (last 14 days)
    session_history: list[AccountSessionRecord]

    # FBR
    fbr_snapshot: Optional[FBRSnapshotRecord]
    fbr_history: list[FBRSnapshotRecord]  # last 5 snapshots

    # Sources
    source_count: int  # active sources
    source_inspection: Optional[SourceInspectionResult]  # lazy
    fbr_analysis: Optional[FBRAnalysisResult]  # lazy
    source_usage: Optional[SourceUsageResult]  # lazy

    # Tags
    bot_tags: list[AccountTag]
    operator_tags: list[AccountTag]

    # Operator actions (audit log)
    actions: list[OperatorActionRecord]

    # Delete history affecting this account
    delete_events: list[DeleteItem]

    # Device
    device_status: Optional[str]
    device_accounts: list[AccountRecord]  # other accounts on same device

    # Alerts (computed, not persisted)
    alerts: list[AccountAlert]

    # Peer comparison
    device_avg_follow: float
    fleet_avg_follow: float
```

### New service: AccountDetailService

```python
class AccountDetailService:
    """
    Aggregation layer for the Account Detail View.
    Fetches all data needed in minimal queries.
    """

    def __init__(self, account_repo, session_repo, fbr_snapshot_repo,
                 source_assignment_repo, tag_repo, operator_action_repo,
                 delete_history_repo):
        ...

    def get_summary(self, account_id: int) -> AccountDetailData:
        """Fast path — only data needed for Summary tab."""
        ...

    def get_sources(self, account_id: int, bot_root: str) -> tuple:
        """Lazy load — inspection + FBR + usage for Sources tab."""
        ...

    def get_history(self, account_id: int, limit: int = 50) -> list:
        """Lazy load — unified timeline for History tab."""
        ...

    def compute_alerts(self, data: AccountDetailData) -> list:
        """Compute alerts from current data."""
        ...
```

### Services and repos needed

| Component | Status | Notes |
|-----------|--------|-------|
| `AccountRepository` | EXISTS | Has `get_by_id()` — sufficient |
| `SessionRepository` | EXISTS, needs extension | Add `get_recent_for_account(account_id, days=14)` |
| `FBRSnapshotRepository` | EXISTS | Has `get_for_account()` — sufficient |
| `SourceAssignmentRepository` | EXISTS | Has `get_active_source_counts()` — sufficient |
| `TagRepository` | EXISTS | Has `get_tags_for_account()` — sufficient |
| `OperatorActionRepository` | EXISTS | Has `get_for_account()` — sufficient |
| `DeleteHistoryRepository` | EXISTS, needs extension | Add `get_items_for_account(account_id)` |
| `SourceInspector` | EXISTS | Used for Sources tab (lazy) |
| `FBRCalculator` | EXISTS | Used for Sources tab (lazy) |
| `SourceUsageReader` | EXISTS | Used for Sources tab (lazy) |
| `AccountDetailService` | NEW | Aggregation service |

### Architecture adherence

- UI calls `AccountDetailService` (service layer) — never repos directly
- Service calls repos — never touches bot files
- Bot file access only through modules (SourceInspector, FBRCalculator, etc.)
- All new data flows follow existing `UI -> Service -> Repo/Module` pattern
- No new database tables needed (all data already exists)
- No new migrations needed

---

## 7. MVP Recommendation

### Phase 5a — MVP (build first, 3-5 days)

| Component | Scope |
|-----------|-------|
| Drawer infrastructure | QSplitter, open/close, account switching |
| Summary tab | Identity, performance cards, config, FBR snapshot summary |
| Alerts tab | Auto-generated alerts from existing data, review status |
| Quick actions (inline) | Set/Clear Review, TB+1, Limits+1, Open Folder, Open Sources, Copy Diagnostic |
| Keyboard shortcuts | Space to toggle, Escape to close, arrows to navigate |

**Why this first:** The Summary + Alerts + Actions tabs solve the core problem (fragmented review). They require zero new database queries -- everything comes from data MainWindow already has in memory.

### Phase 5b — Full (build second, 3-5 days)

| Component | Scope |
|-----------|-------|
| Sources tab (embedded) | Full source table with FBR + usage, inline add/remove/cleanup |
| History tab | Unified timeline merging operator actions, FBR analyses, source changes, sessions |
| Session history | 14-day session snapshot table |
| Peer comparison | Device avg and fleet avg for key metrics |
| Related accounts | Other accounts on same device |

**Why second:** These require new queries (session history, delete history per-account, timeline merging) and more complex UI (scrollable timeline, embedded table).

### Phase 5c — Polish (build third, 2-3 days)

| Component | Scope |
|-----------|-------|
| Performance trends | 7-day sparklines |
| Source change log | Add/remove timeline |
| Pin/compare mode | Keep drawer open while selecting different accounts |
| Expand to full page | Open detail as full-screen dialog |
| Contextual action cards | Pattern-specific recommendations (follow pending, try again, no DM sources) |
| Export/print | Copy full profile as text |

### Estimated total: 8-13 days of implementation

---

## Dependencies

| Dependency | Status |
|------------|--------|
| PySide6 QSplitter | Available in PySide6 6.6+ |
| AccountRecord model | Complete |
| Session data | Complete (session_snapshots table) |
| FBR data | Complete (fbr_snapshots table) |
| Source assignments | Complete |
| Operator actions | Complete (operator_actions table) |
| Tag system | Complete |
| Delete history | Complete |
| Recommendations engine | Complete (can reuse alert logic) |

No external dependencies needed. Everything builds on existing infrastructure.

---

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Drawer too narrow on 1366x768 screens | MEDIUM | MEDIUM | Set min-width, auto-hide non-critical table columns, test on 1366px |
| Slow drawer open for accounts with large history | LOW | LOW | Lazy tab loading, pagination, debounce |
| Arrow-key navigation causes rapid DB queries | MEDIUM | LOW | 150ms debounce, reuse MainWindow's cached maps |
| Conflict with existing double-click behavior | LOW | LOW | Single-click opens drawer, double-click opens folder (both coexist) |
| Scope creep from "one more field" requests | HIGH | MEDIUM | Strict MVP boundary, add fields in Phase 5b/5c |

---

## Success Criteria

1. Operator can assess "is this account OK?" in under 5 seconds from drawer open
2. Operator can complete a full account review without opening any other dialog
3. Arrow-key navigation between accounts takes less than 200ms to update drawer
4. No regression in Accounts table performance (< 500ms full refresh with 200 accounts)
5. All existing context menu actions available in the drawer
6. Diagnostic summary copy includes all critical fields in a structured format

---

## Handoff

To break this into implementation tasks, run `/planner` with the feature name "Account Detail View".
