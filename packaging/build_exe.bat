@echo off
chcp 65001 >nul
REM ============================================================
REM  Build RealtimeSubtitle.exe (CPU). Run in Anaconda Prompt,
REM  with the "subtitle" env. Models are copied next to the exe.
REM ============================================================
setlocal
set ENV_NAME=subtitle

REM 切到项目根(本脚本在 packaging\,根是上一级),让 models\ dist\ 在根下解析
cd /d "%~dp0.."

echo [1/4] Installing PyInstaller ...
call conda run -n %ENV_NAME% pip install pyinstaller
if errorlevel 1 goto err

echo [2/4] Building exe from packaging\subtitle.spec ...
call conda run -n %ENV_NAME% pyinstaller --noconfirm packaging\subtitle.spec
if errorlevel 1 goto err

echo [3/4] Copying models into dist ...
if exist models (
    xcopy /E /I /Y models "dist\RealtimeSubtitle\models" >nul
) else (
    echo   WARNING: models\ not found, copy it into dist\RealtimeSubtitle\ manually.
)

echo [4/4] Done.
echo ============================================================
echo  Output: dist\RealtimeSubtitle\RealtimeSubtitle.exe
echo  Double-click to run. On first run, right-click the subtitle
echo  window -^> "set DeepSeek API Key" to enter your key (saved).
echo ============================================================
pause
goto end

:err
echo.
echo Build failed. Please send me the error above.
pause

:end
