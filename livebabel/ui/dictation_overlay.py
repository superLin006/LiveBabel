"""听写 HUD 浮窗:深色胶囊(参考 macOS 系统听写)。

体验设计:
  * 按下热键立刻出现「正在聆听…」+ 呼吸红点 —— 即时反馈热键已生效。
  * 说话时两段式草稿:已定稿文字白色,未定稿(volatile)灰色,一眼分清。
  * 松开后红点变绿、显示最终文本一瞬,再平滑淡出 —— 确认"就是这段话进了输入框"。
  * 单行过长时从左侧省略,始终看得到最新说的词。

无边框、置顶、半透明、不抢焦点(否则注入会注到浮窗自己)。
所有方法须在 Qt 主线程调用(由 DictationService 的信号驱动)。
"""

from __future__ import annotations

import html
import math

from PySide6.QtCore import (
    QEasingCurve, QPropertyAnimation, Qt, QTimer, QVariantAnimation,
)
from PySide6.QtGui import QColor, QFontMetrics, QGuiApplication, QPainter
from PySide6.QtWidgets import (
    QGraphicsDropShadowEffect, QHBoxLayout, QLabel, QWidget,
)

# 状态指示点配色(苹果系统色)
DOT_RECORDING = QColor(255, 69, 58)    # 系统红:录音中(呼吸)
DOT_DONE = QColor(48, 209, 88)         # 系统绿:定稿完成(常亮)

TEXT_MAIN = "#F2F2F7"     # 已定稿/最终文字(近白)
TEXT_VOLATILE = "#98989F" # 未定稿草稿(中性灰)

_MARGIN = 26              # 窗口四周留白,给投影留呼吸空间
_HINT = "正在聆听…"
_FINALIZING = "正在整理文字…"


class _PulseDot(QWidget):
    """录音状态指示点:录音中红色呼吸闪动,定稿后绿色常亮。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._color = DOT_RECORDING
        self._level = 1.0            # 0~1 呼吸亮度
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(2 * math.pi)
        self._anim.setDuration(1500)
        self._anim.setLoopCount(-1)  # 无限循环
        self._anim.valueChanged.connect(self._tick)

    def _tick(self, phase: float) -> None:
        # 正弦呼吸:亮度在 0.35~1.0 间往复
        self._level = 0.675 + 0.325 * math.sin(phase)
        self.update()

    def set_recording(self) -> None:
        self._color = DOT_RECORDING
        self._level = 1.0
        self._anim.start()

    def set_done(self) -> None:
        self._anim.stop()
        self._color = DOT_DONE
        self._level = 1.0
        self.update()

    def stop(self) -> None:
        self._anim.stop()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        c = QColor(self._color)
        c.setAlphaF(self._level)
        p.setBrush(c)
        p.setPen(Qt.NoPen)
        # 呼吸时半径也轻微起伏,观感更"活"
        r = 4.6 + 0.8 * self._level
        cx, cy = self.width() / 2, self.height() / 2
        p.drawEllipse(int(cx - r), int(cy - r), int(2 * r), int(2 * r))


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

        # ---- 胶囊本体:深色磨砂 + 细高光描边 + 柔和投影 ----
        self._pill = QWidget(self)
        self._pill.setObjectName("pill")
        self._pill.setStyleSheet(
            "#pill { background: rgba(28,28,30,238);"
            " border: 1px solid rgba(255,255,255,28);"
            " border-radius: 22px; }"
        )
        shadow = QGraphicsDropShadowEffect(self._pill)
        shadow.setBlurRadius(30)
        shadow.setOffset(0, 6)
        shadow.setColor(QColor(0, 0, 0, 100))
        self._pill.setGraphicsEffect(shadow)

        row = QHBoxLayout(self._pill)
        row.setContentsMargins(18, 11, 20, 11)
        row.setSpacing(11)

        self._dot = _PulseDot(self._pill)
        row.addWidget(self._dot, 0, Qt.AlignVCenter)

        self._label = QLabel("", self._pill)
        self._label.setTextFormat(Qt.RichText)
        self._label.setWordWrap(False)
        f = self._label.font()
        f.setFamilies(["PingFang SC", "Microsoft YaHei", "Segoe UI"])
        f.setPixelSize(17)
        self._label.setFont(f)
        self._label.setStyleSheet(
            f"color: {TEXT_MAIN}; background: transparent;")
        row.addWidget(self._label, 1, Qt.AlignVCenter)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(_MARGIN, _MARGIN, _MARGIN, _MARGIN)
        outer.addWidget(self._pill)

        # ---- 状态 ----
        self._active = False   # 当前是否处于一轮听写(False 时忽略残留草稿)

        # 定稿停留计时:显示最终文本一瞬后触发淡出
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._fade_out)

        # 透明度动画(淡入/淡出共用),淡到 0 后真正 hide
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._fade.finished.connect(self._after_fade)

    # ---------- 内部:动画 ----------

    def _fade_to(self, end: float, ms: int) -> None:
        self._fade.stop()
        self._fade.setDuration(ms)
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(end)
        self._fade.start()

    def _fade_out(self) -> None:
        self._fade_to(0.0, 240)

    def _after_fade(self) -> None:
        if self.windowOpacity() < 0.01:
            self._dot.stop()
            self.hide()

    def _show_now(self) -> None:
        """立即以完全不透明显示(打断进行中的淡出)。"""
        self._fade.stop()
        self.setWindowOpacity(1.0)
        if not self.isVisible():
            self.show()

    # ---------- 内部:文本渲染 ----------

    def _screen_geo(self):
        scr = QGuiApplication.primaryScreen()
        return scr.availableGeometry() if scr else None

    def _set_text(self, committed: str, volatile: str) -> None:
        """已定稿白色 + 未定稿灰色;过长时从左省略已定稿部分,
        保证最新说的词(volatile)始终完整可见。"""
        geo = self._screen_geo()
        max_w = (geo.width() if geo else 1280) - 260
        fm = QFontMetrics(self._label.font())
        vol_w = fm.horizontalAdvance(volatile) if volatile else 0
        com = fm.elidedText(committed, Qt.ElideLeft, max(80, max_w - vol_w))
        parts = [f'<span style="color:{TEXT_MAIN};">{html.escape(com)}</span>']
        if volatile:
            parts.append(
                f'<span style="color:{TEXT_VOLATILE};">'
                f'{html.escape(volatile)}</span>')
        self._label.setText("".join(parts))

    def _set_hint(self) -> None:
        self._label.setText(
            f'<span style="color:{TEXT_VOLATILE};">{html.escape(_HINT)}</span>')

    def _reposition(self) -> None:
        geo = self._screen_geo()
        if geo is None:
            return
        self.adjustSize()   # 布局按当前文本自适应
        x = geo.x() + (geo.width() - self.width()) // 2
        # 胶囊(不含投影留白)落在屏幕底部偏上
        y = geo.y() + int(geo.height() * 0.82) - _MARGIN
        self.move(x, y)

    # ---------- 供 service 信号调用(均在 Qt 主线程)----------

    def begin_session(self) -> None:
        """一轮听写开始:立即显示「正在聆听」+ 呼吸红点(即时反馈热键生效)。"""
        self._active = True
        self._hold.stop()
        self._label.clear()
        self._dot.set_recording()
        self._set_hint()
        self._reposition()
        self._show_now()

    def show_finalizing(self) -> None:
        if not self._active:
            return
        self._label.setText(
            f'<span style="color:{TEXT_VOLATILE};">{html.escape(_FINALIZING)}</span>')
        self._reposition()
        self._show_now()

    def show_draft(self, committed: str, volatile: str) -> None:
        # 已结束的一轮里,残留草稿信号一律忽略(防竞态导致浮窗卡住不隐藏)
        if not self._active:
            return
        self._hold.stop()
        if committed or volatile:
            self._set_text(committed, volatile)
        else:
            self._set_hint()
        self._reposition()
        self._show_now()

    def end_session(self, final_text: str = "") -> None:
        """一轮听写结束:停止接收草稿;有最终文本则绿点+白字停留一瞬再淡出。"""
        self._active = False
        self._hold.stop()
        if final_text:
            self._dot.set_done()
            self._set_text(final_text, "")
            self._reposition()
            self._show_now()
            self._hold.start(900)
        else:
            self._fade_out()
