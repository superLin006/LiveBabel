"""macOS 音频采集后端(用 sounddevice / PortAudio,跨平台,替代 Windows 的 pyaudiowpatch)。

macOS 系统不允许应用直接抓"系统正在播放的声音"。方案:用户安装免费的
BlackHole 虚拟声卡,把系统输出路由进 BlackHole(建一个「多输出设备」同时含扬声器
和 BlackHole,既能听到又能被录),我们录 BlackHole 这个输入设备即得系统声。

  * BlackHoleSource    —— 录 BlackHole(= Windows 的 loopback/"远端")
  * MacMicrophoneSource —— 录默认麦克风(= 会议里的"我")

两者都与 WasapiLoopbackSource 同接口:frames() 产出 16k mono float32 块,stop() 停止。
依赖 sounddevice(pip install sounddevice;底层 PortAudio,macOS 自带)。
"""

from __future__ import annotations

import sys
import time
from queue import Empty, Queue
from typing import Iterator, Optional

import numpy as np

from livebabel.asr.audio_source import SAMPLE_RATE, AudioSource


def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
    """线性重采样到 dst(16k)。够 ASR 用。"""
    if len(audio) == 0:
        return audio
    n_dst = int(round(len(audio) * dst / src))
    if n_dst <= 0:
        return np.zeros(0, dtype=np.float32)
    x_src = np.linspace(0, 1, len(audio), endpoint=False)
    x_dst = np.linspace(0, 1, n_dst, endpoint=False)
    return np.interp(x_dst, x_src, audio).astype(np.float32)


def _find_device(name_substr: str, want_input: bool = True):
    """按名字子串找设备,返回 (index, info)。找不到返回 (None, None)。"""
    import sounddevice as sd
    name_substr = name_substr.lower()
    for idx, d in enumerate(sd.query_devices()):
        ch = d["max_input_channels"] if want_input else d["max_output_channels"]
        if ch > 0 and name_substr in d["name"].lower():
            return idx, d
    return None, None


def has_blackhole() -> bool:
    """系统是否装了 BlackHole(决定 Mac 上能否抓系统声)。"""
    try:
        idx, _ = _find_device("blackhole", want_input=True)
        return idx is not None
    except Exception:
        return False


def pick_microphone():
    """选麦克风设备(排除 BlackHole,别把系统声当麦克风)。返回 (index, info)。

    优先默认输入设备;若默认是 BlackHole 或无默认,则取第一个非 BlackHole 的输入设备。
    找不到返回 (None, None)。会议模式与实时模式共用,避免两处重复+不一致。
    """
    import sounddevice as sd
    default_in = sd.default.device[0]
    if default_in is not None and default_in >= 0:
        try:
            d = sd.query_devices(default_in)
            if d["max_input_channels"] > 0 and "blackhole" not in d["name"].lower():
                return default_in, d
        except Exception:
            pass
    for i, d in enumerate(sd.query_devices()):
        if d["max_input_channels"] > 0 and "blackhole" not in d["name"].lower():
            return i, d
    return None, None


class _SdSourceBase(AudioSource):
    """sounddevice 采集基类:回调把 PCM 塞队列,frames() 从队列取并重采样到 16k。

    用回调而非阻塞 read —— 与 Windows 侧的经验一致(回调在 PortAudio 内部线程,
    避免多个 Python 线程并发 read PortAudio 导致原生崩溃)。
    """

    def __init__(self, chunk_ms: int = 100, device_index: Optional[int] = None) -> None:
        self.chunk_ms = chunk_ms
        self.device_index = device_index
        self._stop = False
        self._q: "Queue[np.ndarray]" = Queue(maxsize=200)

    def stop(self) -> None:
        self._stop = True

    def _resolve_device(self):
        """子类返回 (index, native_rate, channels)。"""
        raise NotImplementedError

    def frames(self) -> Iterator[np.ndarray]:
        import sounddevice as sd

        idx, native_rate, channels = self._resolve_device()
        print(f"[audio-mac] 采集设备 index={idx} rate={native_rate} ch={channels}",
              file=sys.stderr)
        blocksize = int(native_rate * self.chunk_ms / 1000)

        def callback(indata, frames, time_info, status):
            # indata: (frames, channels) float32。降混单声道后入队(满则丢最旧,不阻塞回调)
            mono = indata.mean(axis=1) if indata.ndim > 1 and indata.shape[1] > 1 \
                else indata.reshape(-1)
            try:
                self._q.put_nowait(mono.copy())
            except Exception:
                pass

        stream = sd.InputStream(
            samplerate=native_rate, blocksize=blocksize, device=idx,
            channels=channels, dtype="float32", callback=callback,
        )
        with stream:
            while not self._stop:
                try:
                    mono = self._q.get(timeout=0.2)
                except Empty:
                    continue
                if native_rate != SAMPLE_RATE:
                    mono = _resample(mono, native_rate, SAMPLE_RATE)
                yield mono.astype(np.float32)


class BlackHoleSource(_SdSourceBase):
    """录 BlackHole 虚拟声卡(= 系统正在播放的声音 / 会议"远端")。"""

    def _resolve_device(self):
        idx = self.device_index
        info = None
        if idx is None:
            idx, info = _find_device("blackhole", want_input=True)
        if idx is None:
            raise RuntimeError(
                "未找到 BlackHole 虚拟声卡。请先安装 BlackHole 并在「音频 MIDI 设置」里\n"
                "建一个多输出设备(同时含扬声器和 BlackHole),把系统输出切到它。")
        import sounddevice as sd
        info = info or sd.query_devices(idx)
        rate = int(info["default_samplerate"])
        ch = int(info["max_input_channels"])
        return idx, rate, max(1, ch)


class MacMicrophoneSource(_SdSourceBase):
    """录默认麦克风(会议模式的"我")。"""

    @staticmethod
    def has_microphone() -> bool:
        try:
            import sounddevice as sd
            for d in sd.query_devices():
                name = d["name"].lower()
                if d["max_input_channels"] > 0 and "blackhole" not in name:
                    return True
            return False
        except Exception:
            return False

    def _resolve_device(self):
        import sounddevice as sd
        idx = self.device_index
        if idx is None:
            idx, _ = pick_microphone()
            if idx is None:
                raise RuntimeError("未找到可用麦克风。")
        info = sd.query_devices(idx)
        rate = int(info["default_samplerate"])
        ch = int(info["max_input_channels"])
        return idx, rate, max(1, ch)
