# LiveBabel sherpa-onnx wheels

LiveBabel 使用的 Qwen3-ASR ONNX Python wheel：

- `wheels/sherpa_onnx-1.12.17-cp311-cp311-win_amd64.whl`：Windows CPU 版。
- `wheels/sherpa_onnx-1.12.17+cuda-cp311-cp311-win_amd64.whl`：Windows NVIDIA CUDA 版。

两个 wheel 都提供 `OfflineRecognizer.from_qwen3_asr` 和每个 `OfflineStream` 的 `set_option` 接口。CPU wheel 不包含 CUDA/TensorRT 运行库；GPU wheel 由 LiveBabel 的 GPU 环境使用。普通安装默认从 ModelScope 获取 CPU wheel，GPU 用户可手动替换为 CUDA wheel。
