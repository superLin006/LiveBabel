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
    t: float                 # 相对会议开始的秒数(定稿时刻,供 UI 显示)
    speaker: str             # 说话人标签("我" / "远端" / 重命名后的真名)
    text: str
    is_me: bool = False      # 是否本机用户("我"那一路),供 UI 气泡左右/配色
    draft: bool = False      # 是否未定稿草稿(zipformer 实时文本,浅色)
    a_start: float = -1.0    # 该段在本路音频里的起止秒(供会后按声纹边界拆分归属)
    a_end: float = -1.0


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
        """会后说话人分离:把 base_speaker(如"远端")按声纹边界细分到具体发言人。

        diar_segments: [SpkSegment(start,end,speaker)],来自 diarize.diarize()。
        对每条 base 转录,用其音频区间 [a_start,a_end] 与声纹分段求重叠:
          * 只重叠一个说话人 → 整条改标 base-发言人N
          * 跨多个说话人 → 按各说话人在该区间的时长占比【拆分文字】,各归各人
        没有音频区间(a_start<0)的旧数据退化为按定稿时刻 t 取最近段。
        返回细分出的发言人数量(编号按出现顺序 1,2,3…)。
        """
        from livebabel.meeting.diarize import speaker_at
        with self._lock:
            order: dict = {}          # 原始聚类号 → 顺序号
            def _label(sid):
                nonlocal order
                if sid not in order:
                    order[sid] = len(order) + 1
                return label_fmt.format(base=base_speaker, n=order[sid])

            new_items: List[Utterance] = []
            for u in self._items:
                if u.speaker != base_speaker:
                    new_items.append(u)
                    continue
                # 无音频区间(旧数据):按定稿时刻取最近段
                if u.a_start < 0 or u.a_end <= u.a_start:
                    sid = speaker_at(diar_segments, u.t)
                    u.speaker = _label(sid) if sid is not None else u.speaker
                    new_items.append(u)
                    continue
                # 计算该段音频区间里各说话人的重叠时长
                overlaps: dict = {}
                for s in diar_segments:
                    lo, hi = max(u.a_start, s.start), min(u.a_end, s.end)
                    if hi > lo:
                        overlaps[s.speaker] = overlaps.get(s.speaker, 0.0) + (hi - lo)
                if not overlaps:
                    sid = speaker_at(diar_segments, u.t)
                    u.speaker = _label(sid) if sid is not None else u.speaker
                    new_items.append(u)
                    continue
                if len(overlaps) == 1:
                    u.speaker = _label(next(iter(overlaps)))
                    new_items.append(u)
                    continue
                # 跨多人:按时长占比拆分文字(无字级时间戳,按比例粗分,顺序按时间)
                new_items.extend(self._split_utterance(u, diar_segments, _label))
            self._items = new_items
            return len(order)

    def _split_utterance(self, u: "Utterance", diar_segments, label_fn) -> List["Utterance"]:
        """把一条跨多说话人的转录,按声纹分段的时间顺序拆成多条,文字按时长比例分配。"""
        # 取与该段重叠的声纹片段,按时间排序;相邻同一说话人合并
        pieces = []  # (speaker_id, dur)
        for s in sorted(diar_segments, key=lambda x: x.start):
            lo, hi = max(u.a_start, s.start), min(u.a_end, s.end)
            if hi <= lo:
                continue
            if pieces and pieces[-1][0] == s.speaker:
                pieces[-1] = (s.speaker, pieces[-1][1] + (hi - lo))
            else:
                pieces.append((s.speaker, hi - lo))
        if len(pieces) <= 1:
            sid = pieces[0][0] if pieces else None
            if sid is not None:
                u.speaker = label_fn(sid)
            return [u]
        total = sum(d for _, d in pieces) or 1.0
        text = u.text
        out: List[Utterance] = []
        idx = 0
        n = len(text)
        for k, (sid, dur) in enumerate(pieces):
            # 最后一段吃掉剩余,避免取整丢字
            take = n - idx if k == len(pieces) - 1 else max(1, round(n * dur / total))
            chunk = text[idx:idx + take].strip()
            idx += take
            if chunk:
                out.append(Utterance(t=u.t, speaker=label_fn(sid), text=chunk,
                                     is_me=False, a_start=u.a_start, a_end=u.a_end))
        return out if out else [u]

    def add(self, speaker: str, text: str, a_start: float = -1.0, a_end: float = -1.0) -> None:
        """定稿一条(SenseVoice 最终文本):入正式列表,并清掉该说话人的草稿。

        a_start/a_end: 该段在本路音频里的起止秒(供会后按声纹边界拆分归属)。
        """
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._items.append(Utterance(t=time.time() - self._t0, speaker=speaker, text=text,
                                         a_start=a_start, a_end=a_end))
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
