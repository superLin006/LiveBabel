"""透明置顶双语字幕悬浮窗(PySide6)—— 桌面歌词式体验。

特性:
  * 紧凑滚动:默认显示最近 N 句(N 可调),新句从下往上,像桌面歌词。
  * 双语上下排:原文白色在上,译文青色在下。volatile 未定稿行浅灰斜体。
  * 窗口可自由缩放:拖动右下角手柄改大小;按住左键拖动整体移动。
  * 右键菜单:切换目标语种 / 字号 / 显示行数 / 是否显示原文 / 锁定位置 / 退出。
  * 设置持久化:字号、行数、语种、窗口位置大小存到 settings.json,下次自动恢复。

线程模型:ASR/翻译在后台线程,通过 Qt 信号把文本送到 GUI 线程刷新。
切换语种通过 lang_changed 信号通知 app 层去改 translator。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import List, Optional

from PySide6.QtCore import Qt, QPoint, QTimer, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QFont
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QSizeGrip,
    QVBoxLayout,
    QWidget,
)

from livebabel.paths import SETTINGS_PATH

LANGS = ["英语", "中文", "日语", "韩语"]

DEFAULTS = {
    "font_pt": 18,
    "max_lines": 1,
    "lang": "英语",
    "show_source": True,
    "geometry": None,   # [x, y, w, h]
    "locked": False,
    "api_key": "",      # DeepSeek key;留空则用环境变量 DEEPSEEK_API_KEY
}


def load_settings() -> dict:
    s = dict(DEFAULTS)
    if os.path.exists(SETTINGS_PATH):
        try:
            with open(SETTINGS_PATH, encoding="utf-8") as f:
                s.update(json.load(f))
        except Exception:
            pass
    return s


def save_settings(s: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


@dataclass
class SubtitleLine:
    source: str
    translation: Optional[str]
    committed: bool
    provisional: bool = False   # 临时(段未结束,Pass1 草稿译文),显示偏暗


class SubtitleOverlay(QWidget):
    _lines_signal = Signal(list)
    lang_changed = Signal(str)    # 通知 app 层切换翻译目标语种
    pause_toggled = Signal(bool)  # True=暂停,False=继续
    api_key_changed = Signal(str) # 设置了新的 DeepSeek key

    def __init__(self) -> None:
        super().__init__()
        self.s = load_settings()
        self._drag_pos: Optional[QPoint] = None

        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setMinimumSize(220, 60)

        self._bg = QWidget(self)
        self._hovered = False
        self._apply_bg()      # 默认无背景(像桌面歌词,只有文字)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self._bg)

        self._layout = QVBoxLayout(self._bg)
        self._layout.setContentsMargins(14, 6, 14, 8)
        self._layout.setSpacing(2)

        # 顶部工具条(悬停才显示):暂停 / 隐藏原文 / 语种下拉 / 退出
        self._toolbar = self._build_toolbar()
        self._layout.addWidget(self._toolbar)
        self._toolbar.hide()

        self._layout.addStretch(1)   # 内容靠下,新句从底部出现(滚动感)

        self._labels: List[QLabel] = []
        self._last_lines: List[SubtitleLine] = []
        self._paused = False

        # 右下角缩放手柄(放在最上层,否则会被背景框盖住拉不动)
        self._grip_size = 22
        self._grip = QSizeGrip(self)
        self._grip.setStyleSheet(
            "background: rgba(255,255,255,40); border-radius: 3px;"
        )
        self._grip.raise_()
        self._grip.hide()     # 平时隐藏,鼠标悬停才出现

        self._lines_signal.connect(self._render)

        # 几何持久化做防抖:拖动/缩放停止 0.6 秒后才写一次盘,避免每像素都写文件
        self._geo_timer = QTimer(self)
        self._geo_timer.setSingleShot(True)
        self._geo_timer.setInterval(600)
        self._geo_timer.timeout.connect(self._save_geo)

        # 恢复几何
        geo = self.s.get("geometry")
        if geo and len(geo) == 4:
            self.setGeometry(*geo)
        else:
            screen = QApplication.primaryScreen().geometry()
            w, h = int(screen.width() * 0.5), 130
            self.setGeometry(
                (screen.width() - w) // 2, int(screen.height() * 0.80), w, h
            )

    # ---- 线程安全更新 ----

    def update_lines(self, lines: List[SubtitleLine]) -> None:
        self._lines_signal.emit(lines)

    # ---- 渲染 ----

    def _make_label(self, text: str, color: str, italic: bool, size: int) -> QLabel:
        lab = QLabel(text)
        lab.setWordWrap(True)
        lab.setTextFormat(Qt.PlainText)
        lab.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        f = QFont("Microsoft YaHei", max(1, int(size)))   # 字号兜底 >=1,防 fp-1 取到 0/负
        f.setItalic(italic)
        f.setBold(not italic)
        lab.setFont(f)
        lab.setStyleSheet(f"color: {color}; background: transparent;")
        shadow = QGraphicsDropShadowEffect(lab)
        shadow.setBlurRadius(5)
        shadow.setColor(QColor(0, 0, 0, 235))
        shadow.setOffset(0, 0)
        lab.setGraphicsEffect(shadow)
        return lab

    def _clear(self) -> None:
        for lab in self._labels:
            self._layout.removeWidget(lab)
            lab.deleteLater()
        self._labels = []

    def _render(self, lines: List[SubtitleLine]) -> None:
        self._last_lines = lines
        self._clear()
        fp = self.s["font_pt"]
        show_src = self.s["show_source"]
        for ln in lines:
            if ln.committed:
                # 临时行:原文白色,译文用醒目的琥珀色(清晰可读,又能和最终的青色区分)
                # 最终行:原文白色,译文青色
                src_color = "#FFFFFF"
                tr_color = "#FFD24A" if ln.provisional else "#7FE7FF"
                if show_src:
                    self._labels.append(self._make_label(ln.source, src_color, False, fp))
                tr = ln.translation if ln.translation is not None else "…"
                self._labels.append(self._make_label(tr, tr_color, False, fp - 1))
            else:
                self._labels.append(
                    self._make_label(ln.source + " ▎", "#C8C8C8", True, fp)
                )
        for lab in self._labels:
            self._layout.addWidget(lab)

    # ---- 顶部工具条 ----

    def _build_toolbar(self) -> QWidget:
        bar = QWidget(self._bg)
        bar.setStyleSheet("background: transparent;")
        h = QHBoxLayout(bar)
        h.setContentsMargins(0, 0, 0, 2)
        h.setSpacing(6)

        btn_css = (
            "QPushButton{color:#fff;background:rgba(255,255,255,30);border:none;"
            "border-radius:4px;padding:2px 8px;font-size:12px;}"
            "QPushButton:hover{background:rgba(255,255,255,60);}"
        )

        self._btn_pause = QPushButton("暂停")
        self._btn_pause.setStyleSheet(btn_css)
        self._btn_pause.clicked.connect(self._toggle_pause)
        h.addWidget(self._btn_pause)

        self._btn_src = QPushButton("隐藏原文")
        self._btn_src.setStyleSheet(btn_css)
        self._btn_src.clicked.connect(
            lambda: self._set("show_source", not self.s["show_source"]) or self._sync_toolbar()
        )
        h.addWidget(self._btn_src)

        self._cmb_lang = QComboBox()
        self._cmb_lang.addItems(LANGS)
        self._cmb_lang.setCurrentText(self.s["lang"])
        self._cmb_lang.setStyleSheet(
            "QComboBox{color:#fff;background:rgba(255,255,255,30);border:none;"
            "border-radius:4px;padding:2px 6px;font-size:12px;}"
            "QComboBox QAbstractItemView{color:#fff;background:#222;selection-background-color:#444;}"
        )
        self._cmb_lang.currentTextChanged.connect(self._set_lang)
        h.addWidget(self._cmb_lang)

        h.addStretch(1)

        btn_quit = QPushButton("✕")
        btn_quit.setStyleSheet(btn_css)
        btn_quit.clicked.connect(self._quit)
        h.addWidget(btn_quit)

        return bar

    def _toggle_pause(self) -> None:
        self._paused = not self._paused
        self._btn_pause.setText("继续" if self._paused else "暂停")
        self.pause_toggled.emit(self._paused)

    def _sync_toolbar(self) -> None:
        self._btn_src.setText("显示原文" if not self.s["show_source"] else "隐藏原文")

    # ---- 右键菜单 ----

    def contextMenuEvent(self, e) -> None:
        m = QMenu(self)

        lang_menu = m.addMenu("翻译语种")
        grp = QActionGroup(self)
        grp.setExclusive(True)
        for lg in LANGS:
            a = QAction(lg, self, checkable=True)
            a.setChecked(lg == self.s["lang"])
            a.triggered.connect(lambda _=False, x=lg: self._set_lang(x))
            grp.addAction(a)
            lang_menu.addAction(a)

        size_menu = m.addMenu("字号")
        for pt in (12, 14, 16, 18, 22, 26, 32):
            a = QAction(f"{pt}", self, checkable=True)
            a.setChecked(pt == self.s["font_pt"])
            a.triggered.connect(lambda _=False, x=pt: self._set("font_pt", x))
            size_menu.addAction(a)

        line_menu = m.addMenu("显示行数")
        for n in (1, 2, 3, 4, 5):
            a = QAction(f"{n} 句", self, checkable=True)
            a.setChecked(n == self.s["max_lines"])
            a.triggered.connect(lambda _=False, x=n: self._set("max_lines", x))
            line_menu.addAction(a)

        a_src = QAction("显示原文", self, checkable=True)
        a_src.setChecked(self.s["show_source"])
        a_src.triggered.connect(
            lambda _=False: (self._set("show_source", not self.s["show_source"]),
                             self._sync_toolbar())
        )
        m.addAction(a_src)

        a_lock = QAction("锁定位置", self, checkable=True)
        a_lock.setChecked(self.s["locked"])
        a_lock.triggered.connect(lambda _=False: self._set("locked", not self.s["locked"]))
        m.addAction(a_lock)

        m.addSeparator()
        a_key = QAction("设置 DeepSeek API Key…", self)
        a_key.triggered.connect(self._edit_api_key)
        m.addAction(a_key)

        a_quit = QAction("退出", self)
        a_quit.triggered.connect(self._quit)
        m.addAction(a_quit)

        m.exec(e.globalPos())

    def _edit_api_key(self) -> None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit
        cur = self.s.get("api_key", "")
        text, ok = QInputDialog.getText(
            self, "设置 DeepSeek API Key",
            "输入 DeepSeek API Key(留空则用环境变量):",
            QLineEdit.Normal, cur,
        )
        if ok:
            self.s["api_key"] = text.strip()
            save_settings(self.s)
            self.api_key_changed.emit(text.strip())

    def _set(self, key: str, val) -> None:
        self.s[key] = val
        save_settings(self.s)
        self._render(self._last_lines)   # 立即重绘

    def _set_lang(self, lang: str) -> None:
        if lang == self.s["lang"]:
            return                       # 避免下拉/菜单互相触发成环
        self.s["lang"] = lang
        save_settings(self.s)
        # 同步下拉框显示(从右键菜单改时)
        if self._cmb_lang.currentText() != lang:
            self._cmb_lang.blockSignals(True)
            self._cmb_lang.setCurrentText(lang)
            self._cmb_lang.blockSignals(False)
        self.lang_changed.emit(lang)

    @property
    def max_lines(self) -> int:
        return self.s["max_lines"]

    # ---- 拖动 / 缩放 / 几何持久化 ----

    def resizeEvent(self, e) -> None:
        # 缩放手柄放右下角,并保持在最上层
        g = self._grip_size
        self._grip.resize(g, g)
        self._grip.move(self.width() - g, self.height() - g)
        self._grip.raise_()
        self._geo_timer.start()      # 防抖:停止缩放 0.6s 后才写盘
        super().resizeEvent(e)

    # ---- 悬停才显示背景/手柄(桌面歌词式) ----

    def _apply_bg(self) -> None:
        if self._hovered:
            self._bg.setStyleSheet(
                "background-color: rgba(0, 0, 0, 150); border-radius: 10px;"
            )
        else:
            self._bg.setStyleSheet("background: transparent;")

    def enterEvent(self, e) -> None:
        self._hovered = True
        self._apply_bg()
        self._grip.show()
        self._sync_toolbar()
        self._toolbar.show()
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._hovered = False
        self._apply_bg()
        self._grip.hide()
        # 下拉框展开时鼠标会"离开"主窗,别误关工具条
        if not self._cmb_lang.view().isVisible():
            self._toolbar.hide()
        super().leaveEvent(e)

    def _in_grip(self, pos) -> bool:
        g = self._grip_size
        return pos.x() >= self.width() - g and pos.y() >= self.height() - g

    def mousePressEvent(self, e) -> None:
        # 点在右下角手柄区域时不拖动(交给 QSizeGrip 缩放)
        if e.button() == Qt.LeftButton and not self.s["locked"] and not self._in_grip(e.position().toPoint()):
            self._drag_pos = e.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, e) -> None:
        if self._drag_pos is not None and e.buttons() & Qt.LeftButton:
            self.move(e.globalPosition().toPoint() - self._drag_pos)

    def mouseReleaseEvent(self, e) -> None:
        self._drag_pos = None
        self._geo_timer.start()      # 拖动结束后防抖写盘

    def _save_geo(self) -> None:
        g = self.geometry()
        self.s["geometry"] = [g.x(), g.y(), g.width(), g.height()]
        save_settings(self.s)

    def _quit(self) -> None:
        self._save_geo()
        QApplication.quit()
