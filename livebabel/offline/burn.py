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
    return subprocess.run(cmd, capture_output=True)


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

    def base_cmd(venc_args):
        return [
            ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-stats",
            "-i", video_path,
            "-vf", vf,
            *venc_args,
            "-c:a", "copy",          # 音频不重编码
            output_path,
        ]

    # GPU:NVENC,p4 预设(速度/质量平衡),CQ 23 近似 CRF 23
    gpu_args = ["-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23"]
    # CPU:libx264 veryfast,比默认 medium 快好几倍
    cpu_args = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23"]

    if use_gpu:
        if on_log:
            on_log("      用 GPU(NVENC)编码烧录…")
        proc = _run(base_cmd(gpu_args))
        if proc.returncode == 0:
            return
        # NVENC 不可用/失败 → 回退 CPU
        if on_log:
            on_log("      NVENC 不可用,回退 CPU(libx264 veryfast)…")

    proc = _run(base_cmd(cpu_args))
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 烧录字幕失败:\n{proc.stderr.decode(errors='replace')}"
        )
