"""
LikeSourceUsageReader — reads per-account like source consumption data.

USED count:
  From: {bot_root}/{device_id}/{username}/like_sources/{source_name}.db
  Table: like_source_followers(id, username, date_checked)
  Value: COUNT(*) from like_source_followers

Error handling:
  - like_sources/ dir missing           → all records have db_found=False
  - source .db file missing             → record has db_found=False
  - like_source_followers table missing → record has db_error set
  In all cases the record is returned so the UI can show a row.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from oh.models.source_usage import SourceUsageRecord, SourceUsageResult

logger = logging.getLogger(__name__)


class LikeSourceUsageReader:
    def __init__(self, bot_root: str) -> None:
        self._bot_root = Path(bot_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_usage(
        self,
        device_id: str,
        username: str,
        source_name: str,
    ) -> SourceUsageRecord:
        """
        Read USED count for one like source for one account.

        Opens like_sources/{source_name}.db and counts rows in
        like_source_followers.
        """
        like_sources_dir = self._bot_root / device_id / username / "like_sources"
        if not like_sources_dir.is_dir():
            logger.debug(
                f"[LikeSourceUsage] like_sources/ missing for "
                f"{username}@{device_id[:12]}"
            )
            return SourceUsageRecord(source_name=source_name, db_found=False)
        return self._read_used_count(like_sources_dir, source_name)

    def read_all_usage(
        self,
        device_id: str,
        username: str,
        source_names: list[str],
    ) -> SourceUsageResult:
        """
        Read USED count for each like source for one account.

        source_names — raw source names (may be mixed-case).
        """
        like_sources_dir = self._bot_root / device_id / username / "like_sources"
        result = SourceUsageResult(
            account_username=username,
            device_id=device_id,
            sources_dir_found=like_sources_dir.is_dir(),
        )

        logger.info(
            f"[LikeSourceUsage] {username}@{device_id[:12]}: "
            f"{len(source_names)} source(s) — "
            f"like_sources_dir={result.sources_dir_found}"
        )

        if not result.sources_dir_found:
            logger.warning(
                f"[LikeSourceUsage] like_sources/ dir not found for "
                f"{username}: {like_sources_dir}"
            )
            result.records = [
                SourceUsageRecord(source_name=n, db_found=False)
                for n in source_names
            ]
            result.db_count_missing = len(source_names)
            return result

        for name in source_names:
            rec = self._read_used_count(like_sources_dir, name)
            result.records.append(rec)
            if rec.has_data:
                result.db_count_found += 1
            else:
                result.db_count_missing += 1

        logger.info(
            f"[LikeSourceUsage] {username}: "
            f"{result.db_count_found} DBs read, "
            f"{result.db_count_missing} missing/error"
        )
        return result

    # ------------------------------------------------------------------
    # Internal — USED count (like source DB)
    # ------------------------------------------------------------------

    def _read_used_count(
        self, like_sources_dir: Path, source_name: str
    ) -> SourceUsageRecord:
        """Locate like source DB and COUNT(*) from like_source_followers."""
        db_path: Optional[Path] = None
        for candidate in (source_name, source_name.strip().lower()):
            p = like_sources_dir / f"{candidate}.db"
            if p.exists():
                db_path = p
                break

        if db_path is None:
            logger.debug(
                f"[LikeSourceUsage] no DB file for like source {source_name!r}"
            )
            return SourceUsageRecord(source_name=source_name, db_found=False)

        try:
            conn = sqlite3.connect(
                f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=5
            )
            try:
                row = conn.execute(
                    "SELECT COUNT(*) FROM like_source_followers"
                ).fetchone()
                used_count = row[0] if row else 0
                logger.debug(
                    f"[LikeSourceUsage] {source_name}: used_count={used_count}"
                )
                return SourceUsageRecord(
                    source_name=source_name,
                    used_count=used_count,
                    db_found=True,
                )
            except sqlite3.OperationalError as e:
                logger.warning(
                    f"[LikeSourceUsage] schema error in {db_path.name}: {e}"
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
                f"[LikeSourceUsage] failed to open {db_path.name}: {e}"
            )
            return SourceUsageRecord(
                source_name=source_name,
                db_found=True,
                db_error=str(e),
            )
