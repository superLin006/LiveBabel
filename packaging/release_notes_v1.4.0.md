# LiveBabel v1.4.0 发布说明

## 主要变更

### 🏪 模型下载迁移到 ModelScope
- 所有语音模型统一托管在 [ModelScope 魔搭社区](https://modelscope.cn/models/XHxiehuan/LiveBabel-Models)
- 国内直连高速下载，不再需要 GitHub 镜像加速
- 按后端下载单套核心模型：CPU INT8 / GPU FP16，避免两套 Qwen 权重同时占用磁盘；ChatTTS 仍按需下载

### 📁 模型目录重构
- 旧扁平结构 → 分类子目录：`vad/` `zipformer/` `qwen3-asr/` `speaker/` `whisper/` `chattts/`
- 清理不再使用的冗余模型（pyannote-segmentation, eres2netv2 等）

### 🛠 修复与改进
- 补上此前遗漏的 campplus 主力声纹模型下载
- whisper 离线转录模型改为按需询问下载（不占用启动下载量）
- ChatTTS 朗读模型对接统一仓库
- 修复 download_models.bat 使其实际执行下载

### 📦 下载

`LiveBabel-CPU-v1.4.0-win64.zip` (~209MB) — 任何电脑可用，无需显卡。

### 🚀 使用方法

1. 解压到任意目录
2. 双击 `LiveBabel-CPU.exe`
3. 首次启动自动从 ModelScope 下载核心模型（~636MB，仅一次）
4. 设置 DeepSeek API Key 即可使用翻译功能

### ⚠️ 已知问题
- 无数字签名，部分杀毒软件可能误报，选择"信任"即可
- 翻译功能需要 DeepSeek API Key
