"""
SyncModule — compares a fresh discovery result against the OH registry
and applies adds, removes, and metadata updates.

Records a complete sync run with per-account event history.
"""
import json
import logging
from datetime import datetime, timezone

from oh.models.account import AccountRecord, DiscoveredAccount, DeviceRecord
from oh.models.sync import SyncRun, SyncSummary
from oh.repositories.account_repo import AccountRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.sync_repo import SyncRepository

logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


class SyncModule:
    """
    Processes a list of DiscoveredAccount objects against the OH registry.

    Outcomes per discovered account:
      - Not in registry          → INSERT + 'added' event
      - In registry, removed     → undelete (clear removed_at) + 'added' event
      - In registry, active, no change → UPDATE last_seen_at only
      - In registry, active, changed   → UPDATE metadata + 'metadata_changed' event

    Outcomes for registry accounts NOT in current scan:
      - Active in registry but absent → soft-delete + 'removed' event

    Orphan folders (folder exists but not in accounts.db) are surfaced
    in discovery results for UI display but are NOT written to the registry.
    """

    def __init__(
        self,
        account_repo: AccountRepository,
        device_repo: DeviceRepository,
        sync_repo: SyncRepository,
    ) -> None:
        self._account_repo = account_repo
        self._device_repo = device_repo
        self._sync_repo = sync_repo

    def run(
        self, discovered: list, triggered_by: str = "manual"
    ) -> SyncRun:
        sync_run = self._sync_repo.create_run(triggered_by=triggered_by)
        summary = SyncSummary()

        try:
            self._process(sync_run, summary, discovered)
            self._sync_repo.complete_run(sync_run.id, summary)

            # Populate the returned object with final counts for the UI
            sync_run.status = "completed"
            sync_run.devices_scanned = summary.devices_scanned
            sync_run.accounts_scanned = summary.accounts_scanned
            sync_run.accounts_added = summary.accounts_added
            sync_run.accounts_removed = summary.accounts_removed
            sync_run.accounts_updated = summary.accounts_updated
            sync_run.accounts_unchanged = summary.accounts_unchanged

            logger.info(
                f"Sync complete — "
                f"+{summary.accounts_added} added, "
                f"-{summary.accounts_removed} removed, "
                f"~{summary.accounts_updated} updated, "
                f"={summary.accounts_unchanged} unchanged"
            )

        except Exception as e:
            logger.exception("Sync failed.")
            self._sync_repo.fail_run(sync_run.id, str(e))
            sync_run.status = "failed"
            raise

        return sync_run

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _process(
        self, sync_run: SyncRun, summary: SyncSummary, discovered: list
    ) -> None:
        now = _utcnow()

        # --- Upsert devices seen in this scan ---
        # Build a map to avoid O(n) scan per unique device_id
        device_samples: dict[str, DiscoveredAccount] = {}
        for d in discovered:
            if d.device_id not in device_samples:
                device_samples[d.device_id] = d

        for device_id, sample in device_samples.items():
            self._device_repo.upsert(DeviceRecord(
                device_id=sample.device_id,
                device_name=sample.device_name,
                last_known_status=sample.device_status,
                first_discovered_at=now,
                last_synced_at=now,
                is_active=True,
            ))
        summary.devices_scanned = len(device_samples)

        # Keyset of non-orphan accounts in this scan
        scanned_keys: set[tuple] = set()
        for d in discovered:
            if not d.is_orphan_folder:
                scanned_keys.add((d.device_id, d.username))
        summary.accounts_scanned = len(scanned_keys)

        # --- Process each discovered account ---
        for disc in discovered:
            if disc.is_orphan_folder:
                # Surfaced in UI via discovery results; not written to registry
                continue

            account = AccountRecord(
                device_id=disc.device_id,
                username=disc.username,
                discovered_at=now,
                last_seen_at=now,
                follow_enabled=disc.follow_enabled,
                unfollow_enabled=disc.unfollow_enabled,
                limit_per_day=disc.limit_per_day,
                start_time=disc.start_time,
                end_time=disc.end_time,
                data_db_exists=disc.data_db_exists,
                sources_txt_exists=disc.sources_txt_exists,
                bot_tags_raw=disc.bot_tags_raw,
                follow_limit_perday=disc.follow_limit_perday,
                like_limit_perday=disc.like_limit_perday,
            )

            existing = self._account_repo.get_by_device_and_username(
                disc.device_id, disc.username
            )

            if existing is None or existing.removed_at is not None:
                # New account or re-appearing removed account
                saved = self._account_repo.insert(account)
                self._sync_repo.record_event(
                    sync_run_id=sync_run.id,
                    event_type="added",
                    device_id=disc.device_id,
                    username=disc.username,
                    account_id=saved.id,
                )
                summary.accounts_added += 1

            else:
                # Active account — check metadata delta
                changes = _metadata_diff(existing, disc)
                self._account_repo.update(existing.id, account)

                if changes:
                    self._sync_repo.record_event(
                        sync_run_id=sync_run.id,
                        event_type="metadata_changed",
                        device_id=disc.device_id,
                        username=disc.username,
                        account_id=existing.id,
                        changed_fields=json.dumps(changes),
                    )
                    summary.accounts_updated += 1
                else:
                    summary.accounts_unchanged += 1

        # --- Soft-delete accounts no longer present ---
        # get_active_id_map() returns {(device_id, username): id} in one query,
        # eliminating a per-account SELECT in the removal loop.
        active_id_map = self._account_repo.get_active_id_map()
        removed_keys = set(active_id_map.keys()) - scanned_keys

        for device_id, username in removed_keys:
            account_id = active_id_map[(device_id, username)]
            self._account_repo.mark_removed(account_id, now, sync_run.id)
            self._sync_repo.record_event(
                sync_run_id=sync_run.id,
                event_type="removed",
                device_id=device_id,
                username=username,
                account_id=account_id,
            )
            summary.accounts_removed += 1


def _metadata_diff(existing: AccountRecord, disc: DiscoveredAccount) -> dict:
    """Returns a dict of {field: [old, new]} for any changed metadata fields."""
    changes = {}
    checks = [
        ("follow_enabled",      existing.follow_enabled,      disc.follow_enabled),
        ("unfollow_enabled",    existing.unfollow_enabled,    disc.unfollow_enabled),
        ("limit_per_day",       existing.limit_per_day,       disc.limit_per_day),
        ("start_time",          existing.start_time,          disc.start_time),
        ("end_time",            existing.end_time,            disc.end_time),
        ("bot_tags_raw",        existing.bot_tags_raw,        disc.bot_tags_raw),
        ("follow_limit_perday", existing.follow_limit_perday, disc.follow_limit_perday),
        ("like_limit_perday",   existing.like_limit_perday,   disc.like_limit_perday),
    ]
    for field, old, new in checks:
        if old != new:
            changes[field] = [old, new]
    return changes
