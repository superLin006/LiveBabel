"""基于 VAD 的两遍 ASR 引擎(更稳健的分段方案)。

与 asr_engine.py 的区别:不靠流式模型的 endpoint 规则 / 人为静音来切句,
而是用 silero-VAD 主动检测"语音段"边界。这样:
  * 段边界由真实的语音/静音决定,适配任意视频(连读、长停顿都行)。
  * Pass2 只对 VAD 切出的纯语音段复识,不含前后静音 → 几乎不产生幻觉碎段。
  * 流式 Pass1 仍并行跑,负责段内的实时 volatile 显示。

工作方式:
  feed(samples) 同时喂给 (a) 流式识别器出 volatile,(b) VAD。
  VAD 攒够一个完整语音段后,从队列 pop 出来 → Pass2 复识 → 该段 commit。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional

import numpy as np
import sherpa_onnx

SAMPLE_RATE = 16000

_cached_provider = None


def detect_provider() -> str:
    """探测 sherpa-onnx 能否真正用 CUDA,可以则 "cuda",否则 "cpu"。

    关键:不能靠 `import onnxruntime`(那是 faster-whisper 的 pip 包,sherpa 用的是
    自带 lib 里的另一份 onnxruntime)。两份混用会导致 cuda provider 初始化失败
    (Error 1114)。所以直接看 sherpa_onnx 是否报告 cuda 可用 / 是否带 cuda provider。
    结果缓存。任何异常安全回退 cpu。
    """
    global _cached_provider
    if _cached_provider is not None:
        return _cached_provider
    # 纯 CPU 版打包用此开关强制 CPU,避免在有 GPU 机器上尝试加载没打包的 GPU dll
    import os as _os
    if _os.environ.get("LIVEBABEL_CPU_ONLY", "").strip() in ("1", "true", "True"):
        _cached_provider = "cpu"
        return "cpu"
    provider = "cpu"
    try:
        # GPU 版 sherpa-onnx 的 lib 目录里会有 onnxruntime_providers_cuda.dll
        import os as _os
        import sherpa_onnx as _so
        libdir = _os.path.join(_os.path.dirname(_so.__file__), "lib")
        has_cuda_dll = _os.path.isfile(_os.path.join(libdir, "onnxruntime_providers_cuda.dll")) \
            or _os.path.isfile(_os.path.join(libdir, "libonnxruntime_providers_cuda.so"))
        if has_cuda_dll:
            provider = "cuda"
    except Exception:
        pass
    _cached_provider = provider
    return provider


_PUNCT = re.compile(r"[\s\.,!?;:、。，！？；：…·\-\"'()\[\]<>]+")
_FILLERS = {"the", "a", "i", "yeah", "you", "uh", "um", "oh", "嗯", "啊", "呃", "哦"}


def _clean(text: str) -> str:
    """去标点空白后的有效内容(用于判断子句长度)。"""
    return _PUNCT.sub("", text)


def _is_garbage(text: str) -> bool:
    s = _clean(text).lower()
    return len(s) < 2 or s in _FILLERS


# 含连续大写英文字母的片段(SenseVoice 英文输出常全大写)
_ALLCAP = re.compile(r"[A-Z]{2,}")
# 每个英文句子的开头字母(句首/. ! ? 后)
_SENT_START = re.compile(r"(^|[.!?]\s+)([a-z])")


def normalize_case(text: str) -> str:
    """把全大写的英文识别结果转成自然大小写:整体小写,再把句首字母大写,'i' 还原为 'I'。

    只在文本明显是全大写英文时处理,避免影响中文或已正常的英文。
    """
    if not _ALLCAP.search(text):
        return text
    # 只动英文字母,中文/数字/标点不变
    out = text.lower()
    # 句首字母大写
    out = _SENT_START.sub(lambda m: m.group(1) + m.group(2).upper(), out)
    if out and out[0].isalpha():
        out = out[0].upper() + out[1:]
    # 独立的 i 还原成 I
    out = re.sub(r"\bi\b", "I", out)
    out = re.sub(r"\bi'", "I'", out)
    return out


# 子句边界:出现这些标点视为一个可提前翻译的子句结束
_CLAUSE_END = re.compile(r"[,，。.!?！？;；]$")

# 段内提前翻译的触发参数
# 段内"提前翻译"的默认参数(平衡:优先在标点处切,极长无停顿才强制,避免碎句)
PROVISIONAL_MIN_CHARS = 8          # 标点结束的子句:至少这么多字才值得提前翻
PROVISIONAL_MIN_CHARS_TIMEOUT = 10 # 超时强制时的最低字数(够长才强制,免得切出"报告警告"这种碎片)
PROVISIONAL_MAX_SECONDS = 6.0      # 距上次提前翻译超过这么久,即使没标点也强制


@dataclass
class AsrEvent:
    """一次 ASR 状态。kind:
       'volatile'    未定稿草稿(原文显示,不翻译)
       'provisional' 临时定稿(段未结束,先翻一版,译文浅色,可被覆盖)
       'final'       最终定稿(段结束,Pass2 高精度,替换临时译文并锁定)
    """
    kind: str
    text: str = ""
    seg_index: int = -1
    utt_id: int = -1          # 所属语音段(utterance)的 id。同段的 provisional 共享它
    replace_seg: bool = False  # final 专用:True 表示用本段 SenseVoice 文本替换该段所有 provisional

    # 向后兼容旧字段名
    @property
    def volatile_text(self) -> str:
        return self.text if self.kind == "volatile" else ""

    @property
    def committed_text(self) -> Optional[str]:
        return self.text if self.kind in ("provisional", "final") else None


class VadTwoPassAsr:
    def __init__(self, first_dir: str, second_dir: str, num_threads: int = 2,
                 provisional: bool = True,
                 prov_max_seconds: float = PROVISIONAL_MAX_SECONDS,
                 provider: str = "auto") -> None:
        # provider: "auto"(默认,检测到 onnxruntime-gpu 的 CUDA provider 就用 cuda,
        # 否则 cpu)/ "cpu" / "cuda"。装了 onnxruntime-gpu + N 卡即自动 GPU 加速。
        import sys as _sys
        self.provider = detect_provider() if provider == "auto" else provider
        # GPU 模式:先注册/预加载 cuBLAS/cuDNN DLL,否则 sherpa 的 CUDA provider 会因
        # 找不到 cublasLt64_12.dll 等而加载失败。与离线 faster-whisper 复用同一套逻辑。
        if self.provider == "cuda":
            try:
                from livebabel.offline.cuda_dll import ensure_cuda_dlls
                ensure_cuda_dlls()
            except Exception:
                pass

        # 构建三个模型。GPU 构建若失败(如缺 cuDNN、provider 加载失败),
        # 自动回退 CPU 重建,保证一定能跑起来而不是直接报错。
        try:
            self._build_models(first_dir, second_dir, num_threads)
        except Exception as e:
            if self.provider == "cuda":
                print(f"[asr] GPU 初始化失败({type(e).__name__}: {e}),回退 CPU",
                      file=_sys.stderr)
                self.provider = "cpu"
                self._build_models(first_dir, second_dir, num_threads)
            else:
                raise
        print(f"[asr] 实时识别使用 {'GPU(CUDA)' if self.provider == 'cuda' else 'CPU'}",
              file=_sys.stderr)
        self._committed_count = 0
        # 段内提前翻译:provisional=False 则完全关闭(只在段结束时整段翻译)
        self.provisional = provisional
        self.prov_max_seconds = prov_max_seconds
        self._provisional_prefix = ""   # 当前段已经提前翻译过的文本前缀
        self._samples_since_prov = 0    # 距上次提前翻译累计的样本数
        self._utt_id = 0                # 当前语音段 id
        self._utt_had_prov = False      # 当前段是否出过临时子句(决定段尾是否要替换)

    # ---------- 构建 ----------

    def _build_models(self, first_dir: str, second_dir: str, nt: int) -> None:
        """按当前 self.provider 构建三个模型 + 流。GPU 失败时由 __init__ 改 cpu 重调。"""
        self.first = self._build_first(first_dir, nt)
        self.second = self._build_second(second_dir, nt)
        self.vad = self._build_vad(nt)
        self.stream = self.first.create_stream()

    def _build_first(self, d: str, nt: int) -> sherpa_onnx.OnlineRecognizer:
        return sherpa_onnx.OnlineRecognizer.from_transducer(
            tokens=f"{d}/tokens.txt",
            encoder=f"{d}/encoder-epoch-99-avg-1.onnx",
            decoder=f"{d}/decoder-epoch-99-avg-1.onnx",
            joiner=f"{d}/joiner-epoch-99-avg-1.onnx",
            num_threads=nt,
            sample_rate=SAMPLE_RATE,
            feature_dim=80,
            enable_endpoint_detection=False,   # 分段交给 VAD,不用 endpoint
            decoding_method="greedy_search",
            provider=self.provider,
        )

    def _build_second(self, d: str, nt: int) -> sherpa_onnx.OfflineRecognizer:
        return sherpa_onnx.OfflineRecognizer.from_sense_voice(
            model=f"{d}/model.int8.onnx",
            tokens=f"{d}/tokens.txt",
            num_threads=nt,
            use_itn=True,
            provider=self.provider,
        )

    def _build_vad(self, nt: int) -> sherpa_onnx.VoiceActivityDetector:
        from livebabel.paths import VAD_MODEL
        cfg = sherpa_onnx.VadModelConfig()
        cfg.silero_vad.model = VAD_MODEL
        cfg.silero_vad.threshold = 0.5
        cfg.silero_vad.min_silence_duration = 0.5   # 静音超过此值(秒)判定段结束
        cfg.silero_vad.min_speech_duration = 0.25   # 语音短于此值忽略
        cfg.silero_vad.max_speech_duration = 12.0   # 段最长,超过强制切
        cfg.sample_rate = SAMPLE_RATE
        cfg.num_threads = nt
        cfg.provider = self.provider
        return sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)

    # ---------- Pass2 ----------

    def _refine(self, audio: np.ndarray) -> str:
        if len(audio) < SAMPLE_RATE * 0.2:
            return ""
        s = self.second.create_stream()
        s.accept_waveform(SAMPLE_RATE, audio)
        self.second.decode_stream(s)
        return normalize_case(s.result.text.strip())

    # ---------- 主接口 ----------

    def reset(self) -> None:
        """丢弃当前未完成的识别状态(暂停时调用,避免暂停前后的音频被接成一句)。

        清空流式识别器、VAD 缓冲、以及段内 provisional 状态。已定稿的句子不受影响。
        """
        try:
            self.first.reset(self.stream)
        except Exception:
            pass
        try:
            self.vad.reset()
        except Exception:
            pass
        self._provisional_prefix = ""
        self._samples_since_prov = 0
        self._utt_had_prov = False
        self._utt_id += 1

    def _next_idx(self) -> int:
        i = self._committed_count
        self._committed_count += 1
        return i

    def feed(self, samples: np.ndarray) -> List[AsrEvent]:
        """喂一帧,返回若干事件(volatile / provisional / final)。"""
        events: List[AsrEvent] = []

        # (a) 流式识别 → 当前 utterance 的累计文本
        self.stream.accept_waveform(SAMPLE_RATE, samples)
        while self.first.is_ready(self.stream):
            self.first.decode_stream(self.stream)
        streaming = normalize_case(self.first.get_result(self.stream).strip())
        self._samples_since_prov += len(samples)

        # (b) 喂 VAD
        self.vad.accept_waveform(samples.astype(np.float32))

        # (c) VAD 关闭语音段 → 最终定稿(Pass2 SenseVoice 高精度,整段)
        seg_closed = False
        while not self.vad.empty():
            seg = self.vad.front
            seg_audio = np.array(seg.samples, dtype=np.float32)
            self.vad.pop()
            refined = self._refine(seg_audio)   # SenseVoice 整段重识(高精度)
            if refined and not _is_garbage(refined):
                # 若本段出过临时子句,用整段高精度结果"替换"它们;否则正常新增一行
                events.append(AsrEvent(
                    kind="final", text=refined, seg_index=self._next_idx(),
                    utt_id=self._utt_id, replace_seg=self._utt_had_prov,
                ))
            seg_closed = True

        if seg_closed:
            # 段结束,清空段内状态,进入下一段
            self.first.reset(self.stream)
            self._provisional_prefix = ""
            self._samples_since_prov = 0
            self._utt_had_prov = False
            self._utt_id += 1
            events.append(AsrEvent(kind="volatile", text=""))
            return events

        # (d) 段未结束:检查是否该"提前翻译"一个子句(provisional 关闭时跳过)
        delta = self._strip_prefix(streaming, self._provisional_prefix)
        n = len(_clean(delta))
        timed_out = self._samples_since_prov >= self.prov_max_seconds * SAMPLE_RATE
        should = False
        if self.provisional:
            if n >= PROVISIONAL_MIN_CHARS and _CLAUSE_END.search(delta):
                should = True                   # 子句标点结束 + 够长
            elif timed_out and n >= PROVISIONAL_MIN_CHARS_TIMEOUT:
                should = True                   # 太久没出译文,字数够最低门槛就强制
        if should and not _is_garbage(delta):
            events.append(AsrEvent(kind="provisional", text=delta,
                                   seg_index=self._next_idx(), utt_id=self._utt_id))
            self._provisional_prefix = streaming
            self._samples_since_prov = 0
            self._utt_had_prov = True

        # 末尾仍显示未定稿草稿(只显示 prefix 之后的部分)
        events.append(AsrEvent(kind="volatile", text=delta))
        return events

    def finalize(self) -> List[AsrEvent]:
        """冲刷 VAD 尾部残留语音。"""
        events: List[AsrEvent] = []
        self.vad.flush()
        while not self.vad.empty():
            seg = self.vad.front
            seg_audio = np.array(seg.samples, dtype=np.float32)
            self.vad.pop()
            refined = self._refine(seg_audio)
            if refined and not _is_garbage(refined):
                events.append(AsrEvent(
                    kind="final", text=refined, seg_index=self._next_idx(),
                    utt_id=self._utt_id, replace_seg=self._utt_had_prov,
                ))
            self._utt_had_prov = False
            self._utt_id += 1
        self._provisional_prefix = ""
        return events

    @staticmethod
    def _strip_prefix(text: str, prefix: str) -> str:
        """去掉已提前翻译的前缀,返回新增的尾部。前缀对不齐时回退为整句。"""
        text = text.strip()
        prefix = prefix.strip()
        if prefix and text.startswith(prefix):
            return text[len(prefix):].strip()
        # SenseVoice 和流式模型措辞可能不完全一致,对不齐就按字数粗略截尾
        if prefix and len(text) > len(prefix):
            return text[len(prefix):].strip()
        return text
