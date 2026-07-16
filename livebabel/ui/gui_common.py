"""GUI 通用件:统一的浅色「苹果风」主题样式、字体与小组件,供各页面复用。

设计语言参考 macOS 浅色模式:纯净浅灰背景、大圆角柔和卡片、细分隔线、
系统蓝强调、宽松留白。集中放一处,改主题只动这里。
(实时悬浮窗 overlay.py 自管样式,不受本文件影响。)
"""

from __future__ import annotations

# 应用版本(首页页脚显示;发版时与 git tag 同步)
APP_VERSION = "1.3.0"

# ---- 浅色苹果风色板 ----
BG = "#F5F5F7"            # 窗口背景(macOS 经典浅灰)
CARD = "#FFFFFF"          # 卡片/输入框背景(纯白浮于浅灰之上)
CARD_HOVER = "#F0F0F3"    # 卡片悬停
BORDER = "#E2E2E6"        # 细分隔线/边框(极淡)
TEXT = "#1D1D1F"          # 主文字(近黑)
SUBTEXT = "#86868B"       # 次要文字(中性灰)
ACCENT = "#0A84FF"        # 系统蓝(强调/主按钮)
ACCENT_DEEP = "#0060DF"   # 系统蓝按下态(更深)
DANGER = "#FF3B30"        # 系统红(危险操作)
ON_ACCENT = "#FFFFFF"     # 强调色上的文字(白)

# 苹果界面优先用系统中文黑体;无则回退微软雅黑。
# QSS font-family 需要每个字体名【各自加引号】、逗号分隔;
# 不能整串包一对引号(那样 Qt 当成一个不存在的字体名,解析失败会触发
# "QFont::setPointSize: Point size <= 0" 警告)。
FONT = '"PingFang SC", "Microsoft YaHei", "Segoe UI"'

# ---- 统一窗口尺寸(苹果风:同一应用内功能窗口尺寸一致,观感规整)----
# 功能窗口(离线 / 会议)共用同一基准;首页是入口、内容少,单独略小。
WIN_W, WIN_H = 720, 720        # 功能窗口标准尺寸
LAUNCHER_W, LAUNCHER_H = 720, 478   # 首页:同宽,稍矮(卡片一句话文案后收紧留白)

# 整窗 QSS。各页面 setStyleSheet(STYLESHEET) 即可。
# 苹果风要点:大圆角(10–12px)、细淡边框、宽松内边距、悬停轻微变色而非描边、
# 主按钮纯色蓝、文字层级靠字号+字重拉开。
STYLESHEET = f"""
* {{
    font-family: {FONT};
    color: {TEXT};
}}
QWidget#root {{
    background: {BG};
}}
/* 弹出对话框(选文件/设 Key/确认框)统一浅色 */
QDialog, QMessageBox, QInputDialog, QFileDialog {{
    background: {BG};
}}
QDialog QLabel, QMessageBox QLabel {{
    background: transparent;
    font-size: 13px;
}}
QMessageBox {{ min-width: 360px; }}
/* 对话框按钮:统一尺寸 + 主按钮高亮 */
QDialog QPushButton, QMessageBox QPushButton {{
    min-width: 80px;
    padding: 7px 18px;
}}
QMessageBox QPushButton:default, QDialog QPushButton:default {{
    background: {ACCENT};
    border: none;
    color: {ON_ACCENT};
    font-weight: 600;
}}
QMessageBox QPushButton:default:hover {{ background: {ACCENT_DEEP}; }}
QLabel#title {{
    font-size: 26px;
    font-weight: 700;
    letter-spacing: 0.2px;
}}
QLabel#subtitle {{
    color: {SUBTEXT};
    font-size: 13px;
}}
QLabel#section {{
    color: {SUBTEXT};
    font-size: 12px;
    font-weight: 600;
}}
QLineEdit, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 12px;
    font-size: 13px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT};
}}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 4px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
    outline: none;
}}
/* 普通按钮:白底细边,悬停淡灰(macOS 次级按钮观感) */
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 18px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:pressed {{ background: {BORDER}; }}
QPushButton:disabled {{ color: {SUBTEXT}; background: {BG}; }}
/* 主按钮:纯色系统蓝 */
QPushButton#primary {{
    background: {ACCENT};
    border: none;
    color: {ON_ACCENT};
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: {ACCENT_DEEP}; }}
QPushButton#primary:pressed {{ background: {ACCENT_DEEP}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {SUBTEXT}; }}
/* 危险按钮:文字红,悬停淡红底 */
QPushButton#danger {{
    background: {CARD};
    border: 1px solid {BORDER};
    color: {DANGER};
}}
QPushButton#danger:hover {{ background: #FFF0F0; border: 1px solid {DANGER}; }}
QCheckBox {{ font-size: 13px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 18px; height: 18px;
    border: 1px solid {BORDER};
    border-radius: 5px;
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT};
    border: 1px solid {ACCENT};
}}
QProgressBar {{
    background: {BORDER};
    border: none;
    border-radius: 5px;
    height: 8px;
    text-align: center;
    color: {TEXT};
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 5px;
}}
QPlainTextEdit, QTextEdit {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    font-family: "SF Mono", "Consolas", {FONT};
    font-size: 12px;
    selection-background-color: {ACCENT};
    selection-color: {ON_ACCENT};
}}
QListWidget {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
    padding: 4px;
    outline: none;
}}
QListWidget::item {{
    padding: 7px 8px;
    border-radius: 6px;
}}
QListWidget::item:selected {{
    background: {ACCENT};
    color: {ON_ACCENT};
}}
QListWidget::item:hover:!selected {{ background: {CARD_HOVER}; }}
/* 细长滚动条(macOS 风) */
QScrollBar:vertical {{
    background: transparent; width: 10px; margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #C8C8CE; border-radius: 5px; min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{ background: #B0B0B6; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
"""


def apply_theme(widget) -> None:
    """给顶层窗口套上深色主题。widget 应把 objectName 设为 'root'。"""
    widget.setObjectName("root")
    # 自绘背景:确保整个客户区都铺深色,消除系统默认浅色"白边"
    from PySide6.QtCore import Qt
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setStyleSheet(STYLESHEET)


def card(child=None, padding: int = 18):
    """苹果风卡片容器:纯白圆角 + 柔和投影,浮于浅灰背景之上。

    用法:把若干控件放进一个 QVBoxLayout,传进来包成一张卡片区块。
    传 child(QLayout 或 QWidget)直接装入;不传则返回空卡片 + 其内层 QVBoxLayout
    供调用方 addWidget。返回 (frame, inner_layout)。
    """
    from PySide6.QtWidgets import (
        QFrame, QVBoxLayout, QGraphicsDropShadowEffect, QLayout, QWidget,
    )
    from PySide6.QtGui import QColor

    frame = QFrame()
    frame.setObjectName("appcard")
    frame.setStyleSheet(
        f"#appcard {{ background: {CARD}; border: 1px solid {BORDER};"
        f" border-radius: 14px; }}"
    )
    shadow = QGraphicsDropShadowEffect(frame)
    shadow.setBlurRadius(22)
    shadow.setXOffset(0)
    shadow.setYOffset(3)
    shadow.setColor(QColor(0, 0, 0, 22))
    frame.setGraphicsEffect(shadow)

    inner = QVBoxLayout(frame)
    inner.setContentsMargins(padding, padding, padding, padding)
    inner.setSpacing(12)
    if isinstance(child, QLayout):
        inner.addLayout(child)
    elif isinstance(child, QWidget):
        inner.addWidget(child)
    return frame, inner


def section_label(text: str):
    """区块小标题(灰色、半粗、字间距),苹果设置页常见的分组标题样式。"""
    from PySide6.QtWidgets import QLabel
    lab = QLabel(text)
    lab.setObjectName("section")
    return lab


def enable_dark_titlebar(widget) -> None:
    """把 Windows 系统标题栏设为【浅色】(配合浅色苹果风界面)。

    名字保留 enable_dark_titlebar 是为兼容现有调用点;实际把
    DWMWA_USE_IMMERSIVE_DARK_MODE 关掉(传 0)→ 浅色标题栏。
    仅 Windows 10 1809+ 生效,其它平台或失败都安全跳过。须在原生句柄创建后调用。
    """
    import sys
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        from ctypes import wintypes
        hwnd = int(widget.winId())
        dwm = ctypes.windll.dwmapi
        val = ctypes.c_int(0)   # 0 = 关闭深色 → 浅色标题栏
        # 20 = DWMWA_USE_IMMERSIVE_DARK_MODE(老系统是 19,两个都试)
        for attr in (20, 19):
            dwm.DwmSetWindowAttribute(
                wintypes.HWND(hwnd), ctypes.c_uint(attr),
                ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def app_icon():
    """返回应用 QIcon(找不到图标文件则返回空 QIcon)。"""
    from PySide6.QtGui import QIcon
    from livebabel.paths import find_icon
    path = find_icon()
    return QIcon(path) if path else QIcon()


def _styled_box(parent, title: str, text: str, buttons, default=None):
    """构造一个深色主题、用我们自己 logo(而非系统感叹号/i 图标)的消息框。"""
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtCore import Qt
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setStandardButtons(buttons)
    if default is not None:
        box.setDefaultButton(default)
    # 用应用 logo 替换系统标准图标(information 的蓝色 ⓘ 在深色里很丑)
    icon = app_icon()
    if not icon.isNull():
        box.setIconPixmap(icon.pixmap(48, 48))
    else:
        box.setIcon(QMessageBox.NoIcon)
    return box


def info(parent, title: str, text: str) -> None:
    from PySide6.QtWidgets import QMessageBox
    _styled_box(parent, title, text, QMessageBox.Ok).exec()


def error(parent, title: str, text: str) -> None:
    from PySide6.QtWidgets import QMessageBox
    _styled_box(parent, title, text, QMessageBox.Ok).exec()


def confirm(parent, title: str, text: str) -> bool:
    """是/否确认框,返回 True=用户选「是」。"""
    from PySide6.QtWidgets import QMessageBox
    box = _styled_box(parent, title, text,
                      QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
    # 中文化按钮文字
    box.button(QMessageBox.Yes).setText("是")
    box.button(QMessageBox.No).setText("否")
    return box.exec() == QMessageBox.Yes


def apply_app_theme(app) -> None:
    """给整个 QApplication 套深色调色板 + 全局样式。

    调色板兜底任何没被 QSS 显式覆盖的像素(窗口客户区、原生边、滚动条等),
    这是消除"白边/白底弹窗"的根本手段;QSS 只管细节外观。
    """
    from PySide6.QtGui import QPalette, QColor

    def c(hex_):
        return QColor(hex_)

    pal = QPalette()
    pal.setColor(QPalette.Window, c(BG))
    pal.setColor(QPalette.WindowText, c(TEXT))
    pal.setColor(QPalette.Base, c(CARD))
    pal.setColor(QPalette.AlternateBase, c(CARD_HOVER))
    pal.setColor(QPalette.Text, c(TEXT))
    pal.setColor(QPalette.Button, c(CARD))
    pal.setColor(QPalette.ButtonText, c(TEXT))
    pal.setColor(QPalette.ToolTipBase, c(CARD))
    pal.setColor(QPalette.ToolTipText, c(TEXT))
    pal.setColor(QPalette.Highlight, c(ACCENT))
    pal.setColor(QPalette.HighlightedText, c(ON_ACCENT))
    pal.setColor(QPalette.PlaceholderText, c(SUBTEXT))
    pal.setColor(QPalette.Disabled, QPalette.Text, c(SUBTEXT))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, c(SUBTEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)

    # 全局事件过滤器:任何新顶层窗口(含临时弹窗)显示时自动套浅色标题栏
    # (悬浮窗是无边框 Tool 窗,DWM 调用对它无效,不受影响)
    import sys as _sys
    if _sys.platform.startswith("win"):
        from PySide6.QtCore import QObject, QEvent

        class _LightTitleFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Show:
                    try:
                        from PySide6.QtWidgets import QWidget
                        if isinstance(obj, QWidget) and obj.isWindow():
                            enable_dark_titlebar(obj)
                    except Exception:
                        pass
                return False

        f = _LightTitleFilter(app)
        app.installEventFilter(f)
        app._light_title_filter = f   # 防被 GC
