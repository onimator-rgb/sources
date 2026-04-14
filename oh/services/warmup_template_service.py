"""
WarmupTemplateService — orchestrates template CRUD + deploy operations.

Combines:
  - WarmupTemplateRepository (template CRUD in oh.db)
  - SettingsCopierModule (read/write settings.db)
  - AccountRepository (resolve account paths)
  - OperatorActionRepository (audit trail)
  - SettingsRepository (get bot_root)
"""
import json
import logging
import socket
from typing import List, Optional

from oh.models.operator_action import OperatorActionRecord, ACTION_APPLY_WARMUP
from oh.models.settings_copy import COPYABLE_SETTINGS
from oh.models.warmup_template import (
    WarmupTemplate,
    WarmupDeployPreview,
    WarmupDeployResult,
    WarmupDeployBatchResult,
)
from oh.modules.settings_copier import SettingsCopierModule
from oh.repositories.account_repo import AccountRepository
from oh.repositories.operator_action_repo import OperatorActionRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.repositories.warmup_template_repo import WarmupTemplateRepository

logger = logging.getLogger(__name__)

_MACHINE = socket.gethostname()


class WarmupTemplateService:
    """Orchestrate warmup template CRUD and deploy to accounts."""

    def __init__(
        self,
        warmup_repo: WarmupTemplateRepository,
        account_repo: AccountRepository,
        action_repo: OperatorActionRepository,
        settings_repo: SettingsRepository,
    ) -> None:
        self._warmup = warmup_repo
        self._accounts = account_repo
        self._actions = action_repo
        self._settings = settings_repo

    # ------------------------------------------------------------------
    # Template CRUD (thin wrappers for the repo)
    # ------------------------------------------------------------------

    def get_all_templates(self) -> List[WarmupTemplate]:
        """Return all warmup templates, ordered by name."""
        return self._warmup.get_all()

    def save_template(self, template: WarmupTemplate) -> WarmupTemplate:
        """Create or update a template. Returns the saved template."""
        if template.id is not None:
            self._warmup.update(template)
            return template
        return self._warmup.create(template)

    def delete_template(self, template_id: int) -> None:
        """Delete a template by id."""
        self._warmup.delete(template_id)

    # ------------------------------------------------------------------
    # Deploy — preview
    # ------------------------------------------------------------------

    def preview_deploy(
        self,
        template: WarmupTemplate,
        account_ids: List[int],
    ) -> List[WarmupDeployPreview]:
        """
        For each target account, read current settings and build a preview
        showing what will change. Uses SettingsCopierModule.read_settings().
        """
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return []

        module = SettingsCopierModule(bot_root)
        new_values = template.to_bot_settings()
        previews: List[WarmupDeployPreview] = []

        for account_id in account_ids:
            acc = self._accounts.get_by_id(account_id)
            if acc is None:
                previews.append(WarmupDeployPreview(
                    account_id=account_id,
                    username="?",
                    device_name=None,
                    current_values={},
                    new_values=new_values,
                    changes=[],
                    error="Account not found",
                ))
                continue

            snap = module.read_settings(
                device_id=acc.device_id,
                username=acc.username,
                device_name=acc.device_name,
                account_id=acc.id,
            )

            if snap.error:
                previews.append(WarmupDeployPreview(
                    account_id=acc.id,
                    username=acc.username,
                    device_name=acc.device_name,
                    current_values={},
                    new_values=new_values,
                    changes=[],
                    error=snap.error,
                ))
                continue

            # Build human-readable change list
            current_vals = {}
            changes: List[str] = []
            for key, new_val in new_values.items():
                display = COPYABLE_SETTINGS.get(key, key)
                cur_val = snap.values.get(key)
                current_vals[key] = cur_val
                if cur_val != new_val:
                    changes.append(f"{display}: {cur_val} -> {new_val}")

            previews.append(WarmupDeployPreview(
                account_id=acc.id,
                username=acc.username,
                device_name=acc.device_name,
                current_values=current_vals,
                new_values=new_values,
                changes=changes,
            ))

        return previews

    # ------------------------------------------------------------------
    # Deploy — apply
    # ------------------------------------------------------------------

    def apply_deploy(
        self,
        template: WarmupTemplate,
        account_ids: List[int],
    ) -> WarmupDeployBatchResult:
        """
        Deploy the template to all target accounts.

        For each account:
          1. Read current settings (for audit old_value)
          2. Build updates dict from template.to_bot_settings()
          3. Call SettingsCopierModule.write_settings() (backup + write)
          4. Log to operator_actions audit trail

        Per-account errors do not abort the batch.
        """
        bot_root = self._settings.get_bot_root()
        if not bot_root:
            return WarmupDeployBatchResult(
                template_name=template.name,
                total_targets=len(account_ids),
                success_count=0,
                fail_count=len(account_ids),
                results=[],
            )

        module = SettingsCopierModule(bot_root)
        new_values = template.to_bot_settings()

        results: List[WarmupDeployResult] = []
        success_count = 0
        fail_count = 0

        for account_id in account_ids:
            acc = self._accounts.get_by_id(account_id)
            if acc is None:
                fail_count += 1
                results.append(WarmupDeployResult(
                    account_id=account_id,
                    username="?",
                    device_name=None,
                    success=False,
                    backed_up=False,
                    keys_written=[],
                    error="Account not found",
                ))
                continue

            # Read current settings for audit trail
            snap = module.read_settings(
                device_id=acc.device_id,
                username=acc.username,
                device_name=acc.device_name,
                account_id=acc.id,
            )

            old_values = {}
            for key in new_values:
                old_values[key] = snap.values.get(key) if not snap.error else None

            # Write via SettingsCopierModule (handles backup + validation)
            write_result = module.write_settings(
                device_id=acc.device_id,
                username=acc.username,
                updates=new_values,
                device_name=acc.device_name,
                account_id=acc.id,
            )

            deploy_result = WarmupDeployResult(
                account_id=acc.id,
                username=acc.username,
                device_name=acc.device_name,
                success=write_result.success,
                backed_up=write_result.backed_up,
                keys_written=write_result.keys_written,
                error=write_result.error,
            )
            results.append(deploy_result)

            if write_result.success:
                success_count += 1
            else:
                fail_count += 1

            # Log audit trail
            try:
                self._actions.log_action(OperatorActionRecord(
                    account_id=acc.id,
                    username=acc.username,
                    device_id=acc.device_id,
                    action_type=ACTION_APPLY_WARMUP,
                    old_value=json.dumps(old_values, ensure_ascii=False),
                    new_value=json.dumps(new_values, ensure_ascii=False),
                    note=f"Warmup template '{template.name}': {len(write_result.keys_written)} keys written",
                    machine=_MACHINE,
                ))
            except Exception as e:
                logger.warning(f"Failed to log audit for {acc.username}: {e}")

        return WarmupDeployBatchResult(
            template_name=template.name,
            total_targets=len(account_ids),
            success_count=success_count,
            fail_count=fail_count,
            results=results,
        )
