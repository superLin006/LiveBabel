"""听写的系统托盘控制器:开关听写、切注入方式、退出。

持有 DictationService + DictationOverlay,把 service 的信号连到浮窗,
并提供托盘菜单。listen 形态:启用后常驻后台,全局热键随时可用。
"""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from livebabel.dictation.service import DictationService
from livebabel.ui.dictation_overlay import DictationOverlay
from livebabel.ui.gui_common import app_icon
from livebabel.ui.overlay import load_settings, save_settings


class DictationTray:
    """非 QWidget 的轻量控制器,内部建 QSystemTrayIcon。"""

    def __init__(self, parent=None, on_shutdown=None, api_key: str = "") -> None:
        self._settings = load_settings()
        self._service = DictationService(
            api_key=api_key,
            ai_correction=bool(self._settings.get("dictation_ai_correction", False)),
        )
        self._overlay = DictationOverlay()
        self._on_shutdown = on_shutdown   # 关闭时回调(launcher 同步卡片角标)

        self._tray = QSystemTrayIcon(app_icon(), parent)
        self._tray.setToolTip("LiveBabel 语音输入")
        self._build_menu()

        # service 信号 → 主线程更新浮窗
        self._service.started.connect(self._overlay.begin_session)
        self._service.finalizing.connect(self._overlay.show_finalizing)
        self._service.draftChanged.connect(self._overlay.show_draft)
        self._service.finalText.connect(self._overlay.end_session)
        self._service.error.connect(self._on_error)

    # ---------- 菜单 ----------

    def _build_menu(self) -> None:
        menu = QMenu()
        self._act_enable = menu.addAction("启用语音输入")
        self._act_enable.setCheckable(True)
        self._act_enable.toggled.connect(self._toggle_enable)

        menu.addSeparator()
        inj = menu.addMenu("注入方式")
        self._act_paste = inj.addAction("剪贴板粘贴(推荐)")
        self._act_type = inj.addAction("逐字键入")
        for a in (self._act_paste, self._act_type):
            a.setCheckable(True)
        self._act_paste.setChecked(True)
        self._act_paste.triggered.connect(lambda: self._set_mode("paste"))
        self._act_type.triggered.connect(lambda: self._set_mode("type"))

        menu.addSeparator()
        self._act_correct = menu.addAction("AI 矫正口语和错字")
        self._act_correct.setCheckable(True)
        self._act_correct.setChecked(self._service.ai_correction_enabled())
        self._act_correct.toggled.connect(self._set_ai_correction)

        menu.addSeparator()
        quit_act = menu.addAction("退出语音输入")
        quit_act.triggered.connect(self.shutdown)

        self._tray.setContextMenu(menu)

    # ---------- 行为 ----------

    def show(self) -> None:
        self._tray.show()

    def enable(self) -> None:
        """对外:启用听写(等价于勾选托盘菜单项)。launcher 点卡片后调用。"""
        self._act_enable.setChecked(True)

    def _toggle_enable(self, on: bool) -> None:
        if not sys.platform.startswith("win"):
            self._tray.showMessage(
                "暂不支持", "语音输入目前仅 Windows 可用。",
                QSystemTrayIcon.Information, 4000)
            self._act_enable.setChecked(False)
            return
        try:
            if on:
                self._service.enable()
                self._tray.showMessage(
                    "语音输入已启用",
                    "按住右 Ctrl 说话,松开即输入。",
                    QSystemTrayIcon.Information, 4000)
            else:
                self._service.disable()
        except Exception as e:
            self._act_enable.setChecked(False)
            self._tray.showMessage("启用失败", str(e),
                                   QSystemTrayIcon.Warning, 5000)

    def _set_mode(self, mode: str) -> None:
        self._service.set_inject_mode(mode)
        self._act_paste.setChecked(mode == "paste")
        self._act_type.setChecked(mode == "type")

    def _set_ai_correction(self, enabled: bool) -> None:
        self._service.set_ai_correction(enabled)
        # Reload so toggling this menu item cannot overwrite a newer API key
        # that the launcher saved while the tray was already open.
        self._settings = load_settings()
        self._settings["dictation_ai_correction"] = bool(enabled)
        save_settings(self._settings)
        state = "已开启" if enabled else "已关闭"
        self._tray.showMessage(
            "语音输入 AI 矫正", f"{state}；仅在松开热键后处理最终文本。",
            QSystemTrayIcon.Information, 3000)

    def set_api_key(self, api_key: str) -> None:
        self._service.set_api_key(api_key)
        # Keep standalone tray usage persistent too, while preserving any
        # settings changed by the launcher after this tray was created.
        self._settings = persist_setting("api_key", (api_key or "").strip())

    def _on_error(self, msg: str) -> None:
        self._tray.showMessage("语音输入", msg, QSystemTrayIcon.Warning, 4000)

    def shutdown(self) -> None:
        try:
            self._service.disable()
        except Exception:
            pass
        self._overlay.hide()
        self._tray.hide()
        if self._on_shutdown is not None:
            try:
                self._on_shutdown()
            except Exception:
                pass
