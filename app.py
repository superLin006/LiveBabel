"""实时双语字幕 GUI 应用(Windows 主入口)。

把 ASR + 翻译流水线放后台线程,字幕推到透明悬浮窗显示。
音频源默认 WASAPI loopback(系统声音);用 --input 可改成文件(便于在任意平台预览 UI)。

运行(Windows):
    pip install PySide6 pyaudiowpatch
    set DEEPSEEK_API_KEY=你的key
    python app.py                      # 抓系统声音
    python app.py --input demo.mp4     # 用文件预览
"""

from __future__ import annotations

import argparse
import os
import sys
import threading

from livebabel.core.commit_manager import CommitManager
from livebabel.core.translator import Translator
from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.paths import FIRST_DIR, SECOND_DIR


def build_source(args):
    if args.input:
        from livebabel.asr.audio_source import FileSource
        return FileSource(args.input, realtime=True)
    # 抓系统声音:Windows 用 WASAPI loopback;macOS 用 BlackHole 虚拟声卡
    import sys
    if sys.platform == "darwin":
        from livebabel.asr.audio_source_mac import BlackHoleSource
        return BlackHoleSource()
    from livebabel.asr.audio_source_windows import WasapiLoopbackSource
    return WasapiLoopbackSource()


def pipeline_thread(args, manager: CommitManager, translator, on_change,
                    stop_flag, pause_flag):
    """后台:跑音频→ASR→commit→翻译,每次状态变化调用 on_change()。"""
    asr = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
    source = build_source(args)

    def handle(evt):
        if evt.kind == "provisional":
            seg = manager.add_committed(evt.text, provisional=True, utt_id=evt.utt_id)
            if seg and translator:
                translator.submit(seg.id, seg.text, quick=True)   # 快速,不带长上下文
        elif evt.kind == "final":
            if evt.replace_seg:
                # 段结束:用 SenseVoice 整段高精度文本替换该段所有临时子句,并重译
                seg = manager.replace_utterance(evt.utt_id, evt.text)
            else:
                seg = manager.add_committed(evt.text, provisional=False, utt_id=evt.utt_id)
            if seg and translator:
                translator.submit(seg.id, seg.text, quick=False)  # 完整上下文
        elif evt.kind == "volatile":
            manager.update_volatile(evt.text)
        on_change()

    was_paused = False
    for chunk in source.frames():
        if stop_flag():
            break
        if pause_flag():
            if not was_paused:
                asr.reset()       # 进入暂停:清掉半句状态,恢复后不会和暂停前接成一句
                was_paused = True
            continue              # 暂停时丢弃音频,不识别不翻译
        was_paused = False
        for evt in asr.feed(chunk):
            handle(evt)
    for evt in asr.finalize():
        handle(evt)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", help="用音频/视频文件代替系统声音(预览 UI 用)")
    p.add_argument("--no-translate", action="store_true")
    p.add_argument("--no-history", action="store_true", help="不保存历史记录")
    args = p.parse_args()

    from PySide6.QtWidgets import QApplication
    from livebabel.ui.overlay import SubtitleOverlay, SubtitleLine
    from livebabel.history_writer import HistoryWriter

    app = QApplication(sys.argv)
    overlay = SubtitleOverlay()
    overlay.show()

    manager = CommitManager()
    translator = None
    if not args.no_translate:
        # 初始目标语种/key 取自悬浮窗的持久化设置(右键可随时改)
        translator = Translator(
            on_result=manager.set_translation, target_lang=overlay.s["lang"],
            api_key=overlay.s.get("api_key", ""),
        )
        # 右键里改了 key → 更新运行中的 translator
        overlay.api_key_changed.connect(
            lambda k: setattr(translator, "api_key",
                              (k or __import__("os").environ.get("DEEPSEEK_API_KEY", "")).strip())
        )

    def push_to_overlay() -> None:
        committed, volatile = manager.recent(overlay.max_lines)
        lines = [
            SubtitleLine(source=s.text, translation=s.translation,
                         committed=True, provisional=s.provisional)
            for s in committed
        ]
        if volatile is not None:
            lines.append(SubtitleLine(source=volatile.text, translation=None, committed=False))
        overlay.update_lines(lines)

    history = None if args.no_history else HistoryWriter()
    _logged: set[int] = set()   # 已写入历史的段 id,避免重复

    # 译文就绪时:刷新 UI;若是最终段(非临时),写入历史
    if translator:
        def set_and_refresh(seg_id, tr):
            manager.set_translation(seg_id, tr)
            push_to_overlay()
            if history is not None:
                seg = manager.get(seg_id)
                if seg and not seg.provisional and seg.id not in _logged:
                    _logged.add(seg.id)
                    history.add(seg.text, tr)
        translator.on_result = set_and_refresh

    # 右键切换语种 → 改 translator 目标语言;屏幕上已显示的句子重新翻译。
    # 重译用 quick=True:这些是回填,不该再写进上下文历史(避免重复污染)。
    def on_lang_changed(lang: str) -> None:
        if not translator:
            return
        translator.target_lang = lang
        for seg in manager.committed[-overlay.max_lines:]:
            translator.submit(seg.id, seg.text, quick=True)
    overlay.lang_changed.connect(on_lang_changed)

    # 「总结」按钮:取本场转录 → DeepSeek 摘要 → 弹窗展示
    from livebabel.ui.summary_window import wire_summarize
    wire_summarize(
        overlay, manager,
        lambda: (overlay.s.get("api_key", "") or os.environ.get("DEEPSEEK_API_KEY", "")).strip(),
    )

    stopped = {"v": False}
    paused = {"v": False}
    overlay.pause_toggled.connect(lambda p: paused.__setitem__("v", p))

    worker = threading.Thread(
        target=pipeline_thread,
        args=(args, manager, translator, push_to_overlay,
              lambda: stopped["v"], lambda: paused["v"]),
        daemon=True,
    )
    worker.start()

    try:
        app.exec()
    finally:
        stopped["v"] = True


if __name__ == "__main__":
    main()
