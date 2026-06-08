# -*- mode: python ; coding: utf-8 -*-
# PyInstaller 打包配置:LiveBabel(CPU 版)
#
# 在项目根目录(已激活 subtitle 环境)执行:
#     pip install pyinstaller
#     pyinstaller packaging/subtitle.spec
# 产物在 dist\RealtimeSubtitle\,把 models\ 目录拷进去即可分发。
#
# 设计:模型(~600MB)不打进 exe,放在 exe 旁边的 models\,这样 exe 小、可换模型。

import os
from PyInstaller.utils.hooks import collect_dynamic_libs, collect_submodules

# 项目根 = 本 spec 所在目录(packaging/)的上一级
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(SPEC)))

# sherpa-onnx 的 .dll / .so 必须随包带上,否则运行时找不到原生库
binaries = collect_dynamic_libs("sherpa_onnx")

# 动态导入的模块 + 本项目 livebabel 包,显式声明,避免被裁掉
hiddenimports = (
    collect_submodules("sherpa_onnx")
    + collect_submodules("livebabel")
    + ["soundfile", "numpy", "requests"]
)

a = Analysis(
    [os.path.join(ROOT, "app.py")],
    pathex=[ROOT],                  # 让 livebabel 包可被发现
    binaries=binaries,
    datas=[],                       # 模型不打进来(放外部 models\)
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PySide6.QtWebEngineCore"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="RealtimeSubtitle",
    console=False,                  # 无黑窗(GUI 程序)
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    name="RealtimeSubtitle",
)
