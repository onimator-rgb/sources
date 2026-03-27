"""
SourceUsageReader — reads per-account source consumption data.

USED count:
  From: {bot_root}/{device_id}/{username}/sources/{source_name}.db
  Table: source_followers(id, username, date_checked)
  Value: COUNT(*) from source_followers

USED %:
  From: {bot_root}/{device_id}/{username}/.stm/{source_name}-total-followed-percent.txt
  That file stores: follows / total_source_followers × 100

  Given:
    used_count        = COUNT(*) from source_followers
    follows           = follow count from data.db (passed in by caller)
    followed_percent  = value from the .stm percent file

  Formula:
    total_source_followers = follows / (followed_percent / 100)
    used_pct               = used_count / total_source_followers × 100
                           = used_count × followed_percent / follows   (equivalent)

  If the percent file is missing, malformed, follows=0, or the result is
  nonsensical, used_pct is left as None.

Error handling:
  - sources/ dir missing              → all records have db_found=False
  - source .db file missing           → record has db_found=False
  - source_followers table missing    → record has db_error set
  - percent file missing              → pct_file_found=False, used_pct=None
  - percent file malformed            → pct_file_error set, used_pct=None
  - follows=0 or percent<=0           → used_pct=None
  In all cases the record is returned so the UI can show a row.
"""
import logging
import sqlite3
from pathlib import Path
from typing import Optional

from oh.models.source_usage import SourceUsageRecord, SourceUsageResult

logger = logging.getLogger(__name__)


class SourceUsageReader:
    def __init__(self, bot_root: str) -> None:
        self._bot_root = Path(bot_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(
        self,
        device_id: str,
        username: str,
        source_names: list[str],
        follows_map: Optional[dict[str, int]] = None,
    ) -> SourceUsageResult:
        """
        Read USED count and derive USED % for each source for one account.

        source_names — raw source names from SourceInspector (may be mixed-case).
        follows_map  — {normalized_source_name: follow_count} from FBR results.
                       Required to compute used_pct.  If None, only used_count
                       is returned.
        """
        sources_dir = self._bot_root / device_id / username / "sources"
        stm_dir     = self._bot_root / device_id / username / ".stm"
        result = SourceUsageResult(
            account_username=username,
            device_id=device_id,
            sources_dir_found=sources_dir.is_dir(),
        )

        logger.info(
            f"[SourceUsage] {username}@{device_id[:12]}: "
            f"{len(source_names)} source(s) — "
            f"sources_dir={result.sources_dir_found}  "
            f"stm_dir={stm_dir.is_dir()}  "
            f"follows_map={'yes' if follows_map else 'no'}"
        )

        if not result.sources_dir_found:
            logger.warning(
                f"[SourceUsage] sources/ dir not found for {username}: {sources_dir}"
            )
            result.records = [
                SourceUsageRecord(source_name=n, db_found=False)
                for n in source_names
            ]
            result.db_count_missing = len(source_names)
            return result

        for name in source_names:
            key     = name.strip().lower()
            follows = (follows_map or {}).get(key, 0)
            rec     = self._read_one(sources_dir, stm_dir, name, follows)
            result.records.append(rec)
            if rec.has_data:
                result.db_count_found += 1
            else:
                result.db_count_missing += 1
            if rec.used_pct is not None:
                result.pct_count_derived += 1

        logger.info(
            f"[SourceUsage] {username}: "
            f"{result.db_count_found} DBs read, "
            f"{result.db_count_missing} missing/error, "
            f"{result.pct_count_derived} with used_pct"
        )
        return result

    def read_single(
        self,
        device_id: str,
        username: str,
        source_name: str,
        follow_count: int = 0,
    ) -> SourceUsageRecord:
        """
        Read USED count and derive USED % for one source for one account.
        Used by the global Sources detail pane (per-row lookup).

        follow_count — from SourceAccountDetail.follow_count (data.db follows).
        """
        sources_dir = self._bot_root / device_id / username / "sources"
        stm_dir     = self._bot_root / device_id / username / ".stm"
        if not sources_dir.is_dir():
            logger.debug(
                f"[SourceUsage] sources/ missing for {username}@{device_id[:12]}"
            )
            return SourceUsageRecord(source_name=source_name, db_found=False)
        return self._read_one(sources_dir, stm_dir, source_name, follow_count)

    # ------------------------------------------------------------------
    # Internal — read one source
    # ------------------------------------------------------------------

    def _read_one(
        self,
        sources_dir: Path,
        stm_dir: Path,
        source_name: str,
        follows: int,
    ) -> SourceUsageRecord:
        """Read used_count from source DB and derive used_pct from .stm file."""
        rec = self._read_used_count(sources_dir, source_name)
        self._enrich_with_pct(rec, stm_dir, follows)
        return rec

    # ------------------------------------------------------------------
    # Internal — USED count (source DB)
    # ------------------------------------------------------------------

    def _read_used_count(
        self, sources_dir: Path, source_name: str
    ) -> SourceUsageRecord:
        """Locate source DB and COUNT(*) from source_followers."""
        db_path: Optional[Path] = None
        for candidate in (source_name, source_name.strip().lower()):
            p = sources_dir / f"{candidate}.db"
            if p.exists():
                db_path = p
                break

        if db_path is None:
            logger.debug(f"[SourceUsage] no DB file for source {source_name!r}")
            return SourceUsageRecord(source_name=source_name, db_found=False)

        try:
            conn = sqlite3.connect(
                f"file:{db_path}?mode=ro", uri=True, timeout=5
            )
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM source_followers"
                ).fetchone()
                used_count = row[0] if row else 0
                logger.debug(
                    f"[SourceUsage] {source_name}: used_count={used_count}"
                )
                return SourceUsageRecord(
                    source_name=source_name,
                    used_count=used_count,
                    db_found=True,
                )
            except sqlite3.OperationalError as e:
                logger.warning(
                    f"[SourceUsage] schema error in {db_path.name}: {e}"
                )
                return SourceUsageRecord(
                    source_name=source_name,
                    db_found=True,
                    db_error=f"schema: {e}",
                )
            finally:
                conn.close()
        except Exception as e:
            logger.warning(
                f"[SourceUsage] failed to open {db_path.name}: {e}"
            )
            return SourceUsageRecord(
                source_name=source_name,
                db_found=True,
                db_error=str(e),
            )

    # ------------------------------------------------------------------
    # Internal — USED % (from .stm percent file + follows)
    # ------------------------------------------------------------------

    def _enrich_with_pct(
        self,
        rec: SourceUsageRecord,
        stm_dir: Path,
        follows: int,
    ) -> None:
        """
        Try to derive used_pct from the .stm percent file and follows count.
        Mutates `rec` in-place: sets pct_file_found, pct_file_error,
        total_followers_derived, and used_pct.
        """
        if not rec.has_data:
            return  # no used_count → nothing to compute

        # --- Read the percent file ---
        found, followed_pct, parse_error = self._read_pct_file(
            stm_dir, rec.source_name
        )
        rec.pct_file_found = found

        if not found:
            logger.debug(
                f"[UsedPct] {rec.source_name}: percent file not found in .stm/"
            )
            return

        if parse_error is not None:
            rec.pct_file_error = parse_error
            logger.warning(
                f"[UsedPct] {rec.source_name}: percent file parse error: {parse_error}"
            )
            return

        # --- Validate inputs ---
        if follows <= 0:
            logger.debug(
                f"[UsedPct] {rec.source_name}: follows={follows} — "
                f"cannot derive total (follows must be > 0)"
            )
            return

        # followed_pct validated in _read_pct_file (> 0, <= 100)

        # --- Derive total followers ---
        total = follows / (followed_pct / 100.0)
        total_rounded = round(total)

        # Sanity: total should be >= follows (can't follow more than total).
        # Mathematically guaranteed when percent <= 100 (validated above),
        # but check defensively for float edge cases.
        if total < follows * 0.95:
            logger.warning(
                f"[UsedPct] {rec.source_name}: derived total={total:.0f} < "
                f"follows={follows} (followed_pct={followed_pct}) — "
                f"inconsistent, skipping used_pct"
            )
            return

        # --- Compute used_pct ---
        # Formula: used_count * followed_pct / follows
        #   equivalent to: used_count / total * 100
        used_pct = rec.used_count * followed_pct / follows

        # Cap at 100% — source_followers may accumulate duplicates across
        # scrape sessions, making used_count > total plausible.
        if used_pct > 100.0:
            logger.debug(
                f"[UsedPct] {rec.source_name}: raw used_pct={used_pct:.1f}% > 100 "
                f"(used={rec.used_count}, total≈{total:.0f}) — capping at 100"
            )
            used_pct = 100.0

        # Commit results only after all validation passed
        rec.total_followers_derived = total_rounded
        rec.used_pct = round(used_pct, 2)

        logger.debug(
            f"[UsedPct] {rec.source_name}: follows={follows}  "
            f"followed_pct={followed_pct}  total≈{total_rounded}  "
            f"used={rec.used_count}  used_pct={rec.used_pct}%"
        )

    def _read_pct_file(
        self, stm_dir: Path, source_name: str
    ) -> tuple[bool, float, Optional[str]]:
        """
        Read {source_name}-total-followed-percent.txt from stm_dir.

        Returns (found, value, error):
          found — True if the file exists on disk
          value — parsed float, 0.0 if not parseable
          error — human-readable error string, or None on success
        """
        if not stm_dir.is_dir():
            return False, 0.0, None

        # Try exact name, then lowercase (bot may use either)
        for candidate in (source_name, source_name.strip().lower()):
            p = stm_dir / f"{candidate}-total-followed-percent.txt"
            if p.exists():
                try:
                    text = p.read_text(encoding="utf-8").strip()
                    if not text:
                        return True, 0.0, "empty file"
                    val = float(text)
                    if val <= 0:
                        return True, 0.0, f"non-positive value: {val}"
                    if val > 100:
                        return True, 0.0, f"value > 100: {val}"
                    return True, val, None
                except ValueError:
                    return True, 0.0, f"not a number: {text!r}"
                except OSError as e:
                    return True, 0.0, f"read error: {e}"

        return False, 0.0, None
