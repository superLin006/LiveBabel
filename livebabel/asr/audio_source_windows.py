"""Windows 系统声音采集(WASAPI loopback)。

抓"扬声器/耳机正在播放的声音"——无论来自视频播放器、浏览器、会议软件都行。
依赖 pyaudiowpatch(PyAudio 的 WASAPI loopback 分支),只能在 Windows 上跑:

    pip install pyaudiowpatch

设计目标:
  * 启动时正确抓到【当前默认输出设备】的声音。
  * 在不同电脑上通用(设备数量/型号/是否有同名设备都能处理)。
  * 输出与 FileSource 一致:16kHz mono float32 块,主流程不用改。

不做运行中自动切换设备(简单可靠优先)。切了输出设备请重启程序。
"""

from __future__ import annotations

import time
from typing import Iterator

import numpy as np

from livebabel.asr.audio_source import SAMPLE_RATE, AudioSource


class WasapiLoopbackSource(AudioSource):
    def __init__(self, chunk_ms: int = 100, pa=None) -> None:
        self.chunk_ms = chunk_ms
        self._stop = False
        self._pa = pa            # 共享的 PyAudio 实例(会议双流用同一个,避免多实例共存崩溃)

    def stop(self) -> None:
        self._stop = True

    def _find_loopback_device(self, pa):
        """找到【当前默认输出设备】对应的 loopback 录音设备。通用于各种电脑。

        策略(从最可靠到兜底):
          1. 按"默认输出在输出设备列表里的序号" → 取同序号的 loopback
             (loopback 与输出设备一一对应;能处理多个同名设备,如双 HDMI)。
          2. 按默认输出设备名前缀匹配 loopback 名(普通单设备电脑最常见)。
          3. pyaudiowpatch 官方 API get_default_wasapi_loopback()。
          4. 还不行就取第一个 loopback(总比没有强)。
        """
        import pyaudiowpatch as pyaudio
        wasapi = pa.get_host_api_info_by_type(pyaudio.paWASAPI)
        default_idx = wasapi["defaultOutputDevice"]
        default_out = pa.get_device_info_by_index(default_idx)
        target = default_out["name"]

        outputs = [
            pa.get_device_info_by_index(i)
            for i in range(pa.get_device_count())
            if pa.get_device_info_by_index(i).get("hostApi") == wasapi["index"]
            and pa.get_device_info_by_index(i).get("maxOutputChannels", 0) > 0
        ]
        outputs.sort(key=lambda d: d["index"])
        loopbacks = sorted(pa.get_loopback_device_info_generator(), key=lambda d: d["index"])

        if not loopbacks:
            raise RuntimeError("未找到任何 loopback 设备(请确认已安装 pyaudiowpatch)。")

        # 1) 序号一一对应(最可靠,能区分同名设备)
        try:
            pos = next(i for i, d in enumerate(outputs) if d["index"] == default_idx)
            if pos < len(loopbacks):
                return loopbacks[pos]
        except StopIteration:
            pass

        # 2) 名字前缀匹配
        for dev in loopbacks:
            if dev["name"].startswith(target):
                return dev

        # 3) 官方 API
        try:
            dev = pa.get_default_wasapi_loopback()
            if dev is not None:
                return dev
        except Exception:
            pass

        # 4) 兜底:第一个 loopback
        return loopbacks[0]

    def frames(self) -> Iterator[np.ndarray]:
        import sys
        import pyaudiowpatch as pyaudio

        own_pa = self._pa is None       # 自己建的才负责 terminate
        pa = self._pa or pyaudio.PyAudio()
        try:
            dev = self._find_loopback_device(pa)
            print(f"[audio] 抓取设备: {dev['name']} (index={dev['index']}, "
                  f"rate={int(dev['defaultSampleRate'])}, ch={int(dev['maxInputChannels'])})",
                  file=sys.stderr)

            native_rate = int(dev["defaultSampleRate"])
            channels = int(dev["maxInputChannels"])
            frames_per_buffer = int(native_rate * self.chunk_ms / 1000)
            stream = pa.open(
                format=pyaudio.paFloat32, channels=channels, rate=native_rate,
                frames_per_buffer=frames_per_buffer, input=True,
                input_device_index=dev["index"],
            )
            try:
                while not self._stop:
                    try:
                        raw = stream.read(frames_per_buffer, exception_on_overflow=False)
                        audio = np.frombuffer(raw, dtype=np.float32)
                        if channels > 1:                    # 多声道降混成单声道
                            # 截到整数帧,避免 partial read 时 reshape 抛错杀死线程
                            n = (len(audio) // channels) * channels
                            audio = audio[:n].reshape(-1, channels).mean(axis=1)
                        if native_rate != SAMPLE_RATE:       # 重采样到 16k
                            audio = self._resample(audio, native_rate, SAMPLE_RATE)
                    except Exception:
                        time.sleep(0.1)      # 偶发读取/处理错误,稍等重试,不崩
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

    @staticmethod
    def _resample(audio: np.ndarray, src: int, dst: int) -> np.ndarray:
        """线性重采样。够 ASR 用;要更高质量可换 scipy/soxr。"""
        if len(audio) == 0:
            return audio
        n_dst = int(round(len(audio) * dst / src))
        if n_dst <= 0:
            return np.zeros(0, dtype=np.float32)
        x_src = np.linspace(0, 1, len(audio), endpoint=False)
        x_dst = np.linspace(0, 1, n_dst, endpoint=False)
        return np.interp(x_dst, x_src, audio).astype(np.float32)
