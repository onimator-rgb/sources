# OH — Roadmap

> Maintained by the Architect agent (`/architect`). Last updated: 2026-04-01.
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

## Planned

### Phase 5 — Account Detail View (CRITICAL)

> Full proposal: [`docs/plans/account_detail_view.md`](plans/account_detail_view.md)

**Problem:** Operators must jump between 5+ views to review a single account. At 100+ accounts this makes daily reviews impractical.

**Solution:** Right-side drawer panel that opens on account click, consolidating all account data into one tabbed interface with inline actions.

#### Phase 5a — MVP (3-5 days)
- [ ] QSplitter drawer infrastructure (open/close, account switching, keyboard nav)
- [ ] Summary tab (identity, performance cards, config, FBR snapshot summary)
- [ ] Alerts tab (auto-generated alerts, review status, contextual recommendation cards)
- [ ] Inline quick actions (Set/Clear Review, TB+1, Limits+1, Open Folder, Copy Diagnostic)
- [ ] Keyboard shortcuts (Space toggle, Escape close, arrow nav)

#### Phase 5b — Full (3-5 days)
- [ ] Embedded Sources tab (full source table with FBR + usage, inline add/remove/cleanup)
- [ ] History tab (unified timeline: operator actions, FBR analyses, source changes, sessions)
- [ ] Session history (14-day snapshot table)
- [ ] Peer comparison (device avg, fleet avg for key metrics)
- [ ] Related accounts panel (other accounts on same device)
- [ ] AccountDetailService (aggregation service, lazy loading)
- [ ] New repo methods: `session_repo.get_recent_for_account()`, `delete_history_repo.get_items_for_account()`

#### Phase 5c — Polish (2-3 days)
- [ ] Performance trends (7-day sparklines for follow/like counts)
- [ ] Source change log (add/remove timeline)
- [ ] Pin/compare mode (keep drawer open while selecting different accounts)
- [ ] Expand to full-page dialog
- [ ] Contextual action cards (follow pending, try again later, no DM sources)
- [ ] Export/print account profile

**Dependencies:** None — builds entirely on existing infrastructure (no new tables or migrations).

---

## Ideas backlog
_Collect feature ideas here. Architect will prioritize and promote to Planned._

- Reporting agent (analyze bot-generated files into actionable reports)
- Device fleet health dashboard (device-level metrics, uptime, account distribution)
- Bulk account operations (multi-select actions in Accounts table)
- Scheduled auto-scan (periodic Scan & Sync without manual trigger)
- Account performance scoring (composite health score per account)
