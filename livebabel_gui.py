"""LiveBabel 图形化主入口。

新手直接运行这个文件即可,弹出主页选「实时模式」或「离线模式」:
    python livebabel_gui.py

(老的命令行入口仍可用:app.py = 纯实时悬浮窗;tools/offline_subtitle.py = 命令行离线字幕。)
"""

import os
import sys


def _setup_logfile() -> None:
    """无控制台的打包版:把 stdout/stderr 同时写到 history/livebabel.log,便于排查
    (实时/离线用 GPU 还是 CPU 的 [asr]/[设备] 日志都在里面)。源码运行有控制台则不改。"""
    try:
        from livebabel.paths import HISTORY_DIR
        os.makedirs(HISTORY_DIR, exist_ok=True)
        log_path = os.path.join(HISTORY_DIR, "livebabel.log")
        f = open(log_path, "a", encoding="utf-8", buffering=1)

        class _Tee:
            def __init__(self, *streams):
                self._streams = [s for s in streams if s is not None]
            def write(self, data):
                for s in self._streams:
                    try:
                        s.write(data)
                    except Exception:
                        pass
            def flush(self):
                for s in self._streams:
                    try:
                        s.flush()
                    except Exception:
                        pass

        # 打包版 sys.stdout/err 可能为 None;Tee 到文件(+ 控制台若有)
        sys.stdout = _Tee(sys.__stdout__, f)
        sys.stderr = _Tee(sys.__stderr__, f)
        import time
        f.write(f"\n===== LiveBabel 启动 {time.strftime('%Y-%m-%d %H:%M:%S')} =====\n")
    except Exception:
        pass


def main() -> None:
    _setup_logfile()
    # 尽早注册 cuBLAS/cuDNN DLL 搜索路径(在任何 sherpa/ctranslate2 加载 CUDA 之前),
    # 否则打包版里 sherpa 的 cuda provider 因找不到依赖而 "Failed to load shared library"。
    try:
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        ensure_cuda_dlls()
    except Exception:
        pass
    # 清理上次异常退出残留的会议临时音频文件
    try:
        from livebabel.meeting.pipeline import cleanup_stale_temp
        cleanup_stale_temp()
    except Exception:
        pass
    from livebabel.launcher import main as _main
    _main()


if __name__ == "__main__":
    main()
