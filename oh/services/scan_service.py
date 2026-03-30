"""
ScanService — thin orchestration layer between the UI and the core modules.

Keeps DiscoveryModule and SyncModule construction out of the UI layer.

After sync completes, session data collection runs automatically if a
SessionService has been provided.  Session collection failures are logged
but never cause the scan/sync result to fail.
"""
import logging
from typing import Optional

from oh.models.sync import SyncRun
from oh.modules.discovery import DiscoveryModule
from oh.modules.sync_module import SyncModule
from oh.repositories.account_repo import AccountRepository
from oh.repositories.device_repo import DeviceRepository
from oh.repositories.sync_repo import SyncRepository

logger = logging.getLogger(__name__)


class ScanService:
    def __init__(
        self,
        account_repo: AccountRepository,
        device_repo: DeviceRepository,
        sync_repo: SyncRepository,
        session_service=None,
    ) -> None:
        self._account_repo = account_repo
        self._device_repo = device_repo
        self._sync_repo = sync_repo
        self._session_service = session_service
        self._last_bot_root: Optional[str] = None

    def scan(self, bot_root: str) -> list:
        """Run discovery and return raw DiscoveredAccount list."""
        self._last_bot_root = bot_root
        return DiscoveryModule(bot_root).discover()

    def sync(self, discovered: list) -> SyncRun:
        """
        Sync discovery results into the OH registry.

        If a SessionService is configured and scan() was called beforehand,
        session data collection runs automatically after sync.  The sync
        result is returned regardless of session collection outcome.
        """
        sync_run = SyncModule(
            self._account_repo,
            self._device_repo,
            self._sync_repo,
        ).run(discovered)

        # --- Session collection (post-sync, non-fatal) ---
        bot_root = self._last_bot_root
        if self._session_service is not None and bot_root:
            try:
                result = self._session_service.collect_sessions(bot_root)
                logger.info(
                    f"[Session] Post-sync collection: {result.status_line()}"
                )
            except Exception as e:
                logger.warning(
                    f"[Session] Post-sync collection failed: {e}",
                    exc_info=True,
                )

        return sync_run
