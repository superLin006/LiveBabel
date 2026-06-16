"""会议纪要页面:双流录制(我/远端)→ 实时显示带说话人转录 → 生成纪要 → 导出。

阶段2(本版):靠物理双流区分"我"(麦克风)和"远端"(系统声音),不引入 torch。
说话人可重命名。结束后用 DeepSeek 出结构化/简洁纪要,导出 Markdown/TXT。
"""

from __future__ import annotations

import os
import threading
import time

from PySide6.QtCore import Qt, QObject, Signal, QTimer, QSize
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QPushButton, QTextEdit, QVBoxLayout, QWidget,
)

from livebabel.gui_common import (
    apply_theme, app_icon, info, error, SUBTEXT, ACCENT, ACCENT_DEEP, CARD, CARD_HOVER, BORDER,
)
from livebabel.meeting.recorder import MeetingRecorder


# 给不同说话人分配稳定的气泡底色(我=青,远端/其他循环取色)
_SPK_COLORS = ["#2C5C68", "#3A3D48", "#4A3A5A", "#3A4A38", "#5A4A38"]


def _bubble_widget(speaker: str, ts: str, text: str, is_me: bool, draft: bool = False) -> QWidget:
    """一条聊天气泡:我→右侧青色,其他→左侧灰色,顶部小字显示 说话人·时间。

    draft=True 为未定稿草稿:气泡半透明、文字偏暗、末尾加"…",定稿后会被正式气泡替换。
    """
    row = QWidget()
    h = QHBoxLayout(row)
    h.setContentsMargins(8, 3, 8, 3)

    bubble = QFrame()
    bubble.setObjectName("bubble")
    if draft:
        # 草稿:统一暗灰半透明,区别于定稿
        color = "#33363F"
        fg = "#AEB4C0"
        sub = SUBTEXT
    else:
        color = ACCENT_DEEP if is_me else CARD_HOVER
        fg = "#08222A" if is_me else "#E8E9ED"
        sub = "#0A2A33" if is_me else SUBTEXT
    bubble.setStyleSheet(
        f"#bubble{{background:{color};border-radius:10px;}}"
    )
    bv = QVBoxLayout(bubble)
    bv.setContentsMargins(12, 7, 12, 8)
    bv.setSpacing(2)
    head = QLabel(f"{speaker} · {ts}" + ("  ✎" if draft else ""))
    head.setStyleSheet(f"color:{sub};font-size:11px;background:transparent;")
    body = QLabel(text + (" …" if draft else ""))
    body.setWordWrap(True)
    body.setStyleSheet(f"color:{fg};font-size:13px;background:transparent;"
                       + ("font-style:italic;" if draft else ""))
    body.setMaximumWidth(420)
    bv.addWidget(head)
    bv.addWidget(body)

    if is_me:
        h.addStretch(1)
        h.addWidget(bubble)
    else:
        h.addWidget(bubble)
        h.addStretch(1)
    return row


class _Bridge(QObject):
    """后台线程 → GUI 线程的信号桥(转录刷新、纪要结果)。"""
    transcript_dirty = Signal()
    minutes_ok = Signal(str)
    minutes_fail = Signal(str)
    diar_ok = Signal(int)       # 细分出的发言人数
    diar_fail = Signal(str)
    diar_progress = Signal(int) # 0-100
    diar_status = Signal(str)   # 阶段文字(如 AI 校正中)


class MeetingWindow(QWidget):
    def __init__(self, api_key: str = "", parent=None) -> None:
        super().__init__(parent)
        self._api_key = api_key
        self.recorder = MeetingRecorder()
        self.pipeline = None
        self._minutes_md = ""
        self._busy = False
        self._diar_centroids = {}        # 最近一次区分说话人的 {聚类号: 质心},供声纹库登记
        self._recognized_labels = set()  # 被声纹库自动认出的标签

        self.setWindowTitle("LiveBabel · 会议纪要")
        self.resize(680, 680)
        self.setWindowIcon(app_icon())
        apply_theme(self)
        self._dark_titlebar_done = False

        self.bridge = _Bridge(self)
        self.bridge.transcript_dirty.connect(self._mark_dirty)
        self.bridge.minutes_ok.connect(self._on_minutes_ok)
        self.bridge.minutes_fail.connect(self._on_minutes_fail)
        self.bridge.diar_ok.connect(self._on_diar_ok)
        self.bridge.diar_fail.connect(self._on_diar_fail)
        self.bridge.diar_progress.connect(
            lambda p: self.status.setText(f"正在分析声纹区分说话人… {p}%"))
        self.bridge.diar_status.connect(lambda s: self.status.setText(s))
        # 转录刷新做节流,避免高频信号刷爆 UI
        self._dirty = False
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setInterval(400)
        self._refresh_timer.timeout.connect(self._maybe_refresh)
        self._refresh_timer.start()
        # 录制计时器(红点闪烁 + 时长)
        self._rec_timer = QTimer(self)
        self._rec_timer.setInterval(1000)
        self._rec_timer.timeout.connect(self._tick_record)
        self._rec_t0 = 0.0

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

        # 醒目状态条:录制中显示红点 + 计时
        st_row = QHBoxLayout()
        self.rec_dot = QLabel("●")
        self.rec_dot.setStyleSheet("color:#FF5C5C;font-size:13px;")
        self.rec_dot.hide()
        self.status = QLabel("就绪")
        self.status.setObjectName("subtitle")
        st_row.addWidget(self.rec_dot)
        st_row.addWidget(self.status, 1)
        root.addLayout(st_row)

        # 实时转录(聊天气泡)
        head_row = QHBoxLayout()
        head_row.addWidget(self._section("实时转录"))
        head_row.addStretch(1)
        # 会后说话人分离:把"远端"细分成多个发言人
        head_row.addWidget(QLabel("远端人数"))
        self.spk_count = QComboBox()
        self.spk_count.addItems(["2", "3", "4", "5", "6", "自动"])  # 默认 2 人,指定最准
        self.spk_count.setCurrentIndex(0)
        self.spk_count.setToolTip("已知远端有几个人就选几人(最准);「自动」效果不稳定")
        head_row.addWidget(self.spk_count)
        self.diar_btn = QPushButton("区分说话人")
        self.diar_btn.clicked.connect(self._diarize)
        head_row.addWidget(self.diar_btn)
        self.rename_btn = QPushButton("重命名…")
        self.rename_btn.clicked.connect(self._rename_speaker)
        head_row.addWidget(self.rename_btn)
        root.addLayout(head_row)

        self.transcript_list = QListWidget()
        self.transcript_list.setObjectName("transcript")
        self.transcript_list.setStyleSheet(
            f"#transcript{{background:{CARD};border:1px solid {BORDER};"
            f"border-radius:8px;}}#transcript::item{{border:none;}}"
        )
        self.transcript_list.setSpacing(0)
        self.transcript_list.setSelectionMode(QListWidget.NoSelection)
        self.transcript_list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        root.addWidget(self.transcript_list, 3)
        self._bubble_count = 0   # 已渲染的定稿气泡数(增量刷新用)
        self._draft_items = 0    # 当前末尾的草稿气泡数

        # 纪要:标题行带风格选择 + 生成按钮
        m_head = QHBoxLayout()
        m_head.addWidget(self._section("纪要"))
        m_head.addStretch(1)
        self.style_combo = QComboBox()
        self.style_combo.addItems(["结构化纪要", "简洁要点"])
        m_head.addWidget(self.style_combo)
        self.minutes_btn = QPushButton("生成纪要")
        self.minutes_btn.setObjectName("primary")
        self.minutes_btn.clicked.connect(self._make_minutes)
        m_head.addWidget(self.minutes_btn)
        root.addLayout(m_head)

        self.minutes_view = QTextEdit()
        self.minutes_view.setReadOnly(True)
        self.minutes_view.setPlaceholderText("录制结束后,点「生成纪要」由 DeepSeek 总结本场会议…")
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
        from livebabel.meeting import platform_audio
        has_mic = platform_audio.has_microphone()
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
        from livebabel.meeting import platform_audio
        idx = self.src_combo.currentIndex()
        use_mic = idx in (0, 2)
        use_lb = idx in (0, 1)
        # 选了含麦但实际没麦:仅麦克风→拦下;我+远端→降级为仅远端并提示
        if use_mic and not platform_audio.has_microphone():
            if not use_lb:
                error(self, "无麦克风",
                      "未检测到麦克风,无法「仅麦克风」录制。请插麦克风后点「刷新设备」。")
                return
            use_mic = False
            self.status.setText("未检测到麦克风,本次只录系统声音(远端)。")
        # 需要系统声音但采集不可用(macOS 未装 BlackHole):提前给清晰引导,别等启动失败
        if use_lb and not platform_audio.has_system_audio():
            if not use_mic:
                error(self, "无法录系统声音", platform_audio.system_audio_hint())
                return
            use_lb = False
            self.status.setText("无法录系统声音,本次只录麦克风(我)。")
        # 清掉上一场的临时音频文件,避免泄漏
        if self.pipeline is not None:
            try:
                self.pipeline.cleanup()
            except Exception:
                pass
        self.recorder.reset()
        self.transcript_list.clear()
        self._bubble_count = 0
        self._draft_items = 0
        self.status.setText("正在加载模型并录制…(首次稍慢)")
        from livebabel.meeting import platform_audio
        self.pipeline = platform_audio.make_pipeline(
            self.recorder, on_update=self.bridge.transcript_dirty.emit,
            use_mic=use_mic, use_loopback=use_lb)
        try:
            self.pipeline.start()
        except Exception as e:
            dep = "BlackHole / 麦克风" if platform_audio.IS_MAC else "pyaudiowpatch、麦克风"
            error(self, "录制启动失败",
                  f"{type(e).__name__}: {e}\n\n请确认已安装 {dep} 可用。")
            self.pipeline = None
            self.status.setText("✗ 启动失败")
            return
        self.rec_btn.setText("停止录制")
        self.src_combo.setEnabled(False)
        self._rec_t0 = time.time()
        self.rec_dot.show()
        self._rec_timer.start()
        self._tick_record()

    def _stop_record(self) -> None:
        if self.pipeline:
            self.pipeline.stop()
        self.rec_btn.setText("开始录制")
        self.src_combo.setEnabled(True)
        self._rec_timer.stop()
        self.rec_dot.hide()
        self._refresh_transcript()
        self.status.setText("⏹ 已停止录制,可重命名说话人后生成纪要。")

    def _tick_record(self) -> None:
        # 录制计时 + 红点闪烁
        el = int(time.time() - getattr(self, "_rec_t0", time.time()))
        self.rec_dot.setVisible(not self.rec_dot.isVisible() or True)  # 保持显示
        vis = (el % 2 == 0)
        self.rec_dot.setStyleSheet(
            f"color:{'#FF5C5C' if vis else '#7A2A2A'};font-size:13px;")
        self.status.setText(f"录制中  {el // 60:02d}:{el % 60:02d}")

    # ---- 转录刷新(节流)----

    def _mark_dirty(self) -> None:
        # transcript_dirty 信号只置脏标记,真正刷新由定时器合并(降频)
        self._dirty = True

    def _maybe_refresh(self) -> None:
        if self._dirty:
            self._dirty = False
            self._refresh_transcript()

    def _refresh_transcript(self) -> None:
        """定稿气泡增量追加(稳定不闪);草稿气泡每次刷新重建并置于末尾(浅色,会变)。"""
        lst = self.transcript_list
        # 1) 先移除上次的草稿气泡(它们在列表尾部)
        for _ in range(getattr(self, "_draft_items", 0)):
            it = lst.takeItem(lst.count() - 1)
            del it
        self._draft_items = 0

        # 2) 增量追加新定稿
        segs = self.recorder.segments()
        for u in segs[self._bubble_count:]:
            w = _bubble_widget(u.speaker, MeetingRecorder.fmt_ts(u.t), u.text, u.is_me)
            item = QListWidgetItem(lst)
            item.setSizeHint(w.sizeHint())
            lst.addItem(item)
            lst.setItemWidget(item, w)
        self._bubble_count = len(segs)

        # 3) 末尾追加当前草稿(每路至多一条,浅色)
        for u in self.recorder.drafts():
            w = _bubble_widget(u.speaker, MeetingRecorder.fmt_ts(u.t), u.text, u.is_me, draft=True)
            item = QListWidgetItem(lst)
            item.setSizeHint(w.sizeHint())
            lst.addItem(item)
            lst.setItemWidget(item, w)
            self._draft_items += 1

        lst.scrollToBottom()

    # ---- 会后说话人分离(声纹)----

    def _diarize(self) -> None:
        if self._busy:
            return
        if self.pipeline and self.pipeline.running:
            info(self, "请先停止录制", "区分说话人需在录制结束后进行。")
            return
        from livebabel.meeting import diarize as diar
        if not diar.available():
            error(self, "缺少声纹模型",
                  "未找到说话人分离模型(segmentation / embedding)。\n"
                  "请运行 download_models 下载,或放到 models\\ 目录。")
            return
        audio = self.pipeline.get_audio("远端") if self.pipeline else None
        if audio is None or len(audio) < 16000:
            info(self, "无可分析音频", "没有录到足够的「远端」音频用于区分说话人。")
            return
        sel = self.spk_count.currentText()
        num = -1 if sel == "自动" else int(sel)

        self._busy = True
        self.diar_btn.setEnabled(False)
        self.diar_btn.setText("分析中…")
        self.status.setText("正在分析声纹区分说话人…(整段处理,较慢请稍候)")

        api_key = self._api_key
        def work():
            try:
                def prog(done, total):
                    if total:
                        self.bridge.diar_progress.emit(int(100 * done / total))
                segs, centroids = diar.diarize(audio, num_speakers=num,
                                               on_progress=prog, return_centroids=True)
                n = self.recorder.refine_speaker("远端", segs)
                # 声纹库自动认人:每个聚类质心比库,够像(高阈值)就标真名。
                # 在 LLM 之前写,且声纹认出的优先(真实身份 > LLM 猜名)。
                self._diar_centroids = centroids        # 存给"存入声纹库"用
                recognized = set()
                try:
                    from livebabel.meeting import voiceprint as vpmod
                    sid2label = self.recorder.last_diar_labels()
                    for sid, vec in centroids.items():
                        m = vpmod.match(vec)
                        if m and sid in sid2label:
                            self.recorder.rename(sid2label[sid], m[0])
                            recognized.add(sid2label[sid])
                except Exception:
                    pass
                self._recognized_labels = recognized
                # 声纹分完,若多于 1 人且有 key,自动用 LLM 增强:起名/纠错/轻改归属
                if n > 1 and (api_key or "").strip():
                    self.bridge.diar_progress.emit(100)
                    self.bridge.diar_status.emit("正在用 AI 优化(起名/纠错)…")
                    try:
                        self.recorder.apply_llm_correction(
                            api_key=api_key, protect=recognized)
                    except Exception:
                        pass
                self.bridge.diar_ok.emit(n)
            except Exception as e:
                self.bridge.diar_fail.emit(f"{type(e).__name__}: {e}")

        threading.Thread(target=work, daemon=True).start()

    def _on_diar_ok(self, n: int) -> None:
        self._busy = False
        self.diar_btn.setEnabled(True)
        self.diar_btn.setText("区分说话人")
        # 重命名影响气泡 → 全量重建
        self.transcript_list.clear()
        self._bubble_count = 0
        self._draft_items = 0
        self._refresh_transcript()
        rec_n = len(getattr(self, "_recognized_labels", set()))
        if n > 1:
            tip = "(声纹+AI校正,可再重命名)" if (self._api_key or "").strip() else "(可再重命名)"
            msg = f"✓ 远端已区分为 {n} 位发言人{tip}"
            if rec_n:
                msg += f";声纹库自动认出 {rec_n} 人"
            self.status.setText(msg)
        else:
            self.status.setText("✓ 分析完成:远端只识别到 1 位发言人")

    def _on_diar_fail(self, msg: str) -> None:
        self._busy = False
        self.diar_btn.setEnabled(True)
        self.diar_btn.setText("区分说话人")
        self.status.setText("✗ 区分说话人失败")
        error(self, "区分说话人失败", msg)

    # ---- 说话人重命名 ----

    def _rename_speaker(self) -> None:
        choices = self.recorder.speaker_choices()   # [(原始标签, 当前显示名)]
        if not choices:
            info(self, "暂无说话人", "还没有录到内容。")
            return
        # 下拉显示【当前名】(含 AI 起的名),用户才能对上气泡;内部记原始标签做 rename key
        labels = [disp for _, disp in choices]
        disp, ok = QInputDialog.getItem(
            self, "重命名说话人", "选择要重命名的说话人:", labels, 0, False)
        if not ok:
            return
        original = next((orig for orig, d in choices if d == disp), disp)
        name, ok = QInputDialog.getText(
            self, "重命名说话人", f"把「{disp}」显示为:", QLineEdit.Normal, disp)
        if ok and name.strip():
            name = name.strip()
            self.recorder.rename(original, name)
            # 重命名影响已有气泡 → 全量重建
            self.transcript_list.clear()
            self._bubble_count = 0
            self._draft_items = 0
            self._refresh_transcript()
            self._maybe_enroll_voiceprint(original, name)

    def _maybe_enroll_voiceprint(self, label: str, name: str) -> None:
        """若该标签对应一个声纹质心(刚做过区分说话人),问是否把它存入声纹库,
        以后开会自动认出这个人。"""
        centroids = getattr(self, "_diar_centroids", None)
        if not centroids:
            return
        # 标签 "远端-发言人N" → 反查聚类号 sid → 质心
        sid2label = self.recorder.last_diar_labels()
        sid = next((s for s, lab in sid2label.items() if lab == label), None)
        if sid is None or sid not in centroids:
            return
        from livebabel.gui_common import confirm
        if confirm(self, "存入声纹库",
                   f"把「{name}」的声纹记住吗?\n以后开会会自动认出 ta,不用再手动改名。"):
            try:
                from livebabel.meeting import voiceprint as vpmod
                vpmod.enroll(name, centroids[sid])
                self.status.setText(f"✓ 已把「{name}」存入声纹库")
            except Exception as e:
                error(self, "存入失败", str(e))

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
        # 清理临时音频文件
        if self.pipeline is not None:
            try:
                self.pipeline.cleanup()
            except Exception:
                pass
        e.accept()
