"""全局热键监听:按住说话,松开结束。Windows 用 keyboard。

回调:
  on_start() —— 右 Ctrl 按下后开始听写
  on_stop()  —— 右 Ctrl 松开后结束听写

默认热键为键盘右侧 Ctrl:
  * 按住右 Ctrl:开始录音和识别。
  * 松开右 Ctrl:结束录音并输出最终文字。

注意:keyboard 在 Linux 需 root(WSL 无效),Windows 普通权限可用。
监听回调在 keyboard 的内部线程,务必只发信号、不做重活。
"""

from __future__ import annotations

import sys
import threading
from typing import Callable

# 默认触发键。右 Ctrl:按住说话,松开结束。
DEFAULT_KEYS = ("right ctrl",)


class HotkeyManager:
    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None],
                 keys=DEFAULT_KEYS) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._keys = tuple(self._norm(k) for k in keys)
        self._hooked = False

        self._combo_down = False     # 右 Ctrl 当前是否按下
        self._held = set()           # 当前按下的目标键(已归一化名)
        self._lock = threading.Lock()

    def start(self) -> None:
        if not sys.platform.startswith("win"):
            raise NotImplementedError("全局热键目前仅 Windows 实现(keyboard)")
        import keyboard
        with self._lock:
            if self._hooked:
                return
            self._hooked = True
        # 监听全部按键,自己判组合,避免 add_hotkey 不报松开事件
        try:
            keyboard.hook(self._on_key)
        except Exception:
            with self._lock:
                self._hooked = False
            raise

    def stop(self) -> None:
        with self._lock:
            if not self._hooked:
                return
            self._hooked = False
            self._combo_down = False
            self._held.clear()
        import keyboard
        keyboard.unhook(self._on_key)

    def set_hotkey(self, keys) -> None:
        normalized = tuple(self._norm(k) for k in keys)
        if not normalized or len(set(normalized)) != len(normalized):
            raise ValueError("热键必须包含至少一个不同的按键")
        with self._lock:
            self._keys = normalized
            self._combo_down = False
            self._held.clear()

    # ---------- keyboard 钩子回调(内部线程)----------

    @staticmethod
    def _norm(name: str) -> str:
        """归一化按键名,保留 right/left 修饰键方向。"""
        n = (name or "").lower().strip()
        parts = n.split()
        if len(parts) == 2 and parts[0] in ("left", "right"):
            key = "ctrl" if parts[1] in ("ctrl", "control") else parts[1]
            if key in ("ctrl", "alt", "shift", "windows", "cmd"):
                return f"{parts[0]} {key}"
        if n in ("control", "ctrl"):
            return "ctrl"
        for mod in ("ctrl", "alt", "shift", "windows", "cmd"):
            if mod in n:
                return "cmd" if mod in ("windows", "cmd") else mod
        return n

    def _on_key(self, event) -> None:
        # event.event_type: "down" | "up";event.name 可能是 "left ctrl" 等
        name = self._norm(event.name)
        with self._lock:
            if not self._hooked:
                return
            if name not in self._keys:
                return
            etype = getattr(event, "event_type", None)
            if etype not in ("down", "up"):
                return
            if etype == "down":
                self._held.add(name)
            else:
                self._held.discard(name)

            down = all(k in self._held for k in self._keys)
            if down and not self._combo_down:
                self._combo_down = True
                self._safe(self._on_start)
            elif not down and self._combo_down:
                self._combo_down = False
                self._safe(self._on_stop)

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:
            print(f"[听写] 热键回调异常: {e}")
