# LiveBabel sherpa-onnx wheels 与应用包

本仓库同时托管 LiveBabel 使用的 Windows Python wheel，以及 v1.4.1 的 Windows 应用包。

## 应用包

| 文件 | 适用设备 | 说明 |
|---|---|---|
| `app/v1.4.1/LiveBabel-CPU-v1.4.1-win64.zip` | 无 NVIDIA GPU | 约 111MB；CPU INT8 模型按需下载 |
| `app/v1.4.1/LiveBabel-GPU-v1.4.1-win64.zip` | NVIDIA GPU | 约 1.77GB；包含 CUDA/cuDNN/cuFFT/cuBLAS 运行库 |

两个应用包都不内置 ASR/TTS 模型。首次启动会自动从
[LiveBabel-Models](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-Models)
按设备下载所需模型；不需要运行额外的模型下载脚本。

v1.4.1 使用 Zipformer 流式草稿 + SenseVoice 定稿的两阶段路线：CPU 使用 INT8；GPU 的 SenseVoice 和 ChatTTS 使用 FP16；Windows CUDA 流式 Zipformer 默认使用已验证的 FP32 图，以避免未经验证的 FP16 runtime 问题。

## Wheel

wheel 文件仍放在 `wheels/` 目录，CPU/CUDA 版本可并存。请根据 Python 3.11 和设备选择对应文件，不要把应用 ZIP 当作 Python wheel 安装。

## 校验

同一版本的应用 ZIP 附带 `.sha256` 文件。下载后请先核对 SHA256，再解压运行。GPU 包需要 64 位 Windows、可用的 NVIDIA 驱动；没有 NVIDIA GPU 时请使用 CPU 包。

## 兼容版本

v1.5.0 的 Qwen3-ASR 路线和旧版 Whisper/SenseVoice 模型仍保留在各自模型/Release 资源中，供旧用户回滚，不会被 v1.4.1 应用包覆盖。
