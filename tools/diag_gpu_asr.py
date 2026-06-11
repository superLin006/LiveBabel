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
    try:
        import sherpa_onnx
        sdir = os.path.join(os.path.dirname(sherpa_onnx.__file__), "lib")
        print("=" * 60)
        print("sherpa_onnx/lib DLLs:")
        for p in sorted(glob.glob(os.path.join(sdir, "*.dll"))):
            print("   ", os.path.basename(p), f"{os.path.getsize(p)//1024//1024}MB")
    except Exception as e:
        print("[sherpa_onnx] 导入失败:", e)

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
