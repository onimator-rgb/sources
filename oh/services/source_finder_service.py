"""
SourceFinderService — orchestrates the multi-step source discovery pipeline.

Pipeline:
  1. Profile fetch → save query
  2. Collect candidates (suggested + 5x search) → save to DB
  3. Pre-filter (remove private, verified)
  4. Enrich top 25 (full profile data)
  5. Fetch posts + compute ER for top 10
  6. AI scoring (optional, graceful skip)
  7. Rank + save top 10 results

Resume: if a running search exists (started < 1h ago), resumes from
step_reached + 1. Otherwise creates a new search.

Secondary: add_to_sources() appends a result username to sources.txt
with backup-first safety (same pattern as SourceDeleter).
"""
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from oh.models.source_finder import (
    SourceCandidate,
    SourceSearchRecord,
    SourceSearchResult,
    SEARCH_COMPLETED,
    SEARCH_FAILED,
    SEARCH_RUNNING,
)
from oh.modules.source_finder import (
    HikerClient,
    GeminiScorer,
    HikerAPIError,
    build_manual_query,
    build_query_variations,
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
    ) -> None:
        self._search_repo = search_repo
        self._account_repo = account_repo
        self._settings = settings_repo

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

        try:
            # ── Step 1 — Profile fetch ───────────────────────────────
            if start_step <= 1:
                if _check_cancelled(search_id):
                    return []
                _progress(5, "Fetching target profile...")

                account = self._account_repo.get_by_id(account_id)
                if account is None:
                    raise ValueError(f"Account {account_id} not found")

                hiker = HikerClient(hiker_key)

                profile_data = hiker.get_profile(account.username)

                # Build query — try Gemini first, fall back to manual
                gemini_key = self._settings.get("gemini_api_key") or ""
                scorer = GeminiScorer(gemini_key)
                if scorer.is_available:
                    query = scorer.generate_search_query(profile_data)
                if not query:
                    query = build_manual_query(profile_data)

                # Persist query on the search record
                self._search_repo.update_search_query(search_id, query)

                self._search_repo.update_search_step(search_id, 1)
                _progress(10, f"Profile fetched. Query: {query}")
                logger.info(
                    "Step 1 complete: profile fetched for @%s, query=%r",
                    account.username, query,
                )

            # ── Step 2 — Collect candidates ──────────────────────────
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

                # B. Search with query variations
                if not query:
                    query = build_manual_query(profile_data)
                variations = build_query_variations(query)
                search_results_raw: List[dict] = []
                for var in variations:
                    search_results_raw.extend(hiker.search_accounts(var))

                # Deduplicate by username (case-insensitive), mark source_type
                seen_lower: set = set()
                deduped: List[dict] = []

                # Suggested first
                for c in raw_candidates:
                    uname = (c.get("username") or "").lower()
                    if uname and uname not in seen_lower:
                        seen_lower.add(uname)
                        c["_source_type"] = "suggested"
                        deduped.append(c)

                # Search results second
                for c in search_results_raw:
                    uname = (c.get("username") or "").lower()
                    if uname and uname not in seen_lower:
                        seen_lower.add(uname)
                        c["_source_type"] = "search"
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

                self._search_repo.update_search_step(search_id, 4)
                _progress(55, f"{len(candidates)} quality candidates")
                logger.info(
                    "Step 4 complete: %d quality candidates after enrichment",
                    len(candidates),
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

            # ── Step 7 — Rank and finalize ───────────────────────────
            if start_step <= 7:
                if _check_cancelled(search_id):
                    return []
                _progress(90, "Ranking and finalizing results...")

                if not candidates:
                    candidates = self._search_repo.get_candidates(search_id)

                # Sort: by ai_score desc if available, then follower_count desc
                has_ai = any(c.ai_score is not None for c in candidates)
                if has_ai:
                    candidates.sort(
                        key=lambda c: (
                            c.ai_score if c.ai_score is not None else -1,
                            c.follower_count,
                        ),
                        reverse=True,
                    )
                else:
                    candidates.sort(key=lambda c: c.follower_count, reverse=True)

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

                _progress(95, f"Done — {len(results)} sources found")
                logger.info(
                    "Step 7 complete: %d results saved, search %d completed",
                    len(results), search_id,
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
