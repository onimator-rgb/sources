"""CRUD for campaign_templates table."""
import sqlite3
import logging
from datetime import datetime, timezone
from typing import List, Optional

from oh.models.campaign_template import CampaignTemplate

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class CampaignTemplateRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def create(self, template: CampaignTemplate) -> CampaignTemplate:
        now = _utcnow()
        cursor = self._conn.execute(
            """INSERT INTO campaign_templates
               (name, description, niche, language, min_sources, source_niche,
                follow_limit, like_limit, tb_level, limits_level, settings_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (template.name, template.description, template.niche, template.language,
             template.min_sources, template.source_niche, template.follow_limit,
             template.like_limit, template.tb_level, template.limits_level,
             template.settings_json, now, now),
        )
        self._conn.commit()
        template.id = cursor.lastrowid
        template.created_at = now
        template.updated_at = now
        return template

    def update(self, template: CampaignTemplate) -> None:
        self._conn.execute(
            """UPDATE campaign_templates SET
               name=?, description=?, niche=?, language=?, min_sources=?,
               source_niche=?, follow_limit=?, like_limit=?, tb_level=?,
               limits_level=?, settings_json=?, updated_at=?
               WHERE id=?""",
            (template.name, template.description, template.niche, template.language,
             template.min_sources, template.source_niche, template.follow_limit,
             template.like_limit, template.tb_level, template.limits_level,
             template.settings_json, _utcnow(), template.id),
        )
        self._conn.commit()

    def delete(self, template_id: int) -> None:
        self._conn.execute("DELETE FROM campaign_templates WHERE id=?", (template_id,))
        self._conn.commit()

    def get_all(self) -> List[CampaignTemplate]:
        rows = self._conn.execute(
            "SELECT * FROM campaign_templates ORDER BY name"
        ).fetchall()
        return [self._from_row(r) for r in rows]

    def get_by_id(self, template_id: int) -> Optional[CampaignTemplate]:
        row = self._conn.execute(
            "SELECT * FROM campaign_templates WHERE id=?", (template_id,)
        ).fetchone()
        return self._from_row(row) if row else None

    def get_by_name(self, name: str) -> Optional[CampaignTemplate]:
        row = self._conn.execute(
            "SELECT * FROM campaign_templates WHERE name=?", (name,)
        ).fetchone()
        return self._from_row(row) if row else None

    @staticmethod
    def _from_row(row: sqlite3.Row) -> CampaignTemplate:
        return CampaignTemplate(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            niche=row["niche"],
            language=row["language"],
            min_sources=row["min_sources"],
            source_niche=row["source_niche"],
            follow_limit=row["follow_limit"],
            like_limit=row["like_limit"],
            tb_level=row["tb_level"],
            limits_level=row["limits_level"],
            settings_json=row["settings_json"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
