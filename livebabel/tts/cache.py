"""朗读合成结果缓存:按 (文本内容, 音色) 算 key,命中则直接读盘播放,
不重新调用引擎合成。key 里带音色文件内容的 hash,换音色/重新采样声纹后
旧缓存自然失效(不会读到错音色的缓存),不需要额外的失效逻辑。

存储:history/tts_cache/<key>.wav,一个 key 一个完整拼好的 wav 文件。
不做容量上限/过期清理——纪要/字幕文本量级不大,合成产物是纯语音、体积
可控(如 100 字约 1MB),留给用户按需手动清理 history/ 目录即可,
不必增加自动淘汰的复杂度和"缓存突然消失"的意外。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from typing import Optional

import numpy as np

from livebabel.paths import CHATTTS_DIR, TTS_CACHE_DIR

CACHE_VERSION = "v1-cpu-24k"
SAMPLE_RATE = 24000


def _speaker_hash() -> str:
    """音色文件内容的短 hash,换声纹后自动让旧缓存 key 失效。"""
    path = os.path.join(CHATTTS_DIR, "default_speaker.bin")
    try:
        with open(path, "rb") as f:
            data = f.read()
        return hashlib.sha256(data).hexdigest()[:8]
    except OSError:
        return "nospeaker"


def _cache_key(text: str) -> str:
    h = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
    return f"{CACHE_VERSION}_{h}_{_speaker_hash()}"


def _cache_path(text: str) -> str:
    return os.path.join(TTS_CACHE_DIR, _cache_key(text) + ".wav")


def get(text: str) -> Optional[np.ndarray]:
    """命中则返回 float32 mono 音频样本,否则 None。"""
    path = _cache_path(text)
    if not os.path.isfile(path):
        return None
    try:
        import soundfile as sf
        samples, sample_rate = sf.read(path, dtype="float32", always_2d=False)
        samples = np.asarray(samples, dtype=np.float32)
        if sample_rate != SAMPLE_RATE or samples.size == 0 or samples.ndim != 1:
            return None
        return samples
    except Exception:
        return None  # 缓存文件损坏,当作未命中,调用方会重新合成并覆盖它


def put(text: str, samples: np.ndarray, sample_rate: int) -> None:
    """写入缓存,失败(如磁盘满/无权限)静默忽略——缓存本就是可选的加速层。"""
    try:
        samples = np.asarray(samples, dtype=np.float32)
        if sample_rate != SAMPLE_RATE or samples.size == 0 or samples.ndim != 1:
            return
        os.makedirs(TTS_CACHE_DIR, exist_ok=True)
        import soundfile as sf
        fd, temp_path = tempfile.mkstemp(
            prefix=".tts-", suffix=".wav", dir=TTS_CACHE_DIR)
        os.close(fd)
        try:
            sf.write(temp_path, samples, SAMPLE_RATE)
            os.replace(temp_path, _cache_path(text))
        finally:
            try:
                os.unlink(temp_path)
            except FileNotFoundError:
                pass
    except Exception:
        pass
