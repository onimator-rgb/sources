"""
SourceFinderService — orchestrates the multi-step source discovery pipeline.

Pipeline (Smart Discovery v2):
  1. Profile fetch → classify niche → generate multi-strategy queries
  2. Multi-strategy search (niche exact/broad/related + suggested)
  3. Pre-filter (remove private, verified)
  4. Enrich top 25 + niche classification + quality gate
  5. Fetch posts + compute ER for top 10
  6. AI scoring (optional, enhanced niche-aware prompt)
  7. Composite ranking (niche match + AI + ER + strategy bonus) + quality gate

Resume: if a running search exists (started < 1h ago), resumes from
step_reached + 1. Otherwise creates a new search.

Secondary: add_to_sources() appends a result username to sources.txt
with backup-first safety (same pattern as SourceDeleter).
"""
import json
import logging
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from oh.models.source_finder import (
    SourceCandidate,
    SourceSearchRecord,
    SourceSearchResult,
    SEARCH_COMPLETED,
    SEARCH_FAILED,
    SEARCH_RUNNING,
)
from oh.modules.niche_classifier import (
    classify_profile,
    compute_niche_match,
    detect_language,
    NicheResult,
    NICHE_TAXONOMY,
)
from oh.modules.source_finder import (
    HikerClient,
    GeminiScorer,
    HikerAPIError,
    build_manual_query,
    build_query_variations,
    build_niche_queries,
    compute_avg_er,
    pre_filter,
    quality_filter,
)
from oh.repositories.account_repo import AccountRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.source_search_repo import SourceSearchRepository

logger = logging.getLogger(__name__)

# Resume window — searches older than this are considered stale
_RESUME_MAX_AGE = timedelta(hours=1)

# Pipeline limits
_ENRICH_LIMIT = 25
_POST_FETCH_LIMIT = 10
_FINAL_TOP_N = 10
_MIN_FOLLOWERS_QUALITY = 1000

# Quality gate thresholds (reject off-topic candidates)
_NICHE_MATCH_MIN = 20       # minimum niche match score to keep candidate
_COMPOSITE_MIN = 30         # minimum composite score for final results


class SourceFinderService:
    """
    Coordinates source discovery: HikerAPI calls, optional Gemini scoring,
    DB persistence, and sources.txt file writes.
    """

    # Return sentinels for add_to_sources
    ADD_OK = "added"
    ADD_ALREADY = "already_in_sources"
    ADD_FAILED = "failed"

    def __init__(
        self,
        search_repo: SourceSearchRepository,
        account_repo: AccountRepository,
        settings_repo: SettingsRepository,
        source_profile_repo=None,
    ) -> None:
        self._search_repo = search_repo
        self._account_repo = account_repo
        self._settings = settings_repo
        self._profile_repo = source_profile_repo

        # Recover stale searches from previous crash / interrupted runs
        self._search_repo.recover_stale_searches(max_age_hours=24)

    # ------------------------------------------------------------------
    # Public accessors
    # ------------------------------------------------------------------

    def get_latest_search_query(self, account_id: int) -> Optional[str]:
        """Return the query_used from the most recent search for an account."""
        search = self._search_repo.get_latest_search(account_id)
        return search.query_used if search else None

    # ------------------------------------------------------------------
    # Source indexing: scan all active sources into source_profiles
    # ------------------------------------------------------------------

    def scan_and_index_sources(
        self,
        bot_root: str,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> Tuple[int, int, int, List[str]]:
        """
        Scan all active sources across all accounts and index missing ones
        into source_profiles via HikerAPI + NicheClassifier.

        Args:
            bot_root: path to bot directory (unused here but kept for API consistency)
            progress_callback: optional (current, total, message) callback
            cancel_check: optional callable returning True if cancelled

        Returns:
            (indexed_count, skipped_count, failed_count, errors)
            - indexed: new profiles added to source_profiles
            - skipped: already existed in source_profiles
            - failed: HikerAPI or other errors
        """
        if self._profile_repo is None:
            return (0, 0, 0, ["Source profile repository not configured"])

        # 1. Get all unique active source names
        try:
            rows = self._search_repo._conn.execute(
                "SELECT DISTINCT source_name FROM source_assignments WHERE is_active = 1"
            ).fetchall()
            source_names: List[str] = [r[0] if isinstance(r, tuple) else r["source_name"] for r in rows]
        except Exception as exc:
            logger.error("Failed to query active source names: %s", exc)
            return (0, 0, 0, [f"Failed to query active source names: {exc}"])

        total = len(source_names)
        if total == 0:
            logger.info("scan_and_index_sources: no active sources found")
            return (0, 0, 0, [])

        indexed = 0
        skipped = 0
        failed = 0
        errors: List[str] = []

        hiker: Optional[HikerClient] = None

        for i, source_name in enumerate(source_names):
            # Cancel check
            if cancel_check is not None and cancel_check():
                logger.info("scan_and_index_sources cancelled at %d/%d", i, total)
                return (indexed, skipped, failed, errors)

            # Progress callback
            if progress_callback is not None:
                progress_callback(i, total, f"Indexing @{source_name}...")

            # 2. Check if already in source_profiles
            try:
                existing = self._profile_repo.get_profile(source_name)
                if existing is not None:
                    skipped += 1
                    continue
            except Exception as exc:
                logger.warning(
                    "Error checking profile for @%s: %s", source_name, exc,
                )
                # Continue to try fetching anyway

            # 3. Fetch profile via HikerAPI
            if hiker is None:
                try:
                    hiker = self._ensure_hiker()
                except HikerAPIError as exc:
                    msg = f"HikerAPI not available: {exc}"
                    logger.error(msg)
                    errors.append(msg)
                    return (indexed, skipped, failed, errors)

            try:
                profile_data = hiker.get_profile(source_name)
            except HikerAPIError as exc:
                logger.warning(
                    "HikerAPI error for @%s: %s", source_name, exc,
                )
                failed += 1
                errors.append(f"@{source_name}: {exc}")
                time.sleep(0.5)
                continue
            except Exception as exc:
                logger.warning(
                    "Unexpected error fetching @%s: %s", source_name, exc,
                )
                failed += 1
                errors.append(f"@{source_name}: {exc}")
                time.sleep(0.5)
                continue

            # 4. Classify with NicheClassifier
            try:
                bio = profile_data.get("biography", "") or ""
                category = profile_data.get("category", "") or ""
                full_name = profile_data.get("full_name", "") or ""
                niche_result = classify_profile(bio, category, full_name, source_name)
            except Exception as exc:
                logger.warning(
                    "Niche classification failed for @%s: %s", source_name, exc,
                )
                failed += 1
                errors.append(f"@{source_name}: classification error: {exc}")
                time.sleep(0.5)
                continue

            # 5. Save to source_profiles
            try:
                follower_count = int(profile_data.get("follower_count", 0) or 0)
                location = profile_data.get("city_name", "") or None
                profile_json_data = {
                    "username": profile_data.get("username", source_name),
                    "full_name": full_name,
                    "category": category,
                    "city_name": profile_data.get("city_name", ""),
                    "follower_count": follower_count,
                    "following_count": int(profile_data.get("following_count", 0) or 0),
                    "media_count": int(profile_data.get("media_count", 0) or 0),
                    "is_private": profile_data.get("is_private", False),
                    "is_verified": profile_data.get("is_verified", False),
                    "niche": niche_result.primary_niche,
                    "niche_confidence": niche_result.confidence,
                }

                self._profile_repo.upsert_profile(
                    source_name=source_name,
                    niche_category=niche_result.primary_niche,
                    niche_confidence=niche_result.confidence,
                    language=niche_result.language,
                    location=location,
                    follower_count=follower_count,
                    bio=bio[:500] if bio else None,
                    avg_er=None,
                    profile_json=json.dumps(profile_json_data),
                )
                indexed += 1
                logger.debug(
                    "Indexed @%s: niche=%s (%.0f%%), followers=%d",
                    source_name, niche_result.primary_niche,
                    niche_result.confidence * 100, follower_count,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to save profile for @%s: %s", source_name, exc,
                )
                failed += 1
                errors.append(f"@{source_name}: save error: {exc}")

            # 6. Rate limiting
            time.sleep(0.5)

        # Final progress callback
        if progress_callback is not None:
            progress_callback(total, total, "Indexing complete")

        logger.info(
            "scan_and_index_sources complete: indexed=%d, skipped=%d, "
            "failed=%d, total=%d",
            indexed, skipped, failed, total,
        )
        return (indexed, skipped, failed, errors)

    # ------------------------------------------------------------------
    # Primary: run_search
    # ------------------------------------------------------------------

    def run_search(
        self,
        account_id: int,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        cancel_check: Optional[Callable[[], bool]] = None,
    ) -> List[SourceSearchResult]:
        """
        Execute the 7-step source discovery pipeline for *account_id*.

        Args:
            account_id: OH account id to find sources for.
            progress_callback: optional (percent, message) callback for UI.
            cancel_check: optional callable returning True if cancelled.

        Returns list of SourceSearchResult (up to 10) on success.
        Raises on fatal errors (after marking the search as failed).
        """

        def _progress(pct: int, msg: str) -> None:
            if progress_callback is not None:
                progress_callback(pct, msg)

        def _check_cancelled(search_id: int) -> bool:
            if cancel_check is not None and cancel_check():
                logger.info("Search %d cancelled by user", search_id)
                self._search_repo.complete_search(
                    search_id, SEARCH_FAILED, "Cancelled by user",
                )
                return True
            return False

        # ── Recover stale searches ───────────────────────────────────
        self._search_repo.recover_stale_searches(max_age_hours=24)

        # ── Validate API key before any work ─────────────────────────
        hiker_key = self._settings.get("hiker_api_key") or ""
        if not hiker_key or not hiker_key.strip():
            raise HikerAPIError(
                "HikerAPI key not configured. Go to Settings to add your key."
            )

        # ── Resume or create ─────────────────────────────────────────
        search_id = None
        search, start_step, candidates = self._resolve_search(account_id)
        search_id = search.id

        # Shared state across steps
        hiker: Optional[HikerClient] = None
        profile_data: Optional[dict] = None
        query: Optional[str] = search.query_used
        target_niche: Optional[NicheResult] = None
        search_queries: List[dict] = []  # [{"query": str, "strategy": str}]

        try:
            # ── Step 1 — Profile Intelligence ────────────────────────
            if start_step <= 1:
                if _check_cancelled(search_id):
                    return []
                _progress(5, "Fetching target profile...")

                account = self._account_repo.get_by_id(account_id)
                if account is None:
                    raise ValueError(f"Account {account_id} not found")

                hiker = HikerClient(hiker_key)

                profile_data = hiker.get_profile(account.username)

                # 1a. Classify target niche (local, no API call)
                bio = profile_data.get("biography", "") or ""
                category = profile_data.get("category", "") or ""
                full_name = profile_data.get("full_name", "") or ""
                city = profile_data.get("city_name", "") or ""
                target_niche = classify_profile(
                    bio, category, full_name, account.username,
                )
                _progress(7, f"Niche: {target_niche.display_name} "
                             f"({target_niche.confidence:.0%})")

                # 1b. Build query — try Gemini first, fall back to manual
                gemini_key = self._settings.get("gemini_api_key") or ""
                scorer = GeminiScorer(gemini_key)
                if scorer.is_available:
                    query = scorer.generate_search_query(profile_data)
                if not query:
                    query = build_manual_query(profile_data)

                # 1c. Build multi-strategy search queries
                niche_def = NICHE_TAXONOMY.get(target_niche.primary_niche)
                if niche_def is not None:
                    # Gather related niche keywords
                    related_kw: List[str] = []
                    for rn in niche_def.related_niches:
                        rd = NICHE_TAXONOMY.get(rn)
                        if rd is not None:
                            lang = target_niche.language
                            kw_list = rd.keywords_pl if lang == "pl" else rd.keywords_en
                            related_kw.extend(kw_list[:2])

                    search_queries = build_niche_queries(
                        primary_query=query,
                        niche_name=niche_def.name,
                        niche_keywords_pl=niche_def.keywords_pl,
                        niche_keywords_en=niche_def.keywords_en,
                        related_niche_keywords=related_kw,
                        city=city,
                    )
                else:
                    # Fallback to old variation strategy
                    search_queries = [
                        {"query": q, "strategy": "keyword"}
                        for q in build_query_variations(query)
                    ]

                # 1d. Persist query and target data
                self._search_repo.update_search_query(search_id, query)
                try:
                    self._search_repo.update_search_target_data(
                        search_id,
                        target_category=category,
                        target_niche=target_niche.primary_niche,
                        target_bio=bio[:500],
                        target_followers=int(profile_data.get("follower_count", 0) or 0),
                        target_location=city,
                        target_language=target_niche.language,
                        target_profile_json=json.dumps({
                            "username": account.username,
                            "full_name": full_name,
                            "category": category,
                            "city_name": city,
                            "follower_count": int(profile_data.get("follower_count", 0) or 0),
                            "niche": target_niche.primary_niche,
                            "niche_confidence": target_niche.confidence,
                        }),
                    )
                except Exception as exc:
                    logger.warning("Failed to save target data: %s", exc)

                self._search_repo.update_search_step(search_id, 1)
                strategies_str = ", ".join(q["strategy"] for q in search_queries)
                _progress(10, f"Niche: {target_niche.display_name}. "
                              f"Query: {query}. Strategies: {strategies_str}")
                logger.info(
                    "Step 1 complete: @%s classified as %s (%.0f%%), "
                    "query=%r, %d search strategies",
                    account.username, target_niche.primary_niche,
                    target_niche.confidence * 100, query, len(search_queries),
                )

            # ── Step 2 — Multi-Strategy Search ──────────────────────
            if start_step <= 2:
                if _check_cancelled(search_id):
                    return []
                _progress(15, "Collecting candidate profiles...")

                # Ensure hiker is initialised (resume case)
                if hiker is None:
                    hiker = self._ensure_hiker()
                if profile_data is None:
                    account = self._account_repo.get_by_id(account_id)
                    profile_data = hiker.get_profile(account.username)

                user_id = str(profile_data.get("pk", ""))

                # A. Suggested profiles
                raw_candidates = hiker.get_suggested_profiles(user_id)

                # B. Multi-strategy search
                if not search_queries:
                    # Fallback if resuming: use old variation strategy
                    if not query:
                        query = build_manual_query(profile_data)
                    search_queries = [
                        {"query": q, "strategy": "keyword"}
                        for q in build_query_variations(query)
                    ]

                search_results_raw: List[dict] = []
                strategy_map: Dict[str, str] = {}  # username.lower() -> strategy
                for sq in search_queries:
                    results = hiker.search_accounts(sq["query"])
                    for r in results:
                        uname = (r.get("username") or "").lower()
                        if uname and uname not in strategy_map:
                            strategy_map[uname] = sq["strategy"]
                    search_results_raw.extend(results)

                # Deduplicate by username (case-insensitive), mark source_type
                seen_lower: set = set()
                deduped: List[dict] = []

                # Suggested first (highest trust)
                for c in raw_candidates:
                    uname = (c.get("username") or "").lower()
                    if uname and uname not in seen_lower:
                        seen_lower.add(uname)
                        c["_source_type"] = "suggested"
                        c["_search_strategy"] = "suggested"
                        deduped.append(c)

                # Search results second (tagged with strategy)
                for c in search_results_raw:
                    uname = (c.get("username") or "").lower()
                    if uname and uname not in seen_lower:
                        seen_lower.add(uname)
                        c["_source_type"] = "search"
                        c["_search_strategy"] = strategy_map.get(uname, "keyword")
                        deduped.append(c)

                # Remove the target itself
                target_lower = search.username.lower()
                deduped = [c for c in deduped if (c.get("username") or "").lower() != target_lower]

                # Convert to SourceCandidate models and save
                candidates = [
                    SourceCandidate(
                        search_id=search_id,
                        username=c.get("username", ""),
                        full_name=c.get("full_name"),
                        follower_count=int(c.get("follower_count", 0) or 0),
                        bio=c.get("biography") or c.get("bio"),
                        source_type=c.get("_source_type", "search"),
                        is_private=bool(c.get("is_private", False)),
                        is_verified=bool(c.get("is_verified", False)),
                        profile_pic_url=c.get("profile_pic_url"),
                    )
                    for c in deduped
                ]
                # Track strategies for later DB update
                _strategy_by_username = {
                    c.get("username", "").lower(): c.get("_search_strategy", "keyword")
                    for c in deduped
                }

                self._search_repo.save_candidates(search_id, candidates)
                # Reload with IDs
                candidates = self._search_repo.get_candidates(search_id)

                self._search_repo.update_search_step(search_id, 2)
                _progress(25, f"Found {len(candidates)} candidates")
                logger.info(
                    "Step 2 complete: %d candidates saved (search_id=%d)",
                    len(candidates), search_id,
                )

            # ── Step 3 — Pre-filter ──────────────────────────────────
            if start_step <= 3:
                if _check_cancelled(search_id):
                    return []
                _progress(30, "Pre-filtering candidates...")

                if not candidates:
                    candidates = self._search_repo.get_candidates(search_id)

                # Convert to dicts for the filter helpers
                cand_dicts = [self._candidate_to_dict(c) for c in candidates]
                filtered_dicts = pre_filter(cand_dicts)

                # Map back to SourceCandidate objects by username
                filtered_usernames = {d["username"].lower() for d in filtered_dicts}
                candidates = [
                    c for c in candidates
                    if c.username.lower() in filtered_usernames
                ]

                self._search_repo.update_search_step(search_id, 3)
                _progress(35, f"{len(candidates)} candidates after pre-filter")
                logger.info(
                    "Step 3 complete: %d candidates after pre-filter", len(candidates),
                )

            # ── Step 4 — Enrich top 25 ───────────────────────────────
            if start_step <= 4:
                if _check_cancelled(search_id):
                    return []
                _progress(40, "Enriching top candidates...")

                if hiker is None:
                    hiker = self._ensure_hiker()
                if not candidates:
                    candidates = self._search_repo.get_candidates(search_id)

                to_enrich = [c for c in candidates if not c.is_enriched][:_ENRICH_LIMIT]

                for i, cand in enumerate(to_enrich):
                    try:
                        full = hiker.get_profile(cand.username)
                        if full:
                            new_followers = int(full.get("follower_count", 0) or 0)
                            new_bio = full.get("biography") or cand.bio
                            self._search_repo.update_candidate_enrichment(
                                cand.id,
                                follower_count=new_followers,
                                bio=new_bio,
                                avg_er=None,
                                is_enriched=True,
                            )
                            cand.follower_count = new_followers
                            cand.bio = new_bio
                            cand.is_enriched = True
                    except HikerAPIError as exc:
                        logger.warning(
                            "Enrich failed for @%s: %s", cand.username, exc,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Enrich failed for @%s: %s", cand.username, exc,
                        )

                # Reload candidates to get updated data
                candidates = self._search_repo.get_candidates(search_id)

                # Apply quality filter (min 1000 followers)
                cand_dicts = [self._candidate_to_dict(c) for c in candidates]
                quality_dicts = quality_filter(cand_dicts, min_followers=_MIN_FOLLOWERS_QUALITY)
                quality_usernames = {d["username"].lower() for d in quality_dicts}
                candidates = [
                    c for c in candidates
                    if c.username.lower() in quality_usernames
                ]

                # 4b. Niche classification + match scoring for each candidate
                if target_niche is None:
                    # Reconstruct target niche on resume
                    if profile_data is None:
                        account = self._account_repo.get_by_id(account_id)
                        if hiker is None:
                            hiker = self._ensure_hiker()
                        profile_data = hiker.get_profile(account.username)
                    target_niche = classify_profile(
                        profile_data.get("biography", "") or "",
                        profile_data.get("category", "") or "",
                        profile_data.get("full_name", "") or "",
                        search.username,
                    )

                niche_rejected = 0
                for cand in candidates:
                    cand_bio = cand.bio or ""
                    cand_full = cand.full_name or ""
                    # Classify candidate
                    cand_niche = classify_profile(
                        cand_bio, "", cand_full, cand.username,
                    )
                    # Compute match score
                    match_score = compute_niche_match(
                        target_niche, cand_bio, "", cand_full, cand.username,
                    )
                    # Persist niche data
                    try:
                        strategy = getattr(cand, '_search_strategy', None)
                        if strategy is None and hasattr(self, '_strategy_by_username'):
                            strategy = self._strategy_by_username.get(
                                cand.username.lower(), "keyword")
                        self._search_repo.update_candidate_niche(
                            cand.id,
                            niche_category_local=cand_niche.primary_niche,
                            niche_match_score=match_score,
                            search_strategy=strategy,
                            language=cand_niche.language,
                        )
                    except Exception as exc:
                        logger.debug("Niche update failed for %s: %s", cand.username, exc)

                # 4c. Quality gate: reject candidates with low niche match
                before_gate = len(candidates)
                candidates = [
                    c for c in candidates
                    if compute_niche_match(
                        target_niche,
                        c.bio or "", "", c.full_name or "", c.username,
                    ) >= _NICHE_MATCH_MIN
                ]
                niche_rejected = before_gate - len(candidates)

                self._search_repo.update_search_step(search_id, 4)
                _progress(55, f"{len(candidates)} quality candidates "
                              f"({niche_rejected} rejected by niche gate)")
                logger.info(
                    "Step 4 complete: %d quality candidates after enrichment "
                    "(%d rejected by niche gate)",
                    len(candidates), niche_rejected,
                )

            # ── Step 5 — Fetch posts + compute ER ────────────────────
            if start_step <= 5:
                if _check_cancelled(search_id):
                    return []
                _progress(60, "Fetching posts and computing engagement...")

                if hiker is None:
                    hiker = self._ensure_hiker()
                if not candidates:
                    candidates = self._search_repo.get_candidates(search_id)
                    # Re-apply quality filter for resume
                    cand_dicts = [self._candidate_to_dict(c) for c in candidates]
                    quality_dicts = quality_filter(cand_dicts, min_followers=_MIN_FOLLOWERS_QUALITY)
                    quality_usernames = {d["username"].lower() for d in quality_dicts}
                    candidates = [
                        c for c in candidates
                        if c.username.lower() in quality_usernames
                    ]

                # Sort by follower_count desc, take top N for post fetch
                candidates.sort(key=lambda c: c.follower_count, reverse=True)
                top_for_er = candidates[:_POST_FETCH_LIMIT]

                for cand in top_for_er:
                    if cand.avg_er is not None:
                        continue  # already computed
                    try:
                        posts = hiker.get_posts(cand.username, 5)
                        er = compute_avg_er(posts, cand.follower_count)
                        self._search_repo.update_candidate_er(cand.id, er)
                        cand.avg_er = er
                    except Exception as exc:
                        logger.warning(
                            "Post fetch failed for @%s: %s", cand.username, exc,
                        )

                self._search_repo.update_search_step(search_id, 5)
                _progress(70, "Engagement rates computed")
                logger.info("Step 5 complete: engagement rates computed")

            # ── Step 6 — AI scoring (optional) ───────────────────────
            if start_step <= 6:
                if _check_cancelled(search_id):
                    return []
                _progress(75, "AI scoring...")

                gemini_key = self._settings.get("gemini_api_key") or ""
                scorer = GeminiScorer(gemini_key)

                if scorer.is_available:
                    try:
                        if profile_data is None:
                            if hiker is None:
                                hiker = self._ensure_hiker()
                            account = self._account_repo.get_by_id(account_id)
                            profile_data = hiker.get_profile(account.username)

                        if not candidates:
                            candidates = self._search_repo.get_candidates(search_id)

                        # Build candidate dicts for Gemini
                        ai_input = [
                            {
                                "username": c.username,
                                "full_name": c.full_name or "",
                                "bio": c.bio or "",
                                "follower_count": c.follower_count,
                            }
                            for c in candidates
                        ]

                        scores = scorer.categorize_and_score(profile_data, ai_input)

                        for cand in candidates:
                            entry = scores.get(cand.username)
                            if entry:
                                ai_score = float(entry.get("score", 0))
                                ai_cat = entry.get("category", "")
                                self._search_repo.update_candidate_ai(
                                    cand.id, ai_score, ai_cat,
                                )
                                cand.ai_score = ai_score
                                cand.ai_category = ai_cat

                        logger.info(
                            "Step 6 complete: %d candidates scored by AI",
                            len(scores),
                        )
                    except Exception as exc:
                        logger.warning(
                            "AI scoring failed (continuing without): %s", exc,
                        )
                else:
                    logger.info("Step 6: Gemini not available — skipping AI scoring")

                self._search_repo.update_search_step(search_id, 6)
                _progress(85, "AI scoring complete")

            # ── Step 7 — Composite Ranking + Quality Gate ────────────
            if start_step <= 7:
                if _check_cancelled(search_id):
                    return []
                _progress(90, "Computing composite scores and ranking...")

                if not candidates:
                    candidates = self._search_repo.get_candidates(search_id)

                # Reconstruct target niche if needed
                if target_niche is None:
                    if profile_data is None:
                        account = self._account_repo.get_by_id(account_id)
                        if hiker is None:
                            hiker = self._ensure_hiker()
                        profile_data = hiker.get_profile(account.username)
                    target_niche = classify_profile(
                        profile_data.get("biography", "") or "",
                        profile_data.get("category", "") or "",
                        profile_data.get("full_name", "") or "",
                        search.username,
                    )

                # Compute composite score for each candidate
                has_ai = any(c.ai_score is not None for c in candidates)
                for cand in candidates:
                    composite = self._compute_composite_score(
                        cand, target_niche, has_ai,
                    )
                    try:
                        self._search_repo.update_candidate_composite_score(
                            cand.id, composite,
                        )
                    except Exception:
                        pass

                    # Attach for in-memory sort
                    cand._composite = composite  # type: ignore[attr-defined]

                # Quality gate: reject low composite scores
                before_gate = len(candidates)
                candidates = [
                    c for c in candidates
                    if getattr(c, '_composite', 0) >= _COMPOSITE_MIN
                ]
                gate_rejected = before_gate - len(candidates)

                # Sort by composite score descending
                candidates.sort(
                    key=lambda c: getattr(c, '_composite', 0),
                    reverse=True,
                )

                top = candidates[:_FINAL_TOP_N]

                results = [
                    SourceSearchResult(
                        search_id=search_id,
                        candidate_id=cand.id,
                        rank=rank,
                    )
                    for rank, cand in enumerate(top, start=1)
                ]

                self._search_repo.save_results(search_id, results)
                self._search_repo.complete_search(search_id, SEARCH_COMPLETED)

                # Update source_profiles for top results
                self._save_source_profiles(top)

                _progress(95, f"Done — {len(results)} sources found "
                              f"({gate_rejected} rejected by quality gate)")
                logger.info(
                    "Step 7 complete: %d results saved (%d rejected), "
                    "search %d completed",
                    len(results), gate_rejected, search_id,
                )

                # Return with joined candidate data
                return self._search_repo.get_results(search_id)

        except Exception as exc:
            logger.error(
                "Source finder pipeline failed at search_id=%s: %s",
                search_id, exc,
            )
            if search_id is not None:
                self._search_repo.complete_search(
                    search_id, SEARCH_FAILED, str(exc),
                )
            raise

        # Should not reach here, but return empty if somehow it does
        return []

    # ------------------------------------------------------------------
    # Secondary: add_to_sources
    # ------------------------------------------------------------------

    def add_to_sources(
        self, result_id: int, account_id: int, bot_root: str
    ) -> str:
        """
        Append a result's username to the account's sources.txt.

        Uses the backup-first pattern from SourceDeleter:
          1. Read current sources.txt (create if missing)
          2. Check for duplicates (case-insensitive)
          3. Write backup (.bak)
          4. Append username and write

        Returns:
            ADD_OK — source was added successfully.
            ADD_ALREADY — source already exists in the file.
            ADD_FAILED — an error occurred.
        """
        # Get result + candidate
        account = self._account_repo.get_by_id(account_id)
        if account is None:
            logger.error("add_to_sources: account %d not found", account_id)
            return self.ADD_FAILED

        # Find the result's candidate username
        latest_search = self._search_repo.get_latest_search(account_id)
        if latest_search is None:
            logger.error("add_to_sources: no search found for account %d", account_id)
            return self.ADD_FAILED

        results = self._search_repo.get_results(latest_search.id)
        target_result: Optional[SourceSearchResult] = None
        for r in results:
            if r.id == result_id:
                target_result = r
                break

        if target_result is None or target_result.candidate is None:
            logger.error("add_to_sources: result %d not found", result_id)
            return self.ADD_FAILED

        source_username = target_result.candidate.username

        # Build path: bot_root / device_id / username / sources.txt
        path = Path(bot_root) / account.device_id / account.username / "sources.txt"

        # Create parent directory if missing
        if not path.parent.exists():
            logger.error(
                "add_to_sources: directory does not exist: %s", path.parent,
            )
            return self.ADD_FAILED

        # Read current file (or start fresh if it doesn't exist)
        current_content = ""
        current_lines: List[str] = []
        if path.exists():
            try:
                current_content = path.read_text(encoding="utf-8", errors="replace")
                current_lines = current_content.splitlines()
            except OSError as exc:
                logger.error("add_to_sources: cannot read %s: %s", path, exc)
                return self.ADD_FAILED

        # Check for duplicate (case-insensitive)
        existing_lower = {ln.strip().lower() for ln in current_lines}
        if source_username.lower() in existing_lower:
            logger.info(
                "add_to_sources: @%s already in sources.txt for @%s",
                source_username, account.username,
            )
            # Still mark in DB so the UI reflects it
            self._search_repo.mark_added_to_sources(result_id)
            return self.ADD_ALREADY

        # Write backup (only if file already exists)
        if path.exists():
            bak_path = path.with_name("sources.txt.bak")
            try:
                bak_path.write_text(current_content, encoding="utf-8")
            except OSError as exc:
                logger.warning("add_to_sources: backup failed %s: %s", bak_path, exc)
                # Non-fatal: continue without backup

        # Append source username
        new_lines = list(current_lines)
        new_lines.append(source_username)
        new_content = "\n".join(new_lines)
        if not new_content.endswith("\n"):
            new_content += "\n"

        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as exc:
            logger.error("add_to_sources: cannot write %s: %s", path, exc)
            return self.ADD_FAILED

        # Mark in DB
        self._search_repo.mark_added_to_sources(result_id)

        logger.info(
            "Added @%s to sources.txt for @%s (device=%s)",
            source_username, account.username, account.device_id[:8],
        )
        return self.ADD_OK

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _resolve_search(
        self, account_id: int
    ) -> Tuple[SourceSearchRecord, int, List[SourceCandidate]]:
        """
        Check for a resumable search or create a new one.

        Returns (search_record, start_step, existing_candidates).
        start_step is 1-based: 1 means start from beginning.
        """
        latest = self._search_repo.get_latest_search(account_id)

        if latest is not None and latest.status == SEARCH_RUNNING and latest.step_reached > 0:
            # Check age
            try:
                started = datetime.fromisoformat(latest.started_at)
                # Ensure timezone-aware comparison
                if started.tzinfo is None:
                    started = started.replace(tzinfo=timezone.utc)
                now = datetime.now(timezone.utc)
                age = now - started

                if age < _RESUME_MAX_AGE:
                    # Resume from next step
                    candidates = self._search_repo.get_candidates(latest.id)
                    resume_step = latest.step_reached + 1
                    logger.info(
                        "Resuming search %d from step %d (started %s ago, %d candidates)",
                        latest.id, resume_step, str(age).split(".")[0], len(candidates),
                    )
                    return latest, resume_step, candidates
            except (ValueError, TypeError) as exc:
                logger.warning(
                    "Cannot parse started_at for search %d: %s", latest.id, exc,
                )

        # Create new search
        account = self._account_repo.get_by_id(account_id)
        if account is None:
            raise ValueError(f"Account {account_id} not found")

        search = self._search_repo.create_search(account_id, account.username)
        logger.info(
            "Created new search %d for @%s (account_id=%d)",
            search.id, account.username, account_id,
        )
        return search, 1, []

    def _ensure_hiker(self) -> HikerClient:
        """Create a HikerClient from settings. Raises HikerAPIError if no key."""
        hiker_key = self._settings.get("hiker_api_key") or ""
        return HikerClient(hiker_key)

    @staticmethod
    def _candidate_to_dict(cand: SourceCandidate) -> dict:
        """Convert a SourceCandidate to a dict compatible with filter helpers."""
        return {
            "username": cand.username,
            "full_name": cand.full_name,
            "follower_count": cand.follower_count,
            "biography": cand.bio,
            "bio": cand.bio,
            "is_private": cand.is_private,
            "is_verified": cand.is_verified,
            "profile_pic_url": cand.profile_pic_url,
        }

    @staticmethod
    def _compute_composite_score(
        cand: SourceCandidate,
        target_niche: NicheResult,
        has_ai_scores: bool,
    ) -> float:
        """Compute composite relevance score (0-100) for a candidate."""
        score = 0.0

        # Niche match (35%) — from NicheClassifier
        niche_match = compute_niche_match(
            target_niche,
            cand.bio or "", "", cand.full_name or "", cand.username,
        )
        score += (niche_match / 100.0) * 35

        # AI relevance (25%) — from Gemini, or fallback
        if has_ai_scores and cand.ai_score is not None:
            score += (cand.ai_score / 10.0) * 25
        else:
            # Fallback: use niche_match as proxy (lower weight)
            score += (niche_match / 100.0) * 15

        # Engagement rate (20%) — normalized, cap at 10%
        if cand.avg_er is not None and cand.avg_er > 0:
            er_norm = min(cand.avg_er, 10.0) / 10.0
            score += er_norm * 20

        # Source strategy bonus (10%)
        strategy_bonuses = {
            "suggested": 10.0,
            "niche_exact": 8.0,
            "niche_broad": 6.0,
            "related_niche": 5.0,
            "keyword": 4.0,
        }
        strategy = cand.source_type if cand.source_type == "suggested" else "keyword"
        score += strategy_bonuses.get(strategy, 3.0)

        # Language match bonus (10%)
        cand_lang = detect_language(cand.bio)
        if cand_lang == target_niche.language:
            score += 10.0
        elif cand_lang == "unknown" or target_niche.language == "unknown":
            score += 5.0

        return round(min(score, 100.0), 2)

    def _save_source_profiles(self, candidates: List[SourceCandidate]) -> None:
        """Save/update source_profiles for discovered candidates."""
        if self._profile_repo is None:
            return
        for cand in candidates:
            try:
                cand_niche = classify_profile(
                    cand.bio or "", "", cand.full_name or "", cand.username,
                )
                self._profile_repo.upsert_profile(
                    source_name=cand.username,
                    niche_category=cand_niche.primary_niche,
                    niche_confidence=cand_niche.confidence,
                    language=cand_niche.language,
                    follower_count=cand.follower_count,
                    bio=cand.bio,
                    avg_er=cand.avg_er,
                )
            except Exception as exc:
                logger.debug(
                    "Failed to save source profile for @%s: %s",
                    cand.username, exc,
                )
