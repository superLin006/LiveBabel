"""离线双语字幕生成 —— 命令行入口。

流程:视频 → faster-whisper 识别(带时间戳) → LLM 翻译 → 生成 SRT+ASS →(可选)硬压进视频。

用法:
    set DEEPSEEK_API_KEY=你的key
    python tools/offline_subtitle.py 视频.mp4 --lang 中文
    python tools/offline_subtitle.py 视频.mp4 --lang 中文 --burn        # 同时烧录进视频
    python tools/offline_subtitle.py 视频.mp4 --source-lang en          # 指定源语言加速

输出(默认在视频同目录,同名):视频.srt / 视频.ass /(--burn 时)视频.bilingual.mp4
"""

from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from livebabel.offline.transcribe import transcribe
from livebabel.offline.translate_batch import translate_sentences
from livebabel.offline.subtitle_writer import write_srt, write_ass
from livebabel.offline.burn import burn_subtitle


def main() -> None:
    p = argparse.ArgumentParser(description="离线双语字幕生成")
    p.add_argument("video", help="输入视频/音频文件")
    p.add_argument("--lang", default="中文", help="翻译目标语种(中文/英语/日语/韩语…)")
    p.add_argument("--source-lang", default=None,
                   help="源语言代码(如 en/zh/ja),不填则自动检测")
    p.add_argument("--model", default="large-v3-turbo", help="whisper 模型")
    p.add_argument("--device", default="auto", help="auto(自动检测)/ cpu / cuda")
    p.add_argument("--compute-type", default="auto",
                   help="auto(随设备:GPU=float16,CPU=int8)/ int8 / float16")
    p.add_argument("--no-translate", action="store_true", help="只出原文字幕,不翻译")
    p.add_argument("--burn", action="store_true", help="把 ASS 字幕硬压进视频")
    p.add_argument("--out-dir", default=None, help="输出目录(默认与视频同目录)")
    args = p.parse_args()

    if not os.path.isfile(args.video):
        raise SystemExit(f"找不到文件:{args.video}")

    # 自动探测设备:有 GPU 走 cuda+float16,否则 cpu+int8
    from livebabel.offline.transcribe import detect_device
    auto = args.device == "auto"
    if auto:
        device, auto_ct = detect_device()
    else:
        device = args.device
        auto_ct = "float16" if device == "cuda" else "int8"
    compute_type = auto_ct if args.compute_type == "auto" else args.compute_type
    print(f"[设备] {device} ({compute_type})"
          + ("  ← 自动检测到 GPU" if auto and device == "cuda" else ""))

    base = os.path.splitext(os.path.basename(args.video))[0]
    out_dir = args.out_dir or os.path.dirname(os.path.abspath(args.video))
    os.makedirs(out_dir, exist_ok=True)
    srt_path = os.path.join(out_dir, base + ".srt")
    ass_path = os.path.join(out_dir, base + ".ass")

    print(f"[1/4] 识别中(faster-whisper {args.model})…")
    def prog(done, total):
        pct = 100 * done / total if total else 0
        print(f"\r      {done:6.1f}/{total:.1f}s ({pct:4.1f}%)", end="", file=sys.stderr)
    sents = transcribe(args.video, model_size=args.model, language=args.source_lang,
                       device=device, compute_type=compute_type, on_progress=prog)
    print(f"\n      识别完成,共 {len(sents)} 句。")

    if not args.no_translate:
        print(f"[2/4] 翻译成{args.lang}(DeepSeek)…")
        def tprog(done, total):
            print(f"\r      {done}/{total} 句", end="", file=sys.stderr)
        translate_sentences(sents, target_lang=args.lang, on_progress=tprog)
        print()
    else:
        print("[2/4] 跳过翻译")

    bilingual = not args.no_translate
    print("[3/4] 生成字幕 SRT + ASS …")
    write_srt(sents, srt_path, bilingual=bilingual)
    write_ass(sents, ass_path, bilingual=bilingual)
    print(f"      {srt_path}\n      {ass_path}")

    if args.burn:
        out_mp4 = os.path.join(out_dir, base + ".bilingual.mp4")
        print(f"[4/4] 烧录字幕进视频 → {out_mp4} …")
        burn_subtitle(args.video, ass_path, out_mp4,
                      use_gpu=(device == "cuda"),
                      on_log=lambda m: print(m))
        print("      完成。")
    else:
        print("[4/4] 未烧录(加 --burn 可硬压进视频)")


if __name__ == "__main__":
    main()
