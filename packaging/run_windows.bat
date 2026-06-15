@echo off
chcp 65001 >nul
REM ============================================================
REM  Realtime Bilingual Subtitle - launch
REM  Subtitle window: left-drag to move, right-click to quit.
REM ============================================================
setlocal

set ENV_NAME=subtitle
cd /d "%~dp0.."

if "%DEEPSEEK_API_KEY%"=="" (
    set /p DEEPSEEK_API_KEY=Enter DeepSeek API Key:
)

echo Starting... (first run loads models, ~10-20s)
call conda run -n %ENV_NAME% --no-capture-output python app.py %*

if errorlevel 1 (
    echo.
    echo Launch failed. Please send me the error above.
    pause
)
