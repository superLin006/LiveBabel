"""把文字注入当前焦点输入框。平台抽象,Windows 先行。

两种方式:
  * paste: 写系统剪贴板 → 模拟 Ctrl+V → 恢复原剪贴板。中文最稳,默认。
  * type : 逐字键入(keyboard.write)。不污染剪贴板,但中文/特殊字符易错,备选。

注入靠模拟按键 → 必须有真实桌面(WSL 无效)。Windows 用 keyboard;
macOS 后续用 pynput(需辅助功能权限)。
"""

from __future__ import annotations

import sys
import time

_IS_WIN = sys.platform.startswith("win")


class TextInjector:
    """注入器抽象基类。"""

    def inject(self, text: str) -> None:
        raise NotImplementedError


def _set_clipboard(text: str) -> None:
    """用 Qt 剪贴板写文本,带重试。

    Windows 剪贴板同一时刻只能一个进程打开,输入法/剪贴板管理器可能正占用 →
    OleSetClipboard 报 CLIPBRD_E_CANT_OPEN(0x800401d0)。重试几次通常就成功。
    setText 后用 processEvents 让 Qt 真正把数据提交给系统剪贴板。
    """
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        raise RuntimeError("无 QApplication,无法访问剪贴板")
    cb = app.clipboard()
    last = None
    for _ in range(8):
        try:
            cb.setText(text)
            app.processEvents()
            if cb.text() == text:
                return
        except Exception as e:
            last = e
        time.sleep(0.04)
    if last is not None:
        raise last


def _get_clipboard() -> str:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance()
    if app is None:
        return ""
    try:
        return app.clipboard().text()
    except Exception:
        return ""


class ClipboardPasteInjector(TextInjector):
    """写剪贴板 → 模拟粘贴。默认不恢复旧剪贴板(恢复操作正是 OpenClipboard 冲突源,
    且多数听写场景不介意剪贴板留下刚说的话);需要时可开 restore_clipboard。"""

    def __init__(self, restore_clipboard: bool = False) -> None:
        self._restore = restore_clipboard

    def inject(self, text: str) -> None:
        if not text:
            return
        old = _get_clipboard() if self._restore else None
        _set_clipboard(text)
        time.sleep(0.06)        # 让剪贴板生效再粘贴
        self._send_paste()
        if self._restore:
            # 粘贴必须彻底完成再恢复,否则会粘到旧内容;失败不影响注入本身
            time.sleep(0.4)
            try:
                _set_clipboard(old or "")
            except Exception:
                pass

    def _send_paste(self) -> None:
        if _IS_WIN:
            import keyboard
            keyboard.send("ctrl+v")
        else:
            # macOS 后续:pynput Cmd+V;此处占位防误用
            raise NotImplementedError("粘贴注入目前仅 Windows 实现")


class TypeInjector(TextInjector):
    """逐字键入。不碰剪贴板。"""

    def inject(self, text: str) -> None:
        if not text:
            return
        if _IS_WIN:
            import keyboard
            keyboard.write(text)
        else:
            raise NotImplementedError("逐字键入目前仅 Windows 实现")


def make_injector(mode: str = "paste") -> TextInjector:
    """mode: 'paste'(默认) | 'type'。"""
    if mode == "type":
        return TypeInjector()
    return ClipboardPasteInjector()
