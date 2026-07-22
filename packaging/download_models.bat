@echo off
chcp 65001 >nul
REM ============================================================
REM  下载 LiveBabel 核心模型（从 ModelScope 统一仓库）
REM  按需下载:已存在的文件自动跳过,支持断点续传。
REM  模型仓库: https://modelscope.cn/models/XHxiehuan/LiveBabel-Models
REM ============================================================
cd /d "%~dp0.."

echo LiveBabel 模型下载工具(从 ModelScope)
echo 仓库: https://modelscope.cn/models/XHxiehuan/LiveBabel-Models
echo.

REM 检查 Python
where python >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 Python,请先安装 Python 3.10+。
    pause
    exit /b 1
)

REM 运行下载逻辑（和程序启动时用的是同一套代码）
python -c "from livebabel.model_setup import download_missing, missing_items; \
items = missing_items(); \
if items: \
    print(f'缺失 {len(items)} 个模型, 开始下载…\n'); \
    def log(msg): print(msg); \
    def progress(i, n, d, t): pass; \
    def cancelled(): return False; \
    download_missing(log, progress, cancelled); \
else: \
    print('所有模型已就绪, 无需下载。')"

echo.
pause
exit /b 0
