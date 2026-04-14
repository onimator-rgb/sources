"""CRUD for warmup_templates table."""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Optional

from oh.models.warmup_template import WarmupTemplate

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class WarmupTemplateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, template: WarmupTemplate) -> WarmupTemplate:
        now = _utcnow()
        cursor = self._conn.execute(
            """INSERT INTO warmup_templates
               (name, description, follow_start, follow_increment, follow_cap,
                like_start, like_increment, like_cap, auto_increment,
                enable_follow, enable_like, is_default, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (template.name, template.description,
             template.follow_start, template.follow_increment, template.follow_cap,
             template.like_start, template.like_increment, template.like_cap,
             int(template.auto_increment), int(template.enable_follow),
             int(template.enable_like), int(template.is_default), now, now),
        )
        self._conn.commit()
        template.id = cursor.lastrowid
        template.created_at = now
        template.updated_at = now
        return template

    def update(self, template: WarmupTemplate) -> None:
        self._conn.execute(
            """UPDATE warmup_templates SET
               name=?, description=?, follow_start=?, follow_increment=?,
               follow_cap=?, like_start=?, like_increment=?, like_cap=?,
               auto_increment=?, enable_follow=?, enable_like=?,
               is_default=?, updated_at=?
               WHERE id=?""",
            (template.name, template.description,
             template.follow_start, template.follow_increment, template.follow_cap,
             template.like_start, template.like_increment, template.like_cap,
             int(template.auto_increment), int(template.enable_follow),
             int(template.enable_like), int(template.is_default),
             _utcnow(), template.id),
        )
        self._conn.commit()

    def delete(self, template_id: int) -> None:
        self._conn.execute(
            "DELETE FROM warmup_templates WHERE id=?", (template_id,)
        )
        self._conn.commit()

    def get_all(self) -> List[WarmupTemplate]:
        rows = self._conn.execute(
            "SELECT * FROM warmup_templates ORDER BY name"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_by_id(self, template_id: int) -> Optional[WarmupTemplate]:
        row = self._conn.execute(
            "SELECT * FROM warmup_templates WHERE id=?", (template_id,)
        ).fetchone()
        return self._from_row(row) if row else None

    def get_by_name(self, name: str) -> Optional[WarmupTemplate]:
        row = self._conn.execute(
            "SELECT * FROM warmup_templates WHERE name=?", (name,)
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> WarmupTemplate:
        return WarmupTemplate(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            follow_start=row["follow_start"],
            follow_increment=row["follow_increment"],
            follow_cap=row["follow_cap"],
            like_start=row["like_start"],
            like_increment=row["like_increment"],
            like_cap=row["like_cap"],
            auto_increment=bool(row["auto_increment"]),
            enable_follow=bool(row["enable_follow"]),
            enable_like=bool(row["enable_like"]),
            is_default=bool(row["is_default"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
