"""麦克风输入采集(会议模式用,代表"我")。

与 WasapiLoopbackSource 同接口(frames() 产出 16k mono float32 块),但抓的是
默认输入设备(麦克风),不是 loopback。会议模式里:
  * 麦克风流 = 本机用户("我")
  * 系统声音 loopback = 远端所有人
两路各跑一套 ASR,转录按来源标上说话人,实现无需 torch 的"我/远端"区分。

依赖 pyaudiowpatch(Windows);普通 PyAudio 也兼容,这里统一用 pyaudiowpatch。
"""

from __future__ import annotations

import time
from typing import Iterator, Optional

import numpy as np

from livebabel.asr.audio_source import SAMPLE_RATE, AudioSource
from livebabel.asr.audio_source_windows import WasapiLoopbackSource


class MicrophoneSource(AudioSource):
    def __init__(self, chunk_ms: int = 100, device_index: Optional[int] = None) -> None:
        self.chunk_ms = chunk_ms
        self.device_index = device_index   # None=默认输入设备
        self._stop = False

    def stop(self) -> None:
        self._stop = True

    def frames(self) -> Iterator[np.ndarray]:
        import sys
        import pyaudiowpatch as pyaudio

        pa = pyaudio.PyAudio()
        try:
            idx = self.device_index
            if idx is None:
                idx = pa.get_default_input_device_info()["index"]
            dev = pa.get_device_info_by_index(idx)
            print(f"[mic] 麦克风设备: {dev['name']} (index={idx}, "
                  f"rate={int(dev['defaultSampleRate'])}, "
                  f"ch={int(dev['maxInputChannels'])})", file=sys.stderr)

            native_rate = int(dev["defaultSampleRate"])
            channels = min(int(dev["maxInputChannels"]), 1) or 1   # 麦克风用单声道
            frames_per_buffer = int(native_rate * self.chunk_ms / 1000)
            stream = pa.open(
                format=pyaudio.paFloat32, channels=channels, rate=native_rate,
                frames_per_buffer=frames_per_buffer, input=True,
                input_device_index=idx,
            )
            try:
                while not self._stop:
                    try:
                        raw = stream.read(frames_per_buffer, exception_on_overflow=False)
                        audio = np.frombuffer(raw, dtype=np.float32)
                        if channels > 1:
                            n = (len(audio) // channels) * channels
                            audio = audio[:n].reshape(-1, channels).mean(axis=1)
                        if native_rate != SAMPLE_RATE:
                            audio = WasapiLoopbackSource._resample(audio, native_rate, SAMPLE_RATE)
                    except Exception:
                        time.sleep(0.1)
                        continue
                    yield audio.astype(np.float32)
            finally:
                try:
                    stream.stop_stream()
                    stream.close()
                except Exception:
                    pass
        finally:
            pa.terminate()
