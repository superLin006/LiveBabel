"""历史记录回看:列出 history/ 下过往的字幕/会议记录,选中查看内容,可打开文件夹 / 删除。

实时模式(history_writer)与会议导出都把记录落到 history/,这里统一回看。
左侧按时间倒序列出会话(取同名 .txt/.srt/.md 归为一条),右侧预览选中项内容。
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QListWidget, QListWidgetItem,
    QTextEdit, QPushButton, QLabel, QSplitter, QWidget,
)

from livebabel.gui_common import apply_theme, enable_dark_titlebar, confirm, info


def _history_dir() -> str:
    from livebabel.paths import HISTORY_DIR
    os.makedirs(HISTORY_DIR, exist_ok=True)
    return HISTORY_DIR


def _scan():
    """扫描 history/,把同名不同后缀(stem 相同)的文件归为一条记录。

    返回 [(stem, {ext: path}, mtime)],按 mtime 倒序。只收常见文本类。
    """
    base = _history_dir()
    groups: dict = {}
    for fn in os.listdir(base):
        path = os.path.join(base, fn)
        if not os.path.isfile(path):
            continue
        stem, ext = os.path.splitext(fn)
        ext = ext.lower()
        if ext not in (".txt", ".srt", ".md"):
            continue          # 忽略 .log 等
        g = groups.setdefault(stem, {"files": {}, "mtime": 0.0})
        g["files"][ext] = path
        try:
            g["mtime"] = max(g["mtime"], os.path.getmtime(path))
        except OSError:
            pass
    out = [(stem, g["files"], g["mtime"]) for stem, g in groups.items()]
    out.sort(key=lambda x: x[2], reverse=True)
    return out


def _pretty_time(stem: str, mtime: float) -> str:
    """优先用文件名里的时间戳(history_writer 用 %Y-%m-%d_%H%M%S),否则用 mtime。"""
    for fmt in ("%Y-%m-%d_%H%M%S", "%Y%m%d_%H%M%S"):
        try:
            return datetime.strptime(stem.split(".")[0], fmt).strftime("%Y-%m-%d %H:%M")
        except ValueError:
            continue
    try:
        return datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError):
        return stem


def _open_in_explorer(path: str) -> None:
    """在系统文件管理器里定位/打开。"""
    try:
        if sys.platform.startswith("win"):
            if os.path.isfile(path):
                subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
            else:
                os.startfile(path)  # 目录
        elif sys.platform == "darwin":
            # 文件:open -R 在 Finder 里高亮定位;目录:直接 open 打开
            if os.path.isfile(path):
                subprocess.Popen(["open", "-R", path])
            else:
                subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path if os.path.isdir(path) else os.path.dirname(path)])
    except Exception:
        pass


class HistoryWindow(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("历史记录")
        self.resize(820, 540)
        apply_theme(self)
        enable_dark_titlebar(self)
        self._records = []           # [(stem, files, mtime)]
        self._build()
        self._reload()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 14)
        root.setSpacing(10)

        hint = QLabel("过往的实时字幕 / 会议记录(存于 history\\ 目录)")
        hint.setObjectName("subtitle")
        root.addWidget(hint)

        split = QSplitter(Qt.Horizontal)
        self.list = QListWidget()
        self.list.setMinimumWidth(240)
        self.list.currentRowChanged.connect(self._on_select)
        split.addWidget(self.list)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        split.addWidget(self.view)
        split.setStretchFactor(0, 0)
        split.setStretchFactor(1, 1)
        root.addWidget(split, 1)

        btns = QHBoxLayout()
        self.open_btn = QPushButton("打开所在文件夹")
        self.open_btn.clicked.connect(self._open_folder)
        self.del_btn = QPushButton("删除此记录")
        self.del_btn.clicked.connect(self._delete)
        refresh = QPushButton("刷新")
        refresh.clicked.connect(self._reload)
        btns.addWidget(self.open_btn)
        btns.addWidget(self.del_btn)
        btns.addStretch(1)
        btns.addWidget(refresh)
        root.addLayout(btns)

    def _reload(self) -> None:
        self._records = _scan()
        self.list.clear()
        for stem, files, mtime in self._records:
            exts = "/".join(sorted(e.lstrip(".") for e in files))
            item = QListWidgetItem(f"{_pretty_time(stem, mtime)}   ({exts})")
            self.list.addItem(item)
        if self._records:
            self.list.setCurrentRow(0)
        else:
            self.view.setPlainText("暂无历史记录。\n\n实时模式运行后会自动在 history\\ 生成字幕记录。")
        has = bool(self._records)
        self.open_btn.setEnabled(has)
        self.del_btn.setEnabled(has)

    def _on_select(self, row: int) -> None:
        if not (0 <= row < len(self._records)):
            self.view.clear()
            return
        _, files, _ = self._records[row]
        # 优先显示 .txt(对照纯文本最易读),其次 .md,再 .srt
        path = files.get(".txt") or files.get(".md") or files.get(".srt")
        try:
            with open(path, "r", encoding="utf-8") as f:
                self.view.setPlainText(f.read())
        except Exception as e:
            self.view.setPlainText(f"读取失败:{e}")

    def _open_folder(self) -> None:
        row = self.list.currentRow()
        if 0 <= row < len(self._records):
            _, files, _ = self._records[row]
            _open_in_explorer(next(iter(files.values())))
        else:
            _open_in_explorer(_history_dir())

    def _delete(self) -> None:
        row = self.list.currentRow()
        if not (0 <= row < len(self._records)):
            return
        stem, files, _ = self._records[row]
        if not confirm(self, "删除记录", f"确定删除「{_pretty_time(stem, 0)}」的所有文件?\n此操作不可恢复。"):
            return
        for p in files.values():
            try:
                os.remove(p)
            except OSError:
                pass
        self._reload()
