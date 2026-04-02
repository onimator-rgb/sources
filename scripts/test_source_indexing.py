"""
Test script: Run source indexing for first N sources and log results.
Usage: python scripts/test_source_indexing.py [limit]
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from oh.db.connection import get_connection, close_connection
from oh.db.migrations import run_migrations
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.account_repo import AccountRepository
from oh.repositories.source_search_repo import SourceSearchRepository
from oh.repositories.source_profile_repo import SourceProfileRepository
from oh.services.source_finder_service import SourceFinderService

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

LIMIT = int(sys.argv[1]) if len(sys.argv) > 1 else 50
LOG_FILE = Path(__file__).parent.parent / "logs" / "test_source_indexing.log"

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

LOG_FILE.parent.mkdir(parents=True, exist_ok=True)

fmt = logging.Formatter(
    "%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

root_logger = logging.getLogger()
root_logger.setLevel(logging.DEBUG)

fh = logging.FileHandler(str(LOG_FILE), mode="w", encoding="utf-8")
fh.setLevel(logging.DEBUG)
fh.setFormatter(fmt)
root_logger.addHandler(fh)

ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.INFO)
ch.setFormatter(fmt)
root_logger.addHandler(ch)

logger = logging.getLogger("test_source_indexing")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    logger.info("=" * 70)
    logger.info("SOURCE INDEXING TEST — limit=%d", LIMIT)
    logger.info("Log file: %s", LOG_FILE)
    logger.info("=" * 70)

    conn = get_connection()
    run_migrations(conn)

    settings = SettingsRepository(conn)
    settings.seed_defaults()

    bot_root = settings.get("bot_root_path") or ""
    hiker_key = settings.get("hiker_api_key") or ""
    logger.info("Bot root: %s", bot_root)
    logger.info("HikerAPI key: ****%s", hiker_key[-4:] if len(hiker_key) > 4 else "(not set)")

    if not bot_root or not hiker_key:
        logger.error("Bot root or HikerAPI key not configured. Aborting.")
        return

    # Count sources
    total_active = conn.execute(
        "SELECT COUNT(DISTINCT source_name) FROM source_assignments WHERE is_active = 1"
    ).fetchone()[0]
    already_indexed = conn.execute("SELECT COUNT(*) FROM source_profiles").fetchone()[0]
    logger.info("Total active sources: %d", total_active)
    logger.info("Already indexed: %d", already_indexed)
    logger.info("Will process up to: %d", LIMIT)

    # Get source names to process (limited)
    rows = conn.execute(
        "SELECT DISTINCT source_name FROM source_assignments WHERE is_active = 1 "
        "ORDER BY source_name LIMIT ?",
        (LIMIT,),
    ).fetchall()
    source_names = [r["source_name"] for r in rows]
    logger.info("Sources to process: %d", len(source_names))

    # Initialize services
    account_repo = AccountRepository(conn)
    search_repo = SourceSearchRepository(conn)
    profile_repo = SourceProfileRepository(conn)
    service = SourceFinderService(
        search_repo=search_repo,
        account_repo=account_repo,
        settings_repo=settings,
        source_profile_repo=profile_repo,
    )

    # Run indexing with progress logging
    start_time = time.monotonic()
    results = {
        "indexed": [],
        "skipped": [],
        "failed": [],
        "errors": [],
    }

    from oh.modules.source_finder import HikerClient, HikerAPIError
    from oh.modules.niche_classifier import classify_profile, detect_language

    hiker = HikerClient(hiker_key)

    for i, source_name in enumerate(source_names):
        elapsed = time.monotonic() - start_time
        logger.info(
            "[%d/%d] Processing @%s (elapsed: %.1fs)",
            i + 1, len(source_names), source_name, elapsed,
        )

        # Check if already indexed
        existing = profile_repo.get_profile(source_name)
        if existing is not None:
            logger.info("  SKIP — already in source_profiles")
            results["skipped"].append(source_name)
            continue

        # Fetch profile
        try:
            profile_data = hiker.get_profile(source_name)
        except HikerAPIError as exc:
            logger.warning("  FAIL (HikerAPI) — %s", exc)
            results["failed"].append(source_name)
            results["errors"].append(f"@{source_name}: {exc}")
            continue
        except Exception as exc:
            logger.warning("  FAIL (other) — %s", exc)
            results["failed"].append(source_name)
            results["errors"].append(f"@{source_name}: {exc}")
            continue

        # Classify
        bio = profile_data.get("biography", "") or ""
        category = profile_data.get("category", "") or ""
        full_name = profile_data.get("full_name", "") or ""
        city = profile_data.get("city_name", "") or ""
        followers = int(profile_data.get("follower_count", 0) or 0)
        is_private = bool(profile_data.get("is_private", False))

        niche_result = classify_profile(bio, category, full_name, source_name)

        logger.info(
            "  PROFILE: followers=%s, private=%s, category='%s', city='%s'",
            f"{followers:,}", is_private, category, city,
        )
        logger.info(
            "  NICHE: %s (%s, confidence=%.2f), language=%s",
            niche_result.primary_niche, niche_result.display_name,
            niche_result.confidence, niche_result.language,
        )
        logger.info(
            "  KEYWORDS: %s",
            niche_result.matched_keywords[:5] if niche_result.matched_keywords else "(none)",
        )
        logger.info("  BIO: %s", bio[:100].replace("\n", " ") if bio else "(empty)")

        # Save to DB
        try:
            profile_repo.upsert_profile(
                source_name=source_name,
                niche_category=niche_result.primary_niche,
                niche_confidence=niche_result.confidence,
                language=niche_result.language,
                location=city or None,
                follower_count=followers,
                bio=bio[:500] if bio else None,
                avg_er=None,
                profile_json=json.dumps({
                    "username": source_name,
                    "full_name": full_name,
                    "category": category,
                    "city_name": city,
                    "follower_count": followers,
                    "is_private": is_private,
                    "biography": bio[:200],
                }),
            )
            results["indexed"].append({
                "source": source_name,
                "niche": niche_result.primary_niche,
                "confidence": niche_result.confidence,
                "language": niche_result.language,
                "followers": followers,
                "category": category,
                "city": city,
            })
            logger.info("  OK — indexed as %s", niche_result.primary_niche)
        except Exception as exc:
            logger.error("  FAIL (DB save) — %s", exc)
            results["failed"].append(source_name)
            results["errors"].append(f"@{source_name}: DB error: {exc}")

        # Rate limit
        time.sleep(0.5)

    # ---------------------------------------------------------------------------
    # Summary
    # ---------------------------------------------------------------------------
    total_elapsed = time.monotonic() - start_time
    logger.info("")
    logger.info("=" * 70)
    logger.info("TEST COMPLETE — %.1fs elapsed", total_elapsed)
    logger.info("=" * 70)
    logger.info("Indexed: %d", len(results["indexed"]))
    logger.info("Skipped: %d", len(results["skipped"]))
    logger.info("Failed:  %d", len(results["failed"]))

    if results["errors"]:
        logger.info("")
        logger.info("ERRORS:")
        for err in results["errors"]:
            logger.info("  %s", err)

    # Niche distribution
    niche_counts = {}
    for item in results["indexed"]:
        n = item["niche"]
        niche_counts[n] = niche_counts.get(n, 0) + 1
    if niche_counts:
        logger.info("")
        logger.info("NICHE DISTRIBUTION:")
        for niche, count in sorted(niche_counts.items(), key=lambda x: -x[1]):
            logger.info("  %-20s %d", niche, count)

    # Language distribution
    lang_counts = {}
    for item in results["indexed"]:
        lang = item["language"]
        lang_counts[lang] = lang_counts.get(lang, 0) + 1
    if lang_counts:
        logger.info("")
        logger.info("LANGUAGE DISTRIBUTION:")
        for lang, count in sorted(lang_counts.items(), key=lambda x: -x[1]):
            logger.info("  %-10s %d", lang, count)

    # Confidence stats
    if results["indexed"]:
        confs = [item["confidence"] for item in results["indexed"]]
        logger.info("")
        logger.info("CONFIDENCE STATS:")
        logger.info("  Min:  %.2f", min(confs))
        logger.info("  Max:  %.2f", max(confs))
        logger.info("  Avg:  %.2f", sum(confs) / len(confs))
        low_conf = [item for item in results["indexed"] if item["confidence"] < 0.4]
        logger.info("  Low confidence (<0.4): %d", len(low_conf))
        if low_conf:
            for item in low_conf[:5]:
                logger.info("    @%-25s niche=%-15s conf=%.2f cat='%s'",
                            item["source"], item["niche"], item["confidence"], item["category"])

    # Sample of results
    logger.info("")
    logger.info("SAMPLE RESULTS (first 10):")
    for item in results["indexed"][:10]:
        logger.info(
            "  @%-25s niche=%-15s conf=%.2f lang=%s followers=%s city=%s",
            item["source"], item["niche"], item["confidence"],
            item["language"], f"{item['followers']:,}", item["city"] or "-",
        )

    # Save JSON report
    report_path = LOG_FILE.with_suffix(".json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2, ensure_ascii=False)
    logger.info("")
    logger.info("JSON report saved to: %s", report_path)

    # Verify DB
    count = conn.execute("SELECT COUNT(*) FROM source_profiles").fetchone()[0]
    logger.info("source_profiles table now has: %d rows", count)

    close_connection()
    logger.info("Done.")


if __name__ == "__main__":
    main()
