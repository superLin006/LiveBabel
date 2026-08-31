# LiveBabel sherpa-onnx wheels 与应用包

本仓库托管 LiveBabel 使用的 Windows Python wheel，以及 v1.4.1/v1.5.1 Windows 应用包。

Hugging Face 镜像：[XHxiehuan/LiveBabel-sherpa-onnx-wheels](https://huggingface.co/XHxiehuan/LiveBabel-sherpa-onnx-wheels)。

## 应用包

| 目录 | 文件 | 适用设备 |
|---|---|---|
| `app/v1.4.1/` | `LiveBabel-CPU-v1.4.1-win64.zip` / `LiveBabel-GPU-v1.4.1-win64.zip` | SenseVoice 两阶段路线 |
| `app/v1.5.1/` | `LiveBabel-CPU-v1.5.1-win64.zip` / `LiveBabel-GPU-v1.5.1-win64.zip` | Qwen3-ASR 两阶段路线 |

每个目录同时提供对应 `.sha256` 校验文件。CPU 包不需要 NVIDIA 显卡；GPU 包包含 CUDA/cuDNN/cuFFT/cuBLAS 运行库，需要 64 位 Windows 和可用的 NVIDIA 驱动。

应用包不内置 ASR/TTS 模型。首次启动会自动从
[LiveBabel-Models](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-Models)
按设备下载模型，不需要运行额外的模型下载脚本。

## 版本差异

- v1.4.1：Zipformer 流式草稿 + SenseVoice 定稿/离线识别。
- v1.5.1：保留 v1.4.1 的通用修复和功能，定稿/离线识别改为 Qwen3-ASR-0.6B。
- 两个版本都支持可选 DeepSeek 语音输入 AI 矫正；API Key 保存在本地设置，不会打进发布包。
- Zipformer 流式草稿使用 CPU 混合图（INT8 encoder/joiner + FP32 decoder）或 GPU 全 FP32 图；CPU 不使用有重复风险的 INT8 decoder。
- ChatTTS 按设备下载 CPU INT8 或 GPU FP16；Zipformer GPU 默认使用已验证的 FP32 图。

## Wheel

wheel 文件仍放在 `wheels/` 目录，CPU/CUDA 版本可并存。请根据 Python 3.11 和设备选择对应文件，不要把应用 ZIP 当作 Python wheel 安装。

v1.5.0 的 Qwen3-ASR 路线和旧版 Whisper/SenseVoice 模型仍保留在模型仓库中，供旧用户回滚。
