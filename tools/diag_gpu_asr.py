"""诊断实时 ASR 的 GPU(sherpa-onnx CUDA provider)为什么加载失败(Error 1114)。

在 subtitle 环境、项目根跑:
    python tools/diag_gpu_asr.py
把完整输出发回。
"""

from __future__ import annotations

import glob
import os
import sys


def main() -> None:
    print("=" * 60)
    print("Python:", sys.version)
    print("platform:", sys.platform)

    # 1) onnxruntime 情况
    try:
        import onnxruntime as ort
        print("onnxruntime:", ort.__version__)
        print("providers:", ort.get_available_providers())
    except Exception as e:
        print("[onnxruntime] 导入失败:", e)

    # 2) sherpa_onnx 自带 onnxruntime DLL 列表
    sdir = None
    try:
        import sherpa_onnx
        sdir = os.path.join(os.path.dirname(sherpa_onnx.__file__), "lib")
        print("=" * 60)
        print("sherpa_onnx/lib DLLs:")
        for p in sorted(glob.glob(os.path.join(sdir, "*.dll"))):
            print("   ", os.path.basename(p), f"{os.path.getsize(p)//1024//1024}MB")
    except Exception as e:
        print("[sherpa_onnx] 导入失败:", e)

    # 2b) 关键:先注册 cuBLAS/cuDNN,再直接 WinDLL 加载 sherpa 的 cuda provider,
    #     看它到底缺哪个依赖 dll(用 win32 LoadLibraryEx 拿到真实错误)
    print("=" * 60)
    print("直接加载 onnxruntime_providers_cuda.dll(看缺哪个依赖):")
    try:
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        ensure_cuda_dlls()
    except Exception as e:
        print("  ensure_cuda_dlls:", e)
    if sdir:
        import ctypes
        cuda_dll = os.path.join(sdir, "onnxruntime_providers_cuda.dll")
        # 先把 sherpa lib 目录也加入搜索(它依赖同目录 onnxruntime.dll)
        try:
            os.add_dll_directory(sdir)
        except Exception:
            pass
        try:
            ctypes.WinDLL(cuda_dll)
            print("  [OK] onnxruntime_providers_cuda.dll 加载成功!")
        except OSError as e:
            print("  [FAIL] 加载失败,真实错误:")
            print("   ", repr(e))
            print("  → WinError 126 = 找不到某个依赖 dll;",
                  "可用 dumpbin/Dependencies 看,但通常是缺 cudart64_12.dll(CUDA runtime)")

    # 3) nvidia 包里的 cublas/cudnn DLL
    print("=" * 60)
    try:
        import nvidia
        base = os.path.dirname(nvidia.__file__)
        for sub in ("cublas", "cudnn"):
            d = os.path.join(base, sub, "bin")
            print(f"{sub}/bin:")
            for p in sorted(glob.glob(os.path.join(d, "*.dll"))):
                print("   ", os.path.basename(p), f"{os.path.getsize(p)//1024//1024}MB")
    except Exception as e:
        print("[nvidia] 不存在或读取失败:", e)

    # 4) 注册 DLL 后,尝试用 onnxruntime 直接创建一个 CUDA session
    print("=" * 60)
    print("尝试用 onnxruntime 直接初始化 CUDA(看真实报错):")
    try:
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        added = ensure_cuda_dlls()
        print("  注册的 DLL 目录:", added)
    except Exception as e:
        print("  ensure_cuda_dlls 失败:", e)
    try:
        import numpy as np
        import onnxruntime as ort
        # 构造一个极小模型测试 CUDA EP 能否真正初始化
        import onnx
        from onnx import helper, TensorProto
        X = helper.make_tensor_value_info("X", TensorProto.FLOAT, [1, 2])
        Y = helper.make_tensor_value_info("Y", TensorProto.FLOAT, [1, 2])
        node = helper.make_node("Identity", ["X"], ["Y"])
        g = helper.make_graph([node], "g", [X], [Y])
        m = helper.make_model(g, opset_imports=[helper.make_opsetid("", 13)])
        so = ort.SessionOptions()
        sess = ort.InferenceSession(m.SerializeToString(),
                                    providers=["CUDAExecutionProvider"])
        print("  [OK] CUDA session 创建成功,实际 providers:", sess.get_providers())
    except Exception as e:
        print("  [FAIL] CUDA session 创建失败:")
        print("   ", repr(e))

    print("=" * 60)
    print("诊断结束,请把以上全部输出发回。")


if __name__ == "__main__":
    main()
