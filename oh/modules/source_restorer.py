"""
SourceRestorer — file-level source restoration to sources.txt.

Inverse of SourceDeleter. Adds a source line back to sources.txt if it
is not already present. Creates a backup before modification.

Safety:
  - sources.txt.bak is written before every modification
  - If source is already present, no changes are made
  - data.db is never touched
"""
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class SourceRestoreFileResult:
    """Result of restoring one source to one account's sources.txt."""
    username: str
    device_name: str
    restored: bool            # True if source was added to the file
    already_present: bool     # True if source was already in the file
    backed_up: bool           # sources.txt.bak was created before writing
    error: Optional[str] = None


class SourceRestorer:
    """
    Adds source lines back to bot sources.txt files.
    One instance per bot_root. All methods are stateless.
    """

    def __init__(self, bot_root: str) -> None:
        self._root = Path(bot_root)

    def restore_source(
        self,
        device_id: str,
        username: str,
        device_name: str,
        source_name: str,
    ) -> SourceRestoreFileResult:
        """
        Add source_name to sources.txt for one account if not already present.

        If sources.txt does not exist, it is created.
        A backup is written before any modification.
        """
        path = self._root / device_id / username / "sources.txt"
        target = source_name.strip().lower()

        # Read current content (or empty if file doesn't exist)
        content = ""
        if path.exists():
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except OSError as e:
                logger.warning(f"Cannot read {path}: {e}")
                return SourceRestoreFileResult(
                    username=username, device_name=device_name,
                    restored=False, already_present=False, backed_up=False,
                    error=f"Cannot read: {e}",
                )

        # Check if source is already present
        lines = content.splitlines()
        for ln in lines:
            if ln.strip().lower() == target:
                logger.debug(f"'{source_name}' already present in {path}")
                return SourceRestoreFileResult(
                    username=username, device_name=device_name,
                    restored=False, already_present=True, backed_up=False,
                )

        # Create backup before modifying
        backed_up = False
        if path.exists():
            bak_path = path.with_name("sources.txt.bak")
            try:
                bak_path.write_text(content, encoding="utf-8")
                backed_up = True
            except OSError as e:
                logger.warning(f"Could not write backup {bak_path}: {e}")

        # Add the source line
        lines.append(source_name.strip())
        new_content = "\n".join(lines)
        if content.endswith("\n") or not content:
            new_content += "\n"

        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(new_content, encoding="utf-8")
        except OSError as e:
            logger.error(f"Cannot write {path}: {e}")
            return SourceRestoreFileResult(
                username=username, device_name=device_name,
                restored=False, already_present=False, backed_up=backed_up,
                error=f"Cannot write: {e}",
            )

        logger.info(
            f"Restored '{source_name}' to {username}@{device_id[:8]}  "
            f"backup={'yes' if backed_up else 'no (new file)'}"
        )
        return SourceRestoreFileResult(
            username=username, device_name=device_name,
            restored=True, already_present=False, backed_up=backed_up,
        )
