"""
GlobalLikeSourcesService — orchestrates like source assignment reads and aggregation.

The Like Sources tab reads all data from the DB (no disk access on open).
Like source assignments are populated by LBRService during analysis runs.
"""
from __future__ import annotations

import logging

from oh.models.global_like_source import GlobalLikeSourceRecord, LikeSourceAccountDetail
from oh.repositories.account_repo import AccountRepository
from oh.repositories.lbr_snapshot_repo import LBRSnapshotRepository
from oh.repositories.like_source_assignment_repo import LikeSourceAssignmentRepository

logger = logging.getLogger(__name__)


class GlobalLikeSourcesService:
    def __init__(
        self,
        lbr_snapshot_repo: LBRSnapshotRepository,
        like_assignment_repo: LikeSourceAssignmentRepository,
        account_repo: AccountRepository,
    ) -> None:
        self._snapshots = lbr_snapshot_repo
        self._assignments = like_assignment_repo
        self._accounts = account_repo

    # ------------------------------------------------------------------
    # Reads (DB only, no disk)
    # ------------------------------------------------------------------

    def get_all(self) -> list[GlobalLikeSourceRecord]:
        """
        Return aggregated like source data across all accounts.

        Each GlobalLikeSourceRecord includes:
          - active_accounts / historical_accounts counts
          - total_likes / total_followbacks aggregated from latest LBR snapshots
          - avg_lbr_pct  — arithmetic mean of LBR% across accounts
          - weighted_lbr_pct — sum(likes_i * lbr_i) / sum(likes_i), i.e.
            total_followbacks / total_likes * 100
          - quality_account_count — how many accounts have this source as quality
        """
        return self._assignments.get_global_like_sources()

    def get_detail(self, source_name: str) -> list[LikeSourceAccountDetail]:
        """
        Return per-account breakdown for one like source.

        Active accounts first, then historical.  Within each group ordered
        by like_count DESC.
        """
        return self._assignments.get_accounts_for_source(source_name)

    def has_any_data(self) -> bool:
        """Return True if any like source assignments have been recorded."""
        return self._assignments.has_any_data()

    def get_active_source_counts(self) -> dict[int, int]:
        """Returns {account_id: active_like_source_count} for like source count column."""
        return self._assignments.get_active_source_counts()
