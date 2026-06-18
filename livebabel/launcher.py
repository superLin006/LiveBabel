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

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from livebabel.gui_common import (
    apply_theme, ACCENT, ACCENT_DEEP, BORDER, CARD, CARD_HOVER, SUBTEXT,
    LAUNCHER_W, LAUNCHER_H,
)
from livebabel.overlay import load_settings, save_settings


class ModeCard(QFrame):
    """一张可点击的模式卡片:图标 + 标题 + 说明。整卡可点。"""

    def __init__(self, emoji: str, title: str, desc: str, on_click, enabled=True):
        super().__init__()
        self._on_click = on_click
        self._enabled = enabled
        self.setCursor(Qt.PointingHandCursor if enabled else Qt.ArrowCursor)
        self.setObjectName("card")
        self.setStyleSheet(self._qss())

        # 苹果风卡片:柔和投影,营造"浮于浅灰背景之上"的层次感
        from PySide6.QtWidgets import QGraphicsDropShadowEffect
        from PySide6.QtGui import QColor
        shadow = QGraphicsDropShadowEffect(self)
        shadow.setBlurRadius(24)
        shadow.setXOffset(0)
        shadow.setYOffset(4)
        shadow.setColor(QColor(0, 0, 0, 28))
        self.setGraphicsEffect(shadow)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 24, 24, 24)
        lay.setSpacing(10)

        icon = QLabel(emoji)
        icon.setStyleSheet("font-size: 42px; background: transparent;")
        t = QLabel(title)
        t.setStyleSheet("font-size: 18px; font-weight: 600; background: transparent;")
        d = QLabel(desc)
        d.setWordWrap(True)
        d.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px; background: transparent;")

        lay.addWidget(icon)
        lay.addWidget(t)
        lay.addWidget(d)
        lay.addStretch(1)

        if not enabled:
            badge = QLabel("即将推出")
            badge.setStyleSheet(
                f"color: {SUBTEXT}; font-size: 11px; background: transparent;"
            )
            lay.addWidget(badge)

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

        self.setWindowTitle("LiveBabel")
        self.resize(LAUNCHER_W, LAUNCHER_H)
        from livebabel.gui_common import app_icon
        self.setWindowIcon(app_icon())
        apply_theme(self)
        self._dark_titlebar_done = False
        self._build()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dark_titlebar_done:
            self._dark_titlebar_done = True
            from livebabel.gui_common import enable_dark_titlebar
            enable_dark_titlebar(self)

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(40, 36, 40, 28)
        root.setSpacing(6)

        title = QLabel("LiveBabel")
        title.setObjectName("title")
        sub = QLabel("实时字幕 · 离线字幕 · 会议纪要")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(28)

        cards = QHBoxLayout()
        cards.setSpacing(18)
        cards.addWidget(ModeCard(
            "🎧", "实时模式",
            "抓取电脑正在播放的声音,实时识别并翻译,以悬浮字幕显示。适合看直播 / 视频会议 / 在线课程。",
            self._start_live,
        ))
        cards.addWidget(ModeCard(
            "🎬", "离线模式",
            "选择本地视频文件,生成双语字幕(SRT / ASS),可直接烧录进视频。适合给录播 / 影片配字幕。",
            self._open_offline,
        ))
        cards.addWidget(ModeCard(
            "📝", "会议纪要",
            "录制会议(区分我 / 远端),实时转录,一键生成结构化纪要并导出。适合线上 / 线下会议记录。",
            self._open_meeting,
        ))
        root.addLayout(cards, 1)

        root.addSpacing(24)

        # API Key 底部面板(包成卡片,作为页脚信息区)
        from livebabel.gui_common import card
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

    @staticmethod
    def _whisper_local() -> bool:
        """本地是否已放了离线 whisper 模型目录(放了就不会触发联网下载)。"""
        from livebabel.paths import WHISPER_DIR
        return os.path.isdir(WHISPER_DIR) and bool(os.listdir(WHISPER_DIR))

    def _open_history(self) -> None:
        from livebabel.history_window import HistoryWindow
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
        e.accept()

    # ---- 模式 ----

    def _open_offline(self) -> None:
        # 离线用 faster-whisper(large-v3-turbo)。本地没放模型时首次会自动联网下载
        # (约 1.6GB,下到本机缓存,仅一次)。这里只做一次性友好提示,不阻断。
        if self._offline_win is None and not self._whisper_local():
            from livebabel.gui_common import info
            info(self, "离线模式 · 首次需下载模型",
                 "离线字幕使用 Whisper large-v3-turbo 模型。\n\n"
                 "首次转写会自动联网下载约 1.6GB 模型(仅一次,之后无需联网),"
                 "期间界面可能停顿,属正常现象,请耐心等待。")
        from livebabel.offline_window import OfflineWindow
        if self._offline_win is None:
            self._offline_win = OfflineWindow(api_key=self._effective_key())
            self._offline_win.set_api_key(self._effective_key())
        self._offline_win.show()
        self._offline_win.raise_()
        self._offline_win.activateWindow()

    def _open_meeting(self) -> None:
        from livebabel.meeting_window import MeetingWindow
        if self._meeting_win is None:
            self._meeting_win = MeetingWindow(api_key=self._effective_key())
        self._meeting_win.set_api_key(self._effective_key())
        self._meeting_win.show()
        self._meeting_win.raise_()
        self._meeting_win.activateWindow()

    def _start_live(self) -> None:
        """启动实时悬浮窗。复用 app.py 的流水线;悬浮窗为独立顶层窗,与本启动器共存。"""
        if self._live_thread is not None:
            # 已经起过:提示用户悬浮窗就在桌面上(可能被其他窗口盖住)
            from livebabel.gui_common import info
            info(self, "实时模式已在运行",
                 "实时悬浮字幕已经启动,请在桌面上查看(默认在屏幕下方)。")
            return
        try:
            worker, overlay = _start_live_overlay(self._effective_key())
            self._live_thread = worker
            # 悬浮窗退出后允许再次启动实时模式
            overlay.closed.connect(self._on_live_closed)
        except Exception as e:
            from livebabel.gui_common import error
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

    from livebabel.commit_manager import CommitManager
    from livebabel.translator import Translator
    from livebabel.overlay import SubtitleOverlay, SubtitleLine
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

    def on_lang_changed(lang: str) -> None:
        translator.target_lang = lang
        for seg in manager.committed[-overlay.max_lines:]:
            translator.submit(seg.id, seg.text, quick=True)
    overlay.lang_changed.connect(on_lang_changed)

    # 「总结」按钮:取本场转录 → DeepSeek 摘要 → 弹窗展示
    from livebabel.summary_window import wire_summarize
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
        args=(args, manager, translator, push_to_overlay,
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
    from livebabel.gui_common import apply_app_theme, app_icon
    apply_app_theme(app)            # 全局深色调色板,消除白边/白底弹窗
    app.setWindowIcon(app_icon())   # 任务栏/弹窗/所有窗口默认图标
    # 首次使用:核心模型缺失则先弹下载窗(下完才进主页;取消则退出)
    from livebabel.model_setup import models_ready
    if not models_ready():
        from livebabel.model_download_dialog import ModelDownloadDialog
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
