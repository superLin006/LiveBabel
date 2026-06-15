# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:LiveBabel —— 一份 spec 同时支持 GPU 版 / 纯 CPU 版。
#
# 用环境变量 LIVEBABEL_BUILD 切换(build 脚本会设好,手动跑也可自己 set):
#     GPU 版(默认): pyinstaller packaging/subtitle.spec
#     CPU 版:         set LIVEBABEL_BUILD=cpu  &&  pyinstaller packaging/subtitle.spec
#
# 两版【唯一区别】只有三处(下面用 IS_CPU 开关):
#   1. GPU 库:GPU 版收集 nvidia-*(cuBLAS/cuDNN/cufft 等)→ 开箱即用;
#              CPU 版不收 nvidia,并剔除 sherpa 自带的 cuda/tensorrt provider dll → 省 ~2.5G。
#   2. runtime hook:CPU 版加 rthook_cpu_only.py(启动设 LIVEBABEL_CPU_ONLY=1,强制走 CPU)。
#   3. 产物名:GPU=LiveBabel,CPU=LiveBabel-CPU(目录/exe 都带后缀,可共存)。
# 其余(数据文件 / 排除库 / 隐式导入)两版完全共用,改一处两版同时生效。
#
# 必须在 Windows、已激活 subtitle 环境里执行(PyInstaller 不能跨平台)。
# 产物在 dist\<name>\;再把 models\ 和 ffmpeg\ 拷进去即可整包分发(脚本会自动拷)。
#   - 模型(~600MB):不打进 exe,放 exe 旁 models\(可换模型、首次离线会自动下 whisper)
#   - ffmpeg.exe:放 exe 旁 ffmpeg\(本 spec 会把项目根 ffmpeg\ 一起拷进去)

import os
from PyInstaller.utils.hooks import (
    collect_dynamic_libs, collect_submodules, collect_data_files,
)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

# ============ GPU / CPU 开关 ============
IS_CPU = os.environ.get("LIVEBABEL_BUILD", "").strip().lower() == "cpu"
APP_NAME = "LiveBabel-CPU" if IS_CPU else "LiveBabel"
print("[spec] build target =", "CPU-only" if IS_CPU else "GPU", "->", APP_NAME)

# ---- 原生库(.dll/.so / .pyd 依赖)----
# 这些库带 C 扩展,必须把它们的动态库一起收集,否则运行时崩溃。
# CPU 版额外剔除 sherpa 自带的 GPU provider dll(262M cuda + tensorrt),用不到。
_GPU_DLL_SKIP = ("onnxruntime_providers_cuda", "onnxruntime_providers_tensorrt")
binaries = []
for pkg in ("sherpa_onnx", "ctranslate2", "av", "onnxruntime"):
    for src, dst in collect_dynamic_libs(pkg):
        if IS_CPU and any(s in os.path.basename(src).lower() for s in _GPU_DLL_SKIP):
            continue
        binaries.append((src, dst))

# GPU 版才收集 nvidia-* CUDA 运行时。sherpa CUDA provider 初始化需要:
# cublas/cudnn/cufft/cuda_runtime/cuda_nvrtc/nvjitlink(只带 cublas+cudnn 会报 Error 1114)。
# 实测 cusparse/cusolver/curand 用不到,排除省 ~1G;cuDNN 全保留(删子包会加载失败)。
# CPU 版完全不收 nvidia → 省 ~2.3G,靠 rthook 强制 CPU,即使有 N 卡也不碰 GPU。
if not IS_CPU:
    _NV_SKIP = ("cusparse", "cusolver", "curand")
    try:
        for src, dst in collect_dynamic_libs("nvidia"):
            # dst 形如 nvidia\cusparse\bin;按子包名过滤
            if any(("\\%s\\" % s) in (dst + "\\") or ("/%s/" % s) in (dst + "/") for s in _NV_SKIP):
                continue
            binaries.append((src, dst))
    except Exception:
        pass

# ---- 数据文件(两版一致)----
# faster-whisper 自带 silero_vad_v6.onnx(transcribe 用 vad_filter=True 必需);
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
            datas.append((src, "ffmpeg"))   # 落到 dist\<name>\ffmpeg\

# 应用图标(窗口/任务栏运行时要用)
_icon = os.path.join(ROOT, "assets", "icon.ico")
for f in ("icon.ico", "logo.png"):
    p = os.path.join(ROOT, "assets", f)
    if os.path.isfile(p):
        datas.append((p, "assets"))

# ---- 隐式导入(动态 import,PyInstaller 静态分析抓不到)----
hiddenimports = (
    collect_submodules("sherpa_onnx")
    + collect_submodules("livebabel")
    + collect_submodules("ctranslate2")
    + ["app", "soundfile", "numpy", "requests", "faster_whisper", "av",
       "onnxruntime", "pyaudiowpatch"]
)

# CPU 版:启动即强制 CPU(避免在有 N 卡机器上尝试加载没打包的 GPU dll)
_runtime_hooks = []
if IS_CPU:
    _hook = os.path.join(ROOT, "packaging", "rthook_cpu_only.py")
    if os.path.isfile(_hook):
        _runtime_hooks.append(_hook)

a = Analysis(
    [os.path.join(ROOT, "livebabel_gui.py")],   # 图形化主入口(首页:实时/离线)
    pathex=[ROOT],                  # 让 livebabel 包 + 顶层 app.py 可被发现
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=_runtime_hooks,
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
    name=APP_NAME,
    console=False,                  # 无黑窗(GUI 程序)
    icon=_icon if os.path.isfile(_icon) else None,   # exe 图标
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name=APP_NAME,
)
