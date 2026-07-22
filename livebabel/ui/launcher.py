"""LiveBabel 图形化主入口 —— 选择「实时模式」或「离线模式」。

设计成给新手用的首页:两张大卡片选模式,底部一行设置 DeepSeek API Key。
- 实时模式:启动透明悬浮窗,抓系统声音做实时双语字幕(沿用 app.py 的流水线)。
- 离线模式:打开离线字幕生成页面(offline_window.py)。

API Key 与悬浮窗共用 settings.json,这里设置一次,两个模式都能用。
"""

from __future__ import annotations

import os
import sys
import threading

from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import (
    QColor, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap,
)
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from livebabel.ui.gui_common import (
    apply_theme, ACCENT, ACCENT_DEEP, BORDER, CARD, CARD_HOVER, SUBTEXT,
    LAUNCHER_W, LAUNCHER_H, APP_VERSION,
)
from livebabel.ui.overlay import load_settings, save_settings

# 四种模式的图标主题色(苹果系统色,浅→深轻渐变)
MODE_COLORS = {
    "live":      ("#4DA3FF", "#0A84FF"),   # 蓝:实时
    "offline":   ("#D08BFF", "#BF5AF2"),   # 紫:离线
    "meeting":   ("#5BE080", "#30D158"),   # 绿:会议
    "dictation": ("#FFBE4D", "#FF9F0A"),   # 橙:语音输入
}


def _mode_icon(kind: str, size: int = 46) -> QPixmap:
    """画一枚 macOS 应用图标风格的彩色圆角图标块(渐变底 + 白色图形)。

    不用 emoji:各系统渲染不一,风格也和浅色苹果风不搭;
    QPainter 矢量绘制保证清晰一致,每个模式一个识别色。
    """
    c1, c2 = MODE_COLORS[kind]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    g = QLinearGradient(0, 0, 0, size)
    g.setColorAt(0.0, QColor(c1))
    g.setColorAt(1.0, QColor(c2))
    p.setBrush(g)
    p.setPen(Qt.NoPen)
    p.drawRoundedRect(0, 0, size, size, 11, 11)

    m = size / 2
    white = QColor("white")
    pen = QPen(white, 2.4)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)

    if kind == "live":            # 均衡器竖条:声音
        p.setBrush(white)
        w = 3.8
        for i, h in enumerate((10, 17, 24, 17, 10)):
            x = m + (i - 2) * 6.6
            p.drawRoundedRect(QRectF(x - w / 2, m - h / 2, w, h), w / 2, w / 2)
    elif kind == "offline":       # 播放三角:视频
        tri = QPainterPath()
        tri.moveTo(m - 7, m - 11)
        tri.lineTo(m + 11, m)
        tri.lineTo(m - 7, m + 11)
        tri.closeSubpath()
        p.setBrush(white)
        p.drawPath(tri)
    elif kind == "meeting":       # 一页纪要:白页 + 色线
        page = QRectF(m - 9, m - 12, 18, 24)
        p.setBrush(white)
        p.drawRoundedRect(page, 3, 3)
        lp = QPen(QColor(c2), 2.2)
        lp.setCapStyle(Qt.RoundCap)
        p.setPen(lp)
        for i, dy in enumerate((-5.5, 0.0, 5.5)):
            x2 = page.right() - (4 if i < 2 else 8)   # 末行短一截,更像文档
            p.drawLine(QPointF(page.left() + 4, m + dy), QPointF(x2, m + dy))
    elif kind == "dictation":     # 麦克风
        p.setBrush(white)
        p.drawRoundedRect(QRectF(m - 4.5, m - 14, 9, 15), 4.5, 4.5)
        p.setBrush(Qt.NoBrush)
        p.setPen(pen)
        p.drawArc(QRectF(m - 8.5, m - 9, 17, 16), 0, -180 * 16)
        p.drawLine(QPointF(m, m + 7), QPointF(m, m + 11))
        p.drawLine(QPointF(m - 5, m + 11.5), QPointF(m + 5, m + 11.5))
    p.end()
    return pm


class ModeCard(QFrame):
    """一张可点击的模式卡片:彩色图标块 + 标题 + 一句话说明。整卡可点。

    悬停时投影加深、轻微"浮起";常驻型功能(语音输入)可用 set_running()
    在卡片上显示「● 运行中」角标。完整说明放 tooltip,正文只留一句。
    """

    def __init__(self, kind: str, title: str, desc: str, tip: str,
                 on_click, enabled=True):
        super().__init__()
        self._on_click = on_click
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.setObjectName("card")
        self.setStyleSheet(self._qss())
        if tip:
            self.setToolTip(tip)

        # 苹果风卡片:柔和投影,营造"浮于浅灰背景之上"的层次感
        self._shadow = QGraphicsDropShadowEffect(self)
        self._shadow.setXOffset(0)
        self._set_lift(False)
        self.setGraphicsEffect(self._shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(22, 22, 22, 20)
        lay.setSpacing(0)

        icon = QLabel()
        icon.setPixmap(_mode_icon(kind))
        icon.setStyleSheet("background: transparent;")
        t = QLabel(title)
        t.setStyleSheet("font-size: 17px; font-weight: 600; background: transparent;")
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px; background: transparent;")

        lay.addWidget(icon)
        lay.addSpacing(14)
        lay.addWidget(t)
        lay.addSpacing(6)
        lay.addWidget(d)
        lay.addStretch(1)

        # 运行状态角标(默认隐藏,常驻型功能启用后显示)
        self._badge = QLabel("●  运行中")
        self._badge.setStyleSheet(
            "color: #30D158; font-size: 11px; font-weight: 600;"
            " background: transparent;")
        self._badge.hide()
        lay.addWidget(self._badge)

        if not enabled:
            soon = QLabel("即将推出")
            soon.setStyleSheet(
                f"color: {SUBTEXT}; font-size: 11px; background: transparent;")
            lay.addWidget(soon)

    def set_running(self, on: bool) -> None:
        """显示/隐藏「运行中」角标(语音输入等常驻开关型功能用)。"""
        self._badge.setVisible(on)

    def _set_lift(self, hovered: bool) -> None:
        """悬停"浮起":投影更深更弥散,像卡片被轻轻抬起。"""
        self._shadow.setBlurRadius(32 if hovered else 24)
        self._shadow.setYOffset(8 if hovered else 4)
        self._shadow.setColor(QColor(0, 0, 0, 48 if hovered else 28))

    def enterEvent(self, e) -> None:
        if self._enabled:
            self._set_lift(True)
        super().enterEvent(e)

    def leaveEvent(self, e) -> None:
        self._set_lift(False)
        super().leaveEvent(e)

    def _qss(self) -> str:
        if not self._enabled:
            return (
                f"#card {{ background: {CARD}; border: 1px solid {BORDER};"
                f" border-radius: 14px; }}"
            )
        return (
            f"#card {{ background: {CARD}; border: 1px solid {BORDER};"
            f" border-radius: 14px; }}"
            f"#card:hover {{ background: {CARD}; border: 1.5px solid {ACCENT}; }}"
        )

    def mouseReleaseEvent(self, e) -> None:
        if self._enabled and e.button() == Qt.LeftButton and self.rect().contains(e.pos()):
            self._on_click()
        super().mouseReleaseEvent(e)


class Launcher(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.s = load_settings()
        self._offline_win = None       # 持有引用,防被 GC
        self._meeting_win = None
        self._live_thread = None
        self._dictation_tray = None    # 语音输入托盘服务(惰性创建,常驻后台)

        self.setWindowTitle("LiveBabel")
        self.resize(LAUNCHER_W, LAUNCHER_H)
        from livebabel.ui.gui_common import app_icon
        self.setWindowIcon(app_icon())
        apply_theme(self)
        self._dark_titlebar_done = False
        self._build()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dark_titlebar_done:
            self._dark_titlebar_done = True
            from livebabel.ui.gui_common import enable_dark_titlebar
            enable_dark_titlebar(self)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 28)
        root.setSpacing(6)

        # 品牌头:logo(assets/logo.png)+ 字标,横排居中
        from livebabel.paths import ICON_PNG
        head = QHBoxLayout()
        head.setSpacing(14)
        head.addStretch(1)
        logo_pm = QPixmap(ICON_PNG)
        if not logo_pm.isNull():
            logo = QLabel()
            logo.setPixmap(logo_pm.scaled(
                52, 52, Qt.KeepAspectRatio, Qt.SmoothTransformation))
            logo.setStyleSheet("background: transparent;")
            head.addWidget(logo)
        tcol = QVBoxLayout()
        tcol.setSpacing(2)
        title = QLabel("LiveBabel")
        title.setObjectName("title")
        sub = QLabel("实时字幕 · 离线字幕 · 会议纪要 · 语音输入")
        sub.setObjectName("subtitle")
        tcol.addWidget(title)
        tcol.addWidget(sub)
        head.addLayout(tcol)
        head.addStretch(1)
        root.addLayout(head)
        root.addSpacing(26)

        # 模式卡片:正文一句话,完整说明进 tooltip(文字砖会压垮卡片的呼吸感)
        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(ModeCard(
            "live", "实时模式",
            "实时识别电脑播放的声音,悬浮双语字幕。",
            "抓取电脑正在播放的声音,实时识别并翻译,以悬浮字幕显示。\n"
            "适合看直播 / 视频会议 / 在线课程。",
            self._start_live,
        ))
        cards.addWidget(ModeCard(
            "offline", "离线模式",
            "本地视频一键生成双语字幕(SRT / ASS)。",
            "选择本地视频文件,生成双语字幕(SRT / ASS),可直接烧录进视频。\n"
            "适合给录播 / 影片配字幕。",
            self._open_offline,
        ))
        cards.addWidget(ModeCard(
            "meeting", "会议纪要",
            "录制转录、区分发言人,一键生成纪要。",
            "录制会议,实时转录并区分发言人,一键生成结构化纪要并导出。\n"
            "适合线上 / 线下会议记录。",
            self._open_meeting,
        ))
        self._card_dictation = ModeCard(
            "dictation", "语音输入",
            "按住热键说话,文字输入到任意软件。",
            "全局热键(右 Ctrl)按住说话,松开结束并输入到当前光标处。\n"
            "任意软件可用,适合聊天 / 写文档 / 填表。再点一次卡片可关闭。",
            self._toggle_dictation,
        )
        cards.addWidget(self._card_dictation)
        root.addLayout(cards, 1)

        root.addSpacing(24)

        # API Key 底部面板(包成卡片,作为页脚信息区)
        from livebabel.ui.gui_common import card
        key_card, kc = card(padding=14)
        key_row = QHBoxLayout()
        key_row.setSpacing(10)
        key_lab = QLabel("DeepSeek API Key")
        key_lab.setObjectName("section")
        self.key_status = QLabel()
        self.key_status.setObjectName("subtitle")
        set_btn = QPushButton("设置 Key")
        set_btn.clicked.connect(self._set_key)
        hist_btn = QPushButton("历史记录")
        hist_btn.clicked.connect(self._open_history)
        key_row.addWidget(key_lab)
        key_row.addWidget(self.key_status, 1)
        key_row.addWidget(hist_btn)
        key_row.addWidget(set_btn)
        kc.addLayout(key_row)
        root.addWidget(key_card)
        self._refresh_key_status()

        # 版本页脚
        ver = QLabel(f"v{APP_VERSION}")
        ver.setStyleSheet(f"color: {SUBTEXT}; font-size: 11px;")
        ver.setAlignment(Qt.AlignRight)
        root.addSpacing(4)
        root.addWidget(ver)

    @staticmethod
    def _whisper_local() -> bool:
        """本地是否已有 whisper 模型(通过统一仓库预下载)。"""
        from livebabel.model_setup import whisper_ready
        return whisper_ready()

    def _open_history(self) -> None:
        from livebabel.ui.history_window import HistoryWindow
        HistoryWindow(self).exec()

    # ---- API Key ----

    def _effective_key(self) -> str:
        return (self.s.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")).strip()

    def _refresh_key_status(self) -> None:
        key = self._effective_key()
        if key:
            src = "环境变量" if not self.s.get("api_key") else "已保存"
            self.key_status.setText(f"✓ 已配置({src}:••••{key[-4:]})")
        else:
            self.key_status.setText("⚠ 未设置,翻译将不可用")

    def _set_key(self) -> None:
        cur = self.s.get("api_key", "")
        key, ok = QInputDialog.getText(
            self, "DeepSeek API Key",
            "输入 DeepSeek API Key(留空则使用环境变量 DEEPSEEK_API_KEY):",
            QLineEdit.Normal, cur,
        )
        if ok:
            self.s["api_key"] = key.strip()
            save_settings(self.s)
            self._refresh_key_status()
            if self._offline_win is not None:
                self._offline_win.set_api_key(self._effective_key())
            if self._meeting_win is not None:
                self._meeting_win.set_api_key(self._effective_key())

    def closeEvent(self, e) -> None:
        # 关启动器前,确保离线后台线程已停,避免 "QThread destroyed while running"
        if self._offline_win is not None:
            self._offline_win._stop_worker()
            self._offline_win.close()
        if self._meeting_win is not None:
            self._meeting_win.close()
        # 停掉听写后台(全局热键钩子 + 引擎),避免进程退出后钩子残留
        if self._dictation_tray is not None:
            try:
                self._dictation_tray.shutdown()
            except Exception:
                pass
        e.accept()

    # ---- 模式 ----

    def _open_offline(self) -> None:
        # 离线用 faster-whisper(large-v3-turbo)。本地没放模型时首次会自动联网下载
        # (约 1.6GB,下到本机缓存,仅一次)。这里只做一次性友好提示,不阻断。
        if self._offline_win is None and not self._whisper_local():
            from PySide6.QtWidgets import QMessageBox
            btn = QMessageBox.question(
                self, "离线模式 · 需下载模型",
                "离线字幕使用 Whisper large-v3-turbo 模型(约 1.6GB)。\n\n"
                "推荐从 ModelScope 下载(国内高速),是否现在下载?",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.Yes)
            if btn == QMessageBox.Yes:
                from livebabel.ui.chattts_download_dialog import (
                    WhisperDownloadDialog as _WhisperDlg)
                dlg = _WhisperDlg(self)
                dlg.exec()
        from livebabel.ui.offline_window import OfflineWindow
        if self._offline_win is None:
            self._offline_win = OfflineWindow(api_key=self._effective_key())
            self._offline_win.set_api_key(self._effective_key())
        self._offline_win.show()
        self._offline_win.raise_()
        self._offline_win.activateWindow()

    def _open_meeting(self) -> None:
        from livebabel.ui.meeting_window import MeetingWindow
        if self._meeting_win is None:
            self._meeting_win = MeetingWindow(api_key=self._effective_key())
        self._meeting_win.set_api_key(self._effective_key())
        self._meeting_win.show()
        self._meeting_win.raise_()
        self._meeting_win.activateWindow()

    def _toggle_dictation(self) -> None:
        """点卡片切换语音输入:启用=常驻后台+托盘;再点一次关闭。"""
        if not sys.platform.startswith("win"):
            from livebabel.ui.gui_common import info
            info(self, "暂不支持",
                 "语音输入目前仅 Windows 可用,macOS 适配开发中。")
            return
        if self._dictation_tray is not None:
            # 运行中 → 关闭(shutdown 会回调 _on_dictation_off 清引用+灭角标)
            self._dictation_tray.shutdown()
            return
        try:
            from livebabel.ui.tray import DictationTray
            self._dictation_tray = DictationTray(
                parent=self, on_shutdown=self._on_dictation_off)
            self._dictation_tray.show()
            self._dictation_tray.enable()   # 点卡片即启用
            self._card_dictation.set_running(True)
        except Exception as e:
            self._dictation_tray = None
            self._card_dictation.set_running(False)
            from livebabel.ui.gui_common import error
            error(self, "启用失败",
                  f"语音输入启用失败:\n{type(e).__name__}: {e}\n\n"
                  "请确认已安装 keyboard 依赖(pip install keyboard),且模型已下载。")

    def _on_dictation_off(self) -> None:
        """语音输入被关掉(点卡片 / 托盘菜单「退出」都走这里):同步卡片状态。"""
        self._dictation_tray = None
        self._card_dictation.set_running(False)

    def _start_live(self) -> None:
        """启动实时悬浮窗。复用 app.py 的流水线;悬浮窗为独立顶层窗,与本启动器共存。"""
        if self._live_thread is not None:
            # 已经起过:提示用户悬浮窗就在桌面上(可能被其他窗口盖住)
            from livebabel.ui.gui_common import info
            info(self, "实时模式已在运行",
                 "实时悬浮字幕已经启动,请在桌面上查看(默认在屏幕下方)。")
            return
        try:
            worker, overlay = _start_live_overlay(self._effective_key())
            self._live_thread = worker
            # 悬浮窗退出后允许再次启动实时模式
            overlay.closed.connect(self._on_live_closed)
        except Exception as e:
            from livebabel.ui.gui_common import error
            error(self, "启动失败",
                  f"实时模式启动失败:\n{type(e).__name__}: {e}\n\n"
                  "请确认已安装系统音频采集依赖(pyaudiowpatch),且模型文件已下载。")

    def _on_live_closed(self) -> None:
        self._live_thread = None


def _start_live_overlay(api_key: str):
    """创建实时悬浮窗 + 后台流水线线程。返回 (worker 线程, overlay) 元组。

    直接复用 app.py 里的 pipeline_thread / CommitManager / Translator 装配逻辑,
    只是不自己起 QApplication(由 launcher 的 app 统一管理)。
    """
    from types import SimpleNamespace

    from livebabel.core.commit_manager import CommitManager
    from livebabel.core.translator import Translator
    from livebabel.ui.overlay import SubtitleOverlay, SubtitleLine
    from livebabel.history_writer import HistoryWriter
    import app as live_app   # 复用 pipeline_thread

    overlay = SubtitleOverlay(standalone=False)  # 退出悬浮窗不影响启动器主页
    overlay.show()

    manager = CommitManager()
    translator = Translator(
        on_result=manager.set_translation,
        target_lang=overlay.s["lang"],
        api_key=api_key,
    )
    translator.enabled = overlay.translate_enabled()   # 「不翻译」则不发翻译请求
    overlay.api_key_changed.connect(
        lambda k: setattr(translator, "api_key",
                          (k or os.environ.get("DEEPSEEK_API_KEY", "")).strip())
    )

    def push_to_overlay() -> None:
        committed, volatile = manager.recent(overlay.max_lines)
        lines = [
            SubtitleLine(source=s.text, translation=s.translation,
                         committed=True, provisional=s.provisional)
            for s in committed
        ]
        if volatile is not None:
            lines.append(SubtitleLine(source=volatile.text, translation=None, committed=False))
        overlay.update_lines(lines)

    history = HistoryWriter()
    _logged: set[int] = set()

    def set_and_refresh(seg_id, tr):
        manager.set_translation(seg_id, tr)
        push_to_overlay()
        seg = manager.get(seg_id)
        if seg and not seg.provisional and seg.id not in _logged:
            _logged.add(seg.id)
            history.add(seg.text, tr)
    translator.on_result = set_and_refresh

    def log_untranslated() -> None:
        """「不翻译」时翻译回调永远不触发,历史要在定稿时直接记原文。
        (翻译开着则不在这里写:等译文到了由 set_and_refresh 原文+译文一起写。)"""
        if translator.enabled:
            return
        for seg in manager.committed:
            if not seg.provisional and seg.id not in _logged:
                _logged.add(seg.id)
                history.add(seg.text, None)

    def on_pipeline_change() -> None:
        push_to_overlay()
        log_untranslated()

    def on_lang_changed(lang: str) -> None:
        translator.target_lang = lang
        translator.enabled = overlay.translate_enabled()
        if not translator.enabled:
            push_to_overlay()        # 切到「不翻译」:立刻重绘成只显示原文
            return
        for seg in manager.committed[-overlay.max_lines:]:
            translator.submit(seg.id, seg.text, quick=True)
    overlay.lang_changed.connect(on_lang_changed)

    # 「总结」按钮:取本场转录 → DeepSeek 摘要 → 弹窗展示
    from livebabel.ui.summary_window import wire_summarize
    wire_summarize(
        overlay, manager,
        lambda: (overlay.s.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")).strip(),
    )

    stopped = {"v": False}
    paused = {"v": False}
    overlay.pause_toggled.connect(lambda p: paused.__setitem__("v", p))
    # 悬浮窗退出 → 停掉后台线程(daemon 线程不停也无妨,但停了更干净)
    overlay.closed.connect(lambda: stopped.__setitem__("v", True))

    # 实时模式用系统声音(无 --input)
    args = SimpleNamespace(input=None, no_translate=False, no_history=False)

    worker = threading.Thread(
        target=live_app.pipeline_thread,
        args=(args, manager, translator, on_pipeline_change,
              lambda: stopped["v"], lambda: paused["v"]),
        daemon=True,
    )
    worker.start()
    # 防止 overlay 被 GC(launcher 不直接持有它)——挂到线程对象上
    worker._overlay = overlay  # type: ignore[attr-defined]
    return worker, overlay


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("LiveBabel")
    from livebabel.ui.gui_common import apply_app_theme, app_icon
    apply_app_theme(app)            # 全局深色调色板,消除白边/白底弹窗
    app.setWindowIcon(app_icon())   # 任务栏/弹窗/所有窗口默认图标
    # 首次使用:核心模型缺失则先弹下载窗(下完才进主页;取消则退出)
    from livebabel.model_setup import models_ready
    if not models_ready():
        from livebabel.ui.model_download_dialog import ModelDownloadDialog
        dlg = ModelDownloadDialog()
        dlg.exec()
        if not dlg.models_ready():
            # 用户取消 / 下载未完成:没有模型无法运行,直接退出
            sys.exit(0)

    win = Launcher()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
