# OH — Roadmap

> Maintained by the Architect agent (`/architect`). Last updated: 2026-04-06.
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

### Phase 5 — Account Detail View (2026-03-31 — 2026-04-02)
- [x] QSplitter drawer (open/close, keyboard nav, account switching)
- [x] Summary tab (identity, performance cards, config, FBR, peer comparison)
- [x] Alerts tab (auto-generated alerts, review status, contextual cards)
- [x] Inline quick actions (Review, TB+1, Limits+1, Open Folder, Copy Diagnostic)
- [x] Embedded Sources tab + History tab (unified timeline)

### Phase 6 — Bulk Source Discovery (2026-04-02)
- [x] Multi-account source discovery wizard (3-step)
- [x] Bulk discovery history with revert

### Phase 7 — Smart Source Discovery (2026-04-02)
- [x] NicheClassifier (20 niches), composite ranking
- [x] Source Profile Repository + Source Profiles tab

### Phase 8 — Operational Features v2 (2026-04-02)
- [x] Account Health Score (0-100), Source Health Dashboard
- [x] Source Blacklist, Account Notes, CSV Export
- [x] Auto-Scan Scheduler

### Phase 9 — Fleet & Intelligence (2026-04-02)
- [x] Device Fleet Dashboard, Source Performance Trends
- [x] Cross-Account Source Optimizer, Campaign Templates

### Phase 10 — Error Reporting, Block Detection, Groups (2026-04-03)
- [x] Error reporting (crash capture, optional auto-send)
- [x] Block detection (session pattern analysis)
- [x] Account groups (campaign/client grouping)
- [x] Bulk operations (multi-select TB+1, review, groups)
- [x] Trend analysis (sparkline charts)
- [x] Auto-update system (START.bat pre-launch + in-app check)

---

## Planned

### Phase 11 — Self-Healing & Auto-Fix (NEXT)

Goal: OH automatically fixes problems that don't require operator decisions.

- [ ] **Auto-Source Cleanup** (CRITICAL)
  - After Scan & Sync: detect sources with wFBR=0% + >100 follows
  - Auto-remove from accounts above min source threshold (with backup)
  - Log to `auto_fix_actions` table, report in Cockpit
  - Settings toggle: "Enable auto source cleanup" + threshold config

- [ ] **Auto-TB Escalation** (HIGH)
  - After Scan & Sync: detect accounts with 0 actions for 2+ days in active slot
  - Auto-increment TB level, auto-flag review if TB reaches 4+
  - Respect existing TB level (don't escalate past TB5)
  - Cockpit banner: "Auto-escalated TB: N accounts"

- [ ] **Auto-Source Discovery Scheduler** (HIGH)
  - Timer-based (24h interval): find accounts below source threshold
  - Auto-run Bulk Discovery with configured top-N
  - Requires HikerAPI key; skip gracefully if not configured
  - Report: "Auto-discovered N sources for M accounts"

- [ ] **Dead Device Alerting** (MEDIUM)
  - After Scan & Sync: flag devices with 0% activity in active slots for >4h
  - Banner at top of Cockpit: "N devices offline: [list]"
  - Optional webhook notification (Discord/Slack)

- [ ] **Source Duplicate Cleaner** (MEDIUM)
  - Detect duplicate sources across accounts (same source, different casing)
  - Auto-deduplicate sources.txt (with backup)
  - Report cleaned duplicates in Cockpit

Dependencies: Existing services (BlockDetectionService, BulkDiscoveryService, SourceDeleteService)

### Phase 12 — Intelligence & Learning

Goal: OH learns from data and makes smarter recommendations.

- [ ] **Source Quality Prediction** (HIGH)
  - Track source FBR progression over time (50/100/200 follows milestones)
  - Predict FBR for new sources based on niche, followers, ER
  - Show "Predicted FBR: ~12%" in Find Sources results
  - New table: `source_performance_history`

- [ ] **Optimal Limits Advisor** (MEDIUM)
  - Analyze historical data: what limits work best after TB escalation?
  - Per-niche learning: different niches have different optimal limits
  - Show in Alerts tab: "Suggested: Follow 20/day (based on 15 similar accounts)"

- [ ] **Account Clustering & Insights** (MEDIUM)
  - Group accounts by niche, performance tier, FBR band
  - Dashboard: "Fashion accounts have 35% higher FBR than fitness"
  - Device comparison: "Redmi 47 performs 20% above fleet average"

- [ ] **Source Lifecycle Tracking** (LOW)
  - Track source age: when added, how long active, when retired
  - "Source exhaustion curve": FBR over time per source
  - Predict when a source will become weak

### Phase 13 — Reporting & Notifications

Goal: OH generates reports and notifies operators proactively.

- [ ] **Daily Report Generator** (CRITICAL)
  - Auto-generate at configurable hour (default 23:00)
  - HTML/PDF saved to `%APPDATA%\OH\reports\`
  - Content: fleet summary, top issues, source changes, blocks, FBR trends
  - Optional auto-send to Discord webhook
  - Settings: toggle + hour + endpoint

- [ ] **Discord/Slack Webhook Notifications** (HIGH)
  - Real-time alerts for: CRITICAL issues, blocks, offline devices, auto-fix actions
  - Configurable severity threshold
  - Settings: webhook URL + severity filter + test button

- [ ] **Weekly Performance Report** (MEDIUM)
  - Aggregated weekly: FBR trends, accounts added/removed, source churn
  - Comparison: this week vs last week
  - Top/bottom performing accounts and sources

- [ ] **Client-Facing Export** (LOW)
  - Static HTML export with key metrics (no sensitive data)
  - Account count, avg FBR, health trend, source quality
  - Suitable for emailing to clients

---

## Ideas Backlog

_Collect feature ideas here. Architect will prioritize and promote to Planned._

- Web-based dashboard (local HTTP server for read-only client access)
- Multi-operator support (track which operator did what across multiple PCs)
- Source marketplace (share successful sources between clients with similar niches)
- A/B testing for sources (split-test new vs old sources on same account)
- Anomaly detection ML model (predict blocks before they happen)
- Account lifecycle management (onboard → warmup → active → retire flow)
- Integration with Onimator config (write follow/like limits back to bot — requires bot mod)
- Mobile companion app (read-only status view)
