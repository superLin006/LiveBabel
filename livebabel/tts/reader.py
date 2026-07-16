"""朗读服务:文本 → 按目标长度分段 → 段内真流式合成(边生成边播,无缝) →
顺序播放。合成和播放使用同一个运行状态,停止或失败不会误报完成,也不会污染下一次朗读。
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from livebabel.tts import cache as tts_cache
from livebabel.tts.chattts_engine import SAMPLE_RATE, ChatTtsEngine
from livebabel.tts.text_split import split_into_chunks

_QUEUE_MAXSIZE = 8
_PREBUFFER_SAMPLES = SAMPLE_RATE
_PLAY_BLOCK = SAMPLE_RATE // 10


@dataclass
class _RunState:
    audio_q: "queue.Queue[Optional[tuple[int, np.ndarray]]]"
    worker_count: int = 2
    stop_evt: threading.Event = field(default_factory=threading.Event)
    failed: bool = False
    completed: bool = False
    cancelled: bool = False
    error_reported: bool = False
    workers_done: int = 0
    callback_sent: bool = False
    paused: bool = False
    text: str = ""
    chunks: list[str] = field(default_factory=list)
    total: int = 0
    cached: Optional[np.ndarray] = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class MinutesReader:
    """朗读一段文本(纪要/字幕)。后台合成并播放,回调均需自行转到 Qt 主线程。"""

    def __init__(self, engine: Optional[ChatTtsEngine] = None) -> None:
        self._engine = engine or ChatTtsEngine()
        self._state_lock = threading.Lock()
        self._state: Optional[_RunState] = None
        self._running = False
        self._synth_thread: Optional[threading.Thread] = None
        self._play_thread: Optional[threading.Thread] = None

        self.on_sentence: Optional[Callable[[int, int], None]] = None
        self.on_finished: Optional[Callable[[], None]] = None
        self.on_stopped: Optional[Callable[[], None]] = None
        self.on_failed: Optional[Callable[[], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    def preload(self) -> None:
        self._engine.preload()

    def is_running(self) -> bool:
        with self._state_lock:
            return self._running

    def is_paused(self) -> bool:
        with self._state_lock:
            state = self._state
        return bool(state and getattr(state, "paused", False))

    def start(self, text: str) -> bool:
        with self._state_lock:
            if self._running:
                return False
            cached = tts_cache.get(text)
            if cached is not None:
                state = _RunState(queue.Queue(maxsize=_QUEUE_MAXSIZE), worker_count=1)
                state.cached = cached
                state.text = text
                state.total = 1
                self._state = state
                self._running = True
                self._play_thread = threading.Thread(
                    target=self._run_play_cached, args=(state,),
                    name="tts-play-cached", daemon=True)
                self._play_thread.start()
                return True

            chunks = split_into_chunks(text)
            if not chunks:
                return False
            state = _RunState(queue.Queue(maxsize=_QUEUE_MAXSIZE))
            state.chunks = chunks
            state.text = text
            state.total = len(chunks)
            self._state = state
            self._running = True
            self._synth_thread = threading.Thread(
                target=self._run_synth, args=(state,), name="tts-synth", daemon=True)
            self._play_thread = threading.Thread(
                target=self._run_play, args=(state,), name="tts-play", daemon=True)
            self._synth_thread.start()
            self._play_thread.start()
            return True

    def toggle_pause(self) -> None:
        with self._state_lock:
            state = self._state
        if state is None:
            return
        with state.lock:
            if not state.stop_evt.is_set():
                state.paused = not getattr(state, "paused", False)

    def stop(self) -> None:
        with self._state_lock:
            state = self._state
        if state is not None:
            with state.lock:
                state.cancelled = True
                state.stop_evt.set()
                state.paused = False

    def _report_error(self, state: _RunState, message: str) -> None:
        with state.lock:
            if state.error_reported:
                return
            state.error_reported = True
            state.failed = True
            state.stop_evt.set()
        if self.on_error:
            try:
                self.on_error(message)
            except Exception:
                pass

    def _finish_worker(self, state: _RunState) -> None:
        callback = None
        with state.lock:
            state.workers_done += 1
            if state.workers_done < state.worker_count or state.callback_sent:
                return
            state.callback_sent = True
            success = state.completed and not state.failed and not state.cancelled
            stopped = state.cancelled and not state.failed
        with self._state_lock:
            if self._state is state:
                self._running = False
                self._state = None
        if success:
            callback = self.on_finished
        elif state.failed:
            callback = self.on_failed
        elif stopped:
            callback = self.on_stopped
        if callback:
            try:
                callback()
            except Exception:
                pass

    def _wait_paused(self, state: _RunState) -> bool:
        while True:
            with state.lock:
                if state.stop_evt.is_set():
                    return False
                paused = getattr(state, "paused", False)
            if not paused:
                return True
            state.stop_evt.wait(0.1)

    def _run_synth(self, state: _RunState) -> None:
        try:
            for i, chunk_text in enumerate(state.chunks):
                if not self._wait_paused(state):
                    break

                def on_chunk(samples: np.ndarray, idx: int = i) -> bool:
                    while not state.stop_evt.is_set():
                        try:
                            state.audio_q.put((idx, samples), timeout=0.2)
                            return True
                        except queue.Full:
                            continue
                    return False

                try:
                    self._engine.generate(chunk_text, on_chunk=on_chunk)
                except Exception as e:
                    self._report_error(state, f"第 {i + 1} 段合成失败: {e}")
                    break
            if not state.stop_evt.is_set() and not state.failed:
                while not state.stop_evt.is_set():
                    try:
                        state.audio_q.put(None, timeout=0.2)
                        break
                    except queue.Full:
                        continue
        finally:
            self._finish_worker(state)

    def _write_samples(self, stream, state: _RunState, samples: np.ndarray) -> bool:
        for start in range(0, len(samples), _PLAY_BLOCK):
            if not self._wait_paused(state):
                return False
            try:
                stream.write(samples[start:start + _PLAY_BLOCK])
            except Exception as e:
                self._report_error(state, f"播放失败: {e}")
                return False
        return True

    def _run_play(self, state: _RunState) -> None:
        last_idx = -1
        generated: list[np.ndarray] = []
        pending: deque[np.ndarray] = deque()
        buffered = 0
        started = False
        normal_end = False
        try:
            import sounddevice as sd
            with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32") as stream:
                while not state.stop_evt.is_set():
                    try:
                        item = state.audio_q.get(timeout=0.2)
                    except queue.Empty:
                        continue
                    if item is None:
                        if state.stop_evt.is_set():
                            break
                        normal_end = True
                        while pending and not state.stop_evt.is_set():
                            if not self._write_samples(stream, state, pending.popleft()):
                                break
                        if not state.stop_evt.is_set() and not pending:
                            state.completed = True
                        break
                    idx, samples = item
                    generated.append(samples)
                    if idx != last_idx:
                        last_idx = idx
                        if self.on_sentence:
                            try:
                                self.on_sentence(idx, state.total)
                            except Exception:
                                pass
                    pending.append(samples)
                    buffered += len(samples)
                    if not started and buffered < _PREBUFFER_SAMPLES:
                        continue
                    started = True
                    while pending and not state.stop_evt.is_set():
                        if not self._write_samples(stream, state, pending.popleft()):
                            break
        except Exception as e:
            self._report_error(state, f"播放失败: {e}")
        finally:
            if normal_end and state.completed and not state.failed and generated:
                tts_cache.put(state.text, np.concatenate(generated), SAMPLE_RATE)
            self._finish_worker(state)

    def _run_play_cached(self, state: _RunState) -> None:
        try:
            import sounddevice as sd
            with sd.OutputStream(samplerate=SAMPLE_RATE, channels=1,
                                 dtype="float32") as stream:
                if self.on_sentence:
                    try:
                        self.on_sentence(0, 1)
                    except Exception:
                        pass
                if self._write_samples(stream, state, state.cached):
                    state.completed = True
        except Exception as e:
            self._report_error(state, f"播放失败: {e}")
        finally:
            self._finish_worker(state)
