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
    is_me: bool = False      # 是否本机用户("我"那一路),供 UI 气泡左右/配色
    draft: bool = False      # 是否未定稿草稿(zipformer 实时文本,浅色)


class MeetingRecorder:
    def __init__(self) -> None:
        self._items: List[Utterance] = []
        self._lock = threading.Lock()
        self._t0 = time.time()
        # 说话人重命名映射:原始标签 -> 显示名
        self._rename: dict[str, str] = {}
        # 每个说话人当前未定稿的草稿(zipformer 实时文本),定稿时清空
        self._drafts: dict[str, str] = {}

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
            self._rename.clear()
            self._drafts.clear()
            self._t0 = time.time()

    def refine_speaker(self, base_speaker: str, diar_segments,
                       label_fmt: str = "{base}-发言人{n}") -> int:
        """会后说话人分离:把 base_speaker(如"远端")的每条按时间细分到具体发言人。

        diar_segments: [SpkSegment(start,end,speaker)],来自 diarize.diarize()。
        按每条 Utterance 的时间 t 落到哪个 diar 段,改其 speaker 为 base-发言人N。
        返回细分出的发言人数量。说话人编号按出现顺序重排为 1,2,3…(而非原始聚类号)。
        """
        from livebabel.meeting.diarize import speaker_at
        with self._lock:
            # 原始聚类号 → 顺序号(1,2,3…)
            order: dict = {}
            n_count = 0
            for u in self._items:
                if u.speaker != base_speaker:
                    continue
                sid = speaker_at(diar_segments, u.t)
                if sid is None:
                    continue
                if sid not in order:
                    n_count += 1
                    order[sid] = n_count
                u.speaker = label_fmt.format(base=base_speaker, n=order[sid])
            return n_count

    def add(self, speaker: str, text: str) -> None:
        """定稿一条(SenseVoice 最终文本):入正式列表,并清掉该说话人的草稿。"""
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._items.append(Utterance(t=time.time() - self._t0, speaker=speaker, text=text))
            self._drafts.pop(speaker, None)

    def set_draft(self, speaker: str, text: str) -> None:
        """更新某说话人的实时草稿(zipformer volatile/provisional)。空文本清除。"""
        with self._lock:
            text = text.strip()
            if text:
                self._drafts[speaker] = text
            else:
                self._drafts.pop(speaker, None)

    def drafts(self) -> List[Utterance]:
        """当前各说话人的草稿(应用重命名),供 UI 显示浅色气泡。"""
        with self._lock:
            now = time.time() - self._t0
            return [Utterance(t=now, speaker=self._disp(spk), text=txt,
                              is_me=(spk == "我"), draft=True)
                    for spk, txt in self._drafts.items()]

    def rename(self, original: str, display: str) -> None:
        with self._lock:
            self._rename[original] = display.strip()

    def _disp(self, spk: str) -> str:
        return self._rename.get(spk, spk)

    def speakers(self) -> List[str]:
        """出现过的原始说话人标签(含仅有草稿的,按首次出现顺序)。"""
        with self._lock:
            seen, out = set(), []
            for u in self._items:
                if u.speaker not in seen:
                    seen.add(u.speaker)
                    out.append(u.speaker)
            for spk in self._drafts:
                if spk not in seen:
                    seen.add(spk)
                    out.append(spk)
            return out

    def segments(self) -> List[Utterance]:
        """已定稿条目副本(应用重命名),供 UI / 导出。"""
        with self._lock:
            return [Utterance(t=u.t, speaker=self._disp(u.speaker), text=u.text,
                              is_me=(u.speaker == "我"))
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
