## LiveBabel v1.4.1

v1.4.1 是面向低配置电脑的稳定双阶段版本，保留 Zipformer 流式草稿 + SenseVoice 定稿的产品架构。v1.5.0 的 Qwen3-ASR 路线继续保留，作为独立回滚/对比版本。

### 识别与性能

- Zipformer 流式草稿：CPU 使用 INT8，NVIDIA CUDA 使用 FP16。
- SenseVoice 定稿：CPU 使用 INT8，NVIDIA CUDA 使用 FP16。
- 实时字幕、会议纪要和语音输入共用同一套两阶段引擎，减少低配置机器上的延迟和内存压力。
- 离线字幕改用 SenseVoice + Silero VAD，不再要求安装 faster-whisper/CTranslate2。
- SenseVoice 支持普通话、粤语、英语、日语、韩语；Whisper 模型仍保留在 ModelScope，旧版用户不受影响。
- ChatTTS 按设备下载 CPU INT8 或 NVIDIA GPU FP16，仍为首次朗读时按需下载。

### 语音输入

- 新增托盘开关“AI 矫正口语和错字”，默认关闭。
- 开启后只在松开右 Ctrl、完成本地识别后调用 DeepSeek，校正明显语气词、同音错字和 ASR 错误。
- 录音和实时草稿不会发送到网络；API Key 缺失、超时或失败时自动输入原始识别结果。

### 模型下载

模型统一从 [ModelScope · LiveBabel-Models](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-Models) 下载。程序按实际 provider 只下载一套 Zipformer/SenseVoice/ChatTTS 精度变体，旧的 `sense-voice/`、`whisper/` 路径继续保留用于历史版本兼容。

### 发布包下载

- GitHub Release 仅提供 `LiveBabel-CPU-v1.4.1-win64.zip`，适合没有 NVIDIA 显卡的电脑。
- CPU/GPU 两个应用包同时同步到 [ModelScope · LiveBabel-sherpa-onnx-wheels](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-sherpa-onnx-wheels)；GPU 包需要 NVIDIA 驱动和 CUDA 运行库支持。
- 应用包不内置大模型；模型统一从 `LiveBabel-Models` 按需下载，避免 CPU/GPU 两套模型重复占用空间。

### 已知限制

- SenseVoice 离线模式的语言覆盖少于 Whisper；非中英日韩粤语内容请继续使用 v1.5.0 或旧版 Whisper 流程。
- AI 矫正需要联网并消耗 DeepSeek API 额度，关闭后完全不产生该请求。
- Zipformer GPU FP16 图必须与所用 sherpa-onnx CUDA runtime 一起验证；当前 Windows 流式 runtime 不稳定时保留已验证的 FP32 回退。ChatTTS GPU FP16 已在当前 wheel 上验证。
