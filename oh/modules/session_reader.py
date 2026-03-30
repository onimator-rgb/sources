"""
SessionReader — reads per-account session data from Onimator bot files.

Data sources (all read-only):
  {account}/data.db         → follow_count, unfollow_count per date
  {account}/likes.db        → like_count per date
  {account}/sent_message.db → dm_count per date
  {account}/settings.db     → raw tags, follow/like limits

Tag format in settings.db → accountsettings.settings JSON → "tags" field:
  "[4] SLAVE"        → limits 4, role SLAVE
  "[1] START PK"     → limits 1, status START, status PK
  "[2] TB3 SLAVE AI" → limits 2, TB TB3 (level 3), role SLAVE, role AI

Error handling follows the same pattern as source_usage_reader.py:
  - Missing file / missing table / bad schema → log warning, return defaults
  - Never raise to caller for expected data gaps
"""
import contextlib
import json
import logging
import re
import sqlite3
from pathlib import Path
from typing import Optional

from oh.models.session import (
    AccountSessionRecord,
    AccountTag,
    TAG_SOURCE_BOT,
    TAG_CAT_LIMITS,
    TAG_CAT_TB,
    TAG_CAT_ROLE,
    TAG_CAT_STATUS,
    TAG_CAT_CUSTOM,
    slot_for_times,
)

logger = logging.getLogger(__name__)

# Placeholder date used by Onimator for "never unfollowed"
_UNFOLLOW_PLACEHOLDER = "2000-02-22"

# Known role tokens — everything else goes to status or custom
_ROLE_TOKENS = frozenset({"SLAVE", "AI"})
_STATUS_TOKENS = frozenset({"START", "PK"})

# Pattern: TB followed by a digit (TB1 .. TB9)
_TB_PATTERN = re.compile(r"^TB(\d)$", re.IGNORECASE)

# Pattern: [N] prefix in the raw tags string
_LEVEL_PREFIX = re.compile(r"^\[(\d+)\]\s*")


class SessionReader:
    """
    Reads session counters and tag metadata from Onimator's per-account
    files.  All SQLite connections are read-only.
    """

    def __init__(self, bot_root: str) -> None:
        self._bot_root = Path(bot_root)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_session(
        self,
        account_path: Path,
        account_id: int,
        device_id: str,
        username: str,
        snapshot_date: str,
        start_time: Optional[str],
        end_time: Optional[str],
    ) -> AccountSessionRecord:
        """
        Collect daily counters for one account on a given date.
        Returns a record with sensible defaults for any missing data.
        """
        follow_count = self._count_follows(account_path, snapshot_date)
        unfollow_count = self._count_unfollows(account_path, snapshot_date)
        like_count = self._count_likes(account_path, snapshot_date)
        dm_count = self._count_dms(account_path, snapshot_date)
        follow_limit, like_limit = self.read_account_limits(account_path)

        slot = slot_for_times(start_time, end_time)
        has_activity = (follow_count + like_count + dm_count) > 0

        logger.info(
            f"[Session] {username}@{device_id[:12]}: "
            f"follow={follow_count} like={like_count} dm={dm_count} "
            f"unfollow={unfollow_count} slot={slot} active={has_activity}"
        )

        return AccountSessionRecord(
            account_id=account_id,
            device_id=device_id,
            username=username,
            snapshot_date=snapshot_date,
            slot=slot,
            follow_count=follow_count,
            like_count=like_count,
            dm_count=dm_count,
            unfollow_count=unfollow_count,
            follow_limit=follow_limit,
            like_limit=like_limit,
            has_activity=has_activity,
        )

    def read_tags(
        self, account_path: Path, account_id: int
    ) -> tuple:
        """
        Read and parse tags from settings.db.

        Returns (raw_tags, parsed_tags):
          raw_tags    — the raw string from settings.db, e.g. "[4] SLAVE AI"
          parsed_tags — list[AccountTag] with category/level breakdown
        """
        settings = self._read_settings_json(account_path)
        if settings is None:
            return None, []

        raw_tags = settings.get("tags")
        if not raw_tags or not isinstance(raw_tags, str):
            return None, []

        raw_tags = raw_tags.strip()
        if not raw_tags:
            return None, []

        parsed = self._parse_tags(raw_tags, account_id)
        return raw_tags, parsed

    def read_account_limits(
        self, account_path: Path
    ) -> tuple:
        """
        Read follow and like limits from settings.db.

        Returns (follow_limit, like_limit) as Optional[int].
        Source: settings.db → accountsettings.settings JSON →
          default_action_limit_perday, like_limit_perday.

        Rationale for settings.db over .stm files:
          .stm/follow-action-limit-per-day-{date}.txt reflects the
          *effective* limit after auto-increment, which changes mid-day.
          settings.db/default_action_limit_perday is the configured base
          limit — a stable reference point for operator review.
        """
        settings = self._read_settings_json(account_path)
        if settings is None:
            return None, None

        follow_limit = self._safe_int(
            settings.get("default_action_limit_perday")
        )
        like_limit = self._safe_int(
            settings.get("like_limit_perday")
        )
        return follow_limit, like_limit

    # ------------------------------------------------------------------
    # Internal — action counters
    # ------------------------------------------------------------------

    def _count_follows(self, account_path: Path, date: str) -> int:
        """COUNT(*) from data.db WHERE followeddate = date."""
        db_path = account_path / "data.db"
        return self._count_from_db(
            db_path, "sources", "followeddate", date, "follow"
        )

    def _count_unfollows(self, account_path: Path, date: str) -> int:
        """COUNT(*) from data.db WHERE unfolloweddate = date.
        Excludes the placeholder '2000-02-22' which means 'never unfollowed'."""
        db_path = account_path / "data.db"
        if date == _UNFOLLOW_PLACEHOLDER:
            return 0
        return self._count_from_db(
            db_path, "sources", "unfolloweddate", date, "unfollow"
        )

    def _count_likes(self, account_path: Path, date: str) -> int:
        """SUM(liked) from likes.db WHERE date = date.
        The 'liked' column is an integer count of posts liked per user."""
        db_path = account_path / "likes.db"
        if not db_path.exists():
            return 0
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
                row = conn.execute(
                    "SELECT COALESCE(SUM(liked), 0) FROM likes WHERE date = ?",
                    (date,),
                ).fetchone()
                return row[0] if row else 0
        except sqlite3.OperationalError as e:
            logger.warning(f"[Session] likes.db read error for {account_path.name}: {e}")
            return 0

    def _count_dms(self, account_path: Path, date: str) -> int:
        """COUNT(*) from sent_message.db WHERE date = date.
        sent_message.db is the authoritative log of actually sent DMs.
        directmessage.db tracks template/queue state, not delivery."""
        db_path = account_path / "sent_message.db"
        return self._count_from_db(
            db_path, "sent_message", "date", date, "dm"
        )

    def _count_from_db(
        self,
        db_path: Path,
        table: str,
        date_column: str,
        date_value: str,
        label: str,
    ) -> int:
        """Generic: COUNT(*) from table WHERE date_column = date_value."""
        if not db_path.exists():
            return 0
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
                row = conn.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE {date_column} = ?",
                    (date_value,),
                ).fetchone()
                return row[0] if row else 0
        except sqlite3.OperationalError as e:
            logger.warning(
                f"[Session] {label} count error in {db_path.name} "
                f"for {db_path.parent.name}: {e}"
            )
            return 0

    # ------------------------------------------------------------------
    # Internal — settings.db reader
    # ------------------------------------------------------------------

    def _read_settings_json(self, account_path: Path) -> Optional[dict]:
        """Read and parse the JSON blob from settings.db → accountsettings."""
        db_path = account_path / "settings.db"
        if not db_path.exists():
            return None
        try:
            uri = f"file:{db_path.as_posix()}?mode=ro"
            with contextlib.closing(sqlite3.connect(uri, uri=True, timeout=5)) as conn:
                row = conn.execute(
                    "SELECT settings FROM accountsettings LIMIT 1"
                ).fetchone()
            if not row or not row[0]:
                return None
            return json.loads(row[0])
        except (sqlite3.OperationalError, json.JSONDecodeError) as e:
            logger.warning(
                f"[Session] settings.db read error for {account_path.name}: {e}"
            )
            return None

    # ------------------------------------------------------------------
    # Internal — tag parser
    # ------------------------------------------------------------------

    def _parse_tags(self, raw: str, account_id: int) -> list:
        """
        Parse a raw tag string into a list of AccountTag objects.

        Format: "[N] TOKEN TOKEN ..."
          [N]     → limits tag with level N
          TB1-TB9 → TB tag with level extracted from digit
          SLAVE   → role tag
          AI      → role tag
          START   → status tag
          PK      → status tag
          other   → custom tag
        """
        tags = []

        # Extract [N] prefix
        m = _LEVEL_PREFIX.match(raw)
        if m:
            level = int(m.group(1))
            tags.append(AccountTag(
                account_id=account_id,
                tag_source=TAG_SOURCE_BOT,
                tag_category=TAG_CAT_LIMITS,
                tag_value=f"limits {level}",
                tag_level=level,
            ))
            remainder = raw[m.end():]
        else:
            remainder = raw

        # Split remaining tokens
        for token in remainder.split():
            token_upper = token.upper().strip()
            if not token_upper:
                continue

            tb_match = _TB_PATTERN.match(token_upper)
            if tb_match:
                tb_level = int(tb_match.group(1))
                tags.append(AccountTag(
                    account_id=account_id,
                    tag_source=TAG_SOURCE_BOT,
                    tag_category=TAG_CAT_TB,
                    tag_value=f"TB{tb_level}",
                    tag_level=tb_level,
                ))
            elif token_upper in _ROLE_TOKENS:
                tags.append(AccountTag(
                    account_id=account_id,
                    tag_source=TAG_SOURCE_BOT,
                    tag_category=TAG_CAT_ROLE,
                    tag_value=token_upper,
                ))
            elif token_upper in _STATUS_TOKENS:
                tags.append(AccountTag(
                    account_id=account_id,
                    tag_source=TAG_SOURCE_BOT,
                    tag_category=TAG_CAT_STATUS,
                    tag_value=token_upper,
                ))
            else:
                tags.append(AccountTag(
                    account_id=account_id,
                    tag_source=TAG_SOURCE_BOT,
                    tag_category=TAG_CAT_CUSTOM,
                    tag_value=token_upper,
                ))

        return tags

    # ------------------------------------------------------------------
    # Internal — helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_int(value) -> Optional[int]:
        """Convert a value to int, returning None on failure."""
        if value is None:
            return None
        try:
            return int(value)
        except (ValueError, TypeError):
            return None
