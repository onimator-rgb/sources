"""
Shared table utilities for OH UI layer.
"""
from PySide6.QtWidgets import QTableWidgetItem


class SortableItem(QTableWidgetItem):
    """QTableWidgetItem sorted by an explicit key rather than display text."""

    def __init__(self, display_text: str, sort_key) -> None:
        super().__init__(display_text)
        self._sort_key = sort_key

    def __lt__(self, other: QTableWidgetItem) -> bool:
        if isinstance(other, SortableItem):
            try:
                return self._sort_key < other._sort_key
            except TypeError:
                return str(self._sort_key) < str(other._sort_key)
        return self.text() < other.text()
