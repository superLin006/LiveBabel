# LiveBabel Models

LiveBabel 的本地语音模型仓库，供实时字幕、语音输入、会议记录和离线字幕使用。

Hugging Face 镜像：[XHxiehuan/LiveBabel-Models](https://huggingface.co/XHxiehuan/LiveBabel-Models)。

## 模型清单

| 目录 | 模型/用途 | v1.5 状态 | 约占用 |
|---|---|---|---:|
| `vad/` | Silero VAD 语音分段 | 当前使用 | 1 MB |
| `zipformer/` | 流式 Zipformer 实时草稿（Pass1） | CPU 混合 INT8/FP32；GPU FP32 | 约 200 / 360 MB |
| `qwen3-asr/` | Qwen3-ASR-0.6B 高精度识别（Pass2、离线） | v1.5.0/v1.5.1 当前使用 | CPU INT8 约 1.0 GB；GPU FP16 约 1.8 GB |
| `speaker/` | campplus / eres2net 会议说话人识别 | 当前使用 | 65 MB |
| `chattts/` | ChatTTS 本地朗读 | CPU INT8 / GPU FP16 按需下载 | 470 / 940 MB |
| `sense-voice/` | SenseVoice 非流式识别 | 旧版本兼容保留 | 229 MB |
| `whisper/` | Whisper large-v3-turbo 离线识别 | 旧版本兼容保留 | 1.6 GB |

### Qwen3-ASR 文件

- 公共文件：`conv_frontend.onnx`、`tokenizer/`。
- CPU：`encoder.int8.onnx`、`decoder.int8.onnx`。
- NVIDIA GPU：`encoder.fp16.onnx`、`decoder.fp16.onnx` 及对应 `.data` 文件。
- 远端同时保存 INT8 和 FP16，程序按运行后端只下载/保留实际使用的一套。

### Zipformer 文件

- CPU 实时草稿：`encoder-epoch-99-avg-1.int8.onnx` +
  `decoder-epoch-99-avg-1.onnx`（FP32） +
  `joiner-epoch-99-avg-1.int8.onnx`。
- NVIDIA GPU：三个不带 `.int8` 后缀的 FP32 图。
- 远端保留完整 INT8 图供旧版本兼容，但当前应用不使用 INT8 decoder，
  因为该组合在部分语音中会产生重复草稿。

### 旧版本兼容

`sense-voice/` 和 `whisper/` 不会从仓库删除。v1.5 默认不再使用它们，但旧版 LiveBabel 仍会按原路径读取这些文件，因此旧版本用户可以继续运行。模型文件由程序从本仓库按需下载。

v1.5.0/v1.5.1 默认实时链路是 Zipformer 流式草稿 + Qwen3-ASR 最终修正；离线字幕直接使用 Qwen3-ASR。v1.4.1 使用同一 Zipformer 草稿链路，但定稿和离线字幕使用 SenseVoice。

### 版本对应关系

| 应用版本 | Pass1 流式草稿 | Pass2/离线 | 应用包 |
|---|---|---|---|
| v1.4.1 | Zipformer（CPU INT8 encoder/joiner + FP32 decoder；GPU FP32） | SenseVoice（CPU INT8 / GPU FP16） | `LiveBabel-sherpa-onnx-wheels/app/v1.4.1/` |
| v1.5.1 | Zipformer（CPU INT8 encoder/joiner + FP32 decoder；GPU FP32） | Qwen3-ASR-0.6B（CPU INT8 / GPU FP16） | `LiveBabel-sherpa-onnx-wheels/app/v1.5.1/` |

两套版本共用 VAD、声纹和 ChatTTS 文件。切换应用版本时，程序只下载当前后端所需的 ASR 变体；旧的 SenseVoice、Whisper 和 v1.5.0 兼容文件继续保留。
