# Plan: Smart Source Discovery v2

> Created: 2026-04-02 | Complexity: XL | Status: PLANNED

## Problem

Current source discovery finds profiles that are often **off-topic**:
- Keyword generation is shallow (bio words + category + city)
- No understanding of the client's **niche** — doesn't know that "trener personalny" relates to "fitness coach", "dietetyk sportowy"
- No **thematic validation** — candidates aren't checked for niche match before being recommended
- `avg_er` is computed but **never used in ranking**
- `ai_category` is assigned but **never compared** to target
- Target profile data is **not persisted** — lost after search
- No cross-account source intelligence (avg FBR per source is only in snapshots, not centralized)

## Solution Overview

Three-layer upgrade to the existing pipeline:

```
LAYER 1: Profile Intelligence     — classify target, expand keywords
LAYER 2: Multi-Strategy Search    — different query strategies per niche
LAYER 3: Thematic Validation      — score niche match, composite ranking, quality gate
```

Plus new DB tables for source metadata and target profile persistence.

---

## Database Changes

### Migration 010 — Smart Source Discovery

```sql
-- 1. Global source metadata (one row per source username, cross-account)
CREATE TABLE IF NOT EXISTS source_profiles (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name      TEXT    NOT NULL UNIQUE,
    niche_category   TEXT,
    niche_confidence REAL,
    language         TEXT,
    location         TEXT,
    follower_count   INTEGER,
    bio              TEXT,
    avg_er           REAL,
    is_active_source INTEGER NOT NULL DEFAULT 1,
    first_seen_at    TEXT    NOT NULL,
    updated_at       TEXT    NOT NULL,
    profile_json     TEXT
);

CREATE INDEX IF NOT EXISTS idx_source_profiles_niche
    ON source_profiles(niche_category);

CREATE INDEX IF NOT EXISTS idx_source_profiles_name
    ON source_profiles(source_name);

-- 2. Aggregated FBR per source (updated after each FBR analysis)
--    Denormalized from fbr_source_results for fast lookups
CREATE TABLE IF NOT EXISTS source_fbr_stats (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    source_name           TEXT    NOT NULL UNIQUE,
    total_accounts_used   INTEGER NOT NULL DEFAULT 0,
    total_follows         INTEGER NOT NULL DEFAULT 0,
    total_followbacks     INTEGER NOT NULL DEFAULT 0,
    avg_fbr_pct           REAL    NOT NULL DEFAULT 0.0,
    weighted_fbr_pct      REAL    NOT NULL DEFAULT 0.0,
    quality_account_count INTEGER NOT NULL DEFAULT 0,
    last_analyzed_at      TEXT,
    updated_at            TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_source_fbr_stats_name
    ON source_fbr_stats(source_name);

-- 3. Target profile data on search record (persist what we fetch)
ALTER TABLE source_searches ADD COLUMN target_category TEXT;
ALTER TABLE source_searches ADD COLUMN target_niche TEXT;
ALTER TABLE source_searches ADD COLUMN target_bio TEXT;
ALTER TABLE source_searches ADD COLUMN target_followers INTEGER;
ALTER TABLE source_searches ADD COLUMN target_location TEXT;
ALTER TABLE source_searches ADD COLUMN target_language TEXT;
ALTER TABLE source_searches ADD COLUMN target_profile_json TEXT;

-- 4. Niche match data on candidates
ALTER TABLE source_search_candidates ADD COLUMN niche_category_local TEXT;
ALTER TABLE source_search_candidates ADD COLUMN niche_match_score REAL;
ALTER TABLE source_search_candidates ADD COLUMN composite_score REAL;
ALTER TABLE source_search_candidates ADD COLUMN search_strategy TEXT;
ALTER TABLE source_search_candidates ADD COLUMN language TEXT;
ALTER TABLE source_search_candidates ADD COLUMN location TEXT;
```

### Why two niche fields on candidates?
- `ai_category` — from Gemini (external, may be empty)
- `niche_category_local` — from our NicheClassifier (always available, deterministic)

---

## Niche Taxonomy

Hardcoded in `oh/modules/niche_classifier.py`. ~20 primary niches, each with:

```python
@dataclass
class NicheDefinition:
    name: str                    # "fitness"
    display_name: str            # "Fitness & Training"
    keywords_pl: List[str]       # ["trener", "siłownia", "crossfit", ...]
    keywords_en: List[str]       # ["trainer", "gym", "workout", ...]
    related_niches: List[str]    # ["nutrition", "wellness", "sport"]
    instagram_categories: List[str]  # ["Personal Trainer", "Fitness Model", ...]
    search_strategies: List[str] # query templates for this niche
```

### Proposed niches:

| Niche | PL keywords | EN keywords | Related |
|-------|-------------|-------------|---------|
| fitness | trener, siłownia, crossfit, yoga, pilates, bieganie | trainer, gym, workout, yoga, pilates, running | nutrition, wellness, sport |
| beauty | kosmetyczka, makijaż, brwi, rzęsy, paznokcie, fryzjer | makeup, beauty, lashes, nails, hair, skincare | fashion, wellness, lifestyle |
| fashion | moda, stylizacja, odzież, butik, streetwear | fashion, style, outfit, clothing, streetwear | beauty, lifestyle, luxury |
| food | restauracja, kuchnia, chef, gastro, kawiarnia, cukiernia | restaurant, chef, food, cafe, bakery, cooking | nutrition, lifestyle, travel |
| nutrition | dietetyk, żywienie, dieta, suplementy, zdrowie | dietitian, nutrition, diet, supplements, health | fitness, food, wellness |
| wellness | spa, masaż, relaks, mindfulness, medytacja | spa, massage, wellness, mindfulness, meditation | beauty, fitness, nutrition |
| photography | fotograf, sesja, zdjęcia, studio, portret | photographer, photoshoot, portrait, studio | wedding, art, fashion |
| wedding | ślub, wesele, dekoracje, florystyka, suknia | wedding, bride, ceremony, decoration, florist | photography, event, beauty |
| real_estate | nieruchomości, mieszkanie, dom, agent, deweloper | real estate, apartment, house, agent, developer | finance, interior, luxury |
| automotive | samochód, auto, mechanik, detailing, tuning | car, auto, mechanic, detailing, tuning | luxury, lifestyle, sport |
| education | kurs, szkolenie, nauczyciel, korepetycje, szkoła | course, training, teacher, tutoring, school | business, coaching, tech |
| coaching | coach, mentoring, rozwój, motywacja, mindset | coach, mentoring, development, motivation, mindset | business, education, wellness |
| business | firma, marketing, social media, reklama, branding | business, marketing, advertising, branding, agency | coaching, education, tech |
| travel | podróże, hotel, turystyka, wycieczka | travel, hotel, tourism, adventure, explore | food, photography, lifestyle |
| interior | wnętrza, projektant, meble, aranżacja, remont | interior, design, furniture, renovation, decor | real_estate, architecture, art |
| medical | lekarz, klinika, stomatolog, fizjoterapia, zdrowie | doctor, clinic, dentist, physiotherapy, health | wellness, beauty, fitness |
| pet | zwierzęta, pies, kot, weterynarz, groomer | pet, dog, cat, veterinary, groomer | lifestyle |
| art | sztuka, artysta, galeria, malarstwo, grafika | art, artist, gallery, painting, graphic | photography, fashion, interior |
| sport | sport, piłka, tenis, pływanie, trening | sport, football, tennis, swimming, training | fitness, coaching |
| lifestyle | lifestyle, blog, vlog, daily, życie | lifestyle, blog, vlog, daily, life | fashion, beauty, travel |

---

## NicheClassifier Module

**File:** `oh/modules/niche_classifier.py` (new)

### Classification algorithm:

```python
def classify_profile(bio: str, category: str, full_name: str, username: str) -> NicheResult:
    """
    Classify a profile into a niche.
    Returns NicheResult(primary_niche, sub_niche, confidence, matched_keywords).

    Algorithm:
    1. Normalize text (lowercase, remove emoji/URLs)
    2. Score each niche by keyword matches:
       - category match: +10 per keyword  (strongest signal)
       - bio match: +3 per keyword
       - full_name match: +5 per keyword
       - username match: +2 per keyword
    3. Pick highest scoring niche
    4. Confidence = best_score / (best_score + second_best_score)
       - > 0.7 = high confidence
       - 0.4-0.7 = medium
       - < 0.4 = low (ambiguous profile)
    """
```

### Language detection (simple, no external deps):

```python
def detect_language(text: str) -> str:
    """Detect PL vs EN from text. Returns 'pl', 'en', or 'unknown'."""
    pl_indicators = {"jest", "się", "nie", "dla", "ale", "czy", "lub", "przy",
                     "już", "też", "ą", "ę", "ó", "ś", "ż", "ź", "ć", "ł", "ń"}
    # Count Polish character/word frequency
    # If > 20% Polish indicators → "pl"
    # Else → "en" (default for international accounts)
```

---

## Upgraded Pipeline (source_finder_service.py)

### New Step 1: Profile Intelligence (replaces old step 1)

```
1a. Fetch target profile via HikerAPI                    (1 API call)
1b. Classify niche via NicheClassifier                   (0 calls — local)
1c. Detect language                                       (0 calls — local)
1d. Persist target data on search record                 (1 DB write)
1e. Generate search strategies:
    - If Gemini available: ask for 4 query strategies    (1 Gemini call)
    - Else: build from niche taxonomy                    (0 calls — local)
1f. Build query set (4-6 queries from strategies)
```

### New Step 2: Multi-Strategy Search (replaces old step 2)

```
2a. Instagram suggested profiles                          (1 API call)
2b. Niche exact search: "{niche_keyword} {city}"         (1 API call)
2c. Niche broad search: "{niche_keyword}"                (1 API call)
2d. Related niche search: "{related_keyword} {city}"     (1 API call)
2e. AI/taxonomy keyword search (1-2 extra queries)       (1-2 API calls)
2f. Deduplicate, tag with search_strategy
2g. Save all candidates to DB                            (1 DB write)
```

Total: 5-6 API calls (same as before, but smarter queries)

### Step 3: Pre-filter (unchanged)
Remove private, verified, no username.

### New Step 4: Niche Classification + Enrichment

```
4a. Classify each candidate via NicheClassifier          (0 calls — local)
4b. Compute niche_match_score vs target                  (0 calls — local)
4c. QUALITY GATE: reject candidates with match < 20      (0 calls)
4d. Enrich top 25 remaining via HikerAPI                 (up to 25 calls)
4e. Re-classify after enrichment (bio may have changed)  (0 calls — local)
4f. Apply quality filter (followers >= threshold)
```

### Step 5: Posts + ER (unchanged in logic, but candidates are better)

### New Step 6: AI Scoring (enhanced prompt)

```python
# Enhanced Gemini prompt includes target niche context
prompt = f"""
You are evaluating Instagram profiles for source targeting.

TARGET PROFILE:
- Username: @{target.username}
- Niche: {target_niche.display_name}
- Bio: {target.bio[:200]}
- Category: {target.category}
- Location: {target.city_name}
- Followers: {target.follower_count:,}

Our system classified this profile as "{target_niche.name}" with {confidence:.0%} confidence.

CANDIDATES (already pre-filtered for niche relevance):
{candidates_text}

For each candidate, evaluate:
1. Niche relevance (0-10): How well does this profile's content match the target's niche?
2. Audience overlap (0-10): Would followers of this account also be interested in the target?
3. Quality (0-10): Is this a real, active, quality account?

Return JSON: {{"username": {{"relevance": 8, "audience": 7, "quality": 9, "reason": "..."}}}}
"""
```

### New Step 7: Composite Ranking

```python
def compute_composite_score(candidate, target_niche, has_ai_scores):
    score = 0.0

    # Niche match (35%) — from NicheClassifier
    score += (candidate.niche_match_score / 100.0) * 35

    # AI relevance (25%) — from Gemini, or 0 if unavailable
    if has_ai_scores and candidate.ai_score is not None:
        score += (candidate.ai_score / 10.0) * 25
    else:
        # Fallback: use niche_match as proxy
        score += (candidate.niche_match_score / 100.0) * 15

    # Engagement rate (20%) — normalized
    if candidate.avg_er is not None and candidate.avg_er > 0:
        # Cap ER at 10% for normalization
        er_norm = min(candidate.avg_er, 10.0) / 10.0
        score += er_norm * 20

    # Source strategy bonus (10%)
    strategy_bonuses = {
        "suggested": 10,
        "niche_exact": 8,
        "niche_broad": 6,
        "related_niche": 5,
        "keyword": 4,
    }
    score += strategy_bonuses.get(candidate.search_strategy, 3)

    # Audience match (10%) — follower range + location + language
    audience = 0.0
    if target_niche.location and candidate.location:
        if target_niche.location.lower() in candidate.location.lower():
            audience += 5.0
    if candidate.language == target_niche.language:
        audience += 5.0
    score += audience

    return round(score, 2)  # 0-100
```

### Quality Gate (reject off-topic)

```python
# After composite scoring, before final top 10:
NICHE_MATCH_MIN = 20    # reject clearly off-topic
COMPOSITE_MIN = 30      # reject weak overall matches

candidates = [c for c in candidates if c.niche_match_score >= NICHE_MATCH_MIN]
candidates = [c for c in candidates if c.composite_score >= COMPOSITE_MIN]
```

---

## Source Profile Persistence

### When to update source_profiles:

1. **During source discovery** — when a candidate is enriched (step 4), save/update source_profiles with niche_category, bio, follower_count, language, location
2. **When source is added** — mark as active source, update profile_json with full data
3. **After FBR analysis** — update source_fbr_stats from aggregated fbr_source_results

### source_fbr_stats update (after FBR batch):

```python
def update_source_fbr_stats(self):
    """Aggregate FBR data across all accounts into source_fbr_stats."""
    self._conn.execute("""
        INSERT OR REPLACE INTO source_fbr_stats
            (source_name, total_accounts_used, total_follows, total_followbacks,
             avg_fbr_pct, weighted_fbr_pct, quality_account_count,
             last_analyzed_at, updated_at)
        SELECT
            r.source_name,
            COUNT(DISTINCT s.account_id),
            SUM(r.follow_count),
            SUM(r.followback_count),
            AVG(r.fbr_percent),
            CASE WHEN SUM(r.follow_count) > 0
                 THEN CAST(SUM(r.followback_count) AS REAL) / SUM(r.follow_count) * 100
                 ELSE 0.0 END,
            SUM(r.is_quality),
            MAX(s.analyzed_at),
            ?
        FROM fbr_source_results r
        JOIN fbr_snapshots s ON s.id = r.snapshot_id
        GROUP BY r.source_name
    """, (_utcnow(),))
    self._conn.commit()
```

---

## Implementation Tasks

### Task 1 — Migration 010: Smart Source Discovery Schema
**Agent:** Coder
**Files:** `oh/db/migrations.py`
- Add `source_profiles` table
- Add `source_fbr_stats` table
- ALTER `source_searches` with target profile columns
- ALTER `source_search_candidates` with niche/composite/strategy columns

### Task 2 — Niche Classifier Module
**Agent:** Coder
**Files:** `oh/modules/niche_classifier.py` (new)
- `NicheDefinition` dataclass
- `NicheResult` dataclass
- `NICHE_TAXONOMY` dict with ~20 niches
- `classify_profile(bio, category, full_name, username) -> NicheResult`
- `compute_niche_match(target_niche, candidate_bio, candidate_category, candidate_full_name) -> float`
- `detect_language(text) -> str`
- `extract_niche_keywords(text) -> Set[str]`

### Task 3 — Source Profile Repository
**Agent:** Coder
**Files:** `oh/repositories/source_profile_repo.py` (new)
- `upsert_profile(source_name, niche, language, location, follower_count, bio, avg_er, profile_json)`
- `get_profile(source_name) -> Optional[SourceProfile]`
- `get_profiles_by_niche(niche) -> List[SourceProfile]`
- `update_fbr_stats()` — aggregate query from fbr_source_results

### Task 4 — Source Profile Model
**Agent:** Coder
**Files:** `oh/models/source_profile.py` (new)
- `SourceProfile` dataclass
- `SourceFBRStats` dataclass

### Task 5 — Upgrade Source Finder Service Pipeline
**Agent:** Coder
**Files:** `oh/services/source_finder_service.py`
- Step 1: Add niche classification + persist target data
- Step 2: Multi-strategy search queries
- Step 4: Niche classification of candidates + quality gate
- Step 6: Enhanced AI prompt with niche context
- Step 7: Composite scoring + quality gate ranking
- After add_to_sources: update source_profiles

### Task 6 — Upgrade Source Finder Module
**Agent:** Coder
**Files:** `oh/modules/source_finder.py`
- Add `build_niche_queries(niche_result, city) -> List[SearchStrategy]`
- Update `GeminiScorer.generate_search_query()` to accept niche context
- Update `GeminiScorer.categorize_and_score()` with enhanced prompt

### Task 7 — Source Search Repository Updates
**Agent:** Coder
**Files:** `oh/repositories/source_search_repo.py`
- Add methods to save/read new columns on searches and candidates
- `update_search_target_data(search_id, category, niche, bio, followers, location, language, profile_json)`
- `update_candidate_niche(candidate_id, niche_category_local, niche_match_score, composite_score, search_strategy, language, location)`

### Task 8 — FBR Stats Integration
**Agent:** Coder
**Files:** `oh/services/fbr_service.py`, `oh/repositories/source_profile_repo.py`
- After FBR batch analysis completes, trigger `update_source_fbr_stats()`
- Wire into existing `FBRService.analyze_batch()` completion

### Task 9 — Main.py Bootstrap
**Agent:** Coder
**Files:** `main.py`
- Bootstrap `SourceProfileRepository`
- Pass to services that need it

### Task 10 — Tests
**Agent:** Tester
- Test NicheClassifier (classification, language detection, match scoring)
- Test SourceProfileRepository (CRUD)
- Test composite scoring logic

---

## Execution Order

```
Task 1  (Migration 010)
   ↓
Tasks 2+4 (NicheClassifier + Models) — parallel
   ↓
Tasks 3+7 (Repos) — parallel
   ↓
Tasks 5+6 (Service + Module upgrade)
   ↓
Task 8  (FBR stats integration)
   ↓
Task 9  (Bootstrap)
   ↓
Task 10 (Tests)
```

## API Call Budget (per search)

| Step | Before | After | Change |
|------|--------|-------|--------|
| Profile fetch | 1 | 1 | same |
| Gemini query | 0-1 | 0-1 | same |
| Suggested profiles | 1 | 1 | same |
| Search queries | 5 | 4-5 | same (but smarter) |
| Enrich candidates | 25 | 25 | same (but better filtered) |
| Fetch posts | 10 | 10 | same |
| Gemini scoring | 0-1 | 0-1 | same (enhanced prompt) |
| **Total** | **42-43** | **42-44** | **~same cost, much better results** |

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| NicheClassifier misclassifies profile | Confidence score + Gemini fallback. Low confidence → broader search. |
| Niche taxonomy too rigid | Related niches expand search. Easy to add new niches. |
| Quality gate too aggressive | Configurable thresholds. Start conservative (20/30), tune. |
| Language detection wrong | Simple heuristic, defaults to "en". Only used for scoring, not filtering. |
| Migration alters existing tables | ALTERs only ADD columns (SQLite safe). No data loss. |
