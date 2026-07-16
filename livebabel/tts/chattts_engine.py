"""ChatTTS 朗读引擎:魔改版 sherpa-onnx(集成 ChatTTS onnx int8)的薄封装。

魔改版 sherpa_onnx 是官方包的超集(同时含 ASR 识别 + ChatTTS 合成能力),
直接 import sherpa_onnx 即可,不需要运行时隔离。环境里只装这一个包
(参见 requirements.txt 注释),不再与官方 sherpa-onnx 共存。
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Optional

import numpy as np
import sherpa_onnx

from livebabel.paths import CHATTTS_DIR

SAMPLE_RATE = 24000  # ChatTTS/vocos 输出采样率
_PROVIDER = os.environ.get("LIVEBABEL_TTS_PROVIDER", "cpu").strip().lower()


def _select_provider() -> str:
    if _PROVIDER == "cpu":
        return "cpu"
    if _PROVIDER == "cuda":
        try:
            from livebabel.offline.cuda_dll import ensure_cuda_dlls
            ensure_cuda_dlls()
        except Exception:
            pass
        return "cuda"
    return "cpu"


class ChatTtsEngine:
    """朗读 TTS 引擎。模型懒加载 + 常驻复用(加载约 1.7s,不能每次朗读都重建)。

    generate(text, on_chunk) 支持流式回调:ChatTTS 解码内部本身分块产出音频
    (overlap-windowed decode),每出一块就调一次 on_chunk,不必等整句合成完。
    """

    def __init__(self) -> None:
        self._tts = None
        self._lock = threading.Lock()

    def _ensure_loaded(self):
        with self._lock:
            if self._tts is not None:
                return self._tts

            cfg = sherpa_onnx.OfflineTtsChatTtsModelConfig()
            cfg.gpt = f"{CHATTTS_DIR}/gpt_prefill.int8.onnx"
            cfg.decoder = f"{CHATTTS_DIR}/decoder.int8.onnx"
            cfg.vocos = f"{CHATTTS_DIR}/vocos.int8.onnx"
            cfg.vocab = f"{CHATTTS_DIR}/vocab.txt"
            cfg.homophones_map = f"{CHATTTS_DIR}/homophones_map.json"
            # 不填 speaker_embedding 时引擎用全零声纹,GPT 采样过程会自由发挥出
            # 不同音色,导致逐句换人、听感割裂。固定成同一份声纹(768 维 float32,
            # 从官方 ChatTTS 的说话人分布采样一次、写死种子生成,见项目根
            # scripts/README 或聊天记录)后,相同引擎实例内所有句子音色一致。
            cfg.speaker_embedding = f"{CHATTTS_DIR}/default_speaker.bin"

            provider = _select_provider()
            model_cfg = sherpa_onnx.OfflineTtsModelConfig(
                num_threads=4, provider=provider)
            model_cfg.chattts = cfg
            tts_cfg = sherpa_onnx.OfflineTtsConfig(model=model_cfg)

            self._tts = sherpa_onnx.OfflineTts(tts_cfg)
            return self._tts

    def preload(self) -> None:
        """可提前调用建模型,避免用户第一次点朗读时卡顿。"""
        self._ensure_loaded()

    def generate(self, text: str, on_chunk: Optional[Callable[[np.ndarray], bool]] = None,
                 sid: int = 0, speed: float = 1.0) -> np.ndarray:
        """合成一句/一段文本。on_chunk(samples)->bool 返回 False 可中途停止合成
        (用于用户点了停止朗读时打断当前正在合成的句子)。返回完整音频。"""
        tts = self._ensure_loaded()

        if on_chunk is not None:
            def _cb(samples, _progress):
                cont = on_chunk(np.asarray(samples, dtype=np.float32))
                return 1 if cont is not False else 0
            audio = tts.generate(text, sid=sid, speed=speed, callback=_cb)
        else:
            audio = tts.generate(text, sid=sid, speed=speed)
        return np.asarray(audio.samples, dtype=np.float32)
