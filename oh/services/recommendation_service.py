"""
RecommendationService — generates operational recommendations from current data.

Recommendations are not persisted.  They are computed on demand from
session snapshots, FBR data, source assignments, tags, and device status.

The main method `generate()` receives pre-loaded maps (the same ones
MainWindow already holds) and runs pure logic over them — no heavy DB
queries except for weak source lookup (one fast query).
"""
import logging
import re
from datetime import datetime
from typing import Optional

from oh.models.account import AccountRecord
from oh.models.fbr_snapshot import FBRSnapshotRecord
from oh.models.recommendation import (
    Recommendation,
    REC_LOW_FBR_SOURCE, REC_SOURCE_EXHAUSTION, REC_LOW_LIKE,
    REC_LIMITS_MAX, REC_TB_MAX, REC_ZERO_ACTION,
    REC_SOURCE_FBR_DECLINING, REC_SOURCE_EXHAUSTED,
    SEV_CRITICAL, SEV_HIGH, SEV_MEDIUM, SEV_LOW,
    TARGET_SOURCE, TARGET_ACCOUNT,
)
from oh.models.session import (
    AccountSessionRecord,
    TAG_SOURCE_OPERATOR,
    TAG_CAT_TB,
    TAG_CAT_LIMITS,
)
from oh.repositories.account_repo import AccountRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.tag_repo import TagRepository
from oh.services.global_sources_service import GlobalSourcesService

logger = logging.getLogger(__name__)

_TB_RE = re.compile(r"TB(\d)", re.IGNORECASE)

# Limit on LOW_FBR_SOURCE recommendations to avoid noise
_MAX_WEAK_SOURCE_RECS = 25


class RecommendationService:
    def __init__(
        self,
        global_sources_service: GlobalSourcesService,
        account_repo: AccountRepository,
        tag_repo: TagRepository,
        settings_repo: SettingsRepository,
        source_profile_repo=None,
    ) -> None:
        self._sources = global_sources_service
        self._accounts = account_repo
        self._tags = tag_repo
        self._settings = settings_repo
        self._source_profile_repo = source_profile_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        session_map: dict,
        fbr_map: dict,
        device_status_map: dict,
        op_tags_map: dict,
    ) -> list:
        """
        Generate recommendations from current data.

        Parameters are the same maps already loaded in MainWindow:
          session_map      — {account_id: AccountSessionRecord}
          fbr_map          — {account_id: FBRSnapshotRecord}
          device_status_map — {device_id: "running"|"stop"|...}
          op_tags_map      — {account_id: "TB3 | limits 2"}

        Returns a list of Recommendation objects sorted by severity.
        """
        recs = []

        accounts = self._accounts.get_all_active()
        source_counts = self._sources.get_active_source_counts()
        current_hour = datetime.now().hour

        # --- Source-level recommendations ---
        recs.extend(self._check_low_fbr_sources())

        # --- Account-level recommendations ---
        for acc in accounts:
            if acc.id is None:
                continue

            sess = session_map.get(acc.id)
            snap = fbr_map.get(acc.id)
            src_count = source_counts.get(acc.id, 0)
            op_tags = op_tags_map.get(acc.id, "")
            dev_status = device_status_map.get(acc.device_id, "")

            label = f"{acc.username}@{acc.device_name or acc.device_id}"

            # TB_MAX
            rec = self._check_tb_max(acc, op_tags, label)
            if rec:
                recs.append(rec)

            # LIMITS_MAX
            rec = self._check_limits_max(acc, op_tags, label)
            if rec:
                recs.append(rec)

            # SOURCE_EXHAUSTION
            rec = self._check_source_exhaustion(acc, src_count, snap, label)
            if rec:
                recs.append(rec)

            # ZERO_ACTION (needs session data + active slot)
            rec = self._check_zero_action(
                acc, sess, dev_status, current_hour, label
            )
            if rec:
                recs.append(rec)

            # LOW_LIKE
            rec = self._check_low_like(acc, sess, label)
            if rec:
                recs.append(rec)

        # --- Source health from FBR stats ---
        self._check_source_health(recs)

        recs.sort(key=lambda r: r.sort_key)

        logger.info(
            f"[Recommendations] Generated {len(recs)} recommendations "
            f"for {len(accounts)} accounts"
        )
        return recs

    # ------------------------------------------------------------------
    # Source-level checks
    # ------------------------------------------------------------------

    def _check_low_fbr_sources(self) -> list:
        """Generate LOW_FBR_SOURCE recommendations for weak sources."""
        threshold = self._settings.get_weak_source_threshold()
        min_follows, _ = self._settings.get_fbr_thresholds()
        weak = self._sources.get_sources_below_threshold(threshold, min_follows)

        if not weak:
            return []

        # Sort by FBR ascending (worst first), limit output
        weak.sort(key=lambda s: (s.weighted_fbr_pct or 0.0, s.source_name))

        recs = []
        total_weak = len(weak)

        for src in weak[:_MAX_WEAK_SOURCE_RECS]:
            wfbr = src.weighted_fbr_pct or 0.0

            if wfbr == 0.0:
                sev = SEV_CRITICAL
            elif wfbr < 1.0:
                sev = SEV_HIGH
            else:
                sev = SEV_MEDIUM

            recs.append(Recommendation(
                rec_type=REC_LOW_FBR_SOURCE,
                severity=sev,
                target_type=TARGET_SOURCE,
                target_id=src.source_name,
                target_label=src.source_name,
                reason=(
                    f"wFBR={wfbr:.1f}%, {src.total_follows} follows, "
                    f"{src.active_accounts} active accounts"
                ),
                suggested_action="Delete source via Sources tab",
                metadata={
                    "weighted_fbr_pct": wfbr,
                    "total_follows": src.total_follows,
                    "active_accounts": src.active_accounts,
                },
            ))

        # If there are more weak sources than the limit, add a summary rec
        if total_weak > _MAX_WEAK_SOURCE_RECS:
            remaining = total_weak - _MAX_WEAK_SOURCE_RECS
            recs.append(Recommendation(
                rec_type=REC_LOW_FBR_SOURCE,
                severity=SEV_MEDIUM,
                target_type=TARGET_SOURCE,
                target_id="_bulk",
                target_label=f"+{remaining} more weak sources",
                reason=(
                    f"{total_weak} total sources with wFBR <= {threshold}% "
                    f"(showing top {_MAX_WEAK_SOURCE_RECS})"
                ),
                suggested_action=(
                    f"Use Sources tab -> Bulk Delete Weak Sources "
                    f"(threshold {threshold}%)"
                ),
                metadata={"total_weak": total_weak, "threshold": threshold},
            ))

        return recs

    def _check_source_health(self, recs: list) -> None:
        """Generate source health recommendations from FBR stats."""
        if self._source_profile_repo is None:
            return

        try:
            stats = self._source_profile_repo.get_all_fbr_stats()
        except Exception:
            logger.debug("Failed to load FBR stats for source health check", exc_info=True)
            return

        for stat in stats:
            # Low FBR across all accounts (weighted < 3%)
            if stat.total_accounts_used >= 3 and stat.weighted_fbr_pct < 3.0 and stat.total_follows >= 50:
                recs.append(Recommendation(
                    rec_type=REC_SOURCE_FBR_DECLINING,
                    severity=SEV_HIGH if stat.weighted_fbr_pct < 1.0 else SEV_MEDIUM,
                    target_type=TARGET_SOURCE,
                    target_id=stat.source_name,
                    target_label=stat.source_name,
                    reason=(
                        f"Source @{stat.source_name} has {stat.weighted_fbr_pct:.1f}% weighted FBR "
                        f"across {stat.total_accounts_used} accounts "
                        f"({stat.total_follows} follows, {stat.total_followbacks} followbacks)"
                    ),
                    suggested_action="Consider removing this source from all accounts",
                ))

    # ------------------------------------------------------------------
    # Account-level checks
    # ------------------------------------------------------------------

    def _check_tb_max(self, acc, op_tags, label) -> Optional[Recommendation]:
        """Check for TB5 in operator tags."""
        level = self._extract_operator_level(op_tags, "TB")
        if level is None or level < 5:
            return None

        return Recommendation(
            rec_type=REC_TB_MAX,
            severity=SEV_CRITICAL,
            target_type=TARGET_ACCOUNT,
            target_id=acc.username,
            target_label=label,
            reason="TB5 — account requires relocation",
            suggested_action=(
                "Move account to another device, restart warmup"
            ),
            account_id=acc.id,
            metadata={"tb_level": level, "device_name": acc.device_name},
        )

    def _check_limits_max(self, acc, op_tags, label) -> Optional[Recommendation]:
        """Check for limits 5 in operator tags."""
        level = self._extract_operator_level(op_tags, "limits")
        if level is None or level < 5:
            return None

        return Recommendation(
            rec_type=REC_LIMITS_MAX,
            severity=SEV_HIGH,
            target_type=TARGET_ACCOUNT,
            target_id=acc.username,
            target_label=label,
            reason=f"limits {level} — sources need replacement",
            suggested_action=(
                "Replace most exhausted sources, delete weak sources"
            ),
            account_id=acc.id,
            metadata={"limits_level": level},
        )

    def _check_source_exhaustion(
        self, acc, src_count, snap, label
    ) -> Optional[Recommendation]:
        """Check for too few active sources or zero quality sources."""
        min_warn = self._settings.get_min_source_count_warning()

        if src_count == 0:
            return Recommendation(
                rec_type=REC_SOURCE_EXHAUSTION,
                severity=SEV_HIGH,
                target_type=TARGET_ACCOUNT,
                target_id=acc.username,
                target_label=label,
                reason="0 active sources",
                suggested_action="Add sources to sources.txt",
                account_id=acc.id,
                metadata={"active_sources": 0, "quality_sources": 0},
            )

        if src_count < min_warn:
            quality = snap.quality_sources if snap else 0
            return Recommendation(
                rec_type=REC_SOURCE_EXHAUSTION,
                severity=SEV_MEDIUM,
                target_type=TARGET_ACCOUNT,
                target_id=acc.username,
                target_label=label,
                reason=(
                    f"{src_count} active sources (min={min_warn}), "
                    f"{quality} quality"
                ),
                suggested_action="Add new sources / replace exhausted ones",
                account_id=acc.id,
                metadata={
                    "active_sources": src_count,
                    "quality_sources": quality,
                },
            )

        # Many sources but zero quality
        if snap and snap.quality_sources == 0 and snap.total_sources > 0:
            return Recommendation(
                rec_type=REC_SOURCE_EXHAUSTION,
                severity=SEV_LOW,
                target_type=TARGET_ACCOUNT,
                target_id=acc.username,
                target_label=label,
                reason=(
                    f"{src_count} active sources but 0 quality "
                    f"(out of {snap.total_sources} analyzed)"
                ),
                suggested_action="Replace weak sources with better ones",
                account_id=acc.id,
                metadata={
                    "active_sources": src_count,
                    "quality_sources": 0,
                    "total_analyzed": snap.total_sources,
                },
            )

        return None

    def _check_zero_action(
        self, acc, sess, dev_status, current_hour, label
    ) -> Optional[Recommendation]:
        """Check for zero-action accounts on running devices in active slots."""
        if not acc.follow_enabled:
            return None
        if sess is not None and sess.has_activity:
            return None
        if dev_status != "running":
            return None  # handled by session report / device section
        if not self._is_active_slot(acc, current_hour):
            return None

        return Recommendation(
            rec_type=REC_ZERO_ACTION,
            severity=SEV_HIGH,
            target_type=TARGET_ACCOUNT,
            target_id=acc.username,
            target_label=label,
            reason=(
                "0 actions in active slot, device running"
            ),
            suggested_action=(
                "Check account: popup, 2FA, logout, action block"
            ),
            account_id=acc.id,
            metadata={
                "slot": sess.slot if sess else "—",
                "device_status": dev_status,
            },
        )

    def _check_low_like(self, acc, sess, label) -> Optional[Recommendation]:
        """Check for zero likes on an active account with like enabled."""
        if sess is None or sess.follow_count == 0:
            return None  # account not active today
        if sess.like_count > 0:
            return None  # has likes, OK

        try:
            like_limit = int(acc.like_limit_perday or 0)
        except (ValueError, TypeError):
            like_limit = 0

        if like_limit <= 0:
            return None  # like not configured — not a problem

        return Recommendation(
            rec_type=REC_LOW_LIKE,
            severity=SEV_MEDIUM,
            target_type=TARGET_ACCOUNT,
            target_id=acc.username,
            target_label=label,
            reason=(
                f"follow={sess.follow_count} but like=0 "
                f"(limit={like_limit})"
            ),
            suggested_action=(
                "Check like sources, add similar community"
            ),
            account_id=acc.id,
            metadata={
                "follow_count": sess.follow_count,
                "like_count": 0,
                "like_limit": like_limit,
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_operator_level(op_tags_str: str, keyword: str) -> Optional[int]:
        """
        Extract numeric level from operator tags string.

        op_tags_str is the concatenated string from get_operator_tags_map(),
        e.g. "TB3 | limits 2".  We look for a tag matching the keyword.
        """
        if not op_tags_str:
            return None
        for part in op_tags_str.split("|"):
            part = part.strip()
            if keyword == "TB":
                m = _TB_RE.match(part)
                if m:
                    return int(m.group(1))
            elif keyword == "limits":
                if part.startswith("limits "):
                    try:
                        return int(part.split()[-1])
                    except (ValueError, IndexError):
                        pass
        return None

    @staticmethod
    def _is_active_slot(acc, current_hour: int) -> bool:
        """Check if the account's scheduled slot covers the current hour."""
        try:
            start = int(acc.start_time or 0)
            end = int(acc.end_time or 0)
        except (ValueError, TypeError):
            return False
        if start == 0 and end == 0:
            return False
        return start <= current_hour < end
