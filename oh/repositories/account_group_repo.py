"""
Read/write access to account_groups and account_group_members tables.

Groups organise accounts by client, campaign, or any operator-defined
category.  Membership is many-to-many.
"""
import sqlite3
import logging
from collections import defaultdict
from typing import Dict, List, Optional

from oh.models.account_group import AccountGroup, GroupMembership
from oh.utils import utcnow

logger = logging.getLogger(__name__)


class AccountGroupRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ------------------------------------------------------------------
    # Group CRUD
    # ------------------------------------------------------------------

    def create_group(
        self,
        name: str,
        color: str = "#5B8DEF",
        description: Optional[str] = None,
    ) -> AccountGroup:
        """Create a new group. Returns the group with id set."""
        now = utcnow()
        cursor = self._conn.execute(
            """
            INSERT INTO account_groups (name, color, description, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (name, color, description, now, now),
        )
        self._conn.commit()
        return AccountGroup(
            id=cursor.lastrowid,
            name=name,
            color=color,
            description=description,
            created_at=now,
            updated_at=now,
        )

    def update_group(
        self,
        group_id: int,
        name: str,
        color: str,
        description: Optional[str] = None,
    ) -> None:
        """Update group properties."""
        self._conn.execute(
            """
            UPDATE account_groups
            SET name = ?, color = ?, description = ?, updated_at = ?
            WHERE id = ?
            """,
            (name, color, description, utcnow(), group_id),
        )
        self._conn.commit()

    def delete_group(self, group_id: int) -> None:
        """Delete a group (CASCADE deletes members)."""
        self._conn.execute(
            "DELETE FROM account_groups WHERE id = ?", (group_id,)
        )
        self._conn.commit()

    def get_all_groups(self) -> List[AccountGroup]:
        """Return all groups with member_count."""
        rows = self._conn.execute(
            """
            SELECT g.*,
                   (SELECT COUNT(*) FROM account_group_members
                    WHERE group_id = g.id) AS member_count
            FROM account_groups g
            ORDER BY g.name
            """
        ).fetchall()
        return [self._group_from_row(r) for r in rows]

    def get_group(self, group_id: int) -> Optional[AccountGroup]:
        """Return one group by id, or None."""
        row = self._conn.execute(
            """
            SELECT g.*,
                   (SELECT COUNT(*) FROM account_group_members
                    WHERE group_id = g.id) AS member_count
            FROM account_groups g
            WHERE g.id = ?
            """,
            (group_id,),
        ).fetchone()
        return self._group_from_row(row) if row else None

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    def add_members(self, group_id: int, account_ids: List[int]) -> int:
        """Add accounts to a group. Returns count added (skips duplicates)."""
        now = utcnow()
        added = 0
        for aid in account_ids:
            try:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO account_group_members
                        (group_id, account_id, added_at)
                    VALUES (?, ?, ?)
                    """,
                    (group_id, aid, now),
                )
                added += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return added

    def remove_members(self, group_id: int, account_ids: List[int]) -> int:
        """Remove accounts from a group. Returns count removed."""
        removed = 0
        for aid in account_ids:
            cursor = self._conn.execute(
                """
                DELETE FROM account_group_members
                WHERE group_id = ? AND account_id = ?
                """,
                (group_id, aid),
            )
            removed += cursor.rowcount
        self._conn.commit()
        return removed

    def get_members(self, group_id: int) -> List[int]:
        """Return account IDs in a group."""
        rows = self._conn.execute(
            "SELECT account_id FROM account_group_members WHERE group_id = ?",
            (group_id,),
        ).fetchall()
        return [r["account_id"] for r in rows]

    def get_groups_for_account(self, account_id: int) -> List[AccountGroup]:
        """Return all groups that contain the given account."""
        rows = self._conn.execute(
            """
            SELECT g.*, 0 AS member_count
            FROM account_groups g
            JOIN account_group_members m ON m.group_id = g.id
            WHERE m.account_id = ?
            ORDER BY g.name
            """,
            (account_id,),
        ).fetchall()
        return [self._group_from_row(r) for r in rows]

    def get_membership_map(self) -> Dict[int, List[AccountGroup]]:
        """Return {account_id: [AccountGroup]} for all memberships."""
        rows = self._conn.execute(
            """
            SELECT m.account_id, g.id, g.name, g.color, g.description,
                   g.created_at, g.updated_at
            FROM account_group_members m
            JOIN account_groups g ON g.id = m.group_id
            ORDER BY g.name
            """
        ).fetchall()
        result: Dict[int, List[AccountGroup]] = defaultdict(list)
        for r in rows:
            result[r["account_id"]].append(AccountGroup(
                id=r["id"],
                name=r["name"],
                color=r["color"],
                description=r["description"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            ))
        return dict(result)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _group_from_row(row: sqlite3.Row) -> AccountGroup:
        return AccountGroup(
            id=row["id"],
            name=row["name"],
            color=row["color"],
            description=row["description"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            member_count=row["member_count"] if "member_count" in row.keys() else 0,
        )
