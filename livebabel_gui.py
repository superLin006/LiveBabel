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
    from livebabel.launcher import main as _main
    _main()


if __name__ == "__main__":
    main()
