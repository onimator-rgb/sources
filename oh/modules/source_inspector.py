"""
SourceInspector — reads sources.txt and data.db for a single account
and returns a SourceInspectionResult.

All file and database access is READ-ONLY.
Nothing is written to the Onimator folder.

Error strategy:
  - Missing files are not errors; they set the *_found flags to False.
  - Unreadable files add a warning but don't abort — the other file
    can still produce a partial result.
  - SQLite errors are caught per-connection and added as warnings.
"""
import contextlib
import sqlite3
import logging
from pathlib import Path

from oh.models.source import SourceRecord, SourceInspectionResult

logger = logging.getLogger(__name__)

# Source values that the bot sometimes writes as placeholders — ignore them.
_INVALID_SOURCE_VALUES = frozenset({"", "none", "null"})


class SourceInspector:
    """
    Inspects the source files for a single Onimator account.

    Usage:
        inspector = SourceInspector(bot_root)
        result = inspector.inspect(device_id, username)
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    def inspect(self, device_id: str, username: str) -> SourceInspectionResult:
        """
        Read sources.txt and data.db for the given account, merge, classify,
        and return a SourceInspectionResult.

        Names are merged case-insensitively so that a source whose name differs
        only in casing between sources.txt and data.db is treated as one source,
        not two duplicate rows.  When a source is active, the sources.txt spelling
        is used as the display name; otherwise the data.db spelling is used.
        """
        account_folder = self._root / device_id / username
        result = SourceInspectionResult(device_id=device_id, username=username)

        active_sources     = self._read_sources_txt(account_folder / "sources.txt", result)
        historical_sources = self._read_data_db(account_folder / "data.db", result)

        # Build lowercase-key → original-name maps for case-insensitive union.
        # When both files contain the same name in different cases, prefer the
        # sources.txt spelling (it is what the operator sees and edits).
        active_lower     = {n.lower(): n for n in active_sources}
        historical_lower = {n.lower(): n for n in historical_sources}
        all_lower_keys   = set(active_lower) | set(historical_lower)

        result.sources = sorted(
            [
                SourceRecord(
                    source_name=active_lower.get(key) or historical_lower[key],
                    is_active=(key in active_lower),
                    is_historical=(key in historical_lower),
                )
                for key in all_lower_keys
            ],
            key=lambda s: (not s.is_active, s.source_name.lower()),
        )

        logger.debug(
            f"SourceInspector: {username}@{device_id[:8]}… — "
            f"{len(active_sources)} active, {len(historical_sources)} historical, "
            f"{len(all_lower_keys)} unique (after case-insensitive merge)"
        )
        return result

    # ------------------------------------------------------------------
    # Private readers
    # ------------------------------------------------------------------

    def _read_sources_txt(
        self, path: Path, result: SourceInspectionResult
    ) -> set[str]:
        """
        Returns the set of valid source names from sources.txt.
        Each line is one source name.  Blank lines and known placeholder
        values are silently skipped.
        """
        if not path.exists():
            logger.debug(f"sources.txt not found: {path}")
            return set()

        result.sources_txt_found = True

        try:
            raw = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            result.warnings.append(f"Cannot read sources.txt: {e}")
            logger.warning(f"Cannot read {path}: {e}")
            return set()

        sources: set[str] = set()
        for line in raw.splitlines():
            name = line.strip()
            if name.lower() in _INVALID_SOURCE_VALUES:
                continue
            sources.add(name)

        return sources

    def _read_data_db(
        self, path: Path, result: SourceInspectionResult
    ) -> set[str]:
        """
        Returns the set of distinct source names that have any row in
        data.db's sources table.
        """
        if not path.exists():
            logger.debug(f"data.db not found: {path}")
            return set()

        result.data_db_found = True

        try:
            uri = f"file:{path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT DISTINCT source
                    FROM sources
                    WHERE source IS NOT NULL
                      AND LOWER(TRIM(source)) NOT IN ('none', 'null', '')
                    """
                ).fetchall()
        except sqlite3.OperationalError as e:
            result.warnings.append(f"Cannot read data.db: {e}")
            logger.warning(f"Cannot read {path}: {e}")
            return set()

        sources: set[str] = set()
        for row in rows:
            name = row["source"].strip()
            if name and name.lower() not in _INVALID_SOURCE_VALUES:
                sources.add(name)

        return sources
