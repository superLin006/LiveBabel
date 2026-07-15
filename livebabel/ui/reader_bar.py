"""朗读迷你播放条:嵌入页面(非悬浮窗),浅色苹果风,和 gui_common 主题统一。

不朗读时完全隐藏(不占地方);点朗读后出现,显示"朗读中 第N句"+暂停/停止。
纯 UI + 状态展示,后台合成/播放由 MinutesReader 驱动,本组件只管呈现和转发点击。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

from livebabel.ui.gui_common import ACCENT, BORDER, CARD, SUBTEXT, TEXT


class ReaderBar(QWidget):
    def __init__(self, on_toggle_pause, on_stop, parent=None) -> None:
        super().__init__(parent)
        self._on_toggle_pause = on_toggle_pause
        self._on_stop = on_stop

        self.setStyleSheet(
            f"ReaderBar {{ background: {CARD}; border: 1px solid {BORDER};"
            f" border-radius: 10px; }}"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(14, 8, 10, 8)
        row.setSpacing(10)

        self._icon = QLabel("🔊")
        self._icon.setStyleSheet("background: transparent; font-size: 15px;")
        row.addWidget(self._icon)

        self._label = QLabel("朗读中…")
        self._label.setStyleSheet(
            f"color: {TEXT}; background: transparent; font-size: 13px;")
        row.addWidget(self._label, 1)

        btn_css = (
            f"QPushButton {{ background: transparent; border: 1px solid {BORDER};"
            f" border-radius: 6px; padding: 4px 12px; font-size: 12px; color: {TEXT}; }}"
            f"QPushButton:hover {{ background: {BORDER}; }}"
        )
        self._btn_pause = QPushButton("暂停")
        self._btn_pause.setStyleSheet(btn_css)
        self._btn_pause.clicked.connect(self._toggle_pause)
        row.addWidget(self._btn_pause)

        self._btn_stop = QPushButton("✕")
        self._btn_stop.setStyleSheet(btn_css)
        self._btn_stop.setFixedWidth(30)
        self._btn_stop.clicked.connect(self._on_stop)
        row.addWidget(self._btn_stop)

        self.hide()

    def _toggle_pause(self) -> None:
        self._on_toggle_pause()

    # ---- 供服务层信号调用(均在 Qt 主线程) ----

    def show_reading(self) -> None:
        self._btn_pause.setText("暂停")
        self._label.setText("朗读中…")
        self.show()

    def update_progress(self, idx: int, total: int) -> None:
        n = f"{idx + 1}/{total}" if total > 0 else f"{idx + 1}"
        self._label.setText(f"朗读中  第 {n} 句")

    def set_paused(self, paused: bool) -> None:
        self._btn_pause.setText("继续" if paused else "暂停")
        if paused:
            self._label.setText("已暂停")

    def hide_bar(self) -> None:
        self.hide()
