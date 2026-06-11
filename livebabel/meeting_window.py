"""会议纪要页面:双流录制(我/远端)→ 实时显示带说话人转录 → 生成纪要 → 导出。

阶段2(本版):靠物理双流区分"我"(麦克风)和"远端"(系统声音),不引入 torch。
说话人可重命名。结束后用 DeepSeek 出结构化/简洁纪要,导出 Markdown/TXT。
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QObject, Signal, QTimer
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from livebabel.gui_common import apply_theme, app_icon, info, error, SUBTEXT
from livebabel.meeting.recorder import MeetingRecorder


class _Bridge(QObject):
    """后台线程 → GUI 线程的信号桥(转录刷新、纪要结果)。"""
    transcript_dirty = Signal()
    minutes_ok = Signal(str)
    minutes_fail = Signal(str)


class MeetingWindow(QWidget):
    def __init__(self, api_key: str = "", parent=None) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self.recorder = MeetingRecorder()
        self.pipeline = None
        self._minutes_md = ""
        self._busy = False

        self.setWindowTitle("LiveBabel · 会议纪要")
        self.resize(680, 680)
        self.setWindowIcon(app_icon())
        apply_theme(self)
        self._dark_titlebar_done = False

        self.bridge = _Bridge(self)
        self.bridge.transcript_dirty.connect(self._mark_dirty)
        self.bridge.minutes_ok.connect(self._on_minutes_ok)
        self.bridge.minutes_fail.connect(self._on_minutes_fail)
        # 转录刷新做节流,避免高频信号刷爆 UI
        self._dirty = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._maybe_refresh)
        self._refresh_timer.start()

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
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)

        title = QLabel("会议纪要")
        title.setObjectName("title")
        sub = QLabel("录制会议 → 区分发言方(我 / 远端)→ 一键生成纪要")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        # 音频源 + 录制控制
        ctl = QHBoxLayout()
        ctl.addWidget(QLabel("音频源"))
        self.src_combo = QComboBox()
        self.src_combo.addItems([
            "麦克风 + 系统声音(线上会议:我+远端)",
            "仅系统声音(只录远端/外放)",
            "仅麦克风(只录我/线下)",
        ])
        ctl.addWidget(self.src_combo, 1)
        refresh_btn = QPushButton("刷新设备")
        refresh_btn.clicked.connect(self._refresh_mic_state)
        ctl.addWidget(refresh_btn)
        self.rec_btn = QPushButton("开始录制")
        self.rec_btn.setObjectName("primary")
        self.rec_btn.clicked.connect(self._toggle_record)
        ctl.addWidget(self.rec_btn)
        root.addLayout(ctl)

        self.status = QLabel("就绪")
        self.status.setObjectName("subtitle")
        root.addWidget(self.status)

        # 实时转录
        root.addWidget(self._section("实时转录"))
        self.transcript_view = QTextEdit()
        self.transcript_view.setReadOnly(True)
        root.addWidget(self.transcript_view, 2)

        # 说话人重命名 + 生成纪要
        sp_row = QHBoxLayout()
        rename_btn = QPushButton("重命名说话人…")
        rename_btn.clicked.connect(self._rename_speaker)
        sp_row.addWidget(rename_btn)
        sp_row.addStretch(1)
        sp_row.addWidget(QLabel("纪要风格"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["结构化纪要", "简洁要点"])
        sp_row.addWidget(self.style_combo)
        self.minutes_btn = QPushButton("生成纪要")
        self.minutes_btn.setObjectName("primary")
        self.minutes_btn.clicked.connect(self._make_minutes)
        sp_row.addWidget(self.minutes_btn)
        root.addLayout(sp_row)

        # 纪要结果
        root.addWidget(self._section("纪要"))
        self.minutes_view = QTextEdit()
        self.minutes_view.setReadOnly(True)
        root.addWidget(self.minutes_view, 2)

        exp_row = QHBoxLayout()
        exp_row.addStretch(1)
        self.export_btn = QPushButton("导出(纪要+转录)…")
        self.export_btn.clicked.connect(self._export)
        self.export_btn.setEnabled(False)
        exp_row.addWidget(self.export_btn)
        root.addLayout(exp_row)

        self._refresh_mic_state()   # 根据有无麦克风调整可选项

    def _section(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setObjectName("section")
        return lab

    def _refresh_mic_state(self) -> None:
        """检测麦克风:有则启用含麦选项;无则禁用并默认「仅系统声音」+ 提示。"""
        from PySide6.QtCore import Qt as _Qt
        from livebabel.asr.audio_source_mic import MicrophoneSource
        has_mic = MicrophoneSource.has_microphone()
        model = self.src_combo.model()
        # 索引 0(我+远端)、2(仅麦克风)需要麦克风
        for i in (0, 2):
            item = model.item(i)
            if has_mic:
                item.setFlags(item.flags() | _Qt.ItemIsEnabled)
            else:
                item.setFlags(item.flags() & ~_Qt.ItemIsEnabled)
        if not has_mic:
            self.src_combo.setCurrentIndex(1)   # 仅系统声音
            self.status.setText("未检测到麦克风:只会记录远端/系统声音。"
                                "插好麦克风(或连蓝牙耳麦)后点「刷新设备」。")
        else:
            self.src_combo.setCurrentIndex(0)
            self.status.setText("✓ 已检测到麦克风。就绪")

    # ---- 录制 ----

    def _toggle_record(self) -> None:
        if self.pipeline and self.pipeline.running:
            self._stop_record()
        else:
            self._start_record()

    def _start_record(self) -> None:
        from livebabel.meeting.pipeline import MeetingPipeline
        from livebabel.asr.audio_source_mic import MicrophoneSource
        idx = self.src_combo.currentIndex()
        use_mic = idx in (0, 2)
        use_lb = idx in (0, 1)
        # 选了含麦但实际没麦:仅麦克风→拦下;我+远端→降级为仅远端并提示
        if use_mic and not MicrophoneSource.has_microphone():
            if not use_lb:
                error(self, "无麦克风",
                      "未检测到麦克风,无法「仅麦克风」录制。请插麦克风后点「刷新设备」。")
                return
            use_mic = False
            self.status.setText("未检测到麦克风,本次只录系统声音(远端)。")
        self.recorder.reset()
        self.transcript_view.clear()
        self.status.setText("正在加载模型并录制…(首次稍慢)")
        self.pipeline = MeetingPipeline(
            self.recorder, on_update=self.bridge.transcript_dirty.emit,
            use_mic=use_mic, use_loopback=use_lb)
        try:
            self.pipeline.start()
        except Exception as e:
            error(self, "录制启动失败",
                  f"{type(e).__name__}: {e}\n\n请确认已安装 pyaudiowpatch、麦克风可用。")
            self.pipeline = None
            self.status.setText("✗ 启动失败")
            return
        self.rec_btn.setText("停止录制")
        self.src_combo.setEnabled(False)
        self.status.setText("● 录制中…")

    def _stop_record(self) -> None:
        if self.pipeline:
            self.pipeline.stop()
        self.rec_btn.setText("开始录制")
        self.src_combo.setEnabled(True)
        self._refresh_transcript()
        self.status.setText("⏹ 已停止。可重命名说话人后生成纪要。")

    # ---- 转录刷新(节流)----

    def _mark_dirty(self) -> None:
        # transcript_dirty 信号只置脏标记,真正刷新由定时器合并(降频)
        self._dirty = True

    def _maybe_refresh(self) -> None:
        if self._dirty:
            self._dirty = False
            self._refresh_transcript()

    def _refresh_transcript(self) -> None:
        lines = self.recorder.as_transcript_lines()
        self.transcript_view.setPlainText("\n".join(lines))
        # 滚到底
        sb = self.transcript_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ---- 说话人重命名 ----

    def _rename_speaker(self) -> None:
        speakers = self.recorder.speakers()
        if not speakers:
            info(self, "暂无说话人", "还没有录到内容。")
            return
        spk, ok = QInputDialog.getItem(
            self, "重命名说话人", "选择要重命名的说话人:", speakers, 0, False)
        if not ok:
            return
        name, ok = QInputDialog.getText(
            self, "重命名说话人", f"把「{spk}」显示为:", QLineEdit.Normal, spk)
        if ok and name.strip():
            self.recorder.rename(spk, name.strip())
            self._refresh_transcript()

    # ---- 纪要 ----

    def _make_minutes(self) -> None:
        if self._busy:
            return
        lines = self.recorder.as_transcript_lines()
        if not lines:
            info(self, "暂无内容", "还没有录到可总结的会议内容。")
            return
        if not (self._api_key or "").strip():
            error(self, "未设置 API Key", "请先在主页设置 DeepSeek API Key。")
            return
        style = "structured" if self.style_combo.currentIndex() == 0 else "brief"
        api_key = self._api_key
        self._busy = True
        self.minutes_btn.setEnabled(False)
        self.minutes_btn.setText("生成中…")
        self.status.setText("正在生成纪要…(DeepSeek)")

        def work():
            try:
                from livebabel.meeting.minutes import make_minutes
                md = make_minutes(lines, style=style, api_key=api_key)
                self.bridge.minutes_ok.emit(md)
            except Exception as e:
                self.bridge.minutes_fail.emit(f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_minutes_ok(self, md: str) -> None:
        self._minutes_md = md
        self.minutes_view.setMarkdown(md)
        self.export_btn.setEnabled(True)
        self._reset_minutes_btn()
        self.status.setText("✓ 纪要已生成")

    def _on_minutes_fail(self, msg: str) -> None:
        self.minutes_view.setPlainText("生成失败:\n" + msg)
        self._reset_minutes_btn()
        self.status.setText("✗ 纪要生成失败")

    def _reset_minutes_btn(self) -> None:
        self._busy = False
        self.minutes_btn.setEnabled(True)
        self.minutes_btn.setText("生成纪要")

    # ---- 导出 ----

    def _export(self) -> None:
        lines = self.recorder.as_transcript_lines()
        default = f"会议纪要_{time.strftime('%Y%m%d_%H%M%S')}.md"
        try:
            from livebabel.paths import HISTORY_DIR
            os.makedirs(HISTORY_DIR, exist_ok=True)
            default = os.path.join(HISTORY_DIR, default)
        except Exception:
            pass
        path, _ = QFileDialog.getSaveFileName(
            self, "导出会议纪要", default, "Markdown (*.md);;文本 (*.txt)")
        if not path:
            return
        from livebabel.meeting.minutes import export_markdown, export_txt
        try:
            if path.lower().endswith(".txt"):
                export_txt(lines, self._minutes_md, path)
            else:
                export_markdown(lines, self._minutes_md, path)
            self.status.setText(f"✓ 已导出:{path}")
        except Exception as e:
            error(self, "导出失败", str(e))

    def set_api_key(self, key: str) -> None:
        self._api_key = key

    def closeEvent(self, e) -> None:
        if self.pipeline and self.pipeline.running:
            from livebabel.gui_common import confirm
            if not confirm(self, "正在录制", "会议还在录制中,确定关闭吗?"):
                e.ignore()
                return
            self.pipeline.stop()
        e.accept()
