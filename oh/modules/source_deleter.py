"""
SourceDeleter — file-level source removal from sources.txt.

SAFETY MODEL:
  - sources.txt.bak is written before every modification to sources.txt
  - sources.txt is never truncated or rewritten without first creating the backup
  - data.db is never touched — historical follow data is fully preserved
  - Each call reads the current file fresh — no stale in-memory state
  - Matching is case-insensitive and whitespace-stripped

The caller (SourceDeleteService) is responsible for:
  - Confirming with the operator before calling any remove_ method
  - Updating OH-side source_assignments after successful removal
  - Writing to delete history
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SourceDeleteFileResult:
    """Result of removing one source from one account's sources.txt."""
    username: str
    device_name: str
    found: bool       # source was present in sources.txt
    removed: bool     # file was successfully rewritten without the source
    backed_up: bool   # sources.txt.bak was created
    error: Optional[str] = None


class SourceDeleter:
    """
    Handles writing source removals to the bot's sources.txt files.
    One instance per bot_root.  All methods are stateless and re-read
    the file on every call.
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    def remove_source(
        self,
        device_id: str,
        username: str,
        device_name: str,
        source_name: str,
    ) -> SourceDeleteFileResult:
        """
        Remove source_name from sources.txt for one account.

        Steps:
          1. Read current sources.txt (fails gracefully if missing/unreadable)
          2. Filter out lines matching source_name (case-insensitive strip)
          3. Write sources.txt.bak with the original content
          4. Write new sources.txt without the source

        Backup failure is logged as a warning but does not abort the removal.
        Returns a SourceDeleteFileResult — never raises.
        """
        path = self._root / device_id / username / "sources.txt"

        if not path.exists():
            return SourceDeleteFileResult(
                username=username, device_name=device_name,
                found=False, removed=False, backed_up=False,
                error="sources.txt not found",
            )

        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"Cannot read {path}: {e}")
            return SourceDeleteFileResult(
                username=username, device_name=device_name,
                found=False, removed=False, backed_up=False,
                error=f"Cannot read: {e}",
            )

        lines = content.splitlines()
        target = source_name.strip().lower()
        new_lines = [ln for ln in lines if ln.strip().lower() != target]

        if len(new_lines) == len(lines):
            # Source was not in the file (may have been removed externally already)
            logger.debug(f"'{source_name}' not found in {path}")
            return SourceDeleteFileResult(
                username=username, device_name=device_name,
                found=False, removed=False, backed_up=False,
            )

        # Write backup before modifying
        bak_path = path.with_name("sources.txt.bak")
        backed_up = False
        try:
            bak_path.write_text(content, encoding="utf-8")
            backed_up = True
        except OSError as e:
            logger.warning(f"Could not write backup {bak_path}: {e}")
            # Non-fatal: proceed with removal even without backup

        # Write new sources.txt — preserve trailing newline if original had one
        new_content = "\n".join(new_lines)
        if content.endswith("\n"):
            new_content += "\n"

        try:
            path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            logger.error(f"Cannot write {path}: {e}")
            return SourceDeleteFileResult(
                username=username, device_name=device_name,
                found=True, removed=False, backed_up=backed_up,
                error=f"Cannot write: {e}",
            )

        logger.info(
            f"Removed '{source_name}' from {username}@{device_id[:8]}…"
            f"  backup={'yes' if backed_up else 'SKIPPED'}"
        )
        return SourceDeleteFileResult(
            username=username, device_name=device_name,
            found=True, removed=True, backed_up=backed_up,
        )
