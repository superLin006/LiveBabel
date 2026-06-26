"""听写草稿小浮窗:说话时实时显示流式草稿,松开后显示最终文本一瞬再淡出。

无边框、置顶、半透明、不抢焦点(否则注入会注到浮窗自己)。单行,无翻译。
所有方法须在 Qt 主线程调用(由 DictationService 的信号驱动)。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QLabel, QWidget

from livebabel.ui.gui_common import FONT


class DictationOverlay(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 关键:不抢焦点,否则模拟粘贴会注入到浮窗而非目标输入框
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.NoFocus)

        self._label = QLabel("", self)
        self._label.setAlignment(Qt.AlignCenter)
        self._label.setWordWrap(False)
        self._fade = QTimer(self)
        self._fade.setSingleShot(True)
        self._fade.timeout.connect(self.hide)

        self._apply_style(recording=True)
        self.resize(520, 56)

    def _apply_style(self, recording: bool) -> None:
        # 录音中草稿=灰;最终=深色
        color = "#8E8E93" if recording else "#1C1C1E"
        self._label.setStyleSheet(
            f"QLabel {{ color: {color}; background: rgba(255,255,255,235);"
            f" border-radius: 14px; padding: 10px 18px;"
            f" font-family: {FONT}; font-size: 17px; }}"
        )

    def _reposition(self) -> None:
        scr = QGuiApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.availableGeometry()
        self._label.adjustSize()
        w = max(240, min(self._label.width() + 8, geo.width() - 80))
        self.resize(w, self._label.height() + 8)
        self._label.resize(w, self.height())
        x = geo.x() + (geo.width() - w) // 2
        y = geo.y() + int(geo.height() * 0.82)   # 屏幕底部偏上
        self.move(x, y)

    # ---------- 供 service 信号调用 ----------

    def show_draft(self, text: str) -> None:
        self._fade.stop()
        self._apply_style(recording=True)
        self._label.setText(text or "🎙 说话中…")
        self._reposition()
        if not self.isVisible():
            self.show()

    def show_final(self, text: str) -> None:
        if not text:
            self.fade_out()
            return
        self._fade.stop()
        self._apply_style(recording=False)
        self._label.setText(text)
        self._reposition()
        self.show()
        self._fade.start(900)   # 显示一瞬后淡出

    def fade_out(self) -> None:
        self._fade.start(300)
