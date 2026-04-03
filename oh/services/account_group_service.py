"""
AccountGroupService — manages account groups (campaigns / clients).

Wraps the repository with business logic for group summaries
and bulk membership operations.
"""
import logging
from typing import Dict, List, Optional

from oh.models.account import AccountRecord
from oh.models.account_group import AccountGroup, GroupSummary
from oh.models.session import AccountSessionRecord
from oh.repositories.account_group_repo import AccountGroupRepository

logger = logging.getLogger(__name__)


class AccountGroupService:
    def __init__(self, group_repo: AccountGroupRepository) -> None:
        self._groups = group_repo

    # ------------------------------------------------------------------
    # Group CRUD (delegates to repo)
    # ------------------------------------------------------------------

    def create_group(
        self,
        name: str,
        color: str = "#5B8DEF",
        description: Optional[str] = None,
    ) -> AccountGroup:
        return self._groups.create_group(name, color, description)

    def update_group(
        self,
        group_id: int,
        name: str,
        color: str,
        description: Optional[str] = None,
    ) -> None:
        self._groups.update_group(group_id, name, color, description)

    def delete_group(self, group_id: int) -> None:
        self._groups.delete_group(group_id)

    def get_all_groups(self) -> List[AccountGroup]:
        return self._groups.get_all_groups()

    def get_group(self, group_id: int) -> Optional[AccountGroup]:
        return self._groups.get_group(group_id)

    def get_members(self, group_id: int) -> List[int]:
        return self._groups.get_members(group_id)

    # ------------------------------------------------------------------
    # Membership
    # ------------------------------------------------------------------

    def assign_accounts(self, group_id: int, account_ids: List[int]) -> int:
        return self._groups.add_members(group_id, account_ids)

    def unassign_accounts(self, group_id: int, account_ids: List[int]) -> int:
        return self._groups.remove_members(group_id, account_ids)

    # ------------------------------------------------------------------
    # Summaries
    # ------------------------------------------------------------------

    def get_group_summary(
        self,
        group_id: int,
        accounts: List[AccountRecord],
        session_map: Dict[int, AccountSessionRecord],
        health_map: Dict[int, float],
        block_map: Dict[int, list],
    ) -> Optional[GroupSummary]:
        """Compute aggregated metrics for one group."""
        group = self._groups.get_group(group_id)
        if group is None:
            return None

        member_ids = set(self._groups.get_members(group_id))
        members = [a for a in accounts if a.id in member_ids]

        active = [a for a in members if a.is_active]
        total_follows = 0
        healths = []
        review_count = 0
        blocked_count = 0

        for a in active:
            sess = session_map.get(a.id)
            if sess:
                total_follows += sess.follow_count

            h = health_map.get(a.id)
            if h is not None:
                healths.append(h)

            if a.review_flag:
                review_count += 1

            if a.id in block_map:
                blocked_count += 1

        return GroupSummary(
            group=group,
            total_accounts=len(members),
            active_accounts=len(active),
            avg_health=sum(healths) / len(healths) if healths else 0.0,
            total_follows_today=total_follows,
            blocked_count=blocked_count,
            review_count=review_count,
        )
