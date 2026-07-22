"""朗读 / 离线转录模型的按需下载窗口。"""

from __future__ import annotations

from PySide6.QtCore import QObject, QThread, Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QPlainTextEdit,
    QVBoxLayout,
)

from livebabel import model_setup
from livebabel.ui.gui_common import CARD, SUBTEXT, apply_theme, app_icon, enable_dark_titlebar


class _ChatTtsWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            model_setup.download_chattts(
                log=self.log.emit,
                on_progress=lambda done, total: self.progress.emit(done, total),
                is_cancelled=lambda: self._cancel,
            )
            self.finished.emit(True, "")
        except model_setup.DownloadCancelled:
            self.finished.emit(False, "__cancelled__")
        except Exception as e:
            self.finished.emit(False, f"{type(e).__name__}: {e}")


class ChatTtsDownloadDialog(QDialog):
    """下载 ChatTTS 模型;成功时 exec() 返回 Accepted。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载朗读模型")
        self.setWindowIcon(app_icon())
        self.resize(560, 360)
        apply_theme(self)
        self._dark_done = False
        self._thread: QThread | None = None
        self._worker: _ChatTtsWorker | None = None
        self._done_ok = False
        self._build()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._dark_done:
            self._dark_done = True
            enable_dark_titlebar(self)
            self._start()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)

        title = QLabel("正在下载 ChatTTS 朗读模型")
        title.setObjectName("section")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        tip = QLabel(
            f"模型约 {model_setup.CHATTTS_APPROX_MB}MB，仅用于朗读功能，不影响实时识别和会议录音。\n"
            "下载完成后会自动安装到本地。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)

        self.status = QLabel("准备中…")
        self.status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(self.status)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(200)
        self.console.setStyleSheet(
            f"QPlainTextEdit {{ background: {CARD}; color: {SUBTEXT}; }}"
        )
        root.addWidget(self.console, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.clicked.connect(self._start)
        self.retry_btn.setVisible(False)
        buttons.addWidget(self.retry_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

    def _start(self) -> None:
        if self._thread is not None:
            return
        self.retry_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self._append("开始下载…")
        self._thread = QThread(self)
        self._worker = _ChatTtsWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _append(self, text: str) -> None:
        self.console.appendPlainText(text)

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"正在校验模型文件… {done}/{total}")

    def _on_finished(self, ok: bool, error_text: str) -> None:
        self._teardown_thread()
        if ok:
            self._done_ok = True
            self.bar.setRange(0, 1)
            self.bar.setValue(1)
            self.status.setText("✓ 朗读模型已安装")
            self.accept()
            return
        if error_text == "__cancelled__":
            self._append("已取消。")
            self.reject()
            return
        self.status.setText("✗ 下载失败，可重试")
        self._append(f"错误: {error_text}")
        self.retry_btn.setVisible(True)
        self.cancel_btn.setText("退出")

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _cancel_or_close(self) -> None:
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("正在取消…")
            self._worker.cancel()
        else:
            self.reject()

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._teardown_thread()
        super().closeEvent(event)

    def model_ready(self) -> bool:
        return self._done_ok or model_setup.chattts_ready()


# ---- whisper 下载窗(复用同一 UI 模式)----

class _WhisperWorker(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(bool, str)

    def __init__(self) -> None:
        super().__init__()
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:
        try:
            model_setup.download_whisper(
                log=self.log.emit,
                on_progress=lambda done, total: self.progress.emit(done, total),
                is_cancelled=lambda: self._cancel,
            )
            self.finished.emit(True, "")
        except model_setup.DownloadCancelled:
            self.finished.emit(False, "__cancelled__")
        except Exception as e:
            self.finished.emit(False, f"{type(e).__name__}: {e}")


class WhisperDownloadDialog(QDialog):
    """下载 whisper 模型;成功时 exec() 返回 Accepted。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("下载离线转录模型")
        self.setWindowIcon(app_icon())
        self.resize(560, 360)
        apply_theme(self)
        self._dark_done = False
        self._thread: QThread | None = None
        self._worker: _WhisperWorker | None = None
        self._done_ok = False
        self._build()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        if not self._dark_done:
            self._dark_done = True
            enable_dark_titlebar(self)
            self._start()

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 20)
        root.setSpacing(10)

        title = QLabel("正在下载 Whisper 离线转录模型")
        title.setObjectName("section")
        title.setStyleSheet("font-size: 17px; font-weight: 600;")
        tip = QLabel(
            f"模型约 {model_setup.WHISPER_APPROX_MB}MB，仅用于离线字幕功能。\n"
            "下载来源为 ModelScope，国内直连高速下载。"
        )
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(title)
        root.addWidget(tip)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        root.addWidget(self.bar)

        self.status = QLabel("准备中…")
        self.status.setStyleSheet(f"color: {SUBTEXT}; font-size: 12px;")
        root.addWidget(self.status)

        self.console = QPlainTextEdit()
        self.console.setReadOnly(True)
        self.console.setMaximumBlockCount(200)
        self.console.setStyleSheet(
            f"QPlainTextEdit {{ background: {CARD}; color: {SUBTEXT}; }}"
        )
        root.addWidget(self.console, 1)

        buttons = QHBoxLayout()
        buttons.addStretch(1)
        self.retry_btn = QPushButton("重试")
        self.retry_btn.clicked.connect(self._start)
        self.retry_btn.setVisible(False)
        buttons.addWidget(self.retry_btn)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel_or_close)
        buttons.addWidget(self.cancel_btn)
        root.addLayout(buttons)

    def _start(self) -> None:
        if self._thread is not None:
            return
        self.retry_btn.setVisible(False)
        self.cancel_btn.setEnabled(True)
        self.cancel_btn.setText("取消")
        self._append("开始下载…")
        self._thread = QThread(self)
        self._worker = _WhisperWorker()
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.log.connect(self._append)
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._thread.start()

    def _append(self, text: str) -> None:
        self.console.appendPlainText(text)

    def _on_progress(self, done: int, total: int) -> None:
        self.bar.setRange(0, total)
        self.bar.setValue(done)
        self.status.setText(f"正在校验模型文件… {done}/{total}")

    def _on_finished(self, ok: bool, error_text: str) -> None:
        self._teardown_thread()
        if ok:
            self._done_ok = True
            self.bar.setRange(0, 1)
            self.bar.setValue(1)
            self.status.setText("✓ 离线转录模型已安装")
            self.accept()
            return
        if error_text == "__cancelled__":
            self._append("已取消。")
            self.reject()
            return
        self.status.setText("✗ 下载失败，可重试")
        self._append(f"错误: {error_text}")
        self.retry_btn.setVisible(True)
        self.cancel_btn.setText("退出")

    def _teardown_thread(self) -> None:
        if self._thread is not None:
            self._thread.quit()
            self._thread.wait()
            self._thread = None
            self._worker = None

    def _cancel_or_close(self) -> None:
        if self._worker is not None:
            self.cancel_btn.setEnabled(False)
            self.cancel_btn.setText("正在取消…")
            self._worker.cancel()
        else:
            self.reject()

    def closeEvent(self, event) -> None:
        if self._worker is not None:
            self._worker.cancel()
        self._teardown_thread()
        super().closeEvent(event)

    def model_ready(self) -> bool:
        return self._done_ok or model_setup.whisper_ready()
