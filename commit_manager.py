"""晃动消除 + 低延迟的核心:volatile / provisional / committed 三态管理。

晃动的本质:流式 ASR 每收一帧就重算整句假设,文本不断回退、改写。直接拿它翻译会疯狂跳动。
长句延迟的本质:VAD 要等一整段语音结束才 commit,说话人不停就迟迟没有译文。

三态生命周期(末尾至多一个"进行中"的段):
  * volatile(未定稿):当前正说的子句,文本会变。原文照显,不翻译。
  * provisional(临时定稿):段还没结束,但子句边界/超时触发,先用流式文本翻译一版,
                            让用户尽快看懂大意。译文浅色显示,可被覆盖。
  * committed(最终定稿):VAD 真正结束该段(或强制),用 Pass2 高精度文本重译,
                          替换临时译文并锁定,译文变亮。

一个"段"在生命周期里 id 不变:provisional → committed 是同一个 Segment 的状态升级,
所以临时译文能被最终译文原地替换,而不是新增一行。
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Optional


@dataclass
class Segment:
    id: int
    text: str
    translation: Optional[str] = None
    provisional: bool = False   # True=临时(译文浅色,可被覆盖);False 且 committed=True 为最终
    committed: bool = False      # True=已定稿(provisional 或 final 都算"已离开 volatile")
    utt_id: int = -1             # 所属语音段;段结束时用它找到要替换的临时子句
    audio_start: int = 0
    audio_end: int = 0


class CommitManager:
    def __init__(self) -> None:
        self._segments: list[Segment] = []
        self._ids = itertools.count()
        self._volatile: Optional[Segment] = None

    # ---- volatile:流式 ASR 每出一次结果就调这里 ----

    def update_volatile(self, text: str, audio_start: int = 0, audio_end: int = 0) -> None:
        text = text.strip()
        if not text:
            return
        if self._volatile is None:
            self._volatile = Segment(id=next(self._ids), text=text,
                                     audio_start=audio_start, audio_end=audio_end)
            self._segments.append(self._volatile)
        else:
            self._volatile.text = text
            self._volatile.audio_end = audio_end

    # ---- 子句定稿:把一段文本作为独立的已定稿行加入 ----

    def add_committed(self, text: str, provisional: bool, utt_id: int = -1) -> Optional[Segment]:
        """新增一个已定稿子句行(provisional=临时浅色,False=最终)。返回该段供送翻译。

        加入后清空 volatile(当前草稿已被这一行"吃掉"),后续草稿进新的 volatile 段。
        """
        text = text.strip()
        if not text:
            return None
        seg = Segment(id=next(self._ids), text=text,
                      provisional=provisional, committed=True, utt_id=utt_id)
        self._segments.append(seg)
        self._volatile = None
        return seg

    def replace_utterance(self, utt_id: int, final_text: str) -> Optional[Segment]:
        """段结束:删除该段所有临时子句,用 SenseVoice 整段高精度文本替换为一行最终段。

        保持位置在原临时子句处。返回新的最终段(供重译)。
        """
        final_text = final_text.strip()
        if not final_text:
            return None
        # 找到该段第一条临时子句的位置
        insert_at = None
        kept: list[Segment] = []
        for i, s in enumerate(self._segments):
            if s.utt_id == utt_id and s.provisional:
                if insert_at is None:
                    insert_at = len(kept)
            else:
                kept.append(s)
        seg = Segment(id=next(self._ids), text=final_text,
                      provisional=False, committed=True, utt_id=utt_id)
        if insert_at is None:
            kept.append(seg)
        else:
            kept.insert(insert_at, seg)
        self._segments = kept
        self._volatile = None
        return seg

    # ---- 翻译回填 ----

    def set_translation(self, seg_id: int, translation: str) -> None:
        for seg in self._segments:
            if seg.id == seg_id:
                seg.translation = translation
                return

    def get(self, seg_id: int) -> Optional[Segment]:
        for seg in self._segments:
            if seg.id == seg_id:
                return seg
        return None

    # ---- 查询 ----

    @property
    def committed(self) -> list[Segment]:
        return [s for s in self._segments if s.committed]

    @property
    def volatile(self) -> Optional[Segment]:
        return self._volatile

    def recent(self, n_committed: int = 3):
        return self.committed[-n_committed:], self._volatile
