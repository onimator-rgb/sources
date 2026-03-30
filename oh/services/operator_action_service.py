"""
OperatorActionService — executes operator actions and logs an audit trail.

Every public method:
  1. Reads current state (if needed for old_value or business logic)
  2. Performs the change via AccountRepository / TagRepository
  3. Logs to operator_actions via OperatorActionRepository
  4. Returns a short status string for UI feedback

Operator tags (tag_source='operator') are fully isolated from bot tags
(tag_source='bot').  No method in this service touches bot tags.
"""
import logging
import socket
from typing import Optional

from oh.models.operator_action import (
    OperatorActionRecord,
    ACTION_SET_REVIEW,
    ACTION_CLEAR_REVIEW,
    ACTION_ADD_TAG,
    ACTION_REMOVE_TAG,
    ACTION_INCREMENT_TB,
    ACTION_INCREMENT_LIMITS,
)
from oh.models.session import (
    TAG_SOURCE_OPERATOR,
    TAG_CAT_TB,
    TAG_CAT_LIMITS,
)
from oh.repositories.account_repo import AccountRepository
from oh.repositories.tag_repo import TagRepository
from oh.repositories.operator_action_repo import OperatorActionRepository

logger = logging.getLogger(__name__)

_MACHINE = socket.gethostname()

# TB and limits caps
_TB_MAX = 5
_LIMITS_MAX = 5


class OperatorActionService:
    def __init__(
        self,
        account_repo: AccountRepository,
        tag_repo: TagRepository,
        action_repo: OperatorActionRepository,
    ) -> None:
        self._accounts = account_repo
        self._tags = tag_repo
        self._actions = action_repo

    # ------------------------------------------------------------------
    # Review flag
    # ------------------------------------------------------------------

    def set_review(
        self, account_id: int, note: Optional[str] = None
    ) -> str:
        """Set review flag on an account. Returns 'review_set'."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        old_note = acc.review_note if acc.review_flag else None
        self._accounts.set_review_flag(account_id, note)

        self._log(acc, ACTION_SET_REVIEW,
                  old_value=old_note,
                  new_value=note or "flagged",
                  note=note)

        logger.info(f"[Action] set_review: {acc.username} note={note!r}")
        return "review_set"

    def clear_review(self, account_id: int) -> str:
        """Clear review flag from an account. Returns 'review_cleared'."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        old_note = acc.review_note if acc.review_flag else None
        self._accounts.clear_review_flag(account_id)

        self._log(acc, ACTION_CLEAR_REVIEW,
                  old_value=old_note or "flagged",
                  new_value=None)

        logger.info(f"[Action] clear_review: {acc.username}")
        return "review_cleared"

    # ------------------------------------------------------------------
    # Operator tags
    # ------------------------------------------------------------------

    def add_tag(
        self,
        account_id: int,
        category: str,
        value: str,
        level: Optional[int] = None,
    ) -> str:
        """Add an operator tag. Returns 'tag_added'."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        self._tags.set_operator_tag(account_id, category, value, level)

        self._log(acc, ACTION_ADD_TAG,
                  new_value=f"{category}:{value}")

        logger.info(f"[Action] add_tag: {acc.username} {category}:{value}")
        return "tag_added"

    def remove_tag(
        self,
        account_id: int,
        category: str,
        value: Optional[str] = None,
    ) -> str:
        """Remove operator tag(s). Returns 'tag_removed'."""
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        old_desc = f"{category}:{value}" if value else category
        self._tags.remove_operator_tag(account_id, category, value)

        self._log(acc, ACTION_REMOVE_TAG, old_value=old_desc)

        logger.info(f"[Action] remove_tag: {acc.username} {old_desc}")
        return "tag_removed"

    # ------------------------------------------------------------------
    # TB increment
    # ------------------------------------------------------------------

    def increment_tb(self, account_id: int) -> str:
        """
        Increment the operator TB level for an account.

        Returns:
          'TB1'..'TB5' — the new level after increment
          'tb5_max'    — already at TB5, cannot increment further
          'account_not_found' — invalid account_id
        """
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        current = self._get_operator_level(account_id, TAG_CAT_TB)

        if current is not None and current >= _TB_MAX:
            logger.info(
                f"[Action] increment_tb: {acc.username} already TB{_TB_MAX}"
            )
            return "tb5_max"

        new_level = (current or 0) + 1
        old_value = f"TB{current}" if current else None
        new_value = f"TB{new_level}"

        # Remove all operator TB tags, set the new one
        self._tags.remove_operator_tag(account_id, TAG_CAT_TB)
        self._tags.set_operator_tag(
            account_id, TAG_CAT_TB, new_value, new_level
        )

        self._log(acc, ACTION_INCREMENT_TB,
                  old_value=old_value, new_value=new_value)

        logger.info(
            f"[Action] increment_tb: {acc.username} "
            f"{old_value or 'none'} -> {new_value}"
        )
        return new_value

    # ------------------------------------------------------------------
    # Limits increment
    # ------------------------------------------------------------------

    def increment_limits(self, account_id: int) -> str:
        """
        Increment the operator limits level for an account.

        Returns:
          'limits 1'..'limits 5' — the new level after increment
          'limits5_max'          — already at limits 5, cannot increment
          'account_not_found'    — invalid account_id
        """
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return "account_not_found"

        current = self._get_operator_level(account_id, TAG_CAT_LIMITS)

        if current is not None and current >= _LIMITS_MAX:
            logger.info(
                f"[Action] increment_limits: {acc.username} "
                f"already limits {_LIMITS_MAX}"
            )
            return "limits5_max"

        new_level = (current or 0) + 1
        old_value = f"limits {current}" if current else None
        new_value = f"limits {new_level}"

        # Remove all operator limits tags, set the new one
        self._tags.remove_operator_tag(account_id, TAG_CAT_LIMITS)
        self._tags.set_operator_tag(
            account_id, TAG_CAT_LIMITS, new_value, new_level
        )

        self._log(acc, ACTION_INCREMENT_LIMITS,
                  old_value=old_value, new_value=new_value)

        logger.info(
            f"[Action] increment_limits: {acc.username} "
            f"{old_value or 'none'} -> {new_value}"
        )
        return new_value

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_operator_level(
        self, account_id: int, category: str
    ) -> Optional[int]:
        """
        Find the current operator tag level for a category.
        Returns the numeric level, or None if no operator tag exists.
        """
        tags = self._tags.get_tags_for_account(account_id)
        for tag in tags:
            if (tag.tag_source == TAG_SOURCE_OPERATOR
                    and tag.tag_category == category
                    and tag.tag_level is not None):
                return tag.tag_level
        return None

    def _log(
        self,
        acc,
        action_type: str,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        note: Optional[str] = None,
    ) -> None:
        """Write an audit row for the action."""
        self._actions.log_action(OperatorActionRecord(
            account_id=acc.id,
            username=acc.username,
            device_id=acc.device_id,
            action_type=action_type,
            old_value=old_value,
            new_value=new_value,
            note=note,
            machine=_MACHINE,
        ))
