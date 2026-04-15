"""
SourcesTabContainer — wrapper that holds Follow Sources and Like Sources as sub-tabs.

Replaces the direct SourcesTab in the main tab bar with a QTabWidget containing
two sub-tabs.  Delegates load_data() and set_bot_root() to both children.
"""
import logging
from typing import Optional

from PySide6.QtWidgets import QWidget, QVBoxLayout, QTabWidget

logger = logging.getLogger(__name__)


class SourcesTabContainer(QWidget):
    """
    Container widget with a QTabWidget holding:
      - Tab 0: "Follow Sources" -> existing SourcesTab (unchanged)
      - Tab 1: "Like Sources"   -> new LikeSourcesTab
    """

    def __init__(
        self,
        follow_sources_tab: QWidget,
        like_sources_tab: QWidget,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._follow_tab = follow_sources_tab
        self._like_tab = like_sources_tab
        self._like_tab_loaded = False

        lo = QVBoxLayout(self)
        lo.setContentsMargins(0, 0, 0, 0)
        lo.setSpacing(0)

        self._sub_tabs = QTabWidget()
        self._sub_tabs.addTab(self._follow_tab, "Follow Sources")
        self._sub_tabs.addTab(self._like_tab, "Like Sources")
        self._sub_tabs.currentChanged.connect(self._on_sub_tab_changed)
        lo.addWidget(self._sub_tabs)

    # ------------------------------------------------------------------
    # Public interface — called by MainWindow
    # ------------------------------------------------------------------

    def load_data(self) -> None:
        """
        Load data for the currently visible sub-tab.
        The other sub-tab loads lazily when selected.
        """
        idx = self._sub_tabs.currentIndex()
        if idx == 0:
            self._follow_tab.load_data()
        else:
            self._like_tab.load_data()
            self._like_tab_loaded = True

    def set_bot_root(self, bot_root: Optional[str]) -> None:
        """Delegate bot root to both sub-tabs."""
        self._follow_tab.set_bot_root(bot_root)
        self._like_tab.set_bot_root(bot_root)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _on_sub_tab_changed(self, index: int) -> None:
        """Lazy-load the sub-tab when it becomes active."""
        if index == 0:
            self._follow_tab.load_data()
        elif index == 1:
            self._like_tab.load_data()
            self._like_tab_loaded = True
