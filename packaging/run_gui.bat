@echo off
chcp 65001 >nul
REM ============================================================
REM  LiveBabel - graphical launcher (recommended for new users)
REM  Opens a home screen: choose Live mode or Offline mode.
REM ============================================================
setlocal

set ENV_NAME=subtitle
cd /d "%~dp0.."

echo Starting LiveBabel...
call conda run -n %ENV_NAME% --no-capture-output python livebabel_gui.py %*

if errorlevel 1 (
    echo.
    echo Launch failed. Please send me the error above.
    pause
)
