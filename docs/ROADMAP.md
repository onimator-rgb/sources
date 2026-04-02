# OH — Roadmap

> Maintained by the Architect agent (`/architect`). Last updated: 2026-04-02.
> Full feature proposals live in `docs/plans/`.

## Shipped

### Phase 1 — Foundation (2026-03-25)
- [x] Account discovery & device registry
- [x] Scan & Sync workflow
- [x] Account table with status, config, file presence

### Phase 2 — Analytics & Sources (2026-03-26)
- [x] FBR analytics (per-account, batch, snapshots, anomalies)
- [x] Global Sources tab (cross-account aggregation, wFBR)
- [x] Source deletion (single, bulk, audit trail)
- [x] Per-account Sources dialog
- [x] Settings tab (bot root, FBR thresholds, theme)
- [x] Source usage metrics (Used count, Used %)

### Phase 3 — Operations (2026-03-27 — 2026-03-30)
- [x] Source revert/restore with backup
- [x] Per-account source deletion
- [x] Session monitoring (daily follow/like/DM/unfollow, slot-aware)
- [x] Tag system (bot tags + operator tags)
- [x] Operator actions (review, TB, limits) with audit trail
- [x] Recommendations engine (6 types, severity-based)
- [x] Daily Operations Cockpit
- [x] Session Report (8 sections)

### Phase 4 — Polish (2026-03-30 — 2026-03-31)
- [x] Dark/light theme with semantic palette
- [x] UI density improvements
- [x] Keyboard shortcuts
- [x] Build versioning
- [x] Installation guide

---

### Phase 5 — Account Detail View (2026-03-31 — 2026-04-02)
- [x] QSplitter drawer infrastructure (open/close, account switching, keyboard nav)
- [x] Summary tab (identity, performance cards, config, FBR snapshot, peer comparison)
- [x] Alerts tab (auto-generated alerts, review status, contextual action cards)
- [x] Inline quick actions (Set/Clear Review, TB+1, Limits+1, Open Folder, Copy Diagnostic)
- [x] Keyboard shortcuts (Space toggle, Escape close, arrow nav)
- [x] Embedded Sources tab (source table with FBR metrics, quality flags)
- [x] History tab (unified timeline: operator actions, FBR analyses, sessions)
- [x] Session history (`session_repo.get_recent_for_account()`)
- [x] Peer comparison (device avg, fleet avg health scores)
- [x] Related accounts panel (other accounts on same device with health)
- [x] AccountDetailService (aggregation, alerts, diagnostics)
- [x] Repo methods: `session_repo.get_recent_for_account()`, `delete_history_repo.get_items_for_account()`
- [x] Source change log section in Summary tab
- [x] Contextual action cards (follow pending, low sources, review flag)
- [x] Export account profile to text file

---

### Phase 6 — Bulk Source Discovery (2026-04-02)
- [x] Migration 009: `bulk_discovery_runs` + `bulk_discovery_items` tables
- [x] Models, Repository, Settings, Service (bulk pipeline, revert, qualifying accounts)
- [x] Bulk Discovery Dialog (3-step wizard: preview → progress → results)
- [x] Bulk Discovery History Dialog (past runs, drill-down, revert)
- [x] Main Window + Sources Tab integration (toolbar buttons)
- [x] Error handling (cancellable rate limit wait, worker cleanup, try/except)
- [x] Test suite (54 tests: models, repo, service)

### Phase 7 — Smart Source Discovery (2026-04-02)
- [x] Migration 010: `source_profiles`, `source_fbr_stats`, search/candidate columns
- [x] NicheClassifier module (20 niches, PL+EN keywords, language detection)
- [x] Source Profile Repository + FBR stats aggregation
- [x] Multi-strategy search pipeline (niche exact/broad/related + suggested)
- [x] Composite ranking (niche match 35% + AI 25% + ER 20% + strategy 10% + language 10%)
- [x] Quality gate (reject off-topic candidates)
- [x] Scan & Index Sources button in Settings (bulk index all active sources via HikerAPI)
- [x] Test suite (51 tests: niche classifier, source profile repo)

### Phase 8 — Operational Features v2 (2026-04-02)
- [x] Account Health Score (0-100 composite metric, color-coded column)
- [x] Source Health Dashboard (new Source Profiles tab with niche/FBR/filters)
- [x] Source Blacklist (manage in Settings, checked during discovery)
- [x] Account Notes (operator_notes field, visible in drawer)
- [x] CSV Export (export visible Accounts table rows)
- [x] Source Performance Recommendations (REC_SOURCE_FBR_DECLINING in Cockpit)
- [x] Auto-Scan Scheduler (configurable interval 1-24h, QTimer-based)

### Phase 9 — Fleet & Intelligence (2026-04-02)
- [x] Device Fleet Dashboard (new Fleet tab: per-device metrics, detail pane, health aggregation)
- [x] Source Performance Trends (FBR trend arrows + tooltips in Sources tab)
- [x] Cross-Account Source Optimizer (niche FBR variance detection, mismatch suggestions)
- [x] Campaign Templates (migration 012, CRUD, editor dialog, niche-aware presets)

**Dependencies:** Phase 2 (Source Finder — already shipped).

---

## Ideas backlog
_Collect feature ideas here. Architect will prioritize and promote to Planned._

- Reporting agent (analyze bot-generated files into actionable reports)
- Device fleet health dashboard (device-level metrics, uptime, account distribution)
- Bulk account operations (multi-select actions in Accounts table)
- Scheduled auto-scan (periodic Scan & Sync without manual trigger)
- Account performance scoring (composite health score per account)
