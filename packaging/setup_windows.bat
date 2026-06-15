@echo off
chcp 65001 >nul
REM ============================================================
REM  Realtime Bilingual Subtitle - Windows one-click setup
REM  Run this once on Windows (Anaconda/Miniconda required).
REM ============================================================
setlocal

set ENV_NAME=subtitle
cd /d "%~dp0.."

echo.
echo [1/3] Creating conda env "%ENV_NAME%" (python 3.11) ...
call conda create -y -n %ENV_NAME% python=3.11
if errorlevel 1 goto err

echo.
echo [2/3] Installing dependencies ...
call conda run -n %ENV_NAME% pip install -r requirements.txt
if errorlevel 1 goto err

echo.
echo [3/3] Checking models ...
if not exist "models\sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20" (
    echo   Models NOT found. Copy the WSL "models" folder to project root,
    echo   or run packaging\download_models.bat
) else (
    echo   Models OK.
)

echo.
echo ============================================================
echo  Done. Next steps:
echo    1. set DEEPSEEK_API_KEY=your_key
echo    2. packaging\run_windows.bat
echo ============================================================
pause
goto end

:err
echo.
echo Something went wrong. Please send me the error above.
pause

:end
