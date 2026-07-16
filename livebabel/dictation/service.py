"""听写服务编排:热键 → 两阶段识别(草稿浮窗) → 松开定稿注入。

线程模型(关键):
  * keyboard 钩子回调在 keyboard 的内部线程,**只能发信号**,不能在那儿做
    剪贴板/Qt/注入操作 —— Windows OLE 剪贴板需主线程 COM 上下文,否则
    OleSetClipboard 报 CoInitialize 未调用。
  * 用内部信号 _reqStart/_reqStop 以 QueuedConnection 投递到 Qt 主线程;
    开始录音在主线程触发,结束后的识别在后台线程执行,最终注入回到主线程。
  * engine 内部的采集/识别仍在它自己的工作线程;草稿经 draftChanged 信号回主线程刷浮窗。
"""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Qt, Signal

from livebabel.dictation.hotkey import HotkeyManager
from livebabel.dictation.injector import make_injector
from livebabel.dictation.stream_asr import StreamDictationEngine


class DictationService(QObject):
    # 对外:投递到主线程的信号
    draftChanged = Signal(str, str)  # 流式草稿更新(已定稿, 未定稿),浮窗分色显示
    started = Signal()             # 一次听写开始
    finalText = Signal(str)        # 一轮结束的完整文本(浮窗收尾显示一瞬)
    finalizing = Signal()          # 已松开热键,正在做最终定稿
    error = Signal(str)

    # 内部:后台定稿完成后投递回 Qt 主线程
    _finalized = Signal(str, str)
    _reqStart = Signal()
    _reqStop = Signal()

    def __init__(self, inject_mode: str = "paste") -> None:
        super().__init__()
        self._inject_mode = inject_mode
        self._enabled = False
        self._finalizing = False
        self._engine = StreamDictationEngine(
            on_draft=self._on_draft,
            on_error=self._on_engine_error,
            on_auto_stop=self._on_engine_auto_stop,
        )
        self._hotkey: HotkeyManager | None = None

        # 关键:QueuedConnection 确保槽在 DictationService 所属线程(主线程)执行
        self._reqStart.connect(self._begin, Qt.QueuedConnection)
        self._reqStop.connect(self._end, Qt.QueuedConnection)
        self._finalized.connect(self._deliver_final, Qt.QueuedConnection)

    # ---------- 启停服务 ----------

    def enable(self) -> None:
        if self._enabled:
            return
        # 热键回调只 emit 内部信号,不碰重活
        self._hotkey = HotkeyManager(
            on_start=self._reqStart.emit, on_stop=self._reqStop.emit)
        self._hotkey.start()
        self._enabled = True
        try:
            self._engine.preload()
        except Exception as e:
            self.error.emit(f"模型加载失败: {e}")

    def disable(self) -> None:
        if not self._enabled:
            return
        self._enabled = False
        if self._hotkey is not None:
            self._hotkey.stop()
            self._hotkey = None
        if self._finalizing:
            self.finalText.emit("")
            return
        self._finalizing = False
        if self._engine.is_running():
            self._engine.stop()
        self.finalText.emit("")

    def is_enabled(self) -> bool:
        return self._enabled

    # ---------- 配置 ----------

    def set_inject_mode(self, mode: str) -> None:
        self._inject_mode = mode

    def set_hotkey(self, keys) -> None:
        if self._hotkey is not None:
            self._hotkey.set_hotkey(keys)

    # ---------- 主线程槽(经 QueuedConnection 调用)----------

    def _begin(self) -> None:
        if not self._enabled or self._finalizing:
            return
        try:
            if self._engine.start():
                self.started.emit()
        except Exception as e:
            self.finalText.emit("")
            self.error.emit(f"听写启动失败: {e}")

    def _end(self) -> None:
        if not self._enabled or self._finalizing:
            return
        if not self._engine.is_running():
            return
        self._finalizing = True
        self.finalizing.emit()
        threading.Thread(
            target=self._finalize_in_worker,
            name="dictation-finalize",
            daemon=True,
        ).start()

    def _finalize_in_worker(self) -> None:
        try:
            text = self._engine.stop()
            error = ""
        except Exception as e:
            text = ""
            error = f"听写定稿失败: {e}"
        self._finalized.emit(text, error)

    def _deliver_final(self, text: str, error: str) -> None:
        self._finalizing = False
        if not self._enabled:
            return
        self.finalText.emit(text)
        if error:
            self.error.emit(error)
        elif text:
            self._inject(text)

    def _on_engine_error(self, message: str) -> None:
        self.finalText.emit("")
        self.error.emit(message)

    def _on_engine_auto_stop(self) -> None:
        self._reqStop.emit()

    # ---------- 回调(engine 工作线程)----------

    def _on_draft(self, committed: str, volatile: str) -> None:
        self.draftChanged.emit(committed, volatile)  # 信号自动跨线程到主线程

    # ---------- 注入(主线程)----------

    def _inject(self, text: str) -> None:
        try:
            make_injector(self._inject_mode).inject(text)
        except NotImplementedError as e:
            self.error.emit(str(e))
        except Exception as e:
            self.error.emit(f"注入失败: {e}")
