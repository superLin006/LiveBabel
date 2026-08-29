## LiveBabel v1.5.1

v1.5.1 保留 v1.5.0 的 Qwen3-ASR-0.6B 路线，同时同步 v1.4.1 已验证的通用修复和功能。两者的 ASR 差异仍只有定稿/离线后端：v1.5.1 使用 Qwen3-ASR，v1.4.1 使用 SenseVoice。

### 同步内容

- 语音输入新增可选的 DeepSeek AI 矫正，默认关闭，仅在松开热键后处理最终文本。
- 修复启动器、悬浮窗和托盘并行写设置时覆盖 API Key 的问题，设置改为单字段合并和原子保存。
- ChatTTS 按设备使用 CPU INT8 或 NVIDIA GPU FP16，自动下载对应变体；CPU/GPU 不会同时保存两套图。
- GPU 打包仅携带已验证的 CUDA/cuDNN/cuFFT/cuBLAS 运行库，移除 NVRTC、NVJitLink、TensorRT provider 和未使用的 ffprobe。
- 首次启动自动下载模型，不再需要单独的模型下载脚本。

### 模型和应用包

- Qwen3-ASR CPU 使用 INT8，NVIDIA GPU 使用 FP16；当前 Windows CUDA 流式 Zipformer 草稿使用已验证的 FP32 图。
- 应用包不内置模型。CPU/GPU ZIP 和 SHA256 位于 [ModelScope 应用包仓库](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-sherpa-onnx-wheels) 的 `app/v1.5.1/`。
- v1.5.0 的 Qwen3-ASR 版本继续保留，作为独立回滚版本；旧版 Whisper/SenseVoice 模型也不会删除。
