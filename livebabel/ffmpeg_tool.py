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
import subprocess
import sys

from livebabel.paths import res


def run_hidden(cmd, **kwargs) -> "subprocess.CompletedProcess":
    """像 subprocess.run 一样跑命令,但在 Windows GUI 程序里不弹黑色控制台窗。

    打包成无控制台的 GUI(console=False)后,调用 ffmpeg 这类控制台程序时
    Windows 会给它新开一个控制台窗一闪/常驻。加 CREATE_NO_WINDOW 抑制掉。
    非 Windows 无影响。
    """
    if sys.platform.startswith("win"):
        kwargs.setdefault("creationflags", 0x08000000)  # CREATE_NO_WINDOW
    return subprocess.run(cmd, **kwargs)


def find_ffmpeg() -> str:
    # 1) 环境变量显式指定
    env = os.environ.get("LIVEBABEL_FFMPEG", "").strip()
    if env and os.path.isfile(env):
        return env

    # 2) 随程序分发的 ffmpeg。覆盖多种落点:
    #    - 源码运行:项目根 ffmpeg\
    #    - 打包(PyInstaller onedir):较新版本把数据放在 exe 旁的 _internal\,
    #      旧版本放 exe 同级;onefile 解压到 _MEIPASS。都纳入搜索。
    exe = "ffmpeg.exe" if sys.platform.startswith("win") else "ffmpeg"
    roots = [res()]                       # app_dir():源码=项目根,打包=exe 目录
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        roots.append(os.path.join(os.path.dirname(sys.executable), "_internal"))
    for root in roots:
        for cand in (os.path.join(root, "ffmpeg", exe),
                     os.path.join(root, "ffmpeg", "bin", exe),
                     os.path.join(root, exe)):
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
