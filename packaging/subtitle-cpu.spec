# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:LiveBabel 轻量版(纯 CPU,不打包任何 GPU 库)
#
# 与满血版(subtitle.spec)的唯一区别:
#   1. 不收集 nvidia-* GPU 运行时(cuBLAS/cuDNN/cufft 等)→ 省 ~2.3GB
#   2. runtime hook 设 LIVEBABEL_CPU_ONLY=1 → 实时+离线强制走 CPU,即使有 N 卡也不碰 GPU
#   代码完全共用(cpu-edition 分支)。烧录仍可走 NVENC(不依赖 cuDNN,靠显卡驱动)。
#
# 在 Windows、subtitle 环境执行:
#     pyinstaller packaging/subtitle-cpu.spec
# 产物 dist\LiveBabel-CPU\,把 models\ ffmpeg\ 拷进去分发。适合无 N 卡 / 想要小包的用户。

import os
from PyInstaller.utils.hooks import (
    collect_dynamic_libs, collect_submodules, collect_data_files,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

# ---- 原生库:只收 CPU 必需的;【不收 nvidia GPU 库】----
# 纯 CPU 版不收集 nvidia-* —— 与满血版关键差异,省 ~2.3GB。
# 另外:若环境装的是 GPU 版 sherpa,它带个 262MB 的 onnxruntime_providers_cuda.dll +
# tensorrt provider,CPU 版用不到,一并剔除让包更小。
_GPU_DLL_SKIP = ("onnxruntime_providers_cuda", "onnxruntime_providers_tensorrt")
binaries = []
for pkg in ("sherpa_onnx", "ctranslate2", "av", "onnxruntime"):
    for src, dst in collect_dynamic_libs(pkg):
        if any(s in os.path.basename(src).lower() for s in _GPU_DLL_SKIP):
            continue
        binaries.append((src, dst))

# ---- 数据文件(与满血版一致)----
datas = []
for pkg in ("faster_whisper", "av", "ctranslate2"):
    try:
        datas += collect_data_files(pkg)
    except Exception:
        pass
_ffmpeg_dir = os.path.join(ROOT, "ffmpeg")
if os.path.isdir(_ffmpeg_dir):
    for name in os.listdir(_ffmpeg_dir):
        src = os.path.join(_ffmpeg_dir, name)
        if os.path.isfile(src):
            datas.append((src, "ffmpeg"))

_icon = os.path.join(ROOT, "assets", "icon.ico")
for f in ("icon.ico", "logo.png"):
    p = os.path.join(ROOT, "assets", f)
    if os.path.isfile(p):
        datas.append((p, "assets"))

hiddenimports = (
    collect_submodules("sherpa_onnx")
    + collect_submodules("livebabel")
    + collect_submodules("ctranslate2")
    + ["app", "soundfile", "numpy", "requests", "faster_whisper", "av",
       "onnxruntime", "pyaudiowpatch"]
)

a = Analysis(
    [os.path.join(ROOT, "livebabel_gui.py")],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    # 纯 CPU 版:启动即强制 CPU
    runtime_hooks=[os.path.join(ROOT, "packaging", "rthook_cpu_only.py")],
    excludes=[
        "tkinter", "matplotlib", "PySide6.QtWebEngineCore",
        "torch", "torchaudio", "torchvision",
        "transformers", "funasr", "modelscope", "jieba",
        "numba", "llvmlite", "sklearn", "scikit_learn", "scipy",
        "sympy", "networkx", "pandas",
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
    name="LiveBabel-CPU",
    console=False,
    icon=_icon if os.path.isfile(_icon) else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="LiveBabel-CPU",
)
