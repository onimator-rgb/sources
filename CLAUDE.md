# OH — Operational Hub

## What this software does
OH is a desktop operations dashboard for managing Onimator bot campaigns at scale. It connects to the Onimator bot directory and gives operators a unified control center for all devices, accounts, source assignments, FBR analytics, session monitoring, and operational recommendations — without modifying the bot's runtime behaviour.

## Business context
OH supports commercial services offered through:
- `wizzysocial.com`
- `insta-max.pl`
- `wypromujemy.com`

This is production-oriented software. Changes should be evaluated in terms of reliability, account performance visibility, scalability, and operator usefulness.

## Tech stack
- **Language**: Python 3.9+
- **GUI**: PySide6 6.6+ (Qt 6, Fusion style)
- **Database**: SQLite 3 (WAL mode, foreign keys enforced, 7 migrations)
- **Packaging**: PyInstaller → single-file `dist/OH.exe`
- **Platform**: Windows 10/11
- **Dependencies**: PySide6 only — everything else is stdlib
- **Logging**: RotatingFileHandler → `%APPDATA%\OH\logs\oh.log` (2 MB × 5 files)

## Local development commands
- Install dependencies: `pip install -r requirements.txt`
- Run the main app: `python main.py`
- Run tests: `python -m unittest discover tests/`
- Build .exe: `python scripts/generate_placeholder_assets.py && python -m PyInstaller OH.spec`
- Database migrations: applied automatically on startup via `oh/db/migrations.py`

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

| Layer | Location | Responsibility |
|-------|----------|---------------|
| **models/** | `oh/models/` | Pure dataclasses — no logic, no I/O |
| **modules/** | `oh/modules/` | Stateless readers of bot files (read-only except source_deleter/restorer) |
| **repositories/** | `oh/repositories/` | CRUD on OH's internal database — never touches bot files |
| **services/** | `oh/services/` | Orchestrators: combine modules + repositories |
| **ui/** | `oh/ui/` | PySide6 widgets — calls services, never accesses bot files directly |

**Layer rules (STRICT)**:
- UI → Services → Modules + Repositories
- Never skip layers
- Modules are stateless
- Repositories only touch oh.db
- UI only calls services
- Bot file reads use `?mode=ro` (SQLite URI)
- Background operations use `WorkerThread` from `oh/ui/workers.py`

## Database
- Location: `%APPDATA%\OH\oh.db`
- 7 migrations in `oh/db/migrations.py` (auto-applied on startup)
- Tables: `oh_config`, `oh_devices`, `oh_accounts`, `sync_runs`, `sync_events`, `fbr_snapshots`, `fbr_source_results`, `source_assignments`, `source_delete_actions`, `source_delete_items`, `session_snapshots`, `account_tags`, `operator_actions`

## Existing features (complete and working)
1. **Discovery & Sync** — auto-discovers devices/accounts from bot folder
2. **FBR Analytics** — Follow-Back Rate per source per account, snapshots, anomalies
3. **Global Sources** — cross-account aggregation, wFBR, filtering
4. **Source Management** — delete/restore with backup, bulk delete, audit trail
5. **Session Monitoring** — daily follow/like/DM/unfollow, slot-aware
6. **Operator Actions** — review flags, TB levels (1-5), limits (1-5), tags, audit trail
7. **Recommendations** — 6 types, severity-based (CRITICAL/HIGH/MEDIUM/LOW)
8. **Cockpit** — daily operations overview, 5 sections
9. **Dark/Light theme**, keyboard shortcuts, .exe build

## Code standards
- Python 3.9 compatible (`Optional[X]` not `X | None`)
- Type hints on public methods
- f-strings for formatting
- SQL uses `?` placeholders, never f-strings
- Per-item errors don't abort batch operations
- File paths via `pathlib.Path`
- Logging via `logging.getLogger(__name__)`
- Constants at module top, private methods prefixed `_`

## Engineering expectations
- Prefer small, behavior-preserving changes over broad refactors
- Keep per-device logic isolated (one failing device must not impact the fleet)
- Bot file reads are always read-only (except sources.txt with backup)
- Backup before any destructive file operation
- Keep logs structured and traceable
- Avoid changes that increase per-device memory or DB load
- Preserve data quality for downstream reporting

---

# Agent System

OH uses a 5-agent development workflow. Each agent is a custom command in `.claude/commands/`.

## Agents

```
┌─────────────┐     ┌──────────┐     ┌─────────┐     ┌──────────┐     ┌────────┐     ┌──────────┐
│  Architect   │────>│  Planner  │────>│  Coder  │────>│ Reviewer │────>│ UI/UX  │────>│  Tester  │
│ /architect   │     │ /planner  │     │ /coder  │     │ /reviewer│     │ /uiux  │     │ /tester  │
└─────────────┘     └──────────┘     └─────────┘     └──────────┘     └────────┘     └──────────┘
```

| Agent | Command | Role | Input | Output |
|-------|---------|------|-------|--------|
| **Architect** | `/architect` | Product vision, roadmap, feature proposals | Codebase + business context | Feature proposals in `docs/ROADMAP.md` |
| **Planner** | `/planner` | Break features into implementation tasks | Feature proposal | Plan in `docs/plans/FEATURE_NAME.md` |
| **Coder** | `/coder` | Write production code | Plan from `docs/plans/` | Code changes |
| **Reviewer** | `/reviewer` | Code review — quality, architecture, security | Git diff | Review report (APPROVE/NEEDS CHANGES/REJECT) |
| **UI/UX** | `/uiux` | Design quality, consistency, operator UX | Git diff + UI files | Design review (APPROVE/NEEDS POLISH/REDESIGN) |
| **Tester** | `/tester` | Write tests, run validation | Git diff + plan | Test report (PASS/FAIL) |

## How to use agents

### Full pipeline (new feature)
```
/architect          → proposes feature, updates roadmap
/planner            → creates implementation plan in docs/plans/
/coder              → implements the plan
/reviewer           → reviews code quality, architecture, security
/uiux               → reviews UI/UX design quality (if feature has UI)
/tester             → writes tests, validates everything works
```

### Quick fix (bug or small change)
```
/coder              → implement the fix
/reviewer           → check the change
/tester             → verify it works
```

### UI polish pass
```
/uiux               → audit existing UI, generate improvement list
/coder              → implement fixes
/uiux               → verify fixes
```

### Strategic planning only
```
/architect          → analyze gaps, propose features, update roadmap
```

## Agent rules
1. **Each agent stays in its lane** — Architect doesn't code, Coder doesn't design, Reviewer doesn't fix
2. **Handoff is explicit** — each agent tells you which agent to run next
3. **Plans are persistent** — saved in `docs/plans/` so any session can pick up where you left off
4. **Roadmap is the source of truth** — `docs/ROADMAP.md` tracks all planned features and priorities
5. **Agents read before acting** — every agent reads relevant files before making decisions

## Key directories for agents
- `docs/ROADMAP.md` — product roadmap (Architect maintains)
- `docs/plans/` — implementation plans (Planner creates, Coder follows)
- `tests/` — test suite (Tester creates and maintains)
- `CHANGELOG.md` — shipped features history

---

## Strategic goals
1. **Account performance visibility** — operators see what matters at a glance
2. **Operational efficiency** — reduce manual checks, automate recommendations
3. **Reporting agent** — analyze bot files into actionable reports
4. **Source management intelligence** — smarter source rotation and quality tracking
5. **Device fleet health** — monitoring, anomaly detection, early warnings
6. **Scalability** — maintain performance at 100+ devices, 1000+ accounts
