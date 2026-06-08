"""ASR 调参评估脚本。

把一批音频拼成连续流,跑两遍 ASR,输出每个定稿段 + 统计指标,
用来评估分段是否合理、有没有碎段/超长段、Pass2 是否纠错。
不翻译(隔离 ASR 问题),默认 fast 模式批量跑。
"""

from __future__ import annotations

import argparse
import glob
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livebabel.asr.asr_engine import TwoPassAsr
from livebabel.asr.vad_engine import VadTwoPassAsr
from livebabel.asr.audio_source import ConcatFileSource
from livebabel.paths import FIRST_DIR, SECOND_DIR

SR = 16000


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--dir", required=True)
    p.add_argument("--pattern", default="fleurs_zh_*.wav")
    p.add_argument("--max-files", type=int, default=99)
    p.add_argument("--gap-ms", type=int, default=600)
    p.add_argument("--realtime", action="store_true")
    p.add_argument("--vad", action="store_true", help="用 VAD 分段引擎(否则用 endpoint 引擎)")
    args = p.parse_args()

    paths = sorted(glob.glob(os.path.join(args.dir, args.pattern)))[: args.max_files]
    engine = "VAD" if args.vad else "endpoint"
    print(f"files: {len(paths)}, gap={args.gap_ms}ms, realtime={args.realtime}, engine={engine}")

    source = ConcatFileSource(paths, realtime=args.realtime, gap_ms=args.gap_ms)
    segments: list[tuple[float, str]] = []
    t0 = time.time()
    total_samples = 0

    if args.vad:
        asr = VadTwoPassAsr(FIRST_DIR, SECOND_DIR)
        for chunk in source.frames():
            total_samples += len(chunk)
            for evt in asr.feed(chunk):
                if evt.committed_text is not None:
                    segments.append((0.0, evt.committed_text))  # VAD 段时长另算
        for evt in asr.finalize():
            if evt.committed_text is not None:
                segments.append((0.0, evt.committed_text))
    else:
        asr = TwoPassAsr(FIRST_DIR, SECOND_DIR)
        for chunk in source.frames():
            total_samples += len(chunk)
            evt = asr.feed(chunk)
            if evt.committed_text is not None:
                dur = (evt.audio_end - evt.audio_start) / SR
                segments.append((dur, evt.committed_text))
        last = asr.finalize()
        if last and last.committed_text:
            dur = (last.audio_end - last.audio_start) / SR
            segments.append((dur, last.committed_text))

    wall = time.time() - t0
    audio_dur = total_samples / SR

    print(f"\n{'='*70}")
    for i, (dur, text) in enumerate(segments):
        print(f"[{i:02d}] ({dur:5.1f}s) {text}")
    print(f"{'='*70}")
    print(f"段数: {len(segments)}")
    lens = [len(t) for _, t in segments]
    durs = [d for d, _ in segments]
    if lens:
        print(f"段字数: min={min(lens)} max={max(lens)} avg={sum(lens)/len(lens):.0f}")
        print(f"段时长: min={min(durs):.1f}s max={max(durs):.1f}s avg={sum(durs)/len(durs):.1f}s")
        short = [t for _, t in segments if len(t) < 4]
        long = [d for d in durs if d > 15]
        print(f"疑似碎段(<4字): {len(short)} {short[:5]}")
        print(f"疑似超长段(>15s): {len(long)}")
    print(f"音频时长 {audio_dur:.1f}s, 处理墙钟 {wall:.1f}s, RTF={wall/audio_dur:.3f}")


if __name__ == "__main__":
    main()
