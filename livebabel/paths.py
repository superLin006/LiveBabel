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
HISTORY_DIR = res("history")
SETTINGS_PATH = res("settings.json")
