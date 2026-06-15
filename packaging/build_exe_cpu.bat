@echo off
chcp 65001 >nul
REM ============================================================
REM  Build LiveBabel-CPU.exe (lightweight, no GPU libs).
REM  Run in Anaconda Prompt with the "subtitle" env.
REM ============================================================
setlocal
set ENV_NAME=subtitle

cd /d "%~dp0.."

echo Killing any running LiveBabel ...
taskkill /f /im LiveBabel.exe >nul 2>&1
taskkill /f /im LiveBabel-CPU.exe >nul 2>&1

echo [1/4] Installing PyInstaller ...
call conda run -n %ENV_NAME% pip install pyinstaller
if errorlevel 1 goto err

echo [2/4] Building CPU exe from packaging\subtitle-cpu.spec ...
call conda run -n %ENV_NAME% pyinstaller --noconfirm packaging\subtitle-cpu.spec
if errorlevel 1 goto err

echo [3/4] Copying models into dist ...
if exist models (
    xcopy /E /I /Y models "dist\LiveBabel-CPU\models" >nul
) else (
    echo   WARNING: models\ not found, copy it into dist\LiveBabel-CPU\models\ manually.
)

echo [4/4] Done.
echo ============================================================
echo  Output: dist\LiveBabel-CPU\LiveBabel-CPU.exe  (CPU-only, small)
echo  Distribute the whole dist\LiveBabel-CPU\ folder.
echo ============================================================
pause
goto end

:err
echo.
echo Build failed. Please send me the error above.
pause

:end
