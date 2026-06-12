@echo off
chcp 65001 >nul
REM ============================================================
REM  Download ASR models into models\ (Windows 10+ has curl/tar)
REM  Skip this if you copied the models folder from WSL.
REM ============================================================
setlocal
set BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
cd /d "%~dp0.."
if not exist models mkdir models
cd models

echo [1/3] silero VAD ...
curl -L -o silero_vad.onnx %BASE%/silero_vad.onnx

echo [2/3] streaming zipformer (Pass1, ~300MB) ...
curl -L -o p1.tar.bz2 %BASE%/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
tar xf p1.tar.bz2
del p1.tar.bz2

echo [3/5] SenseVoice (Pass2, ~230MB) ...
curl -L -o p2.tar.bz2 %BASE%/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xf p2.tar.bz2
del p2.tar.bz2

echo [4/5] Speaker segmentation (diarization, ~6MB) ...
curl -L -o seg.tar.bz2 https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
tar xf seg.tar.bz2
del seg.tar.bz2

echo [5/5] Speaker embedding (diarization, ~39MB) ...
curl -L -o 3dspeaker_eres2net_sv_zh.onnx https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx

cd ..
echo Done.
pause
