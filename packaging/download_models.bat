@echo off
chcp 65001 >nul
REM ============================================================
REM  Download ASR models into models\ (Windows 10+ has curl/tar)
REM  Skip this if you copied the models folder from WSL.
REM  Resumable (-C -) + auto retry; verifies each file, stops on failure.
REM ============================================================
setlocal enabledelayedexpansion
set BASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models
set SEGBASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-segmentation-models
set SVBASE=https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models
set CURL=curl -L -C - --retry 5 --retry-delay 3 --retry-all-errors --connect-timeout 30 -o
cd /d "%~dp0.."
if not exist models mkdir models
cd models

echo [1/5] silero VAD ...
%CURL% silero_vad.onnx %BASE%/silero_vad.onnx
if not exist silero_vad.onnx goto :failed

echo [2/5] streaming zipformer (Pass1, ~300MB) ...
%CURL% p1.tar.bz2 %BASE%/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2
if errorlevel 1 goto :failed
if not exist p1.tar.bz2 goto :failed
tar xf p1.tar.bz2
if not exist "sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" goto :failed_extract
del p1.tar.bz2

echo [3/5] SenseVoice (Pass2, ~230MB) ...
%CURL% p2.tar.bz2 %BASE%/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2
if errorlevel 1 goto :failed
if not exist p2.tar.bz2 goto :failed
tar xf p2.tar.bz2
if not exist "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17" goto :failed_extract
del p2.tar.bz2

echo [4/5] Speaker segmentation (diarization, ~6MB) ...
%CURL% seg.tar.bz2 %SEGBASE%/sherpa-onnx-pyannote-segmentation-3-0.tar.bz2
if errorlevel 1 goto :failed
if not exist seg.tar.bz2 goto :failed
tar xf seg.tar.bz2
if not exist "sherpa-onnx-pyannote-segmentation-3-0" goto :failed_extract
del seg.tar.bz2

echo [5/5] Speaker embedding (diarization, ~39MB) ...
%CURL% 3dspeaker_eres2net_sv_zh.onnx %SVBASE%/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx
if not exist 3dspeaker_eres2net_sv_zh.onnx goto :failed

cd ..
echo Done.
pause
exit /b 0

:failed
echo.
echo [FAILED] Download interrupted (network / GitHub unstable).
echo Re-run this script: finished files are skipped, partial ones resume.
cd ..
pause
exit /b 1

:failed_extract
echo.
echo [FAILED] Archive incomplete; removed corrupted file. Re-run to retry.
del *.tar.bz2 2>nul
cd ..
pause
exit /b 1
