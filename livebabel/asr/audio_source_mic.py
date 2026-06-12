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
    def __init__(self, chunk_ms: int = 100, device_index: Optional[int] = None, pa=None) -> None:
        self.chunk_ms = chunk_ms
        self.device_index = device_index   # None=默认输入设备
        self._stop = False
        self._pa = pa            # 共享的 PyAudio 实例(会议双流用同一个,避免多实例共存崩溃)

    def stop(self) -> None:
        self._stop = True

    @staticmethod
    def has_microphone() -> bool:
        """系统当前是否有可用的麦克风(真实输入设备,排除 loopback)。

        会议页据此决定是否启用"含麦克风"的选项。任何异常都按"无麦"处理。
        """
        try:
            import pyaudiowpatch as pyaudio
        except Exception:
            return False
        pa = pyaudio.PyAudio()
        try:
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                name = str(d.get("name", ""))
                if d.get("maxInputChannels", 0) > 0 and "loopback" not in name.lower():
                    return True
            return False
        except Exception:
            return False
        finally:
            try:
                pa.terminate()
            except Exception:
                pass

    @staticmethod
    def _pick_input_device(pa):
        """选一个真实麦克风设备(优先默认输入;默认不可用则取第一个非 loopback 输入)。"""
        try:
            di = pa.get_default_input_device_info()
            if di and di.get("maxInputChannels", 0) > 0:
                return di
        except Exception:
            pass
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("maxInputChannels", 0) > 0 and "loopback" not in str(d.get("name", "")).lower():
                return d
        raise RuntimeError("未找到可用麦克风(没有输入设备)。请插入/连接麦克风后重试。")

    def frames(self) -> Iterator[np.ndarray]:
        import sys
        import pyaudiowpatch as pyaudio

        own_pa = self._pa is None       # 自己建的才负责 terminate
        pa = self._pa or pyaudio.PyAudio()
        try:
            if self.device_index is not None:
                dev = pa.get_device_info_by_index(self.device_index)
            else:
                dev = self._pick_input_device(pa)   # 没有可用麦会抛 RuntimeError
            idx = dev["index"]
            native_rate = int(dev["defaultSampleRate"])
            max_ch = max(1, int(dev["maxInputChannels"]))
            print(f"[mic] 麦克风设备: {dev['name']} (index={idx}, "
                  f"rate={native_rate}, ch={max_ch})", file=sys.stderr)

            frames_per_buffer = int(native_rate * self.chunk_ms / 1000)
            # 先试单声道,设备不支持再用其原生声道数(避免直接打不开)
            stream = None
            for channels in (1, max_ch):
                try:
                    stream = pa.open(
                        format=pyaudio.paFloat32, channels=channels, rate=native_rate,
                        frames_per_buffer=frames_per_buffer, input=True,
                        input_device_index=idx,
                    )
                    break
                except Exception:
                    stream = None
            if stream is None:
                raise RuntimeError(f"无法打开麦克风「{dev['name']}」(设备忙或格式不支持)。")
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
            if own_pa:           # 共享实例不在这里销毁(由创建者统一管理)
                pa.terminate()
