"""统一的资源路径解析,兼容"源码运行"和"PyInstaller 打包后运行"两种情况。

打包后 sys.frozen 为 True,可执行文件目录是 exe 所在目录。模型/历史/设置都放在
exe 旁边(而不是打进 exe),所以以 exe 目录为基准;源码运行则以本文件目录为基准。
"""

from __future__ import annotations

import os
import sys


def app_dir() -> str:
    """程序根目录:打包后是 exe 所在目录,源码运行是项目根目录(本文件在 livebabel/ 下,
    上溯一级到项目根,models/ history/ settings.json 都在那里)。"""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    # livebabel/paths.py → 上溯一级 = 项目根
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def res(*parts: str) -> str:
    """拼出相对于程序根目录的资源路径。"""
    return os.path.join(app_dir(), *parts)


MODELS_DIR = res("models")
FIRST_DIR = res("models", "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20")
SECOND_DIR = res("models", "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
VAD_MODEL = res("models", "silero_vad.onnx")
# 离线 whisper 模型的本地目录(放了就用本地,不重复下载;没放则按模型名自动下载)
WHISPER_DIR = res("models", "faster-whisper-large-v3-turbo")
HISTORY_DIR = res("history")
SETTINGS_PATH = res("settings.json")
# 应用图标:assets/icon.ico(打包时随 datas 收集到 _internal/assets 或 exe 旁)
ICON_ICO = res("assets", "icon.ico")
ICON_PNG = res("assets", "logo.png")


def find_icon() -> str:
    """返回可用的图标文件路径(优先 .ico),找不到返回空串。

    兼容打包:PyInstaller 可能把 assets 放进 _internal/ 或 _MEIPASS,逐个找。
    """
    cands = [ICON_ICO, ICON_PNG]
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        cands += [os.path.join(meipass, "assets", "icon.ico"),
                  os.path.join(meipass, "assets", "logo.png")]
    if getattr(sys, "frozen", False):
        ed = os.path.join(os.path.dirname(sys.executable), "_internal", "assets")
        cands += [os.path.join(ed, "icon.ico"), os.path.join(ed, "logo.png")]
    for c in cands:
        if os.path.isfile(c):
            return c
    return ""
