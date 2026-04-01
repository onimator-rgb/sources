"""
SourceFinder — HikerAPI client + Gemini scorer for discovering similar
Instagram profiles.

Adapted from ig_audit's hiker_client.py and ai_service.py, simplified
for OH's source-discovery pipeline.

All public methods are synchronous (called from a worker QThread).
All API calls have proper error handling — failures never crash the pipeline.
"""

import json
import logging
import re
import time
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

# ── HikerAPI constants ──────────────────────────────────────────────
BASE_URL = "https://api.hikerapi.com"
DEFAULT_TIMEOUT = 30        # seconds per request
RETRY_WAIT = 5              # seconds on 429 / 503
REQUEST_DELAY = 0.3         # polite pause between successful calls

# ── Gemini import guard ─────────────────────────────────────────────
try:
    import google.generativeai as genai
    _GENAI_OK = True
except ImportError:
    _GENAI_OK = False

# ── Stopwords for manual query building ─────────────────────────────
_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "shall",
    "should", "may", "might", "must", "can", "could", "am", "not", "no",
    "and", "or", "but", "if", "for", "nor", "so", "yet", "at", "by",
    "from", "in", "into", "of", "on", "to", "with", "as", "its", "it",
    "this", "that", "these", "those", "i", "me", "my", "we", "our",
    "you", "your", "he", "him", "his", "she", "her", "they", "them",
    "their", "what", "which", "who", "whom", "how", "when", "where",
    "all", "each", "every", "both", "few", "more", "most", "other",
    "some", "such", "than", "too", "very", "just", "also", "about",
    "new", "get", "like", "follow", "dm", "link", "bio", "check", "out",
    "based", "love", "life", "world", "official", "real", "page",
    "contact", "info", "available", "click", "below", "here",
    # Polish common words
    "więcej", "kontakt", "zapisy", "współpraca", "cennik", "oferta",
    "oraz", "dla", "jest", "się", "nie", "też", "przez", "przy",
    "nad", "pod", "jak", "już", "tylko", "tak", "może", "będzie",
    "każdy", "nasz", "swój", "tego", "tej", "ten", "tym", "ale", "aby",
    "czy", "lub",
}

_GENERIC_HASHTAGS = {
    "instagood", "photooftheday", "love", "follow", "followme", "like4like",
    "likeforlikes", "followforfollowback", "photography", "picoftheday",
    "instagram", "instadaily", "instalike", "beautiful", "photo", "style",
    "happy", "fashion", "art", "nature", "reels", "viral", "trending",
    "explore", "explorepage", "fyp", "foryou", "tbt", "throwback",
    "bestoftheday", "nofilter", "selfie", "smile", "fun", "amazing",
}

_EMOJI_RE = re.compile(
    "["
    "\U0001F600-\U0001F64F"
    "\U0001F300-\U0001F5FF"
    "\U0001F680-\U0001F6FF"
    "\U0001F1E0-\U0001F1FF"
    "\U00002702-\U000027B0"
    "\U0000FE00-\U0000FE0F"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FA6F"
    "\U0001FA70-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U0000200D"
    "\U00002B50"
    "]+",
    flags=re.UNICODE,
)

_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)
_MENTION_RE = re.compile(r"@\w+")
_HASHTAG_RE = re.compile(r"#\w+")


# ── Exceptions ──────────────────────────────────────────────────────

class HikerAPIError(Exception):
    """Raised for non-recoverable HikerAPI errors."""


# ── HikerClient ────────────────────────────────────────────────────

class HikerClient:
    """
    Thin wrapper around HikerAPI endpoints for source discovery.

    Handles retry on 429/503, rate limit backoff, and username-to-user_id
    caching. All methods are synchronous.
    """

    def __init__(self, api_key: str) -> None:
        if not api_key or not api_key.strip():
            raise HikerAPIError(
                "HikerAPI key not configured. Go to Settings to add your key."
            )
        self._session = requests.Session()
        self._session.headers.update({
            "x-access-key": api_key,
            "Accept": "application/json",
            "User-Agent": "OH-SourceFinder/1.0",
        })
        self._uid_cache: Dict[str, str] = {}

        key_tail = f"****{api_key[-4:]}" if len(api_key) > 4 else "****"
        logger.info("HikerClient ready (key=%s)", key_tail)

    def get_profile(self, username: str) -> dict:
        """
        Fetch public profile for *username*.
        Endpoint: GET /v1/user/by/username

        Returns raw API dict with keys like pk, username, follower_count, etc.
        Raises HikerAPIError if account not found or response malformed.
        """
        logger.info("Fetching profile for @%s", username)
        t0 = time.monotonic()
        data = self._get("/v1/user/by/username", {"username": username})
        elapsed = time.monotonic() - t0

        if data is None:
            logger.error(
                "Profile @%s not found (HTTP 404, %.2fs)", username, elapsed,
            )
            raise HikerAPIError(
                f"@{username} not found. "
                "Check the username is correct and the account is public."
            )

        if "pk" not in data:
            logger.error(
                "Profile @%s missing 'pk' field (%.2fs)", username, elapsed,
            )
            raise HikerAPIError(
                f"Unexpected API response for @{username} (missing 'pk')"
            )

        user_id = str(data["pk"])
        self._uid_cache[username.lower()] = user_id

        logger.info(
            "Fetched profile @%s (%.2fs): followers=%s",
            data.get("username", username),
            elapsed,
            f"{int(data.get('follower_count', 0)):,}",
        )
        return data

    def get_suggested_profiles(self, user_id: str) -> List[dict]:
        """
        Fetch Instagram-suggested similar profiles for *user_id*.
        Endpoint: GET /v2/user/suggested/profiles

        Returns list of raw user dicts; empty list on any failure.
        """
        logger.info("Fetching suggested profiles for user_id=%s", user_id)
        t0 = time.monotonic()

        try:
            data = self._get(
                "/v2/user/suggested/profiles",
                {"user_id": user_id, "expand_suggestion": "True"},
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch suggested profiles for user_id=%s (%.2fs): %s",
                user_id, time.monotonic() - t0, exc,
            )
            return []

        if not data:
            logger.warning(
                "No suggested profiles returned for user_id=%s (%.2fs)",
                user_id, time.monotonic() - t0,
            )
            return []

        try:
            users = self._extract_user_list(data)
            logger.info(
                "Fetched %d suggested profiles for user_id=%s (%.2fs)",
                len(users), user_id, time.monotonic() - t0,
            )
            return users
        except Exception as exc:
            logger.warning(
                "Failed to parse suggested profiles for user_id=%s: %s",
                user_id, exc,
            )
            return []

    def search_accounts(self, query: str) -> List[dict]:
        """
        Search Instagram accounts by keyword query.
        Endpoint: GET /v2/fbsearch/accounts

        Returns list of raw user dicts; empty list on any failure.
        """
        if not query or not query.strip():
            return []

        query = query.strip()
        logger.info("Searching accounts for query='%s'", query)
        t0 = time.monotonic()

        try:
            data = self._get("/v2/fbsearch/accounts", {"query": query})
        except Exception as exc:
            logger.warning(
                "Search failed for query='%s' (%.2fs): %s",
                query, time.monotonic() - t0, exc,
            )
            return []

        if not data:
            logger.warning(
                "Empty search response for query='%s' (%.2fs)",
                query, time.monotonic() - t0,
            )
            return []

        try:
            if isinstance(data, dict):
                users = data.get("users") or data.get("items") or []
            elif isinstance(data, list):
                users = data
            else:
                users = []

            # Unwrap nested {"user": {...}} if present
            if users and isinstance(users[0], dict) and "user" in users[0]:
                users = [
                    item["user"] for item in users
                    if isinstance(item.get("user"), dict)
                ]

            logger.info(
                "Found %d accounts for query='%s' (%.2fs)",
                len(users), query, time.monotonic() - t0,
            )
            return users[:10]

        except Exception as exc:
            logger.warning(
                "Failed to parse search results for query='%s': %s",
                query, exc,
            )
            return []

    def get_posts(self, username: str, max_count: int = 5) -> List[dict]:
        """
        Fetch recent feed posts for *username* (single page, no full pagination).
        Endpoint: GET /v1/user/medias/chunk

        Returns list of raw media dicts; empty list on failure.
        """
        logger.info("Fetching posts for @%s (max=%d)", username, max_count)
        t0 = time.monotonic()

        try:
            user_id = self._resolve_user_id(username)
        except HikerAPIError:
            logger.warning("Cannot resolve user_id for @%s — skipping posts", username)
            return []

        try:
            data = self._get(
                "/v1/user/medias/chunk",
                {"user_id": user_id},
            )
        except Exception as exc:
            logger.warning(
                "Failed to fetch posts for @%s: %s", username, exc,
            )
            return []

        if not data:
            logger.info("No posts returned for @%s (%.2fs)", username, time.monotonic() - t0)
            return []

        # Response format: [items_array, next_cursor | null]
        if isinstance(data, list) and len(data) == 2 and isinstance(data[0], list):
            items = data[0]
        elif isinstance(data, list):
            items = data
        else:
            items = []

        posts = items[:max_count]
        logger.info(
            "Fetched %d posts for @%s (%.2fs)",
            len(posts), username, time.monotonic() - t0,
        )
        return posts

    # ── Internal helpers ─────────────────────────────────────────────

    def _resolve_user_id(self, username: str) -> str:
        """Return numeric user_id for username, using cache when available."""
        key = username.lower()
        if key in self._uid_cache:
            return self._uid_cache[key]

        profile_data = self._get("/v1/user/by/username", {"username": username})
        if not profile_data or "pk" not in profile_data:
            raise HikerAPIError(f"Could not resolve user ID for @{username}")

        user_id = str(profile_data["pk"])
        self._uid_cache[key] = user_id
        return user_id

    def _get(self, path: str, params: Optional[dict] = None) -> object:
        """
        GET with 3x retry on 429/503, exponential backoff.
        Returns parsed JSON on 200, None on 404.
        Raises HikerAPIError on all other failures.
        """
        url = BASE_URL + path

        for attempt in range(3):
            t0 = time.monotonic()
            try:
                resp = self._session.get(url, params=params, timeout=DEFAULT_TIMEOUT)
            except requests.Timeout:
                logger.error(
                    "GET %s -> TIMEOUT (attempt %d/3)", path, attempt + 1,
                )
                raise HikerAPIError(
                    f"Request timed out after {DEFAULT_TIMEOUT}s on {path}. "
                    "Check your internet connection."
                )
            except requests.ConnectionError as exc:
                logger.error(
                    "GET %s -> CONNECTION ERROR (attempt %d/3): %s",
                    path, attempt + 1, exc,
                )
                raise HikerAPIError(
                    f"Cannot reach HikerAPI: {exc}. Check your internet connection."
                ) from exc
            except requests.RequestException as exc:
                raise HikerAPIError(f"Network error: {exc}") from exc

            elapsed = time.monotonic() - t0

            if resp.status_code == 200:
                logger.debug("GET %s -> 200 (%.3fs)", path, elapsed)
                time.sleep(REQUEST_DELAY)
                return resp.json()

            if resp.status_code == 404:
                logger.debug("GET %s -> 404 (%.3fs)", path, elapsed)
                return None

            if resp.status_code == 422:
                try:
                    detail = resp.json().get("detail", resp.text)
                except Exception:
                    detail = resp.text
                logger.error("GET %s -> 422: %s", path, detail)
                raise HikerAPIError(f"Validation error on {path}: {detail}")

            if resp.status_code in (429, 503):
                wait = RETRY_WAIT * (attempt + 1)
                if attempt < 2:
                    logger.warning(
                        "GET %s -> %d (%.3fs) — retrying %d/3 in %ds",
                        path, resp.status_code, elapsed, attempt + 1, wait,
                    )
                    time.sleep(wait)
                    continue
                if resp.status_code == 429:
                    logger.error(
                        "GET %s -> 429 rate limit persists after 3 attempts", path,
                    )
                    raise HikerAPIError(
                        "HikerAPI rate limit reached. Please wait a few minutes and try again."
                    )

            # Any other non-success status
            logger.error("GET %s -> HTTP %d (%.3fs)", path, resp.status_code, elapsed)
            try:
                resp.raise_for_status()
            except requests.HTTPError as exc:
                raise HikerAPIError(str(exc)) from exc

        raise HikerAPIError(f"Request to {path} failed after 3 retries")

    @staticmethod
    def _extract_user_list(data: object) -> List[dict]:
        """Defensively extract user list from various response shapes."""
        items: List[dict] = []
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            for key in ("users", "suggested_users", "items"):
                if key in data and isinstance(data[key], list):
                    items = data[key]
                    break
            else:
                if "username" in data:
                    items = [data]

        # Handle nested 'user' dicts
        if items and isinstance(items[0], dict) and "user" in items[0]:
            items = [
                item["user"] for item in items
                if isinstance(item.get("user"), dict)
            ]

        return items


# ── GeminiScorer ────────────────────────────────────────────────────

class GeminiScorer:
    """
    Gemini Flash wrapper for generating search queries and scoring
    candidate profiles for relevance.

    All methods are non-blocking (failure returns sensible defaults)
    so the pipeline continues even if the AI layer is unavailable.
    """

    def __init__(self, api_key: str) -> None:
        self._model = None

        if not _GENAI_OK:
            logger.warning(
                "google-generativeai package not installed — AI features disabled"
            )
            return

        if not api_key:
            logger.info("No Gemini API key provided — AI features disabled")
            return

        try:
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel("gemini-2.5-flash")
            logger.info("GeminiScorer initialised with Gemini 2.5 Flash")
        except Exception as exc:
            logger.error("Failed to initialise Gemini model: %s", exc)

    @property
    def is_available(self) -> bool:
        """True if the Gemini model was successfully initialised."""
        return self._model is not None

    def generate_search_query(self, profile_data: dict) -> str:
        """
        Ask Gemini to generate a 3-5 word search query for finding
        similar Instagram accounts.

        Args:
            profile_data: dict with keys like username, full_name,
                          biography, category, city_name, follower_count.

        Returns the query string, or empty string on failure.
        """
        if not self.is_available:
            return ""

        try:
            username = profile_data.get("username", "")
            full_name = (profile_data.get("full_name", "") or "").replace(
                "|", " "
            ).replace("•", " ").replace("·", " ").strip()
            bio = (profile_data.get("biography", "") or "")[:300]
            category = profile_data.get("category", "") or "Not set"
            city = profile_data.get("city_name", "") or "Not set"
            followers = int(profile_data.get("follower_count", 0))

            prompt = (
                "You are helping find Instagram accounts similar to the one below.\n"
                "Generate a 3-5 word search query for Instagram's account search API.\n"
                "The query should describe the NICHE and LOCATION of this account.\n"
                "Return ONLY the query text, nothing else. No quotes, no explanation.\n\n"
                "Example outputs:\n"
                "- trener personalny Gdansk\n"
                "- fotograf slubny Warszawa\n"
                "- fitness coach London\n\n"
                f"Username: @{username}\n"
                f"Display name: {full_name}\n"
                f"Bio: {bio}\n"
                f"Category: {category}\n"
                f"City: {city}\n"
                f"Followers: {followers:,}\n"
            )

            logger.info("Generating AI search query for @%s", username)
            response = self._model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=500,
                ),
                request_options={"timeout": 30},
            )
            query = response.text.strip().strip('"').strip("'")
            logger.info("AI search query for @%s: %r", username, query)
            return query

        except Exception as exc:
            logger.warning(
                "AI search query failed for @%s (continuing without): %s",
                profile_data.get("username", "?"), exc,
            )
            return ""

    def categorize_and_score(
        self,
        target: dict,
        candidates: List[dict],
    ) -> Dict[str, dict]:
        """
        Ask Gemini to categorize and score each candidate profile for
        relevance to the target.

        Args:
            target: dict with username, biography, category, follower_count
            candidates: list of dicts with username, full_name, bio,
                        follower_count

        Returns:
            dict mapping username -> {"category": str, "score": float,
            "reason": str}. Empty dict on failure.
        """
        if not self.is_available or not candidates:
            return {}

        try:
            # Cap at 15 candidates to keep prompt reasonable
            capped = candidates[:15]

            profiles_text = "\n".join(
                f"- @{c.get('username', '?')}: "
                f"{int(c.get('follower_count', 0)):,} followers, "
                f"bio: {(c.get('bio', '') or '')[:100]}"
                for c in capped
            )

            target_username = target.get("username", "?")
            target_bio = (target.get("biography", "") or "")[:200]
            target_category = target.get("category", "") or "Unknown"
            target_followers = int(target.get("follower_count", 0))

            prompt = (
                "You are evaluating Instagram profiles for targeting similarity.\n\n"
                f"TARGET PROFILE: @{target_username}\n"
                f"- Bio: {target_bio}\n"
                f"- Category: {target_category}\n"
                f"- Followers: {target_followers:,}\n\n"
                "CANDIDATE PROFILES:\n"
                f"{profiles_text}\n\n"
                "For each candidate:\n"
                "1. Assign a niche category (3-8 words)\n"
                "2. Score 1-10 for relevance to the target\n"
                "3. Give a one-sentence reason\n\n"
                "Respond ONLY with valid JSON (no markdown, no code fences):\n"
                "{\n"
                '  "username1": {"category": "niche label", "score": 8, '
                '"reason": "explanation"},\n'
                '  "username2": {"category": "niche label", "score": 6, '
                '"reason": "explanation"}\n'
                "}\n"
                "Include all candidates listed above."
            )

            logger.info(
                "Scoring %d candidates via AI for @%s",
                len(capped), target_username,
            )
            response = self._model.generate_content(
                prompt,
                generation_config=genai.types.GenerationConfig(
                    max_output_tokens=2000,
                ),
                request_options={"timeout": 30},
            )

            raw_text = response.text.strip()
            # Strip markdown code fences if present
            raw_text = re.sub(r"^```(?:json)?\s*", "", raw_text)
            raw_text = re.sub(r"\s*```$", "", raw_text)

            result = json.loads(raw_text)

            if not isinstance(result, dict):
                logger.warning("AI scoring returned non-dict — discarding")
                return {}

            # Normalise: ensure each value has the expected keys
            cleaned: Dict[str, dict] = {}
            for uname, val in result.items():
                if not isinstance(val, dict):
                    continue
                cleaned[str(uname)] = {
                    "category": str(val.get("category", "")),
                    "score": float(val.get("score", 0)),
                    "reason": str(val.get("reason", "")),
                }

            logger.info(
                "AI scoring complete for @%s: %d candidates scored",
                target_username, len(cleaned),
            )
            return cleaned

        except json.JSONDecodeError as exc:
            logger.warning("AI scoring JSON parse failed: %s", exc)
            return {}
        except Exception as exc:
            logger.warning(
                "AI scoring failed (continuing without): %s", exc,
            )
            return {}


# ── Helper functions (module-level) ─────────────────────────────────

def build_manual_query(profile: dict) -> str:
    """
    Build a niche-keyword search query from profile data without AI.

    Adapted from ig_audit's analytics.build_similarity_query(). Uses
    profile fields (category, full_name, biography, city_name) to
    construct a 3-5 word query.

    Args:
        profile: dict with keys like username, full_name, biography,
                 category, city_name.

    Returns a search query string, possibly empty if profile data is
    too sparse.
    """
    terms: List[str] = []

    # Build username-based stopwords (exclude username parts from query)
    name_stopwords: set = set()
    username = (profile.get("username", "") or "").lower()
    for part in username.replace(".", "_").split("_"):
        if len(part) >= 2:
            name_stopwords.add(part)

    def _clean_text(text: str) -> str:
        text = _URL_RE.sub(" ", text)
        text = _MENTION_RE.sub(" ", text)
        text = _HASHTAG_RE.sub(" ", text)
        text = _EMOJI_RE.sub(" ", text)
        text = text.replace("|", " ").replace("•", " ").replace("·", " ")
        text = text.replace("–", " ").replace("—", " ")
        return text

    def _extract_keywords(text: str) -> List[str]:
        return [
            w for w in text.lower().split()
            if len(w) >= 3
            and w not in _STOPWORDS
            and w not in name_stopwords
            and w.isalpha()
        ]

    # A1. Profile category — highest weight
    category = (profile.get("category", "") or "").strip()
    if category:
        cat_words = [
            w for w in category.split()
            if w.lower() not in _STOPWORDS and w.lower() not in name_stopwords
        ]
        terms.extend(cat_words[:3])

    # A2. full_name keywords (often contains niche + location)
    full_name_raw = profile.get("full_name", "") or ""
    full_name_words = _extract_keywords(_clean_text(full_name_raw))

    # A3. Biography keywords
    bio = _clean_text(profile.get("biography", "") or "")
    bio_words = _extract_keywords(bio)

    # Fill remaining term slots: category (already added) -> full_name -> bio
    for source in (full_name_words, bio_words):
        remaining = max(0, 4 - len(terms))
        if remaining <= 0:
            break
        existing_lower = {t.lower() for t in terms}
        for w in source:
            if remaining <= 0:
                break
            if w not in existing_lower:
                terms.append(w)
                existing_lower.add(w)
                remaining -= 1

    # Location: prefer city_name
    city = (profile.get("city_name", "") or "").strip()
    if city and city.lower() not in {t.lower() for t in terms}:
        terms.append(city)

    # Final safety filter
    terms = [t for t in terms if t.lower() not in name_stopwords]
    terms = terms[:5]
    query = " ".join(terms)

    logger.info(
        "Manual query for @%s: %r (category=%r, city=%r)",
        username, query,
        category or "(none)", city or "(none)",
    )
    return query


def build_query_variations(query: str) -> List[str]:
    """
    Build up to 5 different search query variations from the primary query.

    Variations:
      1. Original query
      2. Without last word (drop location)
      3. First word only (broadest niche term)
      4. Reversed (last word + first word)
      5. Remaining words or broader term
    """
    words = query.split()
    variations: List[str] = []
    seen: set = set()

    def _add(q: str) -> None:
        q = q.strip()
        if q and q.lower() not in seen:
            seen.add(q.lower())
            variations.append(q)

    # 1. Original query
    _add(query)

    if len(words) >= 2:
        # 2. Without last word (drop location)
        _add(" ".join(words[:-1]))
        # 3. First word only
        _add(words[0])
        # 4. Last word + first word reversed
        _add(f"{words[-1]} {words[0]}")
        # 5. Middle words or second word
        if len(words) >= 3:
            _add(" ".join(words[1:]))
        else:
            _add(words[-1])
    elif len(words) == 1:
        _add(f"{words[0]} creator")
        _add(f"{words[0]} influencer")

    return variations[:5]


def compute_avg_er(posts: List[dict], follower_count: int) -> float:
    """
    Compute average engagement rate from raw post dicts.

    ER per post = (likes + comments) / follower_count * 100
    Returns 0.0 when posts is empty or follower_count <= 0.
    """
    if not posts or follower_count <= 0:
        return 0.0

    total_er = 0.0
    valid = 0
    for p in posts:
        likes = int(p.get("like_count", 0) or 0)
        comments = int(p.get("comment_count", 0) or 0)
        er = (likes + comments) / follower_count * 100
        total_er += er
        valid += 1

    if valid == 0:
        return 0.0
    return round(total_er / valid, 3)


def pre_filter(candidates: List[dict]) -> List[dict]:
    """
    Pre-filter candidate profiles before expensive enrichment.

    Removes:
    - Profiles without a username
    - Private profiles (is_private=True)
    - Verified profiles (is_verified=True)
    """
    filtered: List[dict] = []
    n_private = 0
    n_verified = 0
    n_no_username = 0

    for c in candidates:
        username = c.get("username", "")
        if not username:
            n_no_username += 1
            continue
        if c.get("is_private", False):
            n_private += 1
            continue
        if c.get("is_verified", False):
            n_verified += 1
            continue
        filtered.append(c)

    removed = len(candidates) - len(filtered)
    logger.info(
        "Pre-filter: %d -> %d (removed %d: %d private, %d verified, "
        "%d no username)",
        len(candidates), len(filtered), removed,
        n_private, n_verified, n_no_username,
    )
    return filtered


def quality_filter(
    candidates: List[dict],
    min_followers: int = 1000,
) -> List[dict]:
    """
    Quality filter after enrichment.

    Keeps candidates with:
    - A username
    - follower_count >= min_followers
    - Not private
    - Not verified
    """
    filtered = [
        c for c in candidates
        if c.get("username")
        and int(c.get("follower_count", 0) or 0) >= min_followers
        and not c.get("is_private", False)
        and not c.get("is_verified", False)
    ]

    removed = len(candidates) - len(filtered)
    if removed:
        logger.info(
            "Quality filter: %d -> %d (removed %d below %d followers "
            "or private/verified)",
            len(candidates), len(filtered), removed, min_followers,
        )
    return filtered
