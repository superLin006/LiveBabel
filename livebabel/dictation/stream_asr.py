"""两阶段听写引擎:复用实时/会议模式同款的 VadTwoPassAsr。

说话时:每帧 feed() → 若干事件(volatile 草稿 / provisional / final),经
        on_draft(committed, volatile) 回调实时显示草稿(已定稿/未定稿分开传,浮窗分色)。
松开时:stop() → finalize() 把残留语音段强制定稿,按段拼接返回完整最终文本供注入。

用 VadTwoPassAsr(silero-VAD 主动分段)而非 TwoPassAsr(靠流式 endpoint):后者
单独用时常不出字,前者是项目里验证过能独立工作的引擎。

线程模型:start() 起一个采集线程跑 MicrophoneSource.frames();on_draft 在该线程内
被调用,service 负责把草稿跨线程投递到 Qt 主线程(本模块不碰 UI)。
"""

from __future__ import annotations

import threading
import time
from typing import Callable, Optional

import numpy as np

from livebabel.asr.audio_source_mic import MicrophoneSource
from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.paths import FIRST_DIR, SECOND_DIR

# 防忘松手:单次听写最长时长,超过自动停
MAX_SECONDS = 60.0


class StreamDictationEngine:
    """两阶段听写引擎。on_draft(committed, volatile) 在采集线程内被调用
    (service 负责转主线程):committed=已定稿文本,volatile=未定稿草稿,
    浮窗可分色显示。最终文本由 stop() 返回,一次性注入。"""

    def __init__(self, on_draft: Optional[Callable[[str, str], None]] = None,
                 num_threads: int = 2) -> None:
        self._on_draft = on_draft
        self._num_threads = num_threads
        self._asr: Optional[VadTwoPassAsr] = None   # 懒加载 + 复用
        self._asr_lock = threading.Lock()

        self._thread: Optional[threading.Thread] = None
        self._src = None             # 当前采集源(stop 时用,start 前为 None)
        self._stop_flag = False
        self._running = False
        # 已定稿文本,按语音段 utt_id 存(final 覆盖同段 provisional)
        self._seg_text: dict[int, str] = {}
        self._last_volatile = ""
        self._last_emit = ("", "")   # 草稿去重,内容没变不重复回调

    # ---------- 模型懒加载 ----------

    def _ensure_asr(self) -> VadTwoPassAsr:
        with self._asr_lock:
            if self._asr is None:
                # 复用实时/会议模式同款引擎:silero-VAD 主动分段 + 流式 zipformer
                # + 非流式 SenseVoice。这是项目里验证过能独立工作的那个(TwoPassAsr
                # 靠流式 endpoint 切句,单独用时常不出字)。
                self._asr = VadTwoPassAsr(FIRST_DIR, SECOND_DIR,
                                          num_threads=self._num_threads,
                                          provider="cpu")
            return self._asr

    def preload(self) -> None:
        """可在启用听写时提前建模型,避免首次说话时卡顿。"""
        self._ensure_asr()

    # ---------- 录音 + 识别 ----------

    def is_running(self) -> bool:
        return self._running

    def start(self) -> bool:
        """开始一次听写。已在进行中则返回 False(防叠加)。"""
        if self._running:
            return False
        self._stop_flag = False
        self._running = True
        self._seg_text = {}
        self._last_volatile = ""
        self._last_emit = ("", "")
        self._thread = threading.Thread(target=self._run, name="dictation-asr", daemon=True)
        self._thread.start()
        return True

    def _run(self) -> None:
        asr = self._ensure_asr()
        src = MicrophoneSource(chunk_ms=100)
        self._src = src
        started = time.monotonic()
        try:
            for frame in src.frames():
                if self._stop_flag:
                    break
                if time.monotonic() - started > MAX_SECONDS:
                    break
                for evt in asr.feed(np.asarray(frame, dtype=np.float32)):
                    self._apply_event(evt)
                self._emit_draft()
        except Exception as e:  # 采集/识别异常不应崩主程序
            print(f"[听写] 采集线程异常: {e}")
        finally:
            try:
                src.stop()
            except Exception:
                pass

    def _apply_event(self, evt) -> None:
        """按事件 kind 更新状态。VadTwoPassAsr 用 utt_id 区分语音段,
        final 高精度结果替换同段的 provisional。"""
        kind = getattr(evt, "kind", "")
        text = (evt.text or "").strip()
        uid = getattr(evt, "utt_id", -1)
        if kind == "volatile":
            self._last_volatile = text
        elif kind in ("provisional", "final"):
            # 按段存,final 覆盖该段 provisional
            self._seg_text[uid] = text
            self._last_volatile = ""

    def _committed_text(self) -> str:
        """按段顺序拼接已定稿文本。"""
        return "".join(self._seg_text[k] for k in sorted(self._seg_text))

    def _emit_draft(self) -> None:
        if self._on_draft is None:
            return
        cur = (self._committed_text(), self._last_volatile)
        if cur == self._last_emit:
            return               # 内容没变,不刷 UI
        self._last_emit = cur
        try:
            self._on_draft(*cur)
        except Exception:
            pass

    def stop(self) -> str:
        """停止采集,定稿,返回完整最终文本。"""
        if not self._running:
            return ""
        self._stop_flag = True
        try:
            if self._src is not None:
                self._src.stop()
        except Exception:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5.0)
        # 把残留未定稿的最后一句强制定稿(finalize 返回若干 final 事件)
        try:
            asr = self._ensure_asr()
            for evt in asr.finalize():
                self._apply_event(evt)
        except Exception as e:
            print(f"[听写] finalize 异常: {e}")
        self._running = False
        return self._committed_text().strip()
