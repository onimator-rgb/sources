# Plan: Source Finder

> Created: 2026-04-01 | Complexity: L (Large) | Status: IN PROGRESS

## Feature Summary

Add a "Find Sources" button to OH that discovers 10 similar Instagram profiles for a client account using HikerAPI + Gemini AI scoring. Operator can add selected profiles to sources.txt with one click.

## Architecture Decisions

- **Models** (`oh/models/source_finder.py`) — dataclasses for search state, candidates, results
- **Module** (`oh/modules/source_finder.py`) — HikerAPI client + Gemini scorer (stateless)
- **Repository** (`oh/repositories/source_search_repo.py`) — CRUD for 3 new tables
- **Service** (`oh/services/source_finder_service.py`) — multi-step pipeline with resume
- **UI** (`oh/ui/source_finder_dialog.py`) — dialog with progress + results table
- **Migration** M008 — 3 new tables
- **Dependencies** — `requests`, `google-generativeai`

## Implementation Order

```
Tasks 1-2-3 (DB + models + repo)
    ↓
Tasks 4-5-9 (settings + module + deps) — parallel
    ↓
Task 6 (service)
    ↓
Tasks 7-8 (UI dialog + main window integration)
    ↓
Task 10 (error handling + polish)
```

---

## Task 1 — Database Migration M008: Source Search Tables

**Files:** `oh/db/migrations.py`

**Changes:**
Add `_MIGRATION_008_SQL` with three tables:

```sql
-- source_searches: search history
CREATE TABLE IF NOT EXISTS source_searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES oh_accounts(id),
    username TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL DEFAULT 'running',
    step_reached INTEGER NOT NULL DEFAULT 0,
    query_used TEXT,
    error_message TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_searches_account ON source_searches(account_id, started_at DESC);

-- source_search_candidates: all candidates found
CREATE TABLE IF NOT EXISTS source_search_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES source_searches(id),
    username TEXT NOT NULL,
    full_name TEXT,
    follower_count INTEGER NOT NULL DEFAULT 0,
    bio TEXT,
    source_type TEXT NOT NULL DEFAULT 'suggested',
    is_private INTEGER NOT NULL DEFAULT 0,
    is_verified INTEGER NOT NULL DEFAULT 0,
    is_enriched INTEGER NOT NULL DEFAULT 0,
    avg_er REAL,
    ai_score REAL,
    ai_category TEXT,
    profile_pic_url TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_candidates_search ON source_search_candidates(search_id);

-- source_search_results: final top 10
CREATE TABLE IF NOT EXISTS source_search_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    search_id INTEGER NOT NULL REFERENCES source_searches(id),
    candidate_id INTEGER NOT NULL REFERENCES source_search_candidates(id),
    rank INTEGER NOT NULL,
    added_to_sources INTEGER NOT NULL DEFAULT 0,
    added_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_source_results_search ON source_search_results(search_id, rank);
```

Register as `(8, "source_finder", _MIGRATION_008_SQL)` in `_MIGRATIONS`.

**Dependencies:** None
**Test:** OH starts. `SELECT * FROM schema_migrations WHERE version=8` returns a row.

---

## Task 2 — Models: Source Finder Dataclasses

**Files:** `oh/models/source_finder.py` (new)

**Dataclasses:**
- `SourceSearchRecord` — id, account_id, username, started_at, completed_at, status, step_reached, query_used, error_message. Constants: RUNNING/COMPLETED/FAILED.
- `SourceCandidate` — id, search_id, username, full_name, follower_count, bio, source_type, is_private, is_verified, is_enriched, avg_er, ai_score, ai_category, profile_pic_url.
- `SourceSearchResult` — id, search_id, candidate_id, rank, added_to_sources, added_at, candidate (Optional[SourceCandidate]).

**Dependencies:** None
**Test:** Dataclasses instantiate correctly.

---

## Task 3 — Repository: Source Search CRUD

**Files:** `oh/repositories/source_search_repo.py` (new)

**Methods:**
- `create_search(account_id, username) -> SourceSearchRecord`
- `update_search_step(search_id, step_reached)`
- `complete_search(search_id, status, error_message=None)`
- `get_latest_search(account_id) -> Optional[SourceSearchRecord]`
- `save_candidates(search_id, candidates: list[SourceCandidate])`
- `update_candidate_enrichment(candidate_id, follower_count, bio, avg_er, is_enriched=True)`
- `update_candidate_ai(candidate_id, ai_score, ai_category)`
- `get_candidates(search_id) -> list[SourceCandidate]`
- `save_results(search_id, results: list[SourceSearchResult])`
- `mark_added_to_sources(result_id)`
- `get_results(search_id) -> list[SourceSearchResult]` (JOIN on candidates)

**Dependencies:** Task 1, Task 2
**Test:** Full CRUD round-trip on in-memory DB.

---

## Task 4 — Settings: API Key Configuration

**Files:** `oh/repositories/settings_repo.py`, `oh/ui/settings_tab.py`

**Changes:**
- Add `hiker_api_key` and `gemini_api_key` to `_CONFIG_DEFAULTS`
- Add "Source Finder" group to settings UI with 2 password-masked fields
- Save/load via settings_repo

**Dependencies:** None
**Test:** Fields visible in Settings tab, values persist across restarts.

---

## Task 5 — Module: HikerAPI Client + Gemini Scorer

**Files:** `oh/modules/source_finder.py` (new)

**Classes:**
- `HikerClient(api_key)` — adapted from ig_audit's hiker_client.py
  - `get_profile(username) -> dict`
  - `get_suggested_profiles(user_id) -> list[dict]`
  - `search_accounts(query) -> list[dict]`
  - `get_posts(username, max_count=5) -> list[dict]`
  - `_get(path, params) -> object` — 3-retry on 429/503
- `GeminiScorer(api_key)` — adapted from ig_audit's ai_service.py
  - `is_available -> bool`
  - `generate_search_query(profile_data) -> str`
  - `categorize_and_score(target, candidates) -> dict`
- Helper functions: `build_manual_query()`, `build_query_variations()`, `compute_avg_er()`, `pre_filter()`, `quality_filter()`
- `HikerAPIError(Exception)`

**Dependencies:** Task 2, Task 9 (requests, google-generativeai)
**Test:** Instantiation works. Filter functions correct. Manual query building returns non-empty string.

---

## Task 6 — Service: Source Finder Pipeline

**Files:** `oh/services/source_finder_service.py` (new)

**Class:** `SourceFinderService(search_repo, account_repo, settings_repo)`

**Pipeline** `run_search(account_id, progress_callback=None) -> list[SourceSearchResult]`:
1. Profile fetch → save query
2. Collect candidates (suggested + 5x search) → save to DB
3. Pre-filter (remove private, verified)
4. Enrich top 25 (full profile data)
5. Fetch posts + compute ER for top 10
6. AI scoring (optional, graceful skip)
7. Rank + save top 10 results

**Resume logic:** Check for running search with step_reached > 0, skip completed steps.

**Secondary:** `add_to_sources(result_id, account_id, bot_root) -> bool` — backup + append to sources.txt.

**Dependencies:** Task 3, Task 5
**Test:** Full pipeline with valid API keys. Resume from step 4 after interruption. Works without Gemini.

---

## Task 7 — UI: Source Finder Dialog

**Files:** `oh/ui/source_finder_dialog.py` (new)

**Layout:**
- Progress bar + step label (visible during search)
- Results table: Select (checkbox), Rank, Username, Followers, ER%, Niche, AI Score, Source
- Summary: "Found N profiles for @username. Query: ..."
- Footer: "Add Selected to sources.txt" (green) + "Close"

**Worker:** Custom `SourceFinderWorker(QThread)` with `progress(int, str)` signal.

**Dependencies:** Task 6, Task 2
**Test:** Dialog opens, progress updates, table shows 10 rows, Add button works.

---

## Task 8 — Main Window Integration

**Files:** `oh/ui/main_window.py`, `main.py`

**Changes:**
- Bootstrap `SourceSearchRepository` + `SourceFinderService` in `main.py`
- Pass `source_finder_service` to `MainWindow`
- Add "Find Sources" to account actions menu
- Validate bot_root and hiker_api_key before opening dialog

**Dependencies:** Task 6, Task 7
**Test:** "Find Sources" in menu. Warning if no API key. Dialog opens and pipeline runs.

---

## Task 9 — Dependencies

**Files:** `requirements.txt`

**Add:**
```
requests>=2.31.0
google-generativeai>=0.8.0
```

**Dependencies:** None
**Test:** `pip install -r requirements.txt` succeeds.

---

## Task 10 — Error Handling & Polish

**Files:** Tasks 5, 6, 7 files

**Hardening:**
1. Duplicate source prevention (case-insensitive check)
2. Empty results — friendly message
3. 60s timeout per step
4. Cancel button with cancellation flag
5. Rate limit user-friendly message
6. Create sources.txt if missing
7. Stale search cleanup (>24h running → failed)

**Dependencies:** Tasks 5-8
**Test:** All edge cases pass.

---

## Risk Assessment

| Risk | Impact | Mitigation |
|------|--------|------------|
| HikerAPI rate limits (30-40 calls/search) | Search fails mid-pipeline | 3x retry + checkpoint/resume |
| Gemini API cost | Money per search | Optional — works without it |
| sources.txt write during bot runtime | File conflict | Backup-first pattern (proven) |
| Network drops mid-pipeline | Partial results | Checkpoint + clear error messages |
| Stale partial data from previous run | Confused new run | Fresh start if >1h old |
