"""两遍 ASR 引擎。

Pass1(流式 zipformer):每帧解码,产出会变动的 volatile 文本,并负责 endpoint 检测。
Pass2(非流式 SenseVoice):endpoint 触发时,对该句缓存的音频复识一次,
                          得到更准、不抖的定稿文本。

对外只暴露三件事:
  feed(samples)         喂一帧音频
  poll() -> Event       拿当前状态:文本更新 / 句子结束(committed)
内部维护"当前句"的音频缓冲,以便 commit 时交给 Pass2。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional

import numpy as np
import sherpa_onnx

SAMPLE_RATE = 16000

# 去掉所有标点/空白后得到有效内容
_PUNCT = re.compile(r"[\s\.,!?;:、。，！？；：…·\-\"'()\[\]<>]+")
# 常见的静音/噪声幻觉填充词(流式模型在空白段容易吐这些)
_FILLERS = {
    "the", "a", "i", "yeah", "you", "uh", "um", "oh", "hmm", "mm",
    "嗯", "啊", "呃", "哦", "唉", "诶",
}


def _core_len(text: str) -> int:
    """去标点空白后的有效字符数。英文按词折算(一个词≈2字)更接近中文粒度。"""
    core = _PUNCT.sub("", text)
    return len(core)


def _is_garbage(text: str, seg_dur: float = 0.0) -> bool:
    """判断是否为应丢弃的幻觉碎段。

    规则:
      1. 去标点后 <2 字符 → 垃圾。
      2. 整段就是一个常见填充词(the/嗯/yeah…)→ 垃圾。
      3. 段时长可观(>1.2s)却只识别出极少有效字(<3),说明大半是静音幻觉。
    真实短句(如"好的""谢谢你")字数够、时长短,不会被误杀。
    """
    stripped = _PUNCT.sub("", text).lower()
    if len(stripped) < 2:
        return True
    if stripped in _FILLERS:
        return True
    if seg_dur > 1.2 and _core_len(text) < 3:
        return True
    return False


@dataclass
class AsrEvent:
    """一次 poll 的结果。"""

    volatile_text: str          # 当前句的实时(会变)文本
    committed_text: Optional[str] = None   # 非 None 表示这句定稿了,值为高精度结果
    audio_start: int = 0
    audio_end: int = 0


class TwoPassAsr:
    def __init__(
        self,
        first_dir: str,
        second_dir: str,
        num_threads: int = 2,
    ) -> None:
        self.first = self._build_first(first_dir, num_threads)
        self.second = self._build_second(second_dir, num_threads)
        self.stream = self.first.create_stream()

        # 当前句的音频缓冲(commit 时交给 Pass2),以及它在全局流中的起点
        self._cur_audio: list[np.ndarray] = []
        self._global_pos = 0          # 已喂入的总样本数
        self._seg_start = 0           # 当前句起始样本位置
        self._last_text = ""

    # ---------- 模型构建 ----------

    def _build_first(self, d: str, nt: int) -> sherpa_onnx.OnlineRecognizer:
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=f"{d}/tokens.txt",
            encoder=f"{d}/encoder-epoch-99-avg-1.onnx",
            decoder=f"{d}/decoder-epoch-99-avg-1.onnx",
            joiner=f"{d}/joiner-epoch-99-avg-1.onnx",
            num_threads=nt,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            enable_endpoint_detection=True,
            rule1_min_trailing_silence=2.4,   # 完全静默(无任何解码)时的 endpoint
            rule2_min_trailing_silence=1.4,   # 有内容后的尾静音阈值。调高=少误切自然停顿
            rule3_min_utterance_length=25,    # 句子超过该秒数强制切,防超长段
            decoding_method="greedy_search",
        )

    def _build_second(self, d: str, nt: int) -> sherpa_onnx.OfflineRecognizer:
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=f"{d}/model.int8.onnx",
            tokens=f"{d}/tokens.txt",
            num_threads=nt,
            use_itn=True,   # 反规范化:数字/标点更自然
        )

    # ---------- Pass2 复识 ----------

    def _refine(self, audio: np.ndarray) -> str:
        if len(audio) < SAMPLE_RATE * 0.2:   # 太短不值得复识
            return ""
        s = self.second.create_stream()
        s.accept_waveform(SAMPLE_RATE, audio)
        self.second.decode_stream(s)
        return s.result.text.strip()

    # ---------- 主循环接口 ----------

    def feed(self, samples: np.ndarray) -> AsrEvent:
        """喂一帧,返回本次状态。"""
        self.stream.accept_waveform(SAMPLE_RATE, samples)
        self._cur_audio.append(samples)
        self._global_pos += len(samples)

        while self.first.is_ready(self.stream):
            self.first.decode_stream(self.stream)

        text = self.first.get_result(self.stream).strip()
        is_endpoint = self.first.is_endpoint(self.stream)

        if not is_endpoint:
            self._last_text = text or self._last_text
            return AsrEvent(
                volatile_text=text,
                audio_start=self._seg_start,
                audio_end=self._global_pos,
            )

        # --- endpoint:定稿当前句 ---
        seg_audio = (
            np.concatenate(self._cur_audio) if self._cur_audio else np.zeros(0, np.float32)
        )
        refined = self._refine(seg_audio)
        committed = refined or text or self._last_text

        # 过滤幻觉碎段:这段实际上是静音/噪声,不定稿,只重置
        seg_dur = len(seg_audio) / SAMPLE_RATE
        committed_text = None if _is_garbage(committed, seg_dur) else committed

        evt = AsrEvent(
            volatile_text=text,
            committed_text=committed_text,
            audio_start=self._seg_start,
            audio_end=self._global_pos,
        )

        # 重置,准备下一句
        self.first.reset(self.stream)
        self._cur_audio = []
        self._seg_start = self._global_pos
        self._last_text = ""
        return evt

    def finalize(self) -> Optional[AsrEvent]:
        """音频结束时,把残留未定稿的最后一句强制定稿。"""
        if not self._cur_audio:
            return None
        text = self.first.get_result(self.stream).strip()
        seg_audio = np.concatenate(self._cur_audio)
        refined = self._refine(seg_audio)
        committed = refined or text or self._last_text
        seg_dur = len(seg_audio) / SAMPLE_RATE
        if not committed or _is_garbage(committed, seg_dur):
            return None
        return AsrEvent(
            volatile_text=text,
            committed_text=committed,
            audio_start=self._seg_start,
            audio_end=self._global_pos,
        )
