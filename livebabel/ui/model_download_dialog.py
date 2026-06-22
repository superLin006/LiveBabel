"""首次启动:语音模型下载进度窗。

检测到 models/ 缺核心模型时弹出。在后台线程下载(带镜像回退 + 断点续传),
进度条 + 日志实时显示。下完返回 Accepted;用户取消 / 关窗返回 Rejected。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from livebabel.ui.gui_common import (
    apply_theme, app_icon, enable_dark_titlebar, CARD, SUBTEXT,
)
from livebabel import model_setup


class _Worker(QObject):
    log = Signal(str)
    # idx, count, downloaded_bytes, total_bytes
    progress = Signal(int, int, int, int)
    finished = Signal(bool, str)   # ok, error_message

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            model_setup.download_missing(
                log=self.log.emit,
                on_progress=lambda i, n, d, t: self.progress.emit(i, n, d, t),
                is_cancelled=lambda: self._cancel,
            )
            self.finished.emit(True, "")
        except model_setup.DownloadCancelled:
            self.finished.emit(False, "__cancelled__")
        except Exception as e:  # noqa: BLE001 - 任何失败都要回到 UI 报告
            self.finished.emit(False, f"{type(e).__name__}: {e}")


class ModelDownloadDialog(QDialog):
    """模态下载窗。exec() 返回 QDialog.Accepted 表示模型已就绪。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("首次使用 · 下载语音模型")
        self.setWindowIcon(app_icon())
        self.resize(560, 420)
        apply_theme(self)
        self._dark_done = False
        self._thread: QThread | None = None
        self._worker: _Worker | None = None
        self._done_ok = False
        self._build()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dark_done:
            self._dark_done = True
            enable_dark_titlebar(self)
            # 窗口一出现就自动开始下载
            self._start()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)

        title = QLabel("正在下载语音识别模型")
        title.setObjectName("section")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        total_mb = sum(m.approx_mb for m in model_setup.missing_items())
        tip = QLabel(
            f"首次使用需下载约 {total_mb}MB 模型(仅此一次,之后开箱即用)。\n"
            "下载来源为 GitHub,已自动启用国内镜像加速。请保持联网。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(True)
        root.addWidget(self.bar)

        self.status = QLabel("准备中…")
        self.status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(self.status)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(500)
        # 浅色控制台:用次要文字色,弱化存在感(全局 QSS 已给圆角/边框)
        self.console.setStyleSheet(
            f"QPlainTextEdit {{ background: {CARD}; color: {SUBTEXT}; }}"
        )
        root.addWidget(self.console, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.clicked.connect(self._start)
        self.retry_btn.setVisible(False)
        btn_row.addWidget(self.retry_btn)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

    # ---- 下载控制 ----

    def _start(self) -> None:
        if self._thread is not None:
            return
        self.retry_btn.setVisible(False)
        self.cancel_btn.setText("取消")
        self.cancel_btn.setEnabled(True)
        self._append("开始下载…")

        self._thread = QThread(self)
        self._worker = _Worker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _append(self, line: str) -> None:
        self.console.appendPlainText(line)

    def _on_progress(self, idx: int, count: int, downloaded: int, total: int) -> None:
        if total > 0:
            pct = int(downloaded * 100 / total)
            self.bar.setRange(0, 100)
            self.bar.setValue(pct)
            self.status.setText(
                f"第 {idx}/{count} 个 — {downloaded/1048576:.1f} / {total/1048576:.1f} MB"
            )
        else:
            # 未知大小:走"忙碌"动画
            self.bar.setRange(0, 0)
            self.status.setText(f"第 {idx}/{count} 个 — 已下载 {downloaded/1048576:.1f} MB")

    def _on_finished(self, ok: bool, err: str) -> None:
        self._teardown_thread()
        if ok:
            self._done_ok = True
            self.bar.setRange(0, 100)
            self.bar.setValue(100)
            self.status.setText("✓ 全部完成,正在进入主页…")
            self.accept()
            return
        if err == "__cancelled__":
            self._append("已取消。")
            self.reject()
            return
        # 失败:停在窗口,允许重试(已下部分会断点续传)
        self.bar.setRange(0, 100)
        self.status.setText("✗ 下载失败,可点「重试」继续(已下载的部分会续传)")
        self._append(f"错误:{err}")
        self.retry_btn.setVisible(True)
        self.cancel_btn.setText("退出")

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _on_cancel_clicked(self) -> None:
        if self._worker is not None and self._thread is not None:
            # 正在下:请求取消,等 finished 信号
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("正在取消…")
            self._worker.cancel()
        else:
            # 不在下(失败态):直接退出
            self.reject()

    def closeEvent(self, e) -> None:
        # 关窗 = 取消;先停线程再关,避免 QThread destroyed while running
        if self._worker is not None:
            self._worker.cancel()
        self._teardown_thread()
        super().closeEvent(e)

    def models_ready(self) -> bool:
        return self._done_ok or model_setup.models_ready()
