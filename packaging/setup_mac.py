"""py2app 打包配置:把 LiveBabel 打成 macOS .app。

在 macOS 上、已装依赖的环境里执行(py2app 不能跨平台,必须在 Mac 上跑):
    pip install py2app
    python packaging/setup_mac.py py2app
产物在 dist/LiveBabel.app。再把 models/ 和 ffmpeg/ 拷进 .app 内的资源目录
(见 build_mac.sh,会自动做)。

与 Windows(PyInstaller subtitle.spec)的对应关系:
  * 数据文件(faster_whisper 的 silero_vad、av/ctranslate2 数据):用 collect_data_files 收
  * 隐式导入 / 包:sherpa_onnx / ctranslate2 / livebabel 全收
  * 排除大库(torch/transformers/scipy 等):py2app 的 excludes
  * GPU 库:macOS 不需要(无 CUDA),sounddevice 走 CPU + CoreML
  * 麦克风权限:plist 里声明 NSMicrophoneUsageDescription(否则录音直接崩)

注:本配置在无 Mac 环境下编写,需在 macOS 真机首次打包时按报错微调
(py2app 对 onnxruntime/sherpa 的动态库收集常需补 includes/frameworks)。
"""

import os
import sys

from setuptools import setup

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _collect_data():
    """收集 faster_whisper / av / ctranslate2 的数据文件 + 项目 ffmpeg/ + assets。"""
    data = []
    try:
        from PyInstaller.utils.hooks import collect_data_files  # 若装了 pyinstaller 复用
        for pkg in ("faster_whisper", "av", "ctranslate2"):
            try:
                # collect_data_files 返回 [(src, dest_dir)],py2app 要 (dest_dir, [src...])
                by_dir = {}
                for src, dst in collect_data_files(pkg):
                    by_dir.setdefault(dst, []).append(src)
                data += list(by_dir.items())
            except Exception:
                pass
    except Exception:
        pass
    # 项目根 ffmpeg/(若存在,随包,实现零配置烧录)
    ff = os.path.join(ROOT, "ffmpeg")
    if os.path.isdir(ff):
        files = [os.path.join(ff, n) for n in os.listdir(ff)
                 if os.path.isfile(os.path.join(ff, n))]
        if files:
            data.append(("ffmpeg", files))
    # assets(图标/logo)
    assets = [os.path.join(ROOT, "assets", f) for f in ("icon.ico", "logo.png")
              if os.path.isfile(os.path.join(ROOT, "assets", f))]
    if assets:
        data.append(("assets", assets))
    return data


# Mac 图标:优先 .icns;没有则不指定(py2app 用默认)
_icns = os.path.join(ROOT, "assets", "icon.icns")
ICON = _icns if os.path.isfile(_icns) else None

OPTIONS = {
    "argv_emulation": False,
    "packages": [
        "livebabel", "sherpa_onnx", "ctranslate2", "faster_whisper",
        "av", "sounddevice", "numpy", "PySide6",
    ],
    "includes": [
        "app", "soundfile", "requests", "onnxruntime", "_sounddevice",
    ],
    "excludes": [
        "tkinter", "matplotlib", "pyaudiowpatch",       # pyaudiowpatch 仅 Windows
        "torch", "torchaudio", "torchvision",
        "transformers", "funasr", "modelscope", "jieba",
        "numba", "llvmlite", "sklearn", "scikit_learn", "scipy",
        "sympy", "networkx", "pandas",
        "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
        "PySide6.QtQuick", "PySide6.QtQml", "PySide6.Qt3DCore",
        "PySide6.QtCharts", "PySide6.QtDataVisualization",
        "PySide6.QtMultimedia", "PySide6.QtPdf",
        "PySide6.QtTest", "PySide6.QtDesigner",
    ],
    "plist": {
        "CFBundleName": "LiveBabel",
        "CFBundleDisplayName": "LiveBabel",
        "CFBundleIdentifier": "com.livebabel.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "NSHighResolutionCapable": True,
        # 麦克风权限说明(会议模式录麦克风必需,缺了 macOS 会直接 kill 进程)
        "NSMicrophoneUsageDescription":
            "LiveBabel 需要访问麦克风以进行会议实时转录(录制你本人的发言)。",
        # Apple Silicon 上禁止把 .app 当 Intel 跑(避免架构混淆)
        "LSMinimumSystemVersion": "11.0",
    },
}
if ICON:
    OPTIONS["iconfile"] = ICON

if __name__ == "__main__":
    if sys.platform != "darwin":
        sys.exit("setup_mac.py 只能在 macOS 上运行(py2app 不能跨平台打包)。")
    setup(
        app=[os.path.join(ROOT, "livebabel_gui.py")],
        name="LiveBabel",
        options={"py2app": OPTIONS},
        setup_requires=["py2app"],
    )
