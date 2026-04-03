"""
SparklineWidget — mini line chart for embedding in table cells.

Draws a polyline through data points with a subtle fill gradient,
a last-point dot, and a trend arrow indicator.

Usage:
    widget = SparklineWidget(values=[45, 52, 48, 65, 70], color="#4CAF50")
"""
from typing import List, Optional

from PySide6.QtWidgets import QWidget
from PySide6.QtCore import Qt, QSize, QPointF, QRectF
from PySide6.QtGui import (
    QPainter, QPen, QColor, QLinearGradient, QPolygonF, QPainterPath,
)

# Re-export from trend_service (canonical location) to avoid circular imports
from oh.services.trend_service import (
    compute_trend, TREND_UP, TREND_DOWN, TREND_STABLE, TREND_NONE,
)


# Trend arrow unicode + color
_TREND_ARROWS = {
    TREND_UP:     ("\u25b2", "#4CAF50"),   # ▲ green
    TREND_DOWN:   ("\u25bc", "#F44336"),   # ▼ red
    TREND_STABLE: ("\u25ac", "#9E9E9E"),   # ▬ gray
    TREND_NONE:   ("",       "#9E9E9E"),
}


class SparklineWidget(QWidget):
    """Mini line chart widget suitable for table cells."""

    def __init__(
        self,
        values: Optional[List[float]] = None,
        color: str = "#4CAF50",
        width: int = 80,
        height: int = 24,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._values: List[float] = values or []
        self._color = QColor(color)
        self._w = width
        self._h = height
        self.setFixedSize(width, height)

    def set_values(self, values: List[float], color: Optional[str] = None) -> None:
        """Update data and optionally the line color."""
        self._values = values
        if color:
            self._color = QColor(color)
        self.update()

    def sizeHint(self) -> QSize:
        return QSize(self._w, self._h)

    def paintEvent(self, event) -> None:
        if not self._values or len(self._values) < 2:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        values = self._values
        n = len(values)
        min_v = min(values)
        max_v = max(values)
        val_range = max_v - min_v if max_v != min_v else 1.0

        margin_x = 2
        margin_y = 3
        chart_w = self._w - 2 * margin_x - 14  # leave space for trend arrow
        chart_h = self._h - 2 * margin_y

        # Compute points
        points: List[QPointF] = []
        for i, v in enumerate(values):
            x = margin_x + (i / (n - 1)) * chart_w
            y = margin_y + chart_h - ((v - min_v) / val_range) * chart_h
            points.append(QPointF(x, y))

        # Fill gradient under the line
        polygon_points = list(points)
        polygon_points.append(QPointF(points[-1].x(), margin_y + chart_h))
        polygon_points.append(QPointF(points[0].x(), margin_y + chart_h))

        fill_color = QColor(self._color)
        gradient = QLinearGradient(0, margin_y, 0, margin_y + chart_h)
        fill_color.setAlpha(60)
        gradient.setColorAt(0, fill_color)
        fill_color.setAlpha(10)
        gradient.setColorAt(1, fill_color)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(gradient)
        painter.drawPolygon(QPolygonF(polygon_points))

        # Draw line
        pen = QPen(self._color, 1.5)
        painter.setPen(pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPolyline(QPolygonF(points))

        # Last point dot
        last = points[-1]
        painter.setBrush(self._color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(last, 2.5, 2.5)

        # Trend arrow
        trend = compute_trend(values)
        arrow_text, arrow_color = _TREND_ARROWS.get(trend, ("", "#9E9E9E"))
        if arrow_text:
            painter.setPen(QColor(arrow_color))
            font = painter.font()
            font.setPixelSize(10)
            painter.setFont(font)
            arrow_x = self._w - 12
            arrow_y = self._h // 2 + 4
            painter.drawText(int(arrow_x), int(arrow_y), arrow_text)

        painter.end()
