# LiveBabel-Models

LiveBabel v1.4.1 的模型统一存放于本仓库，程序按实际设备选择精度并按需下载。

| 目录 | 用途 | CPU | NVIDIA GPU |
|---|---|---|---|
| `vad/` | Silero VAD 分段 | 公共 | 公共 |
| `zipformer/` | 中英流式草稿 | `encoder/decoder/joiner.*.int8.onnx` | FP16 图（待目标 Windows CUDA runtime 验证后发布） |
| `sense-voice/` | 两阶段定稿、离线字幕（中英日韩粤） | `model.int8.onnx` | `model.fp16.onnx` |
| `speaker/` | 会议声纹 | 公共 | 公共 |
| `chattts/` | 可选本地朗读 | `*.int8.onnx` | `*.fp16.onnx` |

SenseVoice FP16 是从原始 `iic/SenseVoiceSmall` 权重重新导出，并已在 sherpa-onnx CUDA provider 上验证。ChatTTS FP16/INT8 均由 `Sophon_model_zoo/chatTTS/tools/export_onnx_merged.py` 从原始 safetensors 重新导出，并已在当前 wheel 上验证 CPU/GPU 语音生成。Zipformer 的 INT8 图来自官方同一中英双语模型包；当前 sherpa-onnx Windows CUDA runtime 对该模型的 FP16 流式图仍需单独验证，因此程序在图缺失时回退到已验证的 FP32 图。

## 旧版本兼容

以下目录不会删除：

- `sense-voice/` 的旧 INT8 文件，供 v1.3/v1.4 用户继续使用；
- `whisper/` 的 Whisper large-v3-turbo 文件，供旧版离线字幕使用；
- `qwen3-asr/`（如存在），供 v1.5.0 Qwen 路线回滚/对比使用。

v1.4.1 离线字幕改用 SenseVoice + Silero VAD，不会自动下载 Whisper。
