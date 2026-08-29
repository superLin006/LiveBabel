@echo off
chcp 65001 >nul
REM ============================================================
REM  Build LiveBabel-CPU.exe (lightweight, no GPU runtime DLLs).
REM  Run in Anaconda Prompt with the subtitle-new environment.
REM  The shared subtitle.spec selects the CPU path via LIVEBABEL_BUILD.
REM ============================================================
setlocal
set ENV_NAME=subtitle-new
set LIVEBABEL_BUILD=cpu

cd /d "%~dp0.."

echo Killing any running LiveBabel process ...
taskkill /f /im LiveBabel.exe >nul 2>&1
taskkill /f /im LiveBabel-CPU.exe >nul 2>&1

echo [1/4] Installing PyInstaller ...
call conda run -n %ENV_NAME% pip install pyinstaller
if errorlevel 1 goto err

echo [2/4] Building CPU exe from packaging\subtitle.spec ...
call conda run -n %ENV_NAME% pyinstaller --noconfirm packaging\subtitle.spec
if errorlevel 1 goto err

echo [3/4] Copying local models for smoke testing ...
if exist models (
    xcopy /E /I /Y models "dist\LiveBabel-CPU\models" >nul
) else (
    echo   WARNING: models\ not found; first launch will download them.
)

echo [4/4] Done.
echo ============================================================
echo  Output: dist\LiveBabel-CPU\LiveBabel-CPU.exe
echo  Before release, copy only exe + _internal to a clean release folder.
echo  Do not ship models, settings.json, history\ or log\.
echo ============================================================
pause
goto end

:err
echo.
echo Build failed. Please send me the error above.
pause

:end
