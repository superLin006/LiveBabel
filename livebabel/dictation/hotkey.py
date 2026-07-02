"""全局热键监听:区分 PTT(按住说话)与切换式(双击开/关)。Windows 用 keyboard。

回调:
  on_start() —— 该开始听写(PTT 按下 / 切换式开启)
  on_stop()  —— 该结束听写(PTT 松开 / 切换式再次触发)

默认热键组合 ctrl+alt:
  * 按住不放 ≈ PTT:按下 on_start,松开 on_stop。
  * 在 DOUBLE_TAP 窗口内快速两次"按下-松开" ≈ 切换式:翻转常开状态,
    此时不受松开影响,直到再次双击关闭。

注意:keyboard 在 Linux 需 root(WSL 无效),Windows 普通权限可用。
监听回调在 keyboard 的内部线程,务必只发信号、不做重活。
"""

from __future__ import annotations

import sys
import threading
import time
from typing import Callable

# 默认触发键(同时按下视为组合)。可被 set_hotkey 覆盖。
DEFAULT_KEYS = ("ctrl", "alt")
# 双击判定窗口(秒):两次完整按下-松开都在此窗口内 → 切换式
DOUBLE_TAP = 0.4


class HotkeyManager:
    def __init__(self, on_start: Callable[[], None], on_stop: Callable[[], None],
                 keys=DEFAULT_KEYS) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._keys = tuple(keys)
        self._hooked = False

        self._combo_down = False     # 组合键当前是否全部按下
        self._toggle_on = False      # 切换式:是否处于常开听写
        self._last_release = 0.0     # 上次组合键松开的时间(判双击)
        self._pending_ptt = False    # 当前按下是否已触发 on_start(PTT)
        self._held = set()           # 当前按下的目标键(已归一化名)
        self._lock = threading.Lock()

    def start(self) -> None:
        if not sys.platform.startswith("win"):
            raise NotImplementedError("全局热键目前仅 Windows 实现(keyboard)")
        import keyboard
        # 监听全部按键,自己判组合,避免 add_hotkey 不报松开事件
        keyboard.hook(self._on_key)
        self._hooked = True

    def stop(self) -> None:
        if self._hooked:
            import keyboard
            keyboard.unhook(self._on_key)
            self._hooked = False

    def set_hotkey(self, keys) -> None:
        self._keys = tuple(keys)

    # ---------- keyboard 钩子回调(内部线程)----------

    @staticmethod
    def _norm(name: str) -> str:
        """归一化修饰键名:left ctrl/right ctrl → ctrl,left alt → alt 等。"""
        n = (name or "").lower().strip()
        for mod in ("ctrl", "alt", "shift", "windows", "cmd"):
            if mod in n:
                return "cmd" if mod in ("windows", "cmd") else mod
        return n

    def _on_key(self, event) -> None:
        # event.event_type: "down" | "up";event.name 可能是 "left ctrl" 等
        name = self._norm(event.name)
        if name not in self._keys:
            return
        etype = getattr(event, "event_type", None)
        now = time.monotonic()
        with self._lock:
            if etype == "down":
                self._held.add(name)
            elif etype == "up":
                self._held.discard(name)
            else:
                return

            down = all(k in self._held for k in self._keys)
            if down and not self._combo_down:
                self._combo_down = True
                self._handle_combo_down(now)
            elif not down and self._combo_down:
                self._combo_down = False
                self._handle_combo_up(now)

    def _handle_combo_down(self, now: float) -> None:
        if self._toggle_on:
            # 已在切换式常开 → 这次按下用于"关闭"(在松开时根据双击判定)
            return
        # 进入 PTT:立即开始
        self._pending_ptt = True
        self._safe(self._on_start)

    def _handle_combo_up(self, now: float) -> None:
        is_double = (now - self._last_release) <= DOUBLE_TAP
        self._last_release = now

        if self._toggle_on:
            # 常开中再次完成一次按下-松开 → 关闭常开
            self._toggle_on = False
            self._safe(self._on_stop)
            self._pending_ptt = False
            return

        if is_double:
            # 双击:从 PTT 升级为切换式常开(不在松开时停)
            self._toggle_on = True
            self._pending_ptt = False
            # on_start 已在第一次按下时调用过,保持录音继续,不重复调
            return

        # 普通 PTT:松开即停
        if self._pending_ptt:
            self._pending_ptt = False
            self._safe(self._on_stop)

    @staticmethod
    def _safe(fn: Callable[[], None]) -> None:
        try:
            fn()
        except Exception as e:
            print(f"[听写] 热键回调异常: {e}")
