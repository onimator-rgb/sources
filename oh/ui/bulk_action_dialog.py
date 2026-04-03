"""
BulkActionDialog — confirmation and execution of bulk operator actions.

Shows a count of affected accounts, optional note field (for review),
executes the action, and shows a results summary.
"""
import logging
from typing import Callable, List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QLineEdit, QMessageBox, QProgressBar,
)
from PySide6.QtCore import Qt

logger = logging.getLogger(__name__)


class BulkActionDialog(QDialog):
    """Confirm and execute a bulk action on multiple accounts."""

    def __init__(
        self,
        action_name: str,
        account_ids: List[int],
        action_fn: Callable,
        show_note: bool = False,
        parent=None,
    ) -> None:
        """
        Args:
            action_name: Display name ("Set Review", "TB +1", etc.)
            account_ids: List of account IDs to act on
            action_fn: Callable(account_id, note=None) -> str
            show_note: Show optional note field (for review actions)
        """
        super().__init__(parent)
        self._action_name = action_name
        self._account_ids = account_ids
        self._action_fn = action_fn
        self._show_note = show_note
        self._results: List[str] = []

        self.setWindowTitle(f"Bulk Action: {action_name}")
        self.setMinimumWidth(400)
        self._build_ui()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)

        lo.addWidget(QLabel(
            f"<b>{self._action_name}</b> on <b>{len(self._account_ids)}</b> accounts?"
        ))

        if self._show_note:
            lo.addWidget(QLabel("Note (optional):"))
            self._note_edit = QLineEdit()
            self._note_edit.setPlaceholderText("Enter reason...")
            lo.addWidget(self._note_edit)
        else:
            self._note_edit = None

        self._progress = QProgressBar()
        self._progress.setRange(0, len(self._account_ids))
        self._progress.setValue(0)
        self._progress.setVisible(False)
        lo.addWidget(self._progress)

        self._result_label = QLabel("")
        lo.addWidget(self._result_label)

        btn_row = QHBoxLayout()
        self._confirm_btn = QPushButton("Confirm")
        self._confirm_btn.setDefault(True)
        self._confirm_btn.clicked.connect(self._execute)
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(self._confirm_btn)
        btn_row.addWidget(self._cancel_btn)
        lo.addLayout(btn_row)

    def _execute(self) -> None:
        self._confirm_btn.setEnabled(False)
        self._cancel_btn.setText("Close")
        self._progress.setVisible(True)

        note = self._note_edit.text().strip() if self._note_edit else None
        ok_count = 0
        fail_count = 0

        for i, acc_id in enumerate(self._account_ids):
            try:
                if self._show_note:
                    result = self._action_fn(acc_id, note)
                else:
                    result = self._action_fn(acc_id)
                ok_count += 1
                self._results.append(result)
            except Exception as exc:
                fail_count += 1
                logger.warning(f"Bulk action failed for account {acc_id}: {exc}")
            self._progress.setValue(i + 1)

        summary = f"Done: {ok_count} ok"
        if fail_count:
            summary += f", {fail_count} failed"
        self._result_label.setText(summary)
        logger.info(
            f"Bulk {self._action_name}: {ok_count} ok, {fail_count} failed "
            f"of {len(self._account_ids)} total"
        )
