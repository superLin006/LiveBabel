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
    """跑一路音频源 → ASR,final 文本写进 recorder 并标上 speaker。"""
    def handle(evt):
        # 会议记录只要最终定稿文本;临时/草稿不进会议纪要(避免重复半句)
        if evt.kind == "final":
            text = evt.text.strip()
            if text:
                recorder.add(speaker, text)
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

    def start(self) -> None:
        self._stop = False

        if self.use_mic:
            from livebabel.asr.audio_source_mic import MicrophoneSource
            mic = MicrophoneSource()
            self._sources.append(mic)
            asr_mic = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
            self._threads.append(threading.Thread(
                target=_run_stream,
                args=(mic, asr_mic, "我", self.recorder,
                      lambda: self._stop, self.on_update),
                daemon=True))

        if self.use_loopback:
            from livebabel.asr.audio_source_windows import WasapiLoopbackSource
            lb = WasapiLoopbackSource()
            self._sources.append(lb)
            asr_lb = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
            self._threads.append(threading.Thread(
                target=_run_stream,
                args=(lb, asr_lb, "远端", self.recorder,
                      lambda: self._stop, self.on_update),
                daemon=True))

        for t in self._threads:
            t.start()

    def stop(self) -> None:
        self._stop = True
        for s in self._sources:
            try:
                s.stop()
            except Exception:
                pass

    @property
    def running(self) -> bool:
        return any(t.is_alive() for t in self._threads)
