"""离线模式页面:选视频 → 识别 → 翻译 → 生成 SRT/ASS →(可选)烧录,带进度与日志。

把耗时的流水线放后台 QThread(_Worker),通过 Qt 信号把进度/日志/完成回传 GUI 线程,
保证界面不卡死。复用 tools/offline_subtitle.py 背后的同一套 livebabel.offline 模块。
"""

from __future__ import annotations

import os

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from livebabel.gui_common import apply_theme, SUBTEXT

# 目标语种(下拉)和对应传给翻译器的中文名
TARGET_LANGS = ["中文", "英语", "日语", "韩语"]
# 源语言:界面友好名 → whisper 语言代码(None=自动)
SOURCE_LANGS = {
    "自动检测": None,
    "英语": "en",
    "中文": "zh",
    "日语": "ja",
    "韩语": "ko",
}


def _fmt(seconds: float) -> str:
    """把秒数格式化成 mm:ss(用于已用/剩余时间显示)。"""
    seconds = max(0, int(seconds))
    return f"{seconds // 60:d}:{seconds % 60:02d}"


class _Cancelled(Exception):
    """用户中途取消时抛出,run() 捕获后干净收尾。"""


class _Worker(QThread):
    """后台流水线:识别→翻译→写字幕→(可选)烧录。"""

    progress = Signal(int, str)     # 0-100, 阶段说明
    log = Signal(str)
    done = Signal(bool, str)        # 成功?, 结果说明/错误

    def __init__(self, opts: dict) -> None:
        super().__init__()
        self.o = opts
        self._cancel = False        # 协作式取消标志

    def cancel(self) -> None:
        self._cancel = True

    def _check_cancel(self) -> None:
        if self._cancel:
            raise _Cancelled()

    def run(self) -> None:
        try:
            self._run()
        except _Cancelled:
            self.done.emit(False, "已取消")
        except Exception as e:  # 任何异常都回传 GUI,不让线程静默死掉
            self.done.emit(False, f"{type(e).__name__}: {e}")

    def _run(self) -> None:
        import time
        from livebabel.offline.transcribe import transcribe
        from livebabel.offline.translate_batch import translate_sentences
        from livebabel.offline.subtitle_writer import write_srt, write_ass
        from livebabel.offline.burn import burn_subtitle

        video = self.o["video"]
        base = os.path.splitext(os.path.basename(video))[0]
        out_dir = self.o["out_dir"] or os.path.dirname(os.path.abspath(video))
        os.makedirs(out_dir, exist_ok=True)
        srt_path = os.path.join(out_dir, base + ".srt")
        ass_path = os.path.join(out_dir, base + ".ass")

        translate = self.o["translate"]
        # 进度分配:识别 0-60%,翻译 60-90%,写盘 90-92%,烧录 92-100%
        dev_name = "GPU" if self.o["device"] == "cuda" else "CPU"
        self.log.emit(f"[1/4] 识别中(faster-whisper {self.o['model']},{dev_name})…")

        t0 = time.time()

        def on_t(done, total):
            self._check_cancel()
            pct = int(60 * done / total) if total else 0
            el = time.time() - t0
            # 用已处理时长估算剩余(识别速度近似恒定)
            eta = (el / done * (total - done)) if done > 0.1 else 0
            self.progress.emit(
                pct, f"① 识别 {pct}%  ({done:.0f}/{total:.0f}s 音频 · "
                     f"已用 {_fmt(el)} · 约剩 {_fmt(eta)})")

        def _do_transcribe(device, compute_type):
            return transcribe(
                video, model_size=self.o["model"], language=self.o["source_lang"],
                device=device, compute_type=compute_type, on_progress=on_t,
            )

        try:
            sents = _do_transcribe(self.o["device"], self.o["compute_type"])
        except _Cancelled:
            raise
        except Exception as e:
            # GPU 缺 cuBLAS/cuDNN 等运行时库 → 打印诊断并自动回退 CPU,保证有结果
            msg = str(e)
            is_cuda_lib = self.o["device"] == "cuda" and (
                "cublas" in msg.lower() or "cudnn" in msg.lower()
                or "cuda" in msg.lower() or "library" in msg.lower())
            if not is_cuda_lib:
                raise
            from livebabel.offline.cuda_dll import diagnose
            self.log.emit("      [GPU 不可用] " + msg)
            self.log.emit("      GPU 诊断:\n" + diagnose())
            self.log.emit("      → 自动改用 CPU 重新识别(较慢)。要 GPU 请装 "
                          "nvidia-cublas-cu12 与 nvidia-cudnn-cu12==9.*")
            self.progress.emit(0, "GPU 不可用,改用 CPU 识别…")
            t0 = time.time()
            sents = _do_transcribe("cpu", "int8")
        self._check_cancel()
        self.log.emit(f"      识别完成,共 {len(sents)} 句,耗时 {_fmt(time.time()-t0)}。")

        if translate:
            self.log.emit(f"[2/4] 翻译成{self.o['target_lang']}(DeepSeek)…")
            t1 = time.time()

            def on_tr(done, tot):
                self._check_cancel()
                pct = 60 + int(30 * done / tot) if tot else 60
                el = time.time() - t1
                eta = (el / done * (tot - done)) if done > 0 else 0
                self.progress.emit(
                    pct, f"② 翻译 {done}/{tot} 句 · 已用 {_fmt(el)} · 约剩 {_fmt(eta)}")

            translate_sentences(
                sents, target_lang=self.o["target_lang"],
                api_key=self.o["api_key"], on_progress=on_tr,
            )
            self.log.emit(f"      翻译完成,耗时 {_fmt(time.time()-t1)}。")
        else:
            self.log.emit("[2/4] 跳过翻译(仅原文字幕)")

        self._check_cancel()
        bilingual = translate
        self.log.emit("[3/4] 生成字幕 SRT + ASS …")
        write_srt(sents, srt_path, bilingual=bilingual)
        write_ass(sents, ass_path, bilingual=bilingual)
        self.progress.emit(92, "③ 字幕已生成")
        self.log.emit(f"      {srt_path}")
        self.log.emit(f"      {ass_path}")

        result = f"字幕已保存到:\n{srt_path}\n{ass_path}"
        if self.o["burn"]:
            out_mp4 = os.path.join(out_dir, base + ".bilingual.mp4")
            self.log.emit(f"[4/4] 烧录字幕进视频 → {out_mp4} …(逐帧重编码,较慢,请耐心等待)")
            self.progress.emit(95, "④ 烧录字幕进视频中…(较慢)")
            burn_subtitle(video, ass_path, out_mp4)
            self.log.emit("      烧录完成。")
            result += f"\n带字幕视频:\n{out_mp4}"
        else:
            self.log.emit("[4/4] 未烧录(勾选「烧录进视频」可硬压字幕)")

        self.progress.emit(100, "完成")
        self.done.emit(True, result)


class OfflineWindow(QWidget):
    """离线双语字幕生成页面。独立窗口;关闭时若有任务在跑会提示。"""

    def __init__(self, api_key: str = "", parent=None) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self._worker: _Worker | None = None

        self.setWindowTitle("LiveBabel · 离线字幕")
        self.resize(620, 640)
        apply_theme(self)
        self._dark_titlebar_done = False
        self._build()

    def showEvent(self, e):
        super().showEvent(e)
        if not self._dark_titlebar_done:
            self._dark_titlebar_done = True
            from livebabel.gui_common import enable_dark_titlebar
            enable_dark_titlebar(self)

    # ---- UI ----

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(28, 24, 28, 24)
        root.setSpacing(14)

        title = QLabel("离线字幕生成")
        title.setObjectName("title")
        sub = QLabel("把视频转成双语字幕(SRT / ASS),可选直接烧录进视频")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)
        root.addSpacing(6)

        # 文件选择
        root.addWidget(self._section("视频文件"))
        file_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText("选择要生成字幕的视频 / 音频文件…")
        browse = QPushButton("浏览…")
        browse.clicked.connect(self._pick_file)
        file_row.addWidget(self.path_edit, 1)
        file_row.addWidget(browse)
        root.addLayout(file_row)

        # 语言选项网格
        root.addWidget(self._section("语言"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        grid.addWidget(QLabel("源语言"), 0, 0)
        self.source_combo = QComboBox()
        self.source_combo.addItems(SOURCE_LANGS.keys())
        grid.addWidget(self.source_combo, 0, 1)
        grid.addWidget(QLabel("翻译成"), 0, 2)
        self.target_combo = QComboBox()
        self.target_combo.addItems(TARGET_LANGS)
        grid.addWidget(self.target_combo, 0, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addLayout(grid)

        # 设备 / 精度(自动探测:有 GPU 默认走 GPU)
        root.addWidget(self._section("识别设备"))
        dev_row = QHBoxLayout()
        self.device_combo = QComboBox()
        self.device_combo.addItems(["CPU(通用,慢)", "GPU / CUDA(有 N 卡更快)"])
        from livebabel.offline.transcribe import detect_device
        dev, _ = detect_device()
        self._gpu_available = dev == "cuda"
        # 默认选中探测到的设备
        self.device_combo.setCurrentIndex(1 if self._gpu_available else 0)
        dev_row.addWidget(self.device_combo, 1)
        hint = QLabel("✓ 已检测到 GPU,默认加速" if self._gpu_available
                      else "未检测到 GPU,使用 CPU")
        hint.setObjectName("subtitle")
        dev_row.addWidget(hint)
        root.addLayout(dev_row)

        # 选项开关
        self.cb_translate = QCheckBox("翻译(关闭则只生成原文字幕)")
        self.cb_translate.setChecked(True)
        self.cb_burn = QCheckBox("烧录进视频(生成带字幕的新 .mp4,较慢)")
        root.addWidget(self.cb_translate)
        root.addWidget(self.cb_burn)

        # 开始 / 取消 按钮
        btn_row = QHBoxLayout()
        self.start_btn = QPushButton("开始生成")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._start)
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self._cancel)
        self.cancel_btn.setEnabled(False)
        btn_row.addWidget(self.start_btn, 1)
        btn_row.addWidget(self.cancel_btn)
        root.addLayout(btn_row)

        # 进度 + 状态(进度条显示百分比文字)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(True)
        self.progress.setFormat("%p%")
        self.status = QLabel("就绪")
        self.status.setObjectName("subtitle")
        self.status.setWordWrap(True)
        root.addWidget(self.progress)
        root.addWidget(self.status)

        # 日志
        self.logbox = QPlainTextEdit()
        self.logbox.setReadOnly(True)
        root.addWidget(self.logbox, 1)

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("section")
        return lab

    # ---- 交互 ----

    def _pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "选择视频 / 音频",
            self.path_edit.text() or os.path.expanduser("~"),
            "媒体文件 (*.mp4 *.mkv *.mov *.avi *.flv *.webm *.wav *.mp3 *.m4a *.flac);;所有文件 (*.*)",
        )
        if path:
            self.path_edit.setText(path)

    def _log(self, line: str) -> None:
        self.logbox.appendPlainText(line)

    def _start(self) -> None:
        if self._worker and self._worker.isRunning():
            return                           # 防重复点击
        video = self.path_edit.text().strip()
        if not video or not os.path.isfile(video):
            self.status.setText("⚠ 请先选择一个存在的视频 / 音频文件")
            return

        translate = self.cb_translate.isChecked()
        if translate and not (self._api_key or "").strip():
            # 要翻译却没 key:提示,但允许只出原文(避免每句都 [未设置 KEY])
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "未设置 API Key",
                "已勾选翻译,但还没设置 DeepSeek API Key。\n"
                "选「是」只生成原文字幕;选「否」我去主页设置 Key。",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                return
            translate = False
            self.cb_translate.setChecked(False)

        on_gpu = self.device_combo.currentIndex() == 1
        opts = {
            "video": video,
            "model": "large-v3-turbo",
            "source_lang": SOURCE_LANGS[self.source_combo.currentText()],
            "target_lang": self.target_combo.currentText(),
            "device": "cuda" if on_gpu else "cpu",
            "compute_type": "float16" if on_gpu else "int8",
            "translate": translate,
            "burn": self.cb_burn.isChecked(),
            "out_dir": None,
            "api_key": self._api_key,
        }

        self.logbox.clear()
        self.progress.setValue(0)
        self.status.setText("准备中…")
        self._set_running(True)

        self._worker = _Worker(opts)
        self._worker.progress.connect(self._on_progress)
        self._worker.log.connect(self._log)
        self._worker.done.connect(self._on_done)
        self._worker.start()

    def _cancel(self) -> None:
        if self._worker and self._worker.isRunning():
            self.cancel_btn.setEnabled(False)
            self.status.setText("正在取消…(等当前步骤结束)")
            self._worker.cancel()

    def _on_progress(self, pct: int, label: str) -> None:
        self.progress.setValue(pct)
        self.status.setText(label)

    def _on_done(self, ok: bool, msg: str) -> None:
        self._set_running(False)
        if ok:
            self.status.setText("✓ 完成")
            self._log("\n========\n" + msg)
        else:
            self.status.setText("✗ " + (msg if msg == "已取消" else "失败"))
            self._log("\n[结束] " + msg)
        # 不要立刻把 _worker 置 None:线程对象需活到 run() 真正退出,
        # 否则会触发 "QThread destroyed while running"。done 信号在 run() 末尾发出,
        # 此刻线程即将结束,wait() 几乎立即返回,安全回收。
        if self._worker:
            self._worker.wait(2000)
            self._worker = None

    def _set_running(self, running: bool) -> None:
        self.start_btn.setEnabled(not running)
        self.start_btn.setText("生成中…" if running else "开始生成")
        self.cancel_btn.setEnabled(running)
        for w in (self.path_edit, self.source_combo, self.target_combo,
                  self.device_combo, self.cb_translate, self.cb_burn):
            w.setEnabled(not running)

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def _stop_worker(self) -> None:
        """请求取消并等待后台线程结束(关窗/退出前调用,避免线程未结束被销毁)。"""
        if self._worker and self._worker.isRunning():
            self._worker.cancel()
            # 取消标志只在下一个回调处生效;烧录这种单次长调用可能要等它跑完
            self._worker.wait()
        self._worker = None

    def closeEvent(self, e) -> None:
        if self._worker and self._worker.isRunning():
            from PySide6.QtWidgets import QMessageBox
            r = QMessageBox.question(
                self, "仍在处理",
                "字幕生成尚未完成,确定要关闭吗?(将尝试取消)",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if r != QMessageBox.Yes:
                e.ignore()
                return
            self._stop_worker()             # 等线程干净退出,杜绝销毁崩溃
        e.accept()
