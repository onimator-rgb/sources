"""
ScanService — thin orchestration layer between the UI and the core modules.

Keeps DiscoveryModule and SyncModule construction out of the UI layer.
"""
from oh.models.sync import SyncRun
from oh.modules.discovery import DiscoveryModule
from oh.modules.sync_module import SyncModule
from oh.repositories.account_repo import AccountRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.sync_repo import SyncRepository


class ScanService:
    def __init__(
        self,
        account_repo: AccountRepository,
        device_repo: DeviceRepository,
        sync_repo: SyncRepository,
    ) -> None:
        self._account_repo = account_repo
        self._device_repo = device_repo
        self._sync_repo = sync_repo

    def scan(self, bot_root: str) -> list:
        """Run discovery and return raw DiscoveredAccount list."""
        return DiscoveryModule(bot_root).discover()

    def sync(self, discovered: list) -> SyncRun:
        """Sync discovery results into the OH registry."""
        return SyncModule(
            self._account_repo,
            self._device_repo,
            self._sync_repo,
        ).run(discovered)
