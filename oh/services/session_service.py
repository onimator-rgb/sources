"""
SessionService — orchestrates session data collection for all active accounts.

Responsibilities:
  - Read daily action counters (follow, like, DM, unfollow) from bot files
  - Read and parse bot tags from settings.db
  - Persist session snapshots, tags, and bot metadata to OH database
  - Expose session snapshot maps for the main table

This service is the integration point between SessionReader (pure file I/O)
and the three repositories it writes to.  UI layers call this service;
they do not call SessionReader or the repos directly.
"""
import logging
from datetime import date
from pathlib import Path
from typing import Optional

from oh.models.session import (
    AccountSessionRecord,
    SessionCollectionResult,
)
from oh.modules.session_reader import SessionReader
from oh.repositories.account_repo import AccountRepository
from oh.repositories.session_repo import SessionRepository
from oh.repositories.tag_repo import TagRepository

logger = logging.getLogger(__name__)


class SessionService:
    def __init__(
        self,
        session_repo: SessionRepository,
        tag_repo: TagRepository,
        account_repo: AccountRepository,
    ) -> None:
        self._session_repo = session_repo
        self._tag_repo = tag_repo
        self._account_repo = account_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect_sessions(
        self,
        bot_root: str,
        snapshot_date: Optional[str] = None,
    ) -> SessionCollectionResult:
        """
        Collect session snapshots, tags, and bot metadata for all active
        accounts.  Errors on individual accounts are logged and counted
        but never stop the batch.

        snapshot_date — YYYY-MM-DD; defaults to today's local date.
        """
        if snapshot_date is None:
            snapshot_date = date.today().isoformat()

        reader = SessionReader(bot_root)
        accounts = self._account_repo.get_all_active()
        result = SessionCollectionResult(total=len(accounts))

        logger.info(
            f"[Session] Starting session collection for {len(accounts)} "
            f"active account(s), date={snapshot_date}"
        )

        for acc in accounts:
            try:
                account_path = Path(bot_root) / acc.device_id / acc.username

                # 1. Session snapshot (follow/like/dm/unfollow counts)
                record = reader.read_session(
                    account_path=account_path,
                    account_id=acc.id,
                    device_id=acc.device_id,
                    username=acc.username,
                    snapshot_date=snapshot_date,
                    start_time=acc.start_time,
                    end_time=acc.end_time,
                )
                self._session_repo.upsert_snapshot(record)

                # 2. Bot tags
                raw_tags, parsed_tags = reader.read_tags(
                    account_path, acc.id
                )
                self._tag_repo.upsert_bot_tags(acc.id, parsed_tags)

                # 3. Bot metadata on oh_accounts
                follow_limit, like_limit = reader.read_account_limits(
                    account_path
                )
                self._account_repo.update_bot_metadata(
                    acc.id,
                    bot_tags_raw=raw_tags,
                    follow_limit_perday=(
                        str(follow_limit) if follow_limit is not None else None
                    ),
                    like_limit_perday=(
                        str(like_limit) if like_limit is not None else None
                    ),
                )

                result.collected += 1

            except Exception as e:
                result.failed += 1
                error_msg = f"{acc.username}@{acc.device_id[:12]}: {e}"
                result.errors.append(error_msg)
                logger.warning(f"[Session] Failed to collect: {error_msg}")

        logger.info(
            f"[Session] Collection complete: {result.status_line()}"
        )
        return result

    def get_session_map(
        self, snapshot_date: str
    ) -> dict:
        """Return {account_id: AccountSessionRecord} for a given date."""
        return self._session_repo.get_map_for_date(snapshot_date)
