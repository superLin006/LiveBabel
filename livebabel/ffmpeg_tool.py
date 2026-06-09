"""定位 ffmpeg 可执行文件,并给出友好报错。

查找顺序:
  1. 环境变量 LIVEBABEL_FFMPEG 指定的完整路径
  2. 项目根的 ffmpeg/ 目录(ffmpeg[.exe]),方便随项目分发、不用配 PATH
  3. 系统 PATH 里的 ffmpeg

找不到时抛出带安装指引的清晰错误,而不是看不懂的 WinError 2。
"""

from __future__ import annotations

import os
import shutil
import sys

from livebabel.paths import res


def find_ffmpeg() -> str:
    # 1) 环境变量显式指定
    env = os.environ.get("LIVEBABEL_FFMPEG", "").strip()
    if env and os.path.isfile(env):
        return env

    # 2) 项目目录 ffmpeg/(支持 ffmpeg.exe / ffmpeg/bin/ffmpeg.exe)
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    for cand in (res("ffmpeg", exe), res("ffmpeg", "bin", exe)):
        if os.path.isfile(cand):
            return cand

    # 3) 系统 PATH
    found = shutil.which("ffmpeg")
    if found:
        return found

    raise RuntimeError(
        "未找到 ffmpeg。请任选其一:\n"
        "  1. 下载静态版(https://www.gyan.dev/ffmpeg/builds/),把 ffmpeg.exe 放到\n"
        "     项目的 ffmpeg\\ 目录下(如 F:\\LiveBabel\\ffmpeg\\ffmpeg.exe);或\n"
        "  2. 把 ffmpeg 加入系统 PATH;或\n"
        "  3. 设环境变量 LIVEBABEL_FFMPEG 指向 ffmpeg.exe 的完整路径。"
    )
