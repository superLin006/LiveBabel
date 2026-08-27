"""统一的资源路径解析,兼容"源码运行"和"PyInstaller 打包后运行"两种情况。

打包后 sys.frozen 为 True,可执行文件目录是 exe 所在目录。模型/历史/设置都放在
exe 旁边(而不是打进 exe),所以以 exe 目录为基准;源码运行则以本文件目录为基准。

模型目录结构(v2.0+):
  models/
    vad/silero_vad.onnx
    zipformer/{tokens,encoder,decoder,joiner,bpe.*}
    qwen3-asr/{conv_frontend.onnx,encoder.int8.onnx,decoder.int8.onnx,tokenizer/*}
    (GPU 安装时 encoder/decoder 使用 FP16 及 .data；两种变体不同时保留)
    speaker/{campplus.onnx,eres2net_sv_zh.onnx}
    whisper/{config,model.bin,...}
    chattts/{decoder,gpt_*,vocos,...}
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

# ---- ASR 模型 ----
FIRST_DIR = res("models", "zipformer")         # 原生流式 Pass1
# 可指向一个独立的 Qwen 导出目录，主要用于开发/诊断；正式安装使用
# models/qwen3-asr，并由 model_setup 按 CPU/GPU 只下载一个模型变体。
SECOND_DIR = os.environ.get("LIVEBABEL_QWEN_MODEL_DIR",
                           res("models", "qwen3-asr"))
VAD_MODEL = res("models", "vad", "silero_vad.onnx")

# ---- 声纹模型 ----
SPEAKER_CAMPPLUS = res("models", "speaker", "campplus.onnx")
SPEAKER_ERES2NET = res("models", "speaker", "eres2net_sv_zh.onnx")

# ---- 离线 whisper ----
WHISPER_DIR = res("models", "whisper")

# ---- ChatTTS 语音合成 ----
# TTS 朗读:ChatTTS onnx int8 量化版(自魔改 sherpa-onnx 导出)
CHATTTS_DIR = res("models", "chattts")

# ---- 历史 / 设置 / 图标 ----
HISTORY_DIR = res("history")
# TTS 朗读:合成结果缓存(按 文本+音色 hash 命名),避免重复朗读同一段文字时
# 又重新合成一遍。见 livebabel/tts/cache.py
TTS_CACHE_DIR = res("history", "tts_cache")
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
