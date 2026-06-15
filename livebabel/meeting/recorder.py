"""会议记录:线程安全地收集带时间戳 + 说话人的转录片段。

两路 ASR(麦克风=我、loopback=远端)并发往这里 add(),GUI 线程读 segments() 刷新。
说话人名可后期重命名(把"远端"改成真实姓名),影响最终纪要质量。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import List, Optional


def _smooth_runs(sids: List[Optional[int]], min_run: int = 3) -> List[Optional[int]]:
    """把 token 级说话人序列里【过短的游程】并入相邻说话人,抑制单点跳变噪声。

    例:[A,A,A,B,A,A,A,A](中间单个 B 是重叠窗噪声)→ [A,A,A,A,A,A,A,A]。
    但 [A,A,A,A,B,B,B,B,B](真换人)保留。min_run 是认定为真换人的最少连续 token 数。
    """
    if not sids:
        return sids
    # 切成游程
    runs = []  # [sid, length]
    for s in sids:
        if runs and runs[-1][0] == s:
            runs[-1][1] += 1
        else:
            runs.append([s, 1])
    # 反复把短游程并入较长的相邻游程,直到稳定
    changed = True
    while changed and len(runs) > 1:
        changed = False
        for i, (sid, ln) in enumerate(runs):
            if ln >= min_run:
                continue
            left = runs[i - 1] if i > 0 else None
            right = runs[i + 1] if i < len(runs) - 1 else None
            # 并入更长的那侧邻居
            target = None
            if left and right:
                target = left if left[1] >= right[1] else right
            else:
                target = left or right
            if target is not None:
                target[0] = target[0]   # 保持邻居 sid
                # 把当前短游程的长度算给邻居,然后删掉它
                target[1] += ln
                runs.pop(i)
                changed = True
                break
    # 合并相邻同 sid 游程后展开
    out: List[Optional[int]] = []
    for sid, ln in runs:
        out.extend([sid] * ln)
    # 长度可能因合并错位,按原长度兜底
    if len(out) != len(sids):
        # 退化:不平滑
        return sids
    return out


@dataclass
class Utterance:
    t: float                 # 相对会议开始的秒数(定稿时刻,供 UI 显示)
    speaker: str             # 说话人标签("我" / "远端" / 重命名后的真名)
    text: str
    base: str = ""           # 原始路标签("我"/"远端"),声纹细分/重跑都按它匹配,不受 speaker 改写影响
    is_me: bool = False      # 是否本机用户("我"那一路),供 UI 气泡左右/配色
    draft: bool = False      # 是否未定稿草稿(zipformer 实时文本,浅色)
    a_start: float = -1.0    # 该段在本路音频里的起止秒(供会后按声纹边界拆分归属)
    a_end: float = -1.0
    tokens: list = None      # token 文本列表(SenseVoice)
    timestamps: list = None  # 每个 token 的绝对秒(供精确按字时间拆分)


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

        按 u.base(原始路标签)匹配而非 u.speaker:① 重复点击可重跑(上轮已改名的也能再分);
        ② 若用户已重命名 base(远端→Alice),显示名带重命名前缀(Alice-发言人N),不丢失重命名。
        """
        from livebabel.meeting.diarize import speaker_at
        with self._lock:
            disp_base = self._rename.get(base_speaker, base_speaker)  # base 已重命名则沿用
            order: dict = {}          # 原始聚类号 → 顺序号
            def _label(sid):
                nonlocal order
                if sid not in order:
                    order[sid] = len(order) + 1
                return label_fmt.format(base=disp_base, n=order[sid])

            new_items: List[Utterance] = []
            for u in self._items:
                if u.base != base_speaker:
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
                ranked = sorted(overlaps.items(), key=lambda kv: -kv[1])
                tot = sum(overlaps.values()) or 1.0
                top_sid = ranked[0][0]
                second_share = (ranked[1][1] / tot) if len(ranked) > 1 else 0.0
                second_dur = ranked[1][1] if len(ranked) > 1 else 0.0
                has_tokens = bool(u.tokens and u.timestamps
                                  and len(u.tokens) == len(u.timestamps))
                # 有 token 时间戳:走精确拆分(内部用游程平滑判断真换人,噪声不会切碎),
                # 哪怕次说话人占比小也尝试——这样"一段里换了人"能被拆开。
                # 无 token 时间戳:只能按占比粗切,门槛严(次≥35%且≥2s)防误切。
                if has_tokens:
                    new_items.extend(self._split_utterance(u, diar_segments, _label))
                elif second_share >= 0.35 and second_dur >= 2.0:
                    new_items.extend(self._split_utterance(u, diar_segments, _label))
                else:
                    u.speaker = _label(top_sid)
                    new_items.append(u)
            self._items = new_items
            return len(order)

    def apply_llm_correction(self, api_key: str = "") -> int:
        """声纹分完后,用 LLM 按对话逻辑矫正说话人归属(只改归属,不改文字)。

        只对已细分(speaker 含"-发言人")的条目矫正。返回被改动的条目数。
        无 key / 失败则不改、返回 0。
        """
        from livebabel.meeting.llm_refine import refine_with_llm
        with self._lock:
            # 只取已细分的条(显示用当前 speaker)
            idxs = [i for i, u in enumerate(self._items) if "-发言人" in u.speaker]
            if not idxs:
                return 0
            items = [(i, self._items[i].speaker, self._items[i].text) for i in idxs]
        # 网络请求在锁外做(别占着锁等网络)
        mapping = refine_with_llm(items, api_key=api_key)
        if not mapping:
            return 0
        changed = 0
        with self._lock:
            for i, spk in mapping.items():
                if 0 <= i < len(self._items) and self._items[i].speaker != spk:
                    self._items[i].speaker = spk
                    changed += 1
        return changed

    def _split_utterance(self, u: "Utterance", diar_segments, label_fn) -> List["Utterance"]:
        """把一条跨多说话人的转录按声纹边界拆成多条。

        优先用 SenseVoice 的 token 时间戳【精确按字时间】拆:每个 token 落到它时间点
        所属的声纹说话人,连续同说话人的 token 合成一条。无时间戳则退化为按时长比例粗切。
        """
        from livebabel.meeting.diarize import speaker_at
        # —— 精确路径:有 token 时间戳 ——
        if u.tokens and u.timestamps and len(u.tokens) == len(u.timestamps):
            # 1) 每个 token 落到所属说话人
            sids = [speaker_at(diar_segments, ts) for ts in u.timestamps]
            # 2) 平滑:抹掉过短的"说话人游程"(重叠窗噪声造成的单点跳变),
            #    游程 < MIN_RUN 个 token 的并入相邻较长说话人,避免把句子切碎。
            sids = _smooth_runs(sids, min_run=3)
            # 3) 按平滑后的连续游程切句
            out: List[Utterance] = []
            cur_sid = None
            cur_toks: list = []
            cur_ts: list = []

            def flush():
                if cur_toks and cur_sid is not None:
                    txt = "".join(cur_toks).strip()
                    if txt:
                        out.append(Utterance(t=u.t, speaker=label_fn(cur_sid), text=txt,
                                             base=u.base, is_me=False,
                                             a_start=u.a_start, a_end=u.a_end,
                                             tokens=list(cur_toks), timestamps=list(cur_ts)))
            for tok, ts, sid in zip(u.tokens, u.timestamps, sids):
                if sid != cur_sid:
                    flush()
                    cur_sid, cur_toks, cur_ts = sid, [], []
                cur_toks.append(tok)
                cur_ts.append(ts)
            flush()
            if out:
                return out
            return [u]

        # —— 退化路径:按时长比例粗切 ——
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
            remain = n - idx
            if remain <= 0:
                break                       # 文字已分完(前面取整偶有多占),后续 piece 跳过
            # 最后一段吃掉剩余;否则按比例取,且不超过剩余、至少留够后面每段 1 字
            if k == len(pieces) - 1:
                take = remain
            else:
                take = max(1, round(n * dur / total))
                take = min(take, remain - (len(pieces) - 1 - k))  # 给后面每段至少留 1
                take = max(1, take)
            chunk = text[idx:idx + take].strip()
            idx += take
            if chunk:
                out.append(Utterance(t=u.t, speaker=label_fn(sid), text=chunk,
                                     base=u.base, is_me=False,
                                     a_start=u.a_start, a_end=u.a_end))
        return out if out else [u]

    def add(self, speaker: str, text: str, a_start: float = -1.0, a_end: float = -1.0,
            tokens=None, timestamps=None) -> None:
        """定稿一条(SenseVoice 最终文本):入正式列表,并清掉该说话人的草稿。

        a_start/a_end: 该段在本路音频里的起止秒;tokens/timestamps: token 级文本+绝对秒,
        供会后按声纹边界【精确按字时间】拆分归属。
        """
        text = text.strip()
        if not text:
            return
        with self._lock:
            self._items.append(Utterance(
                t=time.time() - self._t0, speaker=speaker, text=text, base=speaker,
                a_start=a_start, a_end=a_end, tokens=tokens, timestamps=timestamps))
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
