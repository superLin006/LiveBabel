@echo off
chcp 65001 >nul
REM ============================================================
REM  Build LiveBabel.exe. Run in Anaconda Prompt with the
REM  "subtitle" env. ffmpeg is bundled by the spec; models are
REM  copied next to the exe after build.
REM ============================================================
setlocal
set ENV_NAME=subtitle

REM Go to project root (this script is in packaging\, root is one up)
cd /d "%~dp0.."

echo [1/4] Installing PyInstaller ...
call conda run -n %ENV_NAME% pip install pyinstaller
if errorlevel 1 goto err

echo [2/4] Building exe from packaging\subtitle.spec ...
call conda run -n %ENV_NAME% pyinstaller --noconfirm packaging\subtitle.spec
if errorlevel 1 goto err

echo [3/4] Copying models into dist ...
if exist models (
    xcopy /E /I /Y models "dist\LiveBabel\models" >nul
) else (
    echo   WARNING: models\ not found, copy it into dist\LiveBabel\models\ manually.
)

echo [4/4] Done.
echo ============================================================
echo  Output: dist\LiveBabel\LiveBabel.exe
echo  Distribute the whole dist\LiveBabel\ folder (zip it).
echo  Users double-click LiveBabel.exe - no Python/CUDA/ffmpeg needed.
echo  Set DeepSeek API Key on the home screen to enable translation.
echo ============================================================
pause
goto end

:err
echo.
echo Build failed. Please send me the error above.
pause

:end
