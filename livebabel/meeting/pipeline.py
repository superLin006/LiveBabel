"""会议双流采集管线:麦克风("我") + 系统声音 loopback("远端")。

崩溃根因(实测,CPU/GPU 都崩):两路音频在两个 Python 线程里【并发持续 read】
PortAudio 输入流会原生崩溃。解法 = 回调模式 + 单消费线程:
  * 音频用 PortAudio 回调采集(回调在 PortAudio 内部线程,我们不并发 read);
  * 回调只把(重采样后的 16k mono)数据塞进各自队列,不做重活;
  * 单个消费线程轮流从两个队列取数据喂各自的 ASR 引擎(单线程,无并发推理)。
两路 ASR 引擎仍各自独立(流式状态必须隔离),但都在同一消费线程串行调用。
"""

from __future__ import annotations

import queue
import threading
from typing import Callable, List, Optional

import numpy as np

from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.asr.audio_source import SAMPLE_RATE
from livebabel.asr.audio_source_windows import WasapiLoopbackSource
from livebabel.paths import FIRST_DIR, SECOND_DIR


class _Track:
    """一路音频:设备 + 回调流 + 队列 + ASR 引擎 + 说话人标签。"""
    def __init__(self, speaker: str):
        self.speaker = speaker
        self.q: "queue.Queue[np.ndarray]" = queue.Queue(maxsize=200)
        self.asr: Optional[VadTwoPassAsr] = None
        self.stream = None
        self.native_rate = SAMPLE_RATE
        self.channels = 1
        self.audio_chunks: list = []   # 累积的 16k mono 音频(供会后说话人分离)


class MeetingPipeline:
    def __init__(self, recorder, on_update: Callable[[], None],
                 use_mic: bool = True, use_loopback: bool = True) -> None:
        self.recorder = recorder
        self.on_update = on_update
        self.use_mic = use_mic
        self.use_loopback = use_loopback
        self._stop = False
        self._pa = None
        self._tracks: List[_Track] = []
        self._consumer: Optional[threading.Thread] = None
        self._shared_first = None    # 两路共享的 zipformer/SenseVoice
        self._shared_second = None

    # ---- 设备打开(回调模式)----

    def _open_track(self, pa, dev, speaker: str) -> _Track:
        import pyaudiowpatch as pyaudio
        tr = _Track(speaker)
        # 共享模型权重(两路只加载一份 zipformer/SenseVoice,各自独立 vad/stream)
        tr.asr = VadTwoPassAsr(FIRST_DIR, SECOND_DIR,
                               shared_first=self._shared_first,
                               shared_second=self._shared_second)
        tr.native_rate = int(dev["defaultSampleRate"])
        tr.channels = max(1, int(dev["maxInputChannels"]))
        fpb = int(tr.native_rate * 0.1)   # 100ms

        def callback(in_data, frame_count, time_info, status):
            # 回调里只做轻量:转 mono + 重采样 + 入队,绝不做 ASR
            if self._stop:
                return (None, pyaudio.paComplete)
            try:
                audio = np.frombuffer(in_data, dtype=np.float32)
                if tr.channels > 1:
                    n = (len(audio) // tr.channels) * tr.channels
                    audio = audio[:n].reshape(-1, tr.channels).mean(axis=1)
                if tr.native_rate != SAMPLE_RATE:
                    audio = WasapiLoopbackSource._resample(audio, tr.native_rate, SAMPLE_RATE)
                tr.q.put_nowait(audio.astype(np.float32))
            except Exception:
                pass   # 丢一帧不致命
            return (None, pyaudio.paContinue)

        tr.stream = pa.open(
            format=pyaudio.paFloat32, channels=tr.channels, rate=tr.native_rate,
            input=True, input_device_index=dev["index"],
            frames_per_buffer=fpb, stream_callback=callback,
        )
        return tr

    def start(self) -> None:
        import pyaudiowpatch as pyaudio
        from livebabel.asr.vad_engine import build_shared_models
        self._stop = False
        self._pa = pyaudio.PyAudio()

        # 一份共享模型(两路引擎复用,省一份大模型内存)
        self._shared_first, self._shared_second, _ = build_shared_models(FIRST_DIR, SECOND_DIR)

        if self.use_loopback:
            dev = WasapiLoopbackSource()._find_loopback_device(self._pa)
            self._tracks.append(self._open_track(self._pa, dev, "远端"))
        if self.use_mic:
            from livebabel.asr.audio_source_mic import MicrophoneSource
            dev = MicrophoneSource._pick_input_device(self._pa)
            self._tracks.append(self._open_track(self._pa, dev, "我"))

        for tr in self._tracks:
            tr.stream.start_stream()

        self._consumer = threading.Thread(target=self._consume, daemon=True)
        self._consumer.start()

    # ---- 单消费线程:轮流喂两路 ASR(串行,无并发推理)----

    def _consume(self) -> None:
        def handle(evt, speaker):
            if evt.kind == "final":
                t = evt.text.strip()
                if t:
                    self.recorder.add(speaker, t)
                    self.on_update()
            elif evt.kind in ("volatile", "provisional"):
                self.recorder.set_draft(speaker, evt.text)
                self.on_update()

        while not self._stop:
            got_any = False
            for tr in self._tracks:
                try:
                    chunk = tr.q.get(timeout=0.05)
                except queue.Empty:
                    continue
                got_any = True
                tr.audio_chunks.append(chunk)   # 累积音频供会后说话人分离
                try:
                    for evt in tr.asr.feed(chunk):
                        handle(evt, tr.speaker)
                except Exception:
                    pass
            if not got_any:
                continue
        # 收尾:flush 两路
        for tr in self._tracks:
            try:
                for evt in tr.asr.finalize():
                    handle(evt, tr.speaker)
            except Exception:
                pass

    def stop(self) -> None:
        self._stop = True
        for tr in self._tracks:
            try:
                if tr.stream:
                    tr.stream.stop_stream()
                    tr.stream.close()
            except Exception:
                pass
        if self._consumer:
            self._consumer.join(timeout=3.0)
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None
        # 停止前把各路累积音频留存(供会后说话人分离),再清 tracks
        import numpy as np
        self._audio = {}
        for tr in self._tracks:
            if tr.audio_chunks:
                self._audio[tr.speaker] = np.concatenate(tr.audio_chunks)
        self._tracks = []
        # 释放共享模型,回收内存
        self._shared_first = None
        self._shared_second = None

    def get_audio(self, speaker: str):
        """返回某路累积的 16k mono 音频(numpy),没有返回 None。会后说话人分离用。"""
        return getattr(self, "_audio", {}).get(speaker)

    @property
    def running(self) -> bool:
        return self._consumer is not None and self._consumer.is_alive()
