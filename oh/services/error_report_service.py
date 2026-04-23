"""
ErrorReportService — captures crashes and user-reported issues, sends
them to a configurable webhook endpoint (Discord or custom server).

Privacy: never sends account usernames, device names, or client data.
Only technical context: OH version, OS, Python version, log tail, DB stats.
"""
import json
import logging
import os
import platform
import sys
import traceback as tb_module
import urllib.request
import urllib.error
import uuid
from pathlib import Path
from typing import Optional, Type
from types import TracebackType

from oh.models.error_report import (
    ErrorReport,
    ERROR_TYPE_CRASH,
    ERROR_TYPE_MANUAL,
)
from oh.repositories.error_report_repo import ErrorReportRepository
from oh.repositories.settings_repo import SettingsRepository
from oh.utils import utcnow

logger = logging.getLogger(__name__)

_MAX_LOG_LINES = 100
_MAX_TRACEBACK_LEN = 3000
_SEND_TIMEOUT = 10  # seconds


class ErrorReportService:
    def __init__(
        self,
        report_repo: ErrorReportRepository,
        settings_repo: SettingsRepository,
        conn=None,
    ) -> None:
        self._reports = report_repo
        self._settings = settings_repo
        self._conn = conn

    # ------------------------------------------------------------------
    # Capture
    # ------------------------------------------------------------------

    def capture_crash(
        self,
        exc_type: Type[BaseException],
        exc_value: BaseException,
        exc_tb: Optional[TracebackType],
    ) -> ErrorReport:
        """Capture an unhandled exception as a crash report."""
        tb_text = "".join(tb_module.format_exception(exc_type, exc_value, exc_tb))
        if len(tb_text) > _MAX_TRACEBACK_LEN:
            tb_text = "…" + tb_text[-_MAX_TRACEBACK_LEN:]

        report = self._build_report(
            error_type=ERROR_TYPE_CRASH,
            error_message=f"{exc_type.__name__}: {exc_value}",
            traceback_text=tb_text,
        )
        return self._reports.save(report)

    def capture_manual(self, user_note: str) -> ErrorReport:
        """Capture a user-initiated problem report."""
        report = self._build_report(
            error_type=ERROR_TYPE_MANUAL,
            error_message="User-reported issue",
            user_note=user_note,
        )
        return self._reports.save(report)

    # ------------------------------------------------------------------
    # Send
    # ------------------------------------------------------------------

    def send_report(self, report: ErrorReport) -> bool:
        """Send a report to the configured endpoint. Returns True on success."""
        endpoint = self._settings.get("report_endpoint") or ""
        if not endpoint.strip():
            logger.warning("No report endpoint configured — report queued locally.")
            return False

        payload = self._build_payload(report)
        try:
            data = json.dumps(payload).encode("utf-8")
            req = urllib.request.Request(
                endpoint,
                data=data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=_SEND_TIMEOUT) as resp:
                if resp.status < 300:
                    self._reports.mark_sent(report.report_id)
                    logger.info(f"Error report {report.report_id} sent successfully.")
                    return True
                else:
                    logger.warning(
                        f"Report endpoint returned {resp.status} for {report.report_id}"
                    )
                    return False
        except (urllib.error.URLError, OSError) as e:
            logger.warning(f"Failed to send report {report.report_id}: {e}")
            return False

    def retry_unsent(self) -> int:
        """Retry sending any queued (unsent) reports. Returns count sent."""
        unsent = self._reports.get_unsent()
        if not unsent:
            return 0

        sent = 0
        for report in unsent[:10]:  # cap retries per startup
            if self.send_report(report):
                sent += 1
        if sent:
            logger.info(f"Retried {sent}/{len(unsent)} queued error reports.")
        return sent

    def auto_send_enabled(self) -> bool:
        """Check if automatic crash reporting is enabled."""
        return self._settings.get("auto_send_crashes") != "0"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _build_report(
        self,
        error_type: str,
        error_message: Optional[str] = None,
        traceback_text: Optional[str] = None,
        user_note: Optional[str] = None,
    ) -> ErrorReport:
        ctx = self._collect_context()
        return ErrorReport(
            report_id=str(uuid.uuid4()),
            error_type=error_type,
            error_message=error_message,
            traceback=traceback_text,
            oh_version=ctx["oh_version"],
            os_version=ctx["os_version"],
            python_version=ctx["python_version"],
            db_stats=json.dumps(ctx["db_stats"]),
            log_tail=ctx["log_tail"],
            user_note=user_note,
            created_at=utcnow(),
        )

    def _collect_context(self) -> dict:
        """Gather technical context — no client data."""
        try:
            from oh.version import BUILD_VERSION
        except ImportError:
            BUILD_VERSION = "dev"

        db_stats = self._get_db_stats()
        log_tail = self._read_log_tail()

        return {
            "oh_version": BUILD_VERSION,
            "os_version": f"{platform.system()} {platform.version()}",
            "python_version": platform.python_version(),
            "db_stats": db_stats,
            "log_tail": log_tail,
        }

    # Table names used for DB stats — hardcoded whitelist, never user input
    _STAT_TABLES = {
        "oh_devices": "devices",
        "oh_accounts": "accounts",
        "fbr_snapshots": "fbr_snapshots",
        "session_snapshots": "sessions",
    }

    def _get_db_stats(self) -> dict:
        """Get anonymous DB statistics (counts only)."""
        stats = {}
        if self._conn is None:
            return stats
        try:
            for table, key in self._STAT_TABLES.items():
                try:
                    # Table names from hardcoded whitelist above — safe
                    row = self._conn.execute(
                        "SELECT COUNT(*) as cnt FROM " + table
                    ).fetchone()
                    stats[key] = row["cnt"] if row else 0
                except Exception:
                    stats[key] = -1
        except Exception:
            pass
        return stats

    def _read_log_tail(self, lines: int = _MAX_LOG_LINES) -> str:
        """Read last N lines from oh.log."""
        try:
            app_data = os.environ.get("APPDATA") or str(Path.home())
            log_file = Path(app_data) / "OH" / "logs" / "oh.log"
            if not log_file.exists():
                return "(log file not found)"
            with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                all_lines = f.readlines()
            tail = all_lines[-lines:] if len(all_lines) > lines else all_lines
            return "".join(tail)
        except Exception as e:
            return f"(failed to read log: {e})"

    def _build_payload(self, report: ErrorReport) -> dict:
        """Build Discord-webhook-compatible payload."""
        fields = []
        if report.traceback:
            tb_display = report.traceback
            if len(tb_display) > 1000:
                tb_display = "…" + tb_display[-1000:]
            fields.append({
                "name": "Traceback",
                "value": f"```\n{tb_display}\n```",
                "inline": False,
            })

        fields.append({"name": "Version", "value": report.oh_version, "inline": True})
        fields.append({"name": "OS", "value": report.os_version, "inline": True})
        fields.append({"name": "Python", "value": report.python_version, "inline": True})

        if report.db_stats:
            try:
                stats = json.loads(report.db_stats)
                stats_str = ", ".join(f"{k}: {v}" for k, v in stats.items())
            except Exception:
                stats_str = report.db_stats
            fields.append({"name": "DB Stats", "value": stats_str, "inline": False})

        if report.user_note:
            fields.append({
                "name": "User Note",
                "value": report.user_note[:500],
                "inline": False,
            })

        # Color: red for crash, yellow for manual
        color = 15158332 if report.error_type == ERROR_TYPE_CRASH else 16776960

        return {
            "content": f"**OH Error Report** — {report.error_type}",
            "embeds": [{
                "title": f"{report.error_type} | v{report.oh_version} | {report.report_id[:8]}",
                "description": report.error_message or "(no message)",
                "fields": fields,
                "color": color,
                "timestamp": report.created_at,
            }],
        }
