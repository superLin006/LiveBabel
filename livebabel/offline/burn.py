"""用 ffmpeg 把字幕硬压(烧录)进视频,生成新的视频文件。

硬压 = 字幕变成画面像素,任何播放器/平台都能看到,不依赖外挂字幕文件。
用 ASS 烧录能保留双语配色(原文白、译文青)。
"""

from __future__ import annotations

import os
import subprocess


def burn_subtitle(video_path: str, subtitle_path: str, output_path: str) -> None:
    """把 subtitle_path(.ass 或 .srt)烧录进 video_path,输出到 output_path。

    用 ASS 效果最好(保留样式)。ffmpeg 的 subtitles 滤镜对路径里的特殊字符敏感,
    这里转成绝对路径并转义。
    """
    from livebabel.ffmpeg_tool import find_ffmpeg
    ffmpeg = find_ffmpeg()
    sub = os.path.abspath(subtitle_path)
    # ffmpeg subtitles 滤镜里 Windows 盘符冒号、反斜杠、单引号都要转义
    sub_escaped = sub.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = f"subtitles='{sub_escaped}'"
    cmd = [
        ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-stats",
        "-i", video_path,
        "-vf", vf,
        "-c:a", "copy",          # 音频不重编码
        output_path,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 烧录字幕失败:\n{proc.stderr.decode(errors='replace')}"
        )
