"""
SettingsCopierService — orchestrates reading, diffing, and applying
settings copy operations between bot accounts.

Combines the SettingsCopierModule (file I/O) with repositories
(account lookup, audit logging).
"""
import json
import logging
import socket
from typing import List, Optional

from oh.models.operator_action import OperatorActionRecord, ACTION_COPY_SETTINGS
from oh.models.settings_copy import (
    COPYABLE_SETTINGS,
    SettingsSnapshot,
    SettingsDiff,
    SettingsDiffEntry,
    SettingsCopyResult,
    SettingsCopyBatchResult,
)
from oh.modules.settings_copier import SettingsCopierModule
from oh.repositories.account_repo import AccountRepository
from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.repositories.settings_repo import SettingsRepository

logger = logging.getLogger(__name__)

_MACHINE = socket.gethostname()


class SettingsCopierService:
    """Orchestrate settings copy: read source, build diff, apply, audit."""

    def __init__(
        self,
        account_repo: AccountRepository,
        action_repo: OperatorActionRepository,
        settings_repo: SettingsRepository,
    ) -> None:
        self._accounts = account_repo
        self._actions = action_repo
        self._settings = settings_repo

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read_source_settings(self, account_id: int) -> SettingsSnapshot:
        """
        Read copyable settings from the source account.
        Resolves bot_root from settings_repo, account path from account_repo.
        """
        acc = self._accounts.get_by_id(account_id)
        if acc is None:
            return SettingsSnapshot(
                account_id=account_id,
                username="?",
                device_id="?",
                device_name=None,
                values={},
                error="Account not found in OH database",
            )

        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return SettingsSnapshot(
                account_id=account_id,
                username=acc.username,
                device_id=acc.device_id,
                device_name=acc.device_name,
                values={},
                error="Bot root path not configured",
            )

        module = SettingsCopierModule(bot_root)
        return module.read_settings(
            device_id=acc.device_id,
            username=acc.username,
            device_name=acc.device_name,
            account_id=acc.id,
        )

    def preview_diff(
        self,
        source_snapshot: SettingsSnapshot,
        target_account_ids: List[int],
        selected_keys: List[str],
    ) -> List[SettingsDiff]:
        """
        Build a diff for each target: current value vs. source value.
        Only includes keys from selected_keys that are in COPYABLE_SETTINGS.
        """
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return []

        module = SettingsCopierModule(bot_root)

        # Filter to valid keys only
        valid_keys = [k for k in selected_keys if k in COPYABLE_SETTINGS]

        diffs = []
        for target_id in target_account_ids:
            acc = self._accounts.get_by_id(target_id)
            if acc is None:
                continue

            target_snap = module.read_settings(
                device_id=acc.device_id,
                username=acc.username,
                device_name=acc.device_name,
                account_id=acc.id,
            )

            entries = []
            different_count = 0
            for key in valid_keys:
                source_val = source_snapshot.values.get(key)
                target_val = target_snap.values.get(key)
                is_different = source_val != target_val
                if is_different:
                    different_count += 1
                entries.append(SettingsDiffEntry(
                    key=key,
                    display_name=COPYABLE_SETTINGS[key],
                    source_value=source_val,
                    target_value=target_val,
                    is_different=is_different,
                ))

            diffs.append(SettingsDiff(
                target_account_id=acc.id,
                target_username=acc.username,
                target_device_name=acc.device_name,
                entries=entries,
                different_count=different_count,
            ))

        return diffs

    def apply_copy(
        self,
        source_snapshot: SettingsSnapshot,
        target_account_ids: List[int],
        selected_keys: List[str],
    ) -> SettingsCopyBatchResult:
        """
        Execute the copy operation.

        For each target:
          1. Read target's current settings (for audit old_value)
          2. Build updates dict (only selected keys where value differs)
          3. Call module.write_settings()
          4. Log to operator_actions (one row per target account)
        Returns aggregate result.
        """
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return SettingsCopyBatchResult(
                source_username=source_snapshot.username,
                total_targets=len(target_account_ids),
                success_count=0,
                fail_count=len(target_account_ids),
                results=[],
            )

        module = SettingsCopierModule(bot_root)
        valid_keys = [k for k in selected_keys if k in COPYABLE_SETTINGS]

        results = []
        success_count = 0
        fail_count = 0

        for target_id in target_account_ids:
            acc = self._accounts.get_by_id(target_id)
            if acc is None:
                fail_count += 1
                results.append(SettingsCopyResult(
                    target_account_id=target_id,
                    target_username="?",
                    target_device_name=None,
                    success=False,
                    backed_up=False,
                    keys_written=[],
                    error="Account not found",
                ))
                continue

            # Read current target settings for audit trail (old_value)
            target_snap = module.read_settings(
                device_id=acc.device_id,
                username=acc.username,
                device_name=acc.device_name,
                account_id=acc.id,
            )

            # Build updates: only keys that actually differ
            updates = {}
            old_values = {}
            for key in valid_keys:
                source_val = source_snapshot.values.get(key)
                target_val = target_snap.values.get(key)
                # Skip keys missing in source (don't copy null/missing values)
                if source_val is None and key not in source_snapshot.values:
                    continue
                if source_val != target_val:
                    updates[key] = source_val
                    old_values[key] = target_val

            if not updates:
                # Nothing to change — report success with 0 keys written
                results.append(SettingsCopyResult(
                    target_account_id=acc.id,
                    target_username=acc.username,
                    target_device_name=acc.device_name,
                    success=True,
                    backed_up=False,
                    keys_written=[],
                ))
                success_count += 1
                continue

            # Write the updates
            result = module.write_settings(
                device_id=acc.device_id,
                username=acc.username,
                updates=updates,
                device_name=acc.device_name,
                account_id=acc.id,
            )
            results.append(result)

            if result.success:
                success_count += 1
            else:
                fail_count += 1

            # Log audit trail
            try:
                self._actions.log_action(OperatorActionRecord(
                    account_id=acc.id,
                    username=acc.username,
                    device_id=acc.device_id,
                    action_type=ACTION_COPY_SETTINGS,
                    old_value=json.dumps(old_values, ensure_ascii=False),
                    new_value=json.dumps(updates, ensure_ascii=False),
                    note=f"Copied from {source_snapshot.username}: {len(result.keys_written)} settings",
                    machine=_MACHINE,
                ))
            except Exception as e:
                logger.warning(f"Failed to log audit for {acc.username}: {e}")

        return SettingsCopyBatchResult(
            source_username=source_snapshot.username,
            total_targets=len(target_account_ids),
            success_count=success_count,
            fail_count=fail_count,
            results=results,
        )
