"""实时双语字幕原型 —— 主程序。

数据流:
  AudioSource → TwoPassAsr.feed → AsrEvent
     ├─ 只更新 volatile?         → CommitManager.update_volatile
     └─ committed?               → CommitManager.commit + Translator.submit
  Translator(后台)译完 → CommitManager.set_translation
  ConsoleDisplay 持续刷新 manager 的状态

验证目标:committed 文本和译文稳定不动,只有末尾 volatile 行在变。
"""

from __future__ import annotations

import argparse
import glob
import os

from asr_engine import TwoPassAsr
from vad_engine import VadTwoPassAsr
from audio_source import ConcatFileSource, FileSource
from commit_manager import CommitManager
from display import ConsoleDisplay
from translator import Translator

import sys


class JitterLog:
    """把 volatile 的每次变化和 commit 写到 stderr,作为晃动消除的文字证据。

    volatile 行会看到同一句被反复改写(草稿在抖);
    commit 行出现后,该句进入定稿区,之后再不出现于 volatile —— 抖动被隔离。
    """

    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled
        self._last = ""
        self._n = 0

    def volatile(self, text: str) -> None:
        if not self.enabled or text == self._last:
            return
        self._last = text
        self._n += 1
        print(f"  volatile[{self._n:03d}]: {text}", file=sys.stderr)

    def commit(self, text: str) -> None:
        if not self.enabled:
            return
        print(f">>> COMMIT (锁定,不再变): {text}", file=sys.stderr)
        self._last = ""


from paths import FIRST_DIR, SECOND_DIR


def build_source(args) -> object:
    if args.concat_dir:
        paths = sorted(glob.glob(os.path.join(args.concat_dir, args.pattern)))
        if not paths:
            raise SystemExit(f"no files match {args.pattern} in {args.concat_dir}")
        paths = paths[: args.max_files]
        print(f"[concat] {len(paths)} files, realtime={not args.fast}")
        return ConcatFileSource(
            paths, realtime=not args.fast, gap_ms=args.gap_ms
        )
    return FileSource(args.input, realtime=not args.fast)


def main() -> None:
    p = argparse.ArgumentParser(description="实时双语字幕原型(晃动消除验证)")
    p.add_argument("--input", help="单个音频/视频文件")
    p.add_argument("--concat-dir", help="把目录下多个文件拼成连续语音流")
    p.add_argument("--pattern", default="*.wav", help="拼接时的文件匹配模式")
    p.add_argument("--max-files", type=int, default=6)
    p.add_argument("--gap-ms", type=int, default=600, help="拼接时句间静音(触发分段)")
    p.add_argument("--fast", action="store_true", help="不按真实时间,尽快跑完")
    p.add_argument("--lang", default="英文", help="翻译目标语言")
    p.add_argument("--no-translate", action="store_true", help="只验证 ASR 晃动,不翻译")
    p.add_argument("--log-jitter", action="store_true",
                   help="打印 volatile 每次变化 + commit 事件,作为晃动消除的证据")
    p.add_argument("--endpoint", action="store_true",
                   help="用旧的 endpoint 分段引擎(默认用更稳健的 VAD 引擎)")
    args = p.parse_args()

    if not args.input and not args.concat_dir:
        raise SystemExit("需要 --input 或 --concat-dir")

    print("加载模型中…")
    asr = TwoPassAsr(FIRST_DIR, SECOND_DIR) if args.endpoint \
        else VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
    manager = CommitManager()

    translator = None
    if not args.no_translate:
        translator = Translator(
            on_result=manager.set_translation, target_lang=args.lang
        )

    source = build_source(args)

    # jitter 日志:记录 volatile 文本的每一次变化,用来证明"草稿在抖、定稿不抖"
    jlog = JitterLog(args.log_jitter)

    def handle_event(evt) -> None:
        """统一处理一个 AsrEvent。兼容两个引擎(endpoint 引擎无 kind/utt_id)。"""
        kind = getattr(evt, "kind", "")
        utt_id = getattr(evt, "utt_id", -1)
        if evt.committed_text is not None:
            jlog.commit(evt.committed_text)
            if kind == "final" and getattr(evt, "replace_seg", False):
                seg = manager.replace_utterance(utt_id, evt.committed_text)
            else:
                seg = manager.add_committed(
                    evt.committed_text, provisional=(kind == "provisional"), utt_id=utt_id)
            if seg and translator:
                translator.submit(seg.id, seg.text, quick=(kind == "provisional"))
            elif seg:
                manager.set_translation(seg.id, "[已禁用翻译]")
        elif evt.volatile_text:
            jlog.volatile(evt.volatile_text)
            manager.update_volatile(evt.volatile_text)

    def as_events(ret):
        """两个引擎一个返回单事件、一个返回列表,统一成列表。"""
        if ret is None:
            return []
        return ret if isinstance(ret, list) else [ret]

    with ConsoleDisplay(manager) as disp:
        for chunk in source.frames():
            for evt in as_events(asr.feed(chunk)):
                handle_event(evt)
            disp.refresh()

        # 收尾:冲刷尾部残留
        for evt in as_events(asr.finalize()):
            handle_event(evt)
        disp.refresh()

        if translator:
            print("\n等待剩余翻译完成…")
            translator.join()      # 精确等到所有译文完成,不空等不漏译
            translator.close()
            disp.refresh()

    # 最终结果纯文本输出
    print("\n===== 最终字幕 =====")
    for seg in manager.committed:
        print(f"[{seg.id}] {seg.text}")
        print(f"     {seg.translation}")


if __name__ == "__main__":
    main()
