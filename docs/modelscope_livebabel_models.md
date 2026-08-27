# LiveBabel Models

LiveBabel 的本地语音模型仓库，供实时字幕、语音输入、会议记录和离线字幕使用。

## ASR 模型

- `zipformer/`：实时流式草稿识别（Pass1）。
- `qwen3-asr/`：Qwen3-ASR-0.6B 高精度识别（Pass2 和离线模式）。
  - 公共文件：`conv_frontend.onnx`、`tokenizer/`。
  - CPU：`encoder.int8.onnx`、`decoder.int8.onnx`。
  - NVIDIA GPU：`encoder.fp16.onnx`、`decoder.fp16.onnx` 及对应 `.data` 文件。
  - CPU/GPU 变体按运行后端二选一下载，远端同时保存两种变体，单台设备只保留实际使用的一套。
- `vad/`：Silero VAD 语音分段。
- `speaker/`：会议说话人识别模型。

LiveBabel 的默认实时链路是 Zipformer 流式草稿 + Qwen3-ASR 最终修正；离线字幕直接使用 Qwen3-ASR。模型文件由程序从本仓库按需下载。
