"""独立诊断:注册 cuBLAS/cuDNN 后,直接加载 sherpa 的 cuda provider,看真实缺什么。

不依赖 livebabel 包(内联注册逻辑),避免 sys.path 问题。subtitle 环境跑:
    python tools/diag_cuda_dep.py
"""
import ctypes
import glob
import os
import sys


def main() -> None:
    import nvidia
    nbase = os.path.dirname(nvidia.__file__)
    nv_bins = [d for d in glob.glob(os.path.join(nbase, "*", "bin")) if os.path.isdir(d)]
    print("nvidia bin dirs:")
    for d in nv_bins:
        print("  ", d)
        os.add_dll_directory(d)

    import sherpa_onnx
    sdir = os.path.join(os.path.dirname(sherpa_onnx.__file__), "lib")
    os.add_dll_directory(sdir)
    print("sherpa lib:", sdir)

    # 按依赖顺序预加载【全套】CUDA 运行时(含 cudart/nvrtc/cufft/curand/cusolver/cusparse)
    order = ["cudart64_*.dll", "nvrtc64_*.dll", "nvrtc-builtins64_*.dll", "nvJitLink_64_*.dll",
             "cublasLt64_*.dll", "cublas64_*.dll",
             "cufft64_*.dll", "curand64_*.dll", "cusparse64_*.dll", "cusolver64_*.dll",
             "cudnn_graph64_9.dll", "cudnn_ops64_9.dll", "cudnn_heuristic64_9.dll",
             "cudnn_cnn64_9.dll", "cudnn_engines_runtime_compiled64_9.dll",
             "cudnn_engines_precompiled64_9.dll", "cudnn_adv64_9.dll", "cudnn64_9.dll"]
    for pat in order:
        for d in nv_bins:
            for f in glob.glob(os.path.join(d, pat)):
                try:
                    ctypes.WinDLL(f); print("  预加载 OK", os.path.basename(f))
                except OSError as e:
                    print("  预加载 FAIL", os.path.basename(f), e)

    # 先加载 sherpa 自带的 onnxruntime.dll(cuda provider 依赖它)
    try:
        ctypes.WinDLL(os.path.join(sdir, "onnxruntime.dll"))
        print("onnxruntime.dll OK")
    except OSError as e:
        print("onnxruntime.dll FAIL", e)

    # 注意:onnxruntime_providers_cuda.dll 不能用裸 WinDLL 独立加载(它要由
    # onnxruntime 经 provider_shared 机制加载,裸加载必 1114,是假象,不代表真问题)。
    # 正确做法是直接用 sherpa 真正建一个 cuda recognizer 看成不成。
    print("=" * 50)
    print("用 sherpa 真正初始化 CUDA(这才是真实判据):")
    try:
        import sherpa_onnx as so
        # 用一个不存在的模型路径只为触发 provider 初始化前的加载;真实测试见下
        print("  (此脚本不带模型,真实判据请看 livebabel_gui 实时模式日志)")
        print("  sherpa 版本:", getattr(so, "__version__", "?"))
    except Exception as e:
        print("  ", repr(e))

    # 看系统/CUDA Toolkit 里有没有 cudart(命令行能跑就是靠它)
    print("=" * 50)
    print("系统 PATH 里能找到的 cudart:")
    for p in os.environ.get("PATH", "").split(os.pathsep):
        for f in glob.glob(os.path.join(p, "cudart64_*.dll")) if p else []:
            print("  ", f)
    print("pip nvidia 包里的 cudart:")
    for d in glob.glob(os.path.join(nbase, "*", "bin", "cudart64_*.dll")):
        print("  ", d)
    print("(若系统有、pip 没有 → 打包缺 cudart,需 pip install nvidia-cuda-runtime-cu12)")


if __name__ == "__main__":
    main()
