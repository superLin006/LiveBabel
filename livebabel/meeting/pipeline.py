"""会议双流采集管线:麦克风("我") + 系统声音 loopback("远端")并发转录。

每路一个独立线程,各自一套 VadTwoPassAsr(注意:两套模型 ~1GB 内存)。
只取 final 文本(会议要准,不要临时半句),按来源标说话人写入 MeetingRecorder。
on_update() 在有新内容时回调,供 UI 刷新。
"""

from __future__ import annotations

import threading
from typing import Callable, List, Optional

from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.paths import FIRST_DIR, SECOND_DIR


def _run_stream(source, asr: VadTwoPassAsr, speaker: str, recorder,
                stop_flag: Callable[[], bool], on_update: Callable[[], None]) -> None:
    """跑一路音频源 → ASR:volatile/provisional 作实时草稿,final 定稿入记录。"""
    def handle(evt):
        if evt.kind == "final":
            text = evt.text.strip()
            if text:
                recorder.add(speaker, text)   # 定稿:入正式列表 + 清该说话人草稿
                on_update()
        elif evt.kind in ("volatile", "provisional"):
            # zipformer 实时草稿:浅色显示,会被刷新/最终替换,不进纪要
            recorder.set_draft(speaker, evt.text)
            on_update()

    try:
        for chunk in source.frames():
            if stop_flag():
                break
            for evt in asr.feed(chunk):
                handle(evt)
        for evt in asr.finalize():
            handle(evt)
    except Exception:
        # 单路出错不应拖垮另一路;静默结束本路
        pass


class MeetingPipeline:
    """管理双流(或单流)会议转录的启动/停止。"""

    def __init__(self, recorder, on_update: Callable[[], None],
                 use_mic: bool = True, use_loopback: bool = True) -> None:
        self.recorder = recorder
        self.on_update = on_update
        self.use_mic = use_mic
        self.use_loopback = use_loopback
        self._stop = False
        self._threads: List[threading.Thread] = []
        self._sources: list = []
        self._pa = None          # 双流共享的 PyAudio 实例

    def start(self) -> None:
        self._stop = False

        # 双流(mic+loopback)时:两个 PyAudio/WASAPI 实例【共存】会触发 PortAudio
        # 原生崩溃(单路各自正常)。改为两路共用同一个 PyAudio 实例。
        dual = self.use_mic and self.use_loopback
        if dual:
            import pyaudiowpatch as pyaudio
            self._pa = pyaudio.PyAudio()

        # 先在主线程把模型都建好(GPU 上下文别在两个线程里并发创建)。
        specs = []   # (source, asr, speaker)
        if self.use_loopback:
            from livebabel.asr.audio_source_windows import WasapiLoopbackSource
            lb = WasapiLoopbackSource(pa=self._pa)
            self._sources.append(lb)
            specs.append((lb, VadTwoPassAsr(FIRST_DIR, SECOND_DIR), "远端"))
        if self.use_mic:
            from livebabel.asr.audio_source_mic import MicrophoneSource
            mic = MicrophoneSource(pa=self._pa)
            self._sources.append(mic)
            specs.append((mic, VadTwoPassAsr(FIRST_DIR, SECOND_DIR), "我"))

        for source, asr, speaker in specs:
            t = threading.Thread(
                target=_run_stream,
                args=(source, asr, speaker, self.recorder,
                      lambda: self._stop, self.on_update),
                daemon=True)
            self._threads.append(t)
            t.start()

    def stop(self) -> None:
        self._stop = True
        for s in self._sources:
            try:
                s.stop()
            except Exception:
                pass
        # 等采集线程退出后再销毁共享 PyAudio(避免流还在用就 terminate 崩溃)
        for t in self._threads:
            t.join(timeout=2.0)
        if self._pa is not None:
            try:
                self._pa.terminate()
            except Exception:
                pass
            self._pa = None

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)
