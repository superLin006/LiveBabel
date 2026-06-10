"""Windows 下让 CTranslate2 找到并加载 cuBLAS / cuDNN 运行时 DLL。

CTranslate2 4.x 不再自带这些 DLL;它们由 pip 包 nvidia-cublas-cu12 / nvidia-cudnn-cu12
提供,落在 site-packages\\nvidia\\<子包>\\bin\\。仅 os.add_dll_directory() 有时不够
(取决于 CTranslate2 内部用什么方式加载),最稳的是把这些目录全部注册 + 预加载关键 DLL
进进程。本模块在加载模型前调用一次,使源码运行和打包后的 exe 都无需手动配 PATH。

非 Windows(Linux/WSL)上 CTranslate2 的 wheel 自带 .so,本函数直接跳过。
"""

from __future__ import annotations

import glob
import os
import sys

_done = False


def _nvidia_bin_dirs() -> list[str]:
    """列出所有 nvidia-* pip 包里的 bin 目录(cublas/cudnn/cublasLt 等都在其下)。"""
    dirs: list[str] = []
    try:
        import nvidia
        base = os.path.dirname(nvidia.__file__)
    except Exception:
        return dirs
    # site-packages\nvidia\<任意子包>\bin
    for bin_dir in glob.glob(os.path.join(base, "*", "bin")):
        if os.path.isdir(bin_dir):
            dirs.append(bin_dir)
    return dirs


def ensure_cuda_dlls() -> list[str]:
    """注册 + 预加载 cuBLAS/cuDNN 运行时,使 CTranslate2 能在 GPU 上跑。

    做三件事(都只在 Windows、只执行一次):
      1. os.add_dll_directory 注册每个 nvidia 包的 bin 目录;
      2. 同时把这些目录前插进 PATH(兼容某些按 PATH 找 DLL 的加载方式);
      3. 用 ctypes 主动预加载 cublas64_*/cublasLt64_*/cudnn*_9 等关键 DLL,
         加载成功后它们已在进程里,CTranslate2 再要时直接命中。

    返回成功注册的目录列表(诊断用)。任何异常都吞掉,缺库时 CTranslate2 会自报错。
    """
    global _done
    if _done or not sys.platform.startswith("win"):
        return []
    _done = True

    dirs = _nvidia_bin_dirs()
    for d in dirs:
        try:
            os.add_dll_directory(d)
        except OSError:
            pass
    if dirs:
        os.environ["PATH"] = os.pathsep.join(dirs) + os.pathsep + os.environ.get("PATH", "")

    # 主动预加载:按依赖顺序(cublasLt 先于 cublas,cublas 先于 cudnn)
    import ctypes
    patterns = [
        "cublasLt64_*.dll",
        "cublas64_*.dll",
        "cudnn_ops*64_9.dll", "cudnn_cnn*64_9.dll", "cudnn_engines*64_9.dll",
        "cudnn64_9.dll",
    ]
    for pat in patterns:
        for d in dirs:
            for dll in sorted(glob.glob(os.path.join(d, pat))):
                try:
                    ctypes.WinDLL(dll)
                except OSError:
                    pass
    return dirs


def diagnose() -> str:
    """返回一段人类可读的诊断文本:nvidia 包在哪、有哪些 dll、PATH 里有没有 cublas。

    供 GUI/CLI 在 GPU 失败时打印,帮用户快速定位是没装包还是没注册。
    """
    lines: list[str] = []
    lines.append(f"platform = {sys.platform}")
    try:
        import ctranslate2
        lines.append(f"ctranslate2 = {ctranslate2.__version__}, "
                     f"cuda_device_count = {ctranslate2.get_cuda_device_count()}")
    except Exception as e:
        lines.append(f"ctranslate2 导入失败: {e}")
    dirs = _nvidia_bin_dirs()
    if not dirs:
        lines.append("未找到 nvidia-* 运行时包(cublas/cudnn)。请先 pip 安装(见提示)。")
    else:
        for d in dirs:
            dlls = [os.path.basename(p) for p in glob.glob(os.path.join(d, "*.dll"))]
            lines.append(f"{d}\n    -> {', '.join(dlls) if dlls else '(空)'}")
    return "\n".join(lines)
