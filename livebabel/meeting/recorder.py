"""会议记录:线程安全地收集带时间戳 + 说话人的转录片段。

两路 ASR(麦克风=我、loopback=远端)并发往这里 add(),GUI 线程读 segments() 刷新。
说话人名可后期重命名(把"远端"改成真实姓名),影响最终纪要质量。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List


@dataclass
class Utterance:
    t: float                 # 相对会议开始的秒数
    speaker: str             # 说话人标签("我" / "远端" / 重命名后的真名)
    text: str


class MeetingRecorder:
    def __init__(self) -> None:
        self._items: List[Utterance] = []
        self._lock = threading.Lock()
        self._t0 = time.time()
        # 说话人重命名映射:原始标签 -> 显示名
        self._rename: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._rename.clear()
            self._t0 = time.time()

    def add(self, speaker: str, text: str) -> None:
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._items.append(Utterance(t=time.time() - self._t0, speaker=speaker, text=text))

    def rename(self, original: str, display: str) -> None:
        with self._lock:
            self._rename[original] = display.strip()

    def _disp(self, spk: str) -> str:
        return self._rename.get(spk, spk)

    def speakers(self) -> List[str]:
        """出现过的原始说话人标签(按首次出现顺序)。"""
        with self._lock:
            seen, out = set(), []
            for u in self._items:
                if u.speaker not in seen:
                    seen.add(u.speaker)
                    out.append(u.speaker)
            return out

    def segments(self) -> List[Utterance]:
        """副本(应用重命名),供 UI / 导出。"""
        with self._lock:
            return [Utterance(t=u.t, speaker=self._disp(u.speaker), text=u.text)
                    for u in self._items]

    def is_empty(self) -> bool:
        with self._lock:
            return not self._items

    @staticmethod
    def fmt_ts(seconds: float) -> str:
        s = max(0, int(seconds))
        return f"{s // 60:02d}:{s % 60:02d}"

    def as_transcript_lines(self) -> List[str]:
        """成行的「[mm:ss] 说话人:文本」,供摘要/导出。"""
        return [f"[{self.fmt_ts(u.t)}] {u.speaker}:{u.text}" for u in self.segments()]
