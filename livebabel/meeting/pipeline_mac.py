"""macOS 会议双流采集管线:麦克风("我") + BlackHole 系统声("远端")。

复用 Windows 版 MeetingPipeline 的全部精密逻辑(_Track 落盘、单消费线程轮流喂 ASR、
stop/get_audio/cleanup),只【重写平台相关的两处】:用 sounddevice 替代 pyaudiowpatch
打开音频流。这样不复制 200 行已验证逻辑,Windows pipeline 一行不动。

同样遵守"回调采集 + 单消费线程"原则(避免多线程并发 read PortAudio 崩溃)。
"""

from __future__ import annotations

import numpy as np

from livebabel.asr.audio_source import SAMPLE_RATE
from livebabel.asr.audio_source_mac import _resample
from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.meeting.pipeline import MeetingPipeline, _Track
from livebabel.paths import FIRST_DIR, SECOND_DIR


class MacMeetingPipeline(MeetingPipeline):
    """与 MeetingPipeline 接口完全一致,仅采集后端换成 sounddevice。"""

    def _open_track_sd(self, dev_index: int, native_rate: int, channels: int,
                       speaker: str) -> _Track:
        import sounddevice as sd
        tr = _Track(speaker)
        tr.asr = VadTwoPassAsr(FIRST_DIR, SECOND_DIR,
                               shared_first=self._shared_first,
                               shared_second=self._shared_second)
        tr.native_rate = native_rate
        tr.channels = max(1, channels)
        blocksize = int(tr.native_rate * 0.1)   # 100ms

        def callback(indata, frames, time_info, status):
            # 回调里只做轻量:转 mono + 重采样 + 入队(回调在 PortAudio 内部线程)
            if self._stop:
                raise sd.CallbackStop
            try:
                if indata.ndim > 1 and indata.shape[1] > 1:
                    audio = indata.mean(axis=1)
                else:
                    audio = indata.reshape(-1)
                if tr.native_rate != SAMPLE_RATE:
                    audio = _resample(audio, tr.native_rate, SAMPLE_RATE)
                tr.q.put_nowait(audio.astype(np.float32))
            except Exception:
                pass   # 丢一帧不致命

        tr.stream = sd.InputStream(
            samplerate=tr.native_rate, blocksize=blocksize, device=dev_index,
            channels=tr.channels, dtype="float32", callback=callback,
        )
        return tr

    def start(self) -> None:
        import sounddevice as sd
        from livebabel.asr.vad_engine import build_shared_models
        from livebabel.asr.audio_source_mac import (
            BlackHoleSource, MacMicrophoneSource, _find_device,
        )
        self._stop = False
        self._pa = None     # macOS 不用共享 PyAudio 实例;sounddevice 各流独立

        # 一份共享模型(两路引擎复用)
        self._shared_first, self._shared_second, _ = build_shared_models(FIRST_DIR, SECOND_DIR)

        if self.use_loopback:
            idx, info = _find_device("blackhole", want_input=True)
            if idx is None:
                raise RuntimeError(
                    "未找到 BlackHole 虚拟声卡。请安装 BlackHole,并在「音频 MIDI 设置」\n"
                    "里建一个多输出设备(含扬声器 + BlackHole),把系统输出切到它。")
            self._tracks.append(self._open_track_sd(
                idx, int(info["default_samplerate"]),
                int(info["max_input_channels"]), "远端"))
        if self.use_mic:
            # 默认输入设备,排除 BlackHole(别把系统声当麦克风)
            mic_idx, mic_info = None, None
            default_in = sd.default.device[0]
            if default_in is not None:
                d = sd.query_devices(default_in)
                if "blackhole" not in d["name"].lower() and d["max_input_channels"] > 0:
                    mic_idx, mic_info = default_in, d
            if mic_idx is None:
                for i, d in enumerate(sd.query_devices()):
                    if d["max_input_channels"] > 0 and "blackhole" not in d["name"].lower():
                        mic_idx, mic_info = i, d
                        break
            if mic_idx is None:
                raise RuntimeError("未找到可用麦克风。")
            self._tracks.append(self._open_track_sd(
                mic_idx, int(mic_info["default_samplerate"]),
                int(mic_info["max_input_channels"]), "我"))

        for tr in self._tracks:
            tr.stream.start()

        import threading
        self._consumer = threading.Thread(target=self._consume, daemon=True)
        self._consumer.start()

    def stop(self) -> None:
        # sounddevice 的 stream 用 stop()/close() 而非 pyaudio 的 stop_stream()。
        # 复用父类收尾(消费线程 join、文件落盘、模型释放),只先停流。
        self._stop = True
        for tr in self._tracks:
            try:
                if tr.stream:
                    tr.stream.stop()
                    tr.stream.close()
            except Exception:
                pass
        if self._consumer:
            self._consumer.join(timeout=3.0)
        # 后续(关文件、移到 _done_tracks、释放模型)和父类一致,这里手动做
        for tr in self._tracks:
            tr.close_audio()
        self._done_tracks = self._tracks
        self._tracks = []
        self._shared_first = None
        self._shared_second = None
