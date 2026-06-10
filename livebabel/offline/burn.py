"""用 ffmpeg 把字幕硬压(烧录)进视频,生成新的视频文件。

硬压 = 字幕变成画面像素,任何播放器/平台都能看到,不依赖外挂字幕文件。
用 ASS 烧录能保留双语配色(原文白、译文青)。

速度说明:字幕叠加(subtitles 滤镜)是 CPU 软件滤镜,无法 GPU 化;但视频「重编码」
这步可以走 GPU(NVENC),比 CPU 的 libx264 快很多。有 N 卡时优先 NVENC,失败回退
CPU 的 libx264 veryfast(比默认 medium 快得多,体积/画质略有取舍)。
"""

from __future__ import annotations

import os
import subprocess


def _run(cmd) -> subprocess.CompletedProcess:
    from livebabel.ffmpeg_tool import run_hidden
    return run_hidden(cmd, capture_output=True)


def burn_subtitle(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    use_gpu: bool = False,
    on_log=None,
) -> None:
    """把 subtitle_path(.ass 或 .srt)烧录进 video_path,输出到 output_path。

    use_gpu=True 且有 NVENC 时用 GPU 编码(快);失败自动回退 CPU。
    on_log(str): 可选日志回调。
    """
    from livebabel.ffmpeg_tool import find_ffmpeg
    ffmpeg = find_ffmpeg()
    sub = os.path.abspath(subtitle_path)
    # ffmpeg subtitles 滤镜里 Windows 盘符冒号、反斜杠、单引号都要转义
    sub_escaped = sub.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = f"subtitles='{sub_escaped}'"

    def base_cmd(hwaccel_args, venc_args):
        return [
            ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-stats",
            *hwaccel_args,              # 放在 -i 前才对输入解码生效
            "-i", video_path,
            "-vf", vf,
            *venc_args,
            "-c:a", "copy",             # 音频不重编码
            output_path,
        ]

    # GPU:硬件解码(-hwaccel cuda)+ NVENC 编码,解码/编码两端都用 GPU,
    #      只剩字幕滤镜在 CPU(libass 无法 GPU 化)。p4 预设、CQ 23 ≈ CRF 23。
    gpu_hw = ["-hwaccel", "cuda"]
    gpu_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
    # CPU:libx264 veryfast,比默认 medium 快好几倍
    cpu_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]

    if use_gpu:
        if on_log:
            on_log("      用 GPU(CUDA 解码 + NVENC 编码)烧录…")
        proc = _run(base_cmd(gpu_hw, gpu_args))
        if proc.returncode == 0:
            return
        # GPU 硬解+NVENC 失败(驱动/编解码不支持等)→ 回退纯 CPU
        if on_log:
            on_log("      GPU 烧录失败,回退 CPU(libx264 veryfast)…")

    proc = _run(base_cmd([], cpu_args))
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 烧录字幕失败:\n{proc.stderr.decode(errors='replace')}"
        )


def mux_soft_subtitle(
    video_path: str,
    subtitle_path: str,
    output_path: str,
    on_log=None,
) -> None:
    """把字幕作为「软字幕轨道」封装进视频,不重编码任何一帧 → 秒级完成。

    软字幕 = 独立字幕轨,播放器里可开关/选语言,但不是画面像素(部分平台上传后
    可能不显示)。视频/音频都 -c copy 直接拷流,所以极快。
    输出建议用 .mkv(对 ASS 兼容最好);.mp4 只支持 mov_text(会丢 ASS 样式,转成普通字幕)。
    """
    from livebabel.ffmpeg_tool import find_ffmpeg
    ffmpeg = find_ffmpeg()
    ext = os.path.splitext(output_path)[1].lower()
    # mp4 不支持 ass 字幕编码,需转 mov_text;mkv 可原样保留 ass/srt
    sub_codec = "mov_text" if ext == ".mp4" else "copy"
    cmd = [
        ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-stats",
        "-i", video_path,
        "-i", subtitle_path,
        "-map", "0", "-map", "1",
        "-c", "copy",
        "-c:s", sub_codec,
        "-metadata:s:s:0", "language=und",
        output_path,
    ]
    if on_log:
        on_log("      封装软字幕(不重编码,极快)…")
    proc = _run(cmd)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 封装软字幕失败:\n{proc.stderr.decode(errors='replace')}"
        )
