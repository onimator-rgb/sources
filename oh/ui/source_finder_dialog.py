"""
SourceFinderDialog -- modal dialog for discovering similar Instagram profiles.

Shows a progress bar during the search pipeline, then a results table
with checkboxes to add selected profiles to sources.txt.
"""
import logging
from typing import Optional, List

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QProgressBar, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QFrame, QWidget,
    QMessageBox, QCheckBox,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QKeySequence, QShortcut

from oh.models.source_finder import SourceSearchResult, SourceCandidate
from oh.ui.style import sc

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Table columns
# ---------------------------------------------------------------------------

COL_CHECK     = 0
COL_RANK      = 1
COL_USERNAME  = 2
COL_FOLLOWERS = 3
COL_ER        = 4
COL_CATEGORY  = 5
COL_AI_SCORE  = 6
COL_SOURCE    = 7

_HEADERS = ["", "#", "Username", "Followers", "ER%", "Category", "AI Score", "Source"]


# ---------------------------------------------------------------------------
# Sortable numeric item
# ---------------------------------------------------------------------------

class _NumericItem(QTableWidgetItem):
    """QTableWidgetItem that sorts by numeric value, not lexicographic order."""

    def __lt__(self, other: QTableWidgetItem) -> bool:
        try:
            return float(self.text().replace(",", "")) < float(other.text().replace(",", ""))
        except ValueError:
            return self.text() < other.text()


# ---------------------------------------------------------------------------
# Worker thread — custom because we need mid-pipeline progress
# ---------------------------------------------------------------------------

class SourceFinderWorker(QThread):
    """Runs the source-finder pipeline on a background thread."""

    progress = Signal(int, str)
    finished = Signal(list)
    error = Signal(str)

    def __init__(self, service, account_id: int) -> None:
        super().__init__()
        self._service = service
        self._account_id = account_id
        self._cancelled = False

    @property
    def is_cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        try:
            results = self._service.run_search(
                self._account_id,
                progress_callback=self._on_progress,
                cancel_check=lambda: self._cancelled,
            )
            if self._cancelled:
                return
            self.finished.emit(results)
        except Exception as e:
            if not self._cancelled:
                logger.exception("SourceFinderWorker error: %s", e)
                self.error.emit(str(e))

    def _on_progress(self, pct: int, msg: str) -> None:
        if not self._cancelled:
            self.progress.emit(pct, msg)

    def cancel(self) -> None:
        self._cancelled = True


# ---------------------------------------------------------------------------
# Dialog
# ---------------------------------------------------------------------------

class SourceFinderDialog(QDialog):
    """
    Find Sources dialog: runs the source-finder pipeline, shows results,
    and lets the operator add selected profiles to sources.txt.
    """

    def __init__(
        self,
        parent,
        service,
        account_id: int,
        username: str,
        bot_root: str,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._account_id = account_id
        self._username = username
        self._bot_root = bot_root
        self._results: List[SourceSearchResult] = []
        self._checkboxes: List[QCheckBox] = []
        self._worker: Optional[SourceFinderWorker] = None
        self._add_completed: bool = False

        self.setWindowTitle(f"Find Sources \u2014 @{username}")
        self.setMinimumSize(800, 600)
        self.setModal(True)

        self._build_ui()
        QShortcut(QKeySequence("Escape"), self, self.close)
        self._start_search()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)
        lo.setSpacing(8)
        lo.setContentsMargins(12, 12, 12, 12)

        # Header
        self._header = QLabel(f"Finding similar profiles for @{self._username}...")
        self._header.setStyleSheet(
            f"font-size: 14px; color: {sc('heading').name()};"
        )
        lo.addWidget(self._header)

        # Progress section
        self._progress_frame = QFrame()
        progress_lo = QVBoxLayout(self._progress_frame)
        progress_lo.setContentsMargins(0, 4, 0, 4)
        progress_lo.setSpacing(6)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(20)
        progress_lo.addWidget(self._progress_bar)

        self._step_label = QLabel("Starting search...")
        self._step_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()};"
        )
        progress_lo.addWidget(self._step_label)

        cancel_lo = QHBoxLayout()
        cancel_lo.setContentsMargins(0, 0, 0, 0)
        cancel_lo.addStretch()
        self._cancel_btn = QPushButton("Cancel")
        self._cancel_btn.setFixedWidth(80)
        self._cancel_btn.clicked.connect(self._on_cancel)
        cancel_lo.addWidget(self._cancel_btn)
        progress_lo.addLayout(cancel_lo)

        lo.addWidget(self._progress_frame)

        # Summary label (hidden until results)
        self._summary_label = QLabel("")
        self._summary_label.setStyleSheet(
            f"font-size: 11px; color: {sc('text_secondary').name()}; padding: 2px 0;"
        )
        self._summary_label.setVisible(False)
        lo.addWidget(self._summary_label)

        # Select All / Deselect All buttons (hidden until results)
        self._select_frame = QFrame()
        select_lo = QHBoxLayout(self._select_frame)
        select_lo.setContentsMargins(0, 0, 0, 0)
        select_lo.setSpacing(6)
        self._select_all_btn = QPushButton("Select All")
        self._select_all_btn.setFixedWidth(90)
        self._select_all_btn.clicked.connect(self._on_select_all)
        select_lo.addWidget(self._select_all_btn)
        self._deselect_all_btn = QPushButton("Deselect All")
        self._deselect_all_btn.setFixedWidth(90)
        self._deselect_all_btn.clicked.connect(self._on_deselect_all)
        select_lo.addWidget(self._deselect_all_btn)
        select_lo.addStretch()
        self._select_frame.setVisible(False)
        lo.addWidget(self._select_frame)

        # Results table (hidden until results)
        self._table = self._make_table()
        self._table.setVisible(False)
        lo.addWidget(self._table, stretch=1)

        # Footer
        lo.addWidget(self._make_footer())

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_HEADERS))
        t.setHorizontalHeaderLabels(_HEADERS)
        t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setAlternatingRowColors(True)
        t.verticalHeader().setVisible(False)
        t.setShowGrid(True)
        t.setSortingEnabled(False)
        t.setWordWrap(False)

        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(COL_CHECK, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_RANK, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_USERNAME, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(COL_FOLLOWERS, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_ER, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_CATEGORY, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_AI_SCORE, QHeaderView.ResizeMode.Fixed)
        hdr.setSectionResizeMode(COL_SOURCE, QHeaderView.ResizeMode.Fixed)

        t.setColumnWidth(COL_CHECK, 35)
        t.setColumnWidth(COL_RANK, 35)
        t.setColumnWidth(COL_FOLLOWERS, 90)
        t.setColumnWidth(COL_ER, 60)
        t.setColumnWidth(COL_CATEGORY, 120)
        t.setColumnWidth(COL_AI_SCORE, 70)
        t.setColumnWidth(COL_SOURCE, 90)

        return t

    def _make_footer(self) -> QWidget:
        w = QWidget()
        lo = QHBoxLayout(w)
        lo.setContentsMargins(0, 4, 0, 0)

        self._status_label = QLabel("Ready")
        self._status_label.setStyleSheet(
            f"color: {sc('text_secondary').name()}; font-size: 11px;"
        )
        lo.addWidget(self._status_label, stretch=1)

        self._add_btn = QPushButton("Add Selected to sources.txt")
        self._add_btn.setFixedHeight(32)
        self._add_btn.setStyleSheet(
            f"QPushButton {{ background: {sc('success').name()}; color: white; "
            f"border-radius: 4px; padding: 5px 14px; }}"
            f"QPushButton:hover {{ background: {sc('status_ok').name()}; }}"
            f"QPushButton:disabled {{ background: {sc('muted').name()}; "
            f"color: {sc('text_secondary').name()}; }}"
        )
        self._add_btn.setToolTip("Append selected usernames to this account's sources.txt file")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._on_add_selected)
        lo.addWidget(self._add_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedWidth(80)
        close_btn.clicked.connect(self._on_close)
        lo.addWidget(close_btn)

        return w

    # ------------------------------------------------------------------
    # Search lifecycle
    # ------------------------------------------------------------------

    def _start_search(self) -> None:
        self._worker = SourceFinderWorker(self._service, self._account_id)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, pct: int, msg: str) -> None:
        self._progress_bar.setValue(pct)
        self._step_label.setText(msg)

    def _on_finished(self, results: list) -> None:
        self._results = results
        self._progress_frame.setVisible(False)

        if not results:
            self._header.setText(
                f"No similar profiles found for @{self._username}.\n"
                "This can happen if the account is private, new, "
                "or in a very niche category."
            )
            self._header.setWordWrap(True)
            self._header.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._header.setStyleSheet(
                f"font-size: 14px; color: {sc('heading').name()}; padding-top: 40px;"
            )
            self._status_label.setText("Search completed with no results.")
            return

        # Build summary — get search query via service public method
        query = ""
        try:
            query = self._service.get_latest_search_query(self._account_id) or ""
        except Exception:
            pass

        summary = f"Found {len(results)} profiles"
        if query:
            summary += f". Query: '{query}'"
        self._summary_label.setText(summary)
        self._summary_label.setVisible(True)

        self._header.setText(f"Similar profiles for @{self._username}")

        # Populate table
        self._populate_table(results)
        self._select_frame.setVisible(True)
        self._table.setVisible(True)
        self._update_add_btn()

    def _on_error(self, error: str) -> None:
        self._progress_frame.setVisible(False)
        logger.error("Source finder error for @%s: %s", self._username, error)
        QMessageBox.critical(
            self,
            "Search Failed",
            f"Source search failed for @{self._username}:\n\n{error}",
        )
        self._status_label.setText("Search failed.")

    def _on_cancel(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(3000)
            self._worker = None
        self.reject()

    def _on_close(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._on_cancel()
        else:
            self.accept()

    # ------------------------------------------------------------------
    # Table population
    # ------------------------------------------------------------------

    def _populate_table(self, results: List[SourceSearchResult]) -> None:
        self._table.setSortingEnabled(False)
        self._table.setRowCount(len(results))
        self._checkboxes.clear()

        center = Qt.AlignmentFlag.AlignCenter
        right = Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter

        for row, result in enumerate(results):
            cand = result.candidate

            # Checkbox
            cb = QCheckBox()
            cb.setChecked(True)
            cb.stateChanged.connect(self._update_add_btn)
            self._checkboxes.append(cb)
            cb_widget = QFrame()
            cb_lo = QHBoxLayout(cb_widget)
            cb_lo.setContentsMargins(0, 0, 0, 0)
            cb_lo.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cb_lo.addWidget(cb)
            self._table.setCellWidget(row, COL_CHECK, cb_widget)

            # Rank
            rank_item = QTableWidgetItem(str(result.rank))
            rank_item.setTextAlignment(center)
            self._table.setItem(row, COL_RANK, rank_item)

            # Username
            username_text = cand.username if cand else "?"
            self._table.setItem(row, COL_USERNAME, QTableWidgetItem(username_text))

            # Followers
            if cand and cand.follower_count:
                followers_item = _NumericItem(f"{cand.follower_count:,}")
            else:
                followers_item = _NumericItem("--")
            followers_item.setTextAlignment(right)
            self._table.setItem(row, COL_FOLLOWERS, followers_item)

            # ER%
            if cand and cand.avg_er is not None:
                er_item = _NumericItem(f"{cand.avg_er:.1f}")
            else:
                er_item = _NumericItem("--")
            er_item.setTextAlignment(right)
            self._table.setItem(row, COL_ER, er_item)

            # Category
            category_text = cand.ai_category if cand and cand.ai_category else "--"
            cat_item = QTableWidgetItem(category_text)
            cat_item.setTextAlignment(center)
            self._table.setItem(row, COL_CATEGORY, cat_item)

            # AI Score
            if cand and cand.ai_score is not None:
                score_item = _NumericItem(f"{cand.ai_score:.1f}")
                if cand.ai_score >= 7.0:
                    score_item.setForeground(sc("success"))
                elif cand.ai_score >= 4.0:
                    score_item.setForeground(sc("warning"))
                else:
                    score_item.setForeground(sc("muted"))
            else:
                score_item = _NumericItem("--")
                score_item.setForeground(sc("muted"))
            score_item.setTextAlignment(right)
            self._table.setItem(row, COL_AI_SCORE, score_item)

            # Source type
            source_text = cand.source_type if cand else "--"
            src_item = QTableWidgetItem(source_text)
            src_item.setTextAlignment(center)
            self._table.setItem(row, COL_SOURCE, src_item)

        self._table.setSortingEnabled(True)

    # ------------------------------------------------------------------
    # Add to sources
    # ------------------------------------------------------------------

    def _update_add_btn(self) -> None:
        checked_count = sum(1 for cb in self._checkboxes if cb.isChecked())
        total = len(self._checkboxes)
        self._add_btn.setEnabled(checked_count > 0 and not self._add_completed)
        if total > 0 and not self._add_completed:
            self._status_label.setText(f"{checked_count} of {total} selected")

    def _on_select_all(self) -> None:
        for cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(True)

    def _on_deselect_all(self) -> None:
        for cb in self._checkboxes:
            if cb.isEnabled():
                cb.setChecked(False)

    def _on_add_selected(self) -> None:
        from oh.services.source_finder_service import SourceFinderService

        selected = []
        for i, cb in enumerate(self._checkboxes):
            if cb.isChecked() and i < len(self._results):
                selected.append(self._results[i])

        if not selected:
            return

        self._add_btn.setEnabled(False)
        self._status_label.setText("Adding sources...")

        added = 0
        already = 0
        errors = []
        for result in selected:
            try:
                status = self._service.add_to_sources(
                    result.id, self._account_id, self._bot_root
                )
                if status == SourceFinderService.ADD_OK:
                    added += 1
                elif status == SourceFinderService.ADD_ALREADY:
                    already += 1
                else:
                    cand = result.candidate
                    name = cand.username if cand else f"result #{result.rank}"
                    errors.append(name)
            except Exception as e:
                cand = result.candidate
                name = cand.username if cand else f"result #{result.rank}"
                errors.append(f"{name}: {e}")
                logger.warning("Failed to add source %s: %s", name, e)

        # Mark add as completed only if there were no failures
        if not errors:
            self._add_completed = True
        else:
            # Disable checkboxes for successfully-added rows so they can't be double-added
            for i, cb in enumerate(self._checkboxes):
                if cb.isChecked() and i < len(self._results):
                    result = self._results[i]
                    cand = result.candidate
                    name = cand.username if cand else f"result #{result.rank}"
                    # If this row's name is not in the errors list, it succeeded
                    if not any(name in err for err in errors):
                        cb.setChecked(False)
                        cb.setEnabled(False)

        # Build summary message
        parts = []
        if added:
            parts.append(f"{added} added")
        if already:
            parts.append(f"{already} already in sources")
        if errors:
            parts.append(f"{len(errors)} failed")

        if parts:
            self._status_label.setText(", ".join(parts))
        else:
            self._status_label.setText("No changes made")

        if errors:
            logger.warning(
                "Source add errors for @%s: %s",
                self._username, "; ".join(errors),
            )

        logger.info(
            "Source finder: %d added, %d already existed, "
            "%d failed out of %d selected for @%s",
            added, already, len(errors), len(selected), self._username,
        )

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    def closeEvent(self, event) -> None:
        if self._worker is not None and self._worker.isRunning():
            self._worker.cancel()
            self._worker.quit()
            self._worker.wait(3000)
        super().closeEvent(event)
