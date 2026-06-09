"""音频输入层抽象。

设计目标:把"音频从哪来"和"怎么处理"彻底解耦。
现在(WSL)用文件源验证逻辑;以后(Windows)只需新增一个 WasapiLoopbackSource
实现同样的接口,主流程一行不用改。

所有源统一输出:16kHz、单声道、float32、[-1,1] 的 PCM 块(numpy array)。
"""

from __future__ import annotations

import subprocess
import time
from abc import ABC, abstractmethod
from typing import Iterator

import numpy as np

SAMPLE_RATE = 16000


class AudioSource(ABC):
    """音频源接口。迭代它即可拿到一块块 float32 PCM。"""

    sample_rate: int = SAMPLE_RATE

    @abstractmethod
    def frames(self) -> Iterator[np.ndarray]:
        """产出 float32 mono PCM 块,每块形如 (n,)。"""
        raise NotImplementedError


class FileSource(AudioSource):
    """从音频/视频文件读取,用 ffmpeg 解码成 16k mono。

    可选 ``realtime=True`` 按真实时间节流喂入,模拟"边播边识别"的流式场景,
    这样才能真实看到晃动现象;``realtime=False`` 则尽快喂完(快速测试)。
    """

    def __init__(
        self,
        path: str,
        chunk_ms: int = 100,
        realtime: bool = True,
    ) -> None:
        self.path = path
        self.chunk_ms = chunk_ms
        self.realtime = realtime
        self.chunk_samples = int(SAMPLE_RATE * chunk_ms / 1000)

    def _decode(self) -> np.ndarray:
        """用 ffmpeg 把任意输入解码成 16k mono float32。"""
        from livebabel.ffmpeg_tool import find_ffmpeg
        cmd = [
            find_ffmpeg(), "-nostdin", "-loglevel", "error",
            "-i", self.path,
            "-f", "f32le", "-acodec", "pcm_f32le",
            "-ac", "1", "-ar", str(SAMPLE_RATE),
            "pipe:1",
        ]
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"ffmpeg decode failed for {self.path}:\n"
                f"{proc.stderr.decode(errors='replace')}"
            )
        return np.frombuffer(proc.stdout, dtype=np.float32).copy()

    def frames(self) -> Iterator[np.ndarray]:
        pcm = self._decode()
        period = self.chunk_ms / 1000.0
        for start in range(0, len(pcm), self.chunk_samples):
            chunk = pcm[start : start + self.chunk_samples]
            if len(chunk) == 0:
                break
            yield chunk
            if self.realtime:
                time.sleep(period)


class ConcatFileSource(FileSource):
    """把多个短音频文件首尾拼接(中间插静音)成一段连续语音流。

    chattts/fleurs 那些单句样本太短,看不出晃动;拼起来 + 句间静音
    才能模拟真实的连续讲话,并触发 VAD 的分段/commit。
    """

    def __init__(
        self,
        paths: list[str],
        chunk_ms: int = 100,
        realtime: bool = True,
        gap_ms: int = 500,
    ) -> None:
        super().__init__(paths[0], chunk_ms, realtime)
        self.paths = paths
        self.gap_ms = gap_ms

    def _decode(self) -> np.ndarray:
        gap = np.zeros(int(SAMPLE_RATE * self.gap_ms / 1000), dtype=np.float32)
        parts: list[np.ndarray] = []
        for p in self.paths:
            self.path = p
            parts.append(super()._decode())
            parts.append(gap)
        return np.concatenate(parts)
