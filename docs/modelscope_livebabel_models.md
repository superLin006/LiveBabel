# LiveBabel-Models

LiveBabel v1.4.1 的模型统一存放于本仓库，程序按实际设备选择精度并按需下载。

| 目录 | 用途 | CPU | NVIDIA GPU |
|---|---|---|---|
| `vad/` | Silero VAD 分段 | 公共 | 公共 |
| `zipformer/` | 中英流式草稿 | INT8 encoder/joiner + FP32 decoder | 全 FP32 图 |
| `sense-voice/` | 两阶段定稿、离线字幕（中英日韩粤） | `model.int8.onnx` | `model.fp16.onnx` |
| `speaker/` | 会议声纹 | 公共 | 公共 |
| `chattts/` | 可选本地朗读 | `*.int8.onnx` | `*.fp16.onnx` |

SenseVoice FP16 是从原始 `iic/SenseVoiceSmall` 权重重新导出，并已在 sherpa-onnx CUDA provider 上验证。ChatTTS FP16/INT8 均由 `Sophon_model_zoo/chatTTS/tools/export_onnx_merged.py` 从原始 safetensors 重新导出，并已在当前 wheel 上验证 CPU/GPU 语音生成。Zipformer CPU 使用官方 INT8 encoder/joiner 与 FP32 decoder 的混合图，GPU 使用全 FP32 图。

## 旧版本兼容

以下目录不会删除：

- `sense-voice/` 的旧 INT8 文件，供 v1.3/v1.4 用户继续使用；
- `whisper/` 的 Whisper large-v3-turbo 文件，供旧版离线字幕使用；
- `qwen3-asr/`（如存在），供 v1.5.0 Qwen 路线回滚/对比使用。

v1.4.1 离线字幕改用 SenseVoice + Silero VAD，不会自动下载 Whisper。
