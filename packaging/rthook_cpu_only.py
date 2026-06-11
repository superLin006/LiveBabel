"""PyInstaller runtime hook(纯 CPU 版):进程一启动就设 LIVEBABEL_CPU_ONLY=1。

这样即使运行的机器有 N 卡,detect_provider/detect_device 也强制走 CPU,不会去尝试
加载本版本根本没打包的 GPU 库(避免报错/找不到 dll)。比靠用户设环境变量更可靠。
"""

import os

os.environ["LIVEBABEL_CPU_ONLY"] = "1"
