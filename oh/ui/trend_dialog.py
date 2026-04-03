"""
TrendDialog — larger trend charts for a single account.

Shows 4 sections:
  1. Daily follows (sparkline)
  2. Health score trend
  3. FBR% trend
  4. Summary text

Opened by double-clicking the Trend column or via a toolbar button.
"""
import logging
from typing import List, Optional

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QComboBox, QGroupBox, QApplication,
)
from PySide6.QtCore import Qt

from oh.services.trend_service import TrendService
from oh.ui.sparkline_widget import SparklineWidget, compute_trend, TREND_UP, TREND_DOWN

logger = logging.getLogger(__name__)


class TrendDialog(QDialog):
    def __init__(
        self,
        trend_service: TrendService,
        account_id: int,
        username: str,
        device_name: str,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._service = trend_service
        self._account_id = account_id
        self._username = username
        self._days = 14

        self.setWindowTitle(f"Performance Trends — {username}")
        self.setMinimumSize(500, 400)
        self._build_ui()
        self._load_data()

    def _build_ui(self) -> None:
        lo = QVBoxLayout(self)

        # Header
        header = QLabel(f"<b>{self._username}</b>")
        header.setStyleSheet("font-size: 14px;")
        lo.addWidget(header)

        # Date range selector
        range_row = QHBoxLayout()
        range_row.addWidget(QLabel("Period:"))
        self._range_combo = QComboBox()
        self._range_combo.addItems(["7 days", "14 days", "30 days"])
        self._range_combo.setCurrentIndex(1)
        self._range_combo.currentIndexChanged.connect(self._on_range_changed)
        range_row.addWidget(self._range_combo)
        range_row.addStretch()
        lo.addLayout(range_row)

        # Follow trend
        follow_group = QGroupBox("Daily Follows")
        follow_lo = QVBoxLayout(follow_group)
        self._follow_spark = SparklineWidget(width=450, height=80, color="#4CAF50")
        follow_lo.addWidget(self._follow_spark)
        self._follow_label = QLabel("")
        self._follow_label.setStyleSheet("font-size: 11px; color: gray;")
        follow_lo.addWidget(self._follow_label)
        lo.addWidget(follow_group)

        # FBR trend
        fbr_group = QGroupBox("FBR% Trend")
        fbr_lo = QVBoxLayout(fbr_group)
        self._fbr_spark = SparklineWidget(width=450, height=80, color="#2196F3")
        fbr_lo.addWidget(self._fbr_spark)
        self._fbr_label = QLabel("")
        self._fbr_label.setStyleSheet("font-size: 11px; color: gray;")
        fbr_lo.addWidget(self._fbr_label)
        lo.addWidget(fbr_group)

        # Copy button
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        copy_btn = QPushButton("Copy Summary")
        copy_btn.clicked.connect(self._on_copy)
        btn_row.addWidget(copy_btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        lo.addLayout(btn_row)

    def _on_range_changed(self) -> None:
        text = self._range_combo.currentText()
        self._days = int(text.split()[0])
        self._load_data()

    def _load_data(self) -> None:
        follows = self._service.get_follow_trend(self._account_id, self._days)
        fbr = self._service.get_fbr_trend(self._account_id, self._days)

        # Follow sparkline
        if follows and any(f > 0 for f in follows):
            self._follow_spark.set_values([float(f) for f in follows], "#4CAF50")
            avg = sum(follows) / len(follows) if follows else 0
            trend = compute_trend([float(f) for f in follows])
            arrow = {"up": "\u25b2", "down": "\u25bc", "stable": "\u25ac"}.get(trend, "")
            self._follow_label.setText(
                f"Avg: {avg:.0f}/day  |  Trend: {arrow} {trend}  |  "
                f"Last {self._days} days, {len(follows)} data points"
            )
        else:
            self._follow_spark.set_values([])
            self._follow_label.setText("No follow data available.")

        # FBR sparkline
        if fbr and len(fbr) >= 2:
            self._fbr_spark.set_values(fbr, "#2196F3")
            avg_fbr = sum(fbr) / len(fbr)
            trend = compute_trend(fbr)
            arrow = {"up": "\u25b2", "down": "\u25bc", "stable": "\u25ac"}.get(trend, "")
            self._fbr_label.setText(
                f"Avg: {avg_fbr:.1f}%  |  Trend: {arrow} {trend}  |  "
                f"{len(fbr)} snapshots"
            )
        else:
            self._fbr_spark.set_values([])
            self._fbr_label.setText("Not enough FBR data for trend.")

    def _on_copy(self) -> None:
        follows = self._service.get_follow_trend(self._account_id, self._days)
        fbr = self._service.get_fbr_trend(self._account_id, self._days)

        lines = [f"Performance Trends — {self._username}"]
        lines.append(f"Period: last {self._days} days")
        lines.append("")

        if follows:
            avg = sum(follows) / len(follows)
            trend = compute_trend([float(f) for f in follows])
            lines.append(f"Follow avg: {avg:.0f}/day, trend: {trend}")
            lines.append(f"Follow data: {follows}")
        else:
            lines.append("No follow data.")

        if fbr:
            avg_f = sum(fbr) / len(fbr)
            trend = compute_trend(fbr)
            lines.append(f"FBR avg: {avg_f:.1f}%, trend: {trend}")

        text = "\n".join(lines)
        QApplication.clipboard().setText(text)
