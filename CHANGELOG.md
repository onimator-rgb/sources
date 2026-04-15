# Changelog

All notable changes to OH are documented here.

## 1.8.0 — 2026-04-15

### Notifications Browser
- **Notifications tab** — new main tab reading bot's `notificationdatabase.db`
  - Color-coded notification types: Block (orange), Suspended (warning), Error (pink), Login (blue), Added (green), Deleted (red)
  - Filter by device, notification type, account, date range
  - Right-click context menu: filter by account/device/type
  - CSV export, sortable columns

### Like Sources & LBR Analytics
- **Like Sources sub-tab** — Sources tab now has "Follow Sources" and "Like Sources" sub-tabs
  - Like-Back Rate (LBR) analytics mirroring FBR: per-source like count, followback count, LBR%
  - Global like source aggregation: active/historical accounts, avg LBR, weighted LBR, quality flag
  - Detail pane with per-account breakdown for selected like source
- **Analyze LBR button** on Accounts toolbar — batch LBR analysis across all active accounts
- **Account detail drawer** — Sources tab now shows both Follow Sources and Like Sources sections
- DB migration 017: `lbr_snapshots`, `lbr_source_results`, `like_source_assignments` tables

### Enhanced Settings Copier
- **215 settings** across 9 collapsible categories (up from 17 flat settings):
  Follow, Unfollow, Like, Story, Reels, DM, Share, Post, Human Behavior
- **Text file copying**: name_must_include.txt, name_must_not_include.txt, like name filters
- **Collapsible category sections** with select all/none per category
- **Category-level audit trail** in operator actions
- Non-blocking settings loading via WorkerThread

## 2026-03-30

### Stage 5 — Daily Operations Cockpit
- **Cockpit dialog** — one-click operations overview at shift start
  - 5 sections: urgent items, review queue, top recommendations, source actions, today's activity
  - Quick actions: set/clear review, navigate to accounts and sources
  - Drilldown buttons to Session Report, Recommendations, Delete History, Action History
  - Refresh with live status feedback
- Post Scan & Sync status now shows CRITICAL count and Cockpit hint

### Stage 4 — Safe Source Operations
- **Account source cleanup** — remove non-quality sources from a single account
  - Preview with checkboxes per source (FBR%, follows, quality flag)
  - Warning when remaining sources drop below threshold
  - Single audit action with N items per cleanup operation
- **Source actions from Recommendations** — delete weak source or clean account directly from recommendations dialog
- **Source actions from SourceDialog** — "Remove Non-Quality Sources" button
- **Revert awareness** — every delete operation shows revert availability
- Delete History accessible from Recommendations dialog

### Stage 3 — Operational Recommendations
- **Recommendation engine** — 6 types: Weak Source, Source Exhaustion, Low Like, Limits Max, TB Max, Zero Actions
- **RecommendationsDialog** — severity-sorted table with quick filters (All / Critical+High / Accounts / Sources)
- Apply Selected: flag accounts for review with contextual notes
- Deep links: double-click or "Open Target" navigates to account or source
- Copy to clipboard in plain text format
- Noise control: max 25 weak sources + bulk summary recommendation

### Stage 2 — Operator Actions
- **OperatorActionService** — set/clear review, add/remove operator tags, increment TB (1-5), increment limits (1-5)
- **Audit trail** — every operator action logged to `operator_actions` table with old/new values and machine name
- **Action History dialog** — chronological view of recent actions with type coloring and copy to clipboard
- **Quick actions in main table** — per-account "..." menu: Set Review, Clear Review, TB+1, Limits+1
- **Quick actions in Session Report** — Flag for Review, Clear Review, TB+1, Limits+1 per section
- **Operator vs bot tags** — displayed as `[4] SLAVE | OP:TB3 OP:limits 2` with amber highlight
- TB5 max / Limits 5 max — warning dialogs with operational guidance

### Stage 1 — Session Monitoring & Tags
- **Session snapshots** — daily follow, like, DM, unfollow counts per account
  - Slot-aware: 00-06, 06-12, 12-18, 18-24
  - Automatic collection during Scan & Sync
- **SessionReader** — reads `data.db`, `likes.db`, `sent_message.db`, `settings.db` per account
- **Tag system** — bot tags parsed from `settings.db` (TB, limits, role, status, custom) + separate operator tags
- **Session Report dialog** — 8 sections with severity-based operator checklist:
  - Zero actions, devices not running, review flagged, low follow, low like, TB accounts, limits accounts, operator actions
  - Warmup recommendations per TB level (TB1-TB5 with specific Follow/Like limits)
  - Copy report to clipboard
- **Main table enhancements:**
  - 6 new columns: Tags, Follow Today, Like Today, F. Limit, L. Limit, Review
  - Device status color dot (running=green, stop=gray, offline=red)
  - 3 new filters: Tags, Activity, Review only
  - Search extended to tags
- Database migrations 006 (`session_snapshots`, `account_tags`, review flag columns on `oh_accounts`) and 007 (`operator_actions`)
- Discovery reads `settings.db` per account for tags and limits
- Sync persists `bot_tags_raw`, `follow_limit_perday`, `like_limit_perday`

### Earlier (pre-Stage)
- **Source revert/restore** — revert completed delete actions from the History dialog
- `SourceRestorer` module — inverse of `SourceDeleter`
- **Per-account source deletion** — delete a source from a single account
- Delete confirmation dialog for per-account operations
- Delete history enhancements: Status column, Revert button, scope display
- Migration 005 — revert tracking columns

### Changed
- Delete service captures full affected account details for all operations
- History dialog refreshes on close when revert performed
- `_refresh_table()` loads all operational maps (session, FBR, source counts, tags, device status)
- Scan & Sync automatically collects session data and tags post-sync

## 2026-03-27

### Added
- **Source usage metrics** — Used count and Used % columns in per-account Sources dialog and global Sources detail pane
- Used count reads `sources/{name}.db` (COUNT of processed users per source)
- Used % derived from `.stm/{name}-total-followed-percent.txt` + follow count
- Tooltips show derived total follower count on hover

### Fixed
- **Empty columns in Sources dialog** — `setSortingEnabled(True)` was called before row insertion, causing Qt to re-sort mid-fill and place column values in wrong rows. Moved to after the loop.

## 2026-03-26

### Added
- **FBR analytics** — per-account and batch Follow-Back Rate computation from `data.db`
- Persisted FBR snapshots with timestamps
- Quality thresholds (configurable min follows + min FBR %)
- Anomaly detection for inconsistent followback data
- **Global Sources tab** — aggregated cross-account source view with filters
- Per-source detail pane with per-account FBR breakdown
- Average FBR and volume-weighted FBR metrics
- **Source deletion** — single and bulk delete from `sources.txt` across accounts
- Confirmation dialogs with affected account list
- Full deletion history with viewer
- **Per-account Sources dialog** — merged view of sources.txt + data.db with FBR columns
- **Settings tab** — bot root path, FBR thresholds, delete threshold, theme
- **EXE packaging** — PyInstaller spec for single-file `dist/OH.exe`
- Desktop shortcut creation script
- Dark theme with Wizzysocial branding
- Rotating log file at `%APPDATA%\OH\logs\oh.log`

## 2026-03-25

### Added
- **Initial release** — account discovery, device registry, sync, and base UI
- Scan & Sync workflow reading bot directory structure
- Account table with status, config, and file presence columns
- OH internal SQLite database with migrations
