"""LiveBabel 图形化主入口。

新手直接运行这个文件即可,弹出主页选「实时模式」或「离线模式」:
    python livebabel_gui.py

(老的命令行入口仍可用:app.py = 纯实时悬浮窗;tools/offline_subtitle.py = 命令行离线字幕。)
"""

from livebabel.launcher import main

if __name__ == "__main__":
    main()
