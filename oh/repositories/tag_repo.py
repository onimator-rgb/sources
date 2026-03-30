"""
Read/write access to the account_tags table.

Tags come from two sources:
  tag_source = 'bot'      — parsed from the bot's settings.db during scan;
                             replaced wholesale on each scan via upsert_bot_tags().
  tag_source = 'operator' — set manually by the operator in OH;
                             never touched by automated scans.

UNIQUE(account_id, tag_source, tag_category) means one tag per category
per source per account.  Bot tags and operator tags live side by side.
"""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import Optional

from oh.models.session import (
    AccountTag,
    TAG_SOURCE_BOT,
    TAG_SOURCE_OPERATOR,
)

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class TagRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Writes — bot tags
    # ------------------------------------------------------------------

    def upsert_bot_tags(
        self, account_id: int, tags: list[AccountTag]
    ) -> None:
        """
        Replace all bot-sourced tags for an account with the given list.
        Operator tags are never touched.
        """
        self._conn.execute(
            "DELETE FROM account_tags WHERE account_id = ? AND tag_source = ?",
            (account_id, TAG_SOURCE_BOT),
        )

        if tags:
            now = _utcnow()
            self._conn.executemany(
                """
                INSERT INTO account_tags
                    (account_id, tag_source, tag_category, tag_value,
                     tag_level, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        account_id,
                        TAG_SOURCE_BOT,
                        tag.tag_category,
                        tag.tag_value,
                        tag.tag_level,
                        now,
                    )
                    for tag in tags
                ],
            )

        self._conn.commit()

    # ------------------------------------------------------------------
    # Writes — operator tags
    # ------------------------------------------------------------------

    def set_operator_tag(
        self,
        account_id: int,
        category: str,
        value: str,
        level: Optional[int] = None,
    ) -> None:
        """Insert or update a single operator tag for an account."""
        now = _utcnow()
        self._conn.execute(
            """
            INSERT INTO account_tags
                (account_id, tag_source, tag_category, tag_value,
                 tag_level, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, tag_source, tag_value) DO UPDATE SET
                tag_category = excluded.tag_category,
                tag_level    = excluded.tag_level,
                updated_at   = excluded.updated_at
            """,
            (account_id, TAG_SOURCE_OPERATOR, category, value, level, now),
        )
        self._conn.commit()

    def remove_operator_tag(
        self, account_id: int, category: str, value: Optional[str] = None
    ) -> None:
        """
        Remove operator tag(s).  If value is given, removes that specific tag.
        If value is None, removes all operator tags in the category.
        """
        if value is not None:
            self._conn.execute(
                """
                DELETE FROM account_tags
                WHERE account_id = ? AND tag_source = ? AND tag_value = ?
                """,
                (account_id, TAG_SOURCE_OPERATOR, value),
            )
        else:
            self._conn.execute(
                """
                DELETE FROM account_tags
                WHERE account_id = ? AND tag_source = ? AND tag_category = ?
                """,
                (account_id, TAG_SOURCE_OPERATOR, category),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------

    def get_tags_for_account(self, account_id: int) -> list[AccountTag]:
        """Return all tags (bot + operator) for one account."""
        rows = self._conn.execute(
            """
            SELECT * FROM account_tags
            WHERE account_id = ?
            ORDER BY tag_source, tag_category
            """,
            (account_id,),
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_accounts_with_tag(
        self, category: str, value: Optional[str] = None
    ) -> list[int]:
        """
        Return account_ids that have a tag matching the given category
        (and optionally value).  Both bot and operator tags are searched.
        """
        if value is not None:
            rows = self._conn.execute(
                """
                SELECT DISTINCT account_id FROM account_tags
                WHERE tag_category = ? AND tag_value = ?
                """,
                (category, value),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                SELECT DISTINCT account_id FROM account_tags
                WHERE tag_category = ?
                """,
                (category,),
            ).fetchall()
        return [r["account_id"] for r in rows]

    def get_operator_tags_map(self) -> dict:
        """
        Return {account_id: 'TB3 | limits 2 | ...'} for all accounts with
        at least one operator tag.  One query, O(1) lookup per account.
        """
        rows = self._conn.execute(
            """
            SELECT account_id, GROUP_CONCAT(tag_value, ' | ') AS op_tags
            FROM account_tags
            WHERE tag_source = ?
            GROUP BY account_id
            """,
            (TAG_SOURCE_OPERATOR,),
        ).fetchall()
        return {r["account_id"]: r["op_tags"] for r in rows}

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _from_row(row: sqlite3.Row) -> AccountTag:
        return AccountTag(
            id=row["id"],
            account_id=row["account_id"],
            tag_source=row["tag_source"],
            tag_category=row["tag_category"],
            tag_value=row["tag_value"],
            tag_level=row["tag_level"],
            updated_at=row["updated_at"],
        )
