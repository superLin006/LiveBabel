"""字幕历史记录:每次运行把最终定稿字幕自动存成 .srt + .txt,方便事后查看。

  * .srt:带时间轴的标准双语字幕(原文一行、译文一行),可配视频或用播放器打开。
  * .txt:原文/译文对照纯文本,方便快速翻阅、复制。

只记录"最终(committed 且非 provisional)"字幕。临时译文不写入历史。
文件按启动时间命名,存到 history/ 目录。增量写入(每来一条就落盘),
程序中途退出也不丢内容。
"""

from __future__ import annotations

import os
import time
from datetime import datetime
from typing import Optional


def _fmt_ts(seconds: float) -> str:
    """秒 → SRT 时间戳 HH:MM:SS,mmm"""
    if seconds < 0:
        seconds = 0
    ms = int((seconds - int(seconds)) * 1000)
    s = int(seconds) % 60
    m = (int(seconds) // 60) % 60
    h = int(seconds) // 3600
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


class HistoryWriter:
    def __init__(self, save_srt: bool = True, save_txt: bool = True,
                 out_dir: Optional[str] = None) -> None:
        self.save_srt = save_srt
        self.save_txt = save_txt
        from livebabel.paths import HISTORY_DIR
        base = out_dir or HISTORY_DIR
        os.makedirs(base, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        self.srt_path = os.path.join(base, f"{stamp}.srt")
        self.txt_path = os.path.join(base, f"{stamp}.txt")
        self._index = 0
        self._t0 = time.time()      # 用挂钟时间近似字幕出现时刻

    def add(self, source: str, translation: Optional[str]) -> None:
        """记录一条最终字幕。"""
        source = (source or "").strip()
        if not source:
            return
        translation = (translation or "").strip()
        now = time.time() - self._t0
        self._index += 1

        if self.save_srt:
            # 每条给一个 ~3 秒的显示窗(仅供事后阅读,非精确对齐)
            start, end = _fmt_ts(now), _fmt_ts(now + 3.0)
            block = f"{self._index}\n{start} --> {end}\n{source}\n"
            if translation:
                block += f"{translation}\n"
            block += "\n"
            self._append(self.srt_path, block)

        if self.save_txt:
            line = f"{source}\n"
            if translation:
                line += f"  -> {translation}\n"
            self._append(self.txt_path, line)

    def update_last_translation(self, source: str, translation: str) -> None:
        """简化处理:历史只在拿到最终译文时调用 add(),不做回改。"""
        # 预留接口;当前流程在最终译文就绪后才写,无需回改。
        pass

    @staticmethod
    def _append(path: str, text: str) -> None:
        try:
            with open(path, "a", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
