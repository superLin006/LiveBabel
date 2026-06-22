"""显示「总结」结果的小窗口:深色主题,展示 Markdown 摘要,支持复制 / 保存。

实时模式点「总结」后,后台线程出结果,通过这个窗口展示。生成中先显示"正在总结…"。
"""

from __future__ import annotations

import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QLabel, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from PySide6.QtCore import QObject, Signal

from livebabel.ui.gui_common import apply_theme, app_icon


class SummaryWindow(QWidget):
    """摘要结果窗。先 show_loading(),拿到结果后 set_result()。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._md = ""
        self.setWindowTitle("LiveBabel · 内容总结")
        self.resize(560, 560)
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
        root.setContentsMargins(22, 18, 22, 18)
        root.setSpacing(12)

        title = QLabel("内容总结")
        title.setObjectName("title")
        root.addWidget(title)

        self.status = QLabel("正在总结…(发送给 DeepSeek,请稍候)")
        self.status.setObjectName("subtitle")
        root.addWidget(self.status)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        root.addWidget(self.view, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.copy_btn = QPushButton("复制")
        self.copy_btn.clicked.connect(self._copy)
        self.copy_btn.setEnabled(False)
        self.save_btn = QPushButton("保存为 Markdown")
        self.save_btn.setObjectName("primary")
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setEnabled(False)
        btn_row.addWidget(self.copy_btn)
        btn_row.addWidget(self.save_btn)
        root.addLayout(btn_row)

    # ---- 状态切换 ----

    def show_loading(self) -> None:
        self.status.setText("正在总结…(发送给 DeepSeek,请稍候)")
        self.view.clear()
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    def set_result(self, markdown: str) -> None:
        self._md = markdown
        self.status.setText("✓ 总结完成")
        # QTextEdit 能直接渲染 Markdown(Qt 5.14+)
        self.view.setMarkdown(markdown)
        self.copy_btn.setEnabled(True)
        self.save_btn.setEnabled(True)

    def set_error(self, msg: str) -> None:
        self.status.setText("✗ 总结失败")
        self.view.setPlainText(msg)
        self.copy_btn.setEnabled(False)
        self.save_btn.setEnabled(False)

    # ---- 交互 ----

    def _copy(self) -> None:
        from PySide6.QtWidgets import QApplication
        QApplication.clipboard().setText(self._md)
        self.status.setText("✓ 已复制到剪贴板")

    def _save(self) -> None:
        default = f"总结_{time.strftime('%Y%m%d_%H%M%S')}.md"
        try:
            from livebabel.paths import HISTORY_DIR
            os.makedirs(HISTORY_DIR, exist_ok=True)
            default = os.path.join(HISTORY_DIR, default)
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(
            self, "保存总结", default, "Markdown (*.md);;文本 (*.txt)")
        if path:
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(self._md)
                self.status.setText(f"✓ 已保存:{path}")
            except Exception as e:
                self.status.setText(f"✗ 保存失败:{e}")


class _SummaryRunner(QObject):
    """把后台线程的总结结果安全送回 GUI 线程(跨线程必须经 Qt 信号)。"""
    ok = Signal(str)
    fail = Signal(str)


def wire_summarize(overlay, manager, get_api_key) -> None:
    """给悬浮窗的「总结」按钮接上逻辑:取本场转录 → 后台请求 DeepSeek → 弹窗展示。

    overlay: SubtitleOverlay(有 summarize_requested 信号)
    manager: CommitManager(.transcript() 提供已定稿原文)
    get_api_key: 无参函数,返回当前可用的 DeepSeek key
    """
    import threading
    from livebabel.core.summarizer import summarize

    state = {"win": None, "busy": False}
    runner = _SummaryRunner(overlay)

    def on_ok(md):
        if state["win"]:
            state["win"].set_result(md)
        state["busy"] = False

    def on_fail(msg):
        if state["win"]:
            state["win"].set_error(msg)
        state["busy"] = False

    runner.ok.connect(on_ok)
    runner.fail.connect(on_fail)

    def on_request(style: str):
        if state["busy"]:
            return
        transcript = manager.transcript()
        if state["win"] is None:
            state["win"] = SummaryWindow()
        win = state["win"]
        win.show_loading()
        win.show(); win.raise_(); win.activateWindow()
        state["busy"] = True
        api_key = get_api_key()

        def work():
            try:
                md = summarize(transcript, style=style, api_key=api_key)
                runner.ok.emit(md)
            except Exception as e:
                runner.fail.emit(f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    overlay.summarize_requested.connect(on_request)
    overlay._summary_runner = runner   # 防 GC
