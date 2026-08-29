@echo off
chcp 65001 >nul
REM Build LiveBabel-CPU.exe with no NVIDIA runtime DLLs.
setlocal
set ENV_NAME=subtitle-new
set LIVEBABEL_BUILD=cpu
cd /d "%~dp0.."
call conda run -n %ENV_NAME% pip install pyinstaller
if errorlevel 1 goto err
call conda run -n %ENV_NAME% pyinstaller --noconfirm packaging\subtitle.spec
if errorlevel 1 goto err
echo Output: dist\LiveBabel-CPU\LiveBabel-CPU.exe
echo Before release, copy only exe + _internal; models/settings/history are not shipped.
pause
goto end
:err
echo Build failed.
pause
:end
