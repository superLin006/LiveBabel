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

echo [3/3] SenseVoice (Pass2, ~230MB) ...
curl -L -o p2.tar.bz2 %BASE%/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
tar xf p2.tar.bz2
del p2.tar.bz2

cd ..
echo Done.
pause
