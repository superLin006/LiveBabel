# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:LiveBabel(GPU 开箱即用版)
#
# 必须在 Windows 上、已激活 subtitle 环境里执行(PyInstaller 不能跨平台):
#     pip install pyinstaller
#     pyinstaller packaging/subtitle.spec
# 产物在 dist\LiveBabel\。再把 models\ 和 ffmpeg\ 拷进 dist\LiveBabel\ 即可整包分发。
#
# 设计目标:别人解压即用,无需装 Python / CUDA / ffmpeg。
#   - 模型(~600MB):不打进 exe,放 exe 旁 models\(包可换模型、首次离线会自动下 whisper)
#   - ffmpeg.exe:放 exe 旁 ffmpeg\(本 spec 会把项目根 ffmpeg\ 一起拷进去)
#   - GPU 运行时(cuBLAS/cuDNN):随 nvidia-* 包一起收集打包,有 N 卡开箱即用,
#     没 N 卡的机器代码会自动回退 CPU。

import os
from PyInstaller.utils.hooks import (
    collect_dynamic_libs, collect_submodules, collect_data_files,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

# ---- 原生库(.dll/.so / .pyd 依赖)----
# 这些库带 C 扩展,必须把它们的动态库一起收集,否则运行时崩溃。
binaries = []
for pkg in ("sherpa_onnx", "ctranslate2", "av", "onnxruntime"):
    binaries += collect_dynamic_libs(pkg)
# GPU 运行时:nvidia-cublas-cu12 / nvidia-cudnn-cu12 的 DLL(没装这两个包则为空,
# 那就是 CPU-only 包)。装了就自动打进去 → GPU 开箱即用。
for pkg in ("nvidia.cublas", "nvidia.cudnn"):
    try:
        binaries += collect_dynamic_libs(pkg)
    except Exception:
        pass

# ---- 数据文件 ----
# faster-whisper 自带 silero_vad_v6.onnx(我们 transcribe 用 vad_filter=True 必需);
# av/ctranslate2 也可能带数据文件。
datas = []
for pkg in ("faster_whisper", "av", "ctranslate2"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
# 把项目根的 ffmpeg\ 目录原样拷进分发包(若存在),实现零配置烧录/解码
_ffmpeg_dir = os.path.join(ROOT, "ffmpeg")
if os.path.isdir(_ffmpeg_dir):
    for name in os.listdir(_ffmpeg_dir):
        src = os.path.join(_ffmpeg_dir, name)
        if os.path.isfile(src):
            datas.append((src, "ffmpeg"))   # 落到 dist\LiveBabel\ffmpeg\

# ---- 隐式导入(动态 import,PyInstaller 静态分析抓不到)----
hiddenimports = (
    collect_submodules("sherpa_onnx")
    + collect_submodules("livebabel")
    + collect_submodules("ctranslate2")
    + ["app", "soundfile", "numpy", "requests", "faster_whisper", "av",
       "onnxruntime", "pyaudiowpatch"]
)

a = Analysis(
    [os.path.join(ROOT, "livebabel_gui.py")],   # 图形化主入口(首页:实时/离线)
    pathex=[ROOT],                  # 让 livebabel 包 + 顶层 app.py 可被发现
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    # 排除大量不用的库:torch/transformers/funasr/modelscope/jieba 等都是早期
    # 评估 FunASR 时装的残留,改用 faster-whisper(基于 CTranslate2,不依赖 torch)
    # 后已不需要。排除它们能把分发包从 ~4G 砍到 ~1.5G(不含模型)。
    # 这些只是不打进包,不动开发环境。
    excludes=[
        "tkinter", "matplotlib", "PySide6.QtWebEngineCore",
        "torch", "torchaudio", "torchvision",
        "transformers", "funasr", "modelscope", "jieba",
        "numba", "llvmlite", "sklearn", "scikit_learn", "scipy",
        "sympy", "networkx", "pandas",
        # PySide6 里用不到的大模块
        "PySide6.QtWebEngineWidgets", "PySide6.QtQuick", "PySide6.QtQml",
        "PySide6.Qt3DCore", "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtPdf",
        "PySide6.QtTest", "PySide6.QtDesigner",
    ],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="LiveBabel",
    console=False,                  # 无黑窗(GUI 程序)
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LiveBabel",
)
