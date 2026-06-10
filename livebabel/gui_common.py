"""GUI 通用件:统一的深色主题样式、字体与小组件,供主入口和离线页面复用。

集中放在一处,保证两个窗口观感一致(现代深色 + 青色强调),改主题只动这里。
"""

from __future__ import annotations

# 主色板(与悬浮窗的青色译文呼应)
BG = "#1E1F26"            # 窗口背景
CARD = "#2A2C36"          # 卡片/输入框背景
CARD_HOVER = "#33363F"
BORDER = "#3A3D48"
TEXT = "#E8E9ED"          # 主文字
SUBTEXT = "#9AA0AE"       # 次要文字
ACCENT = "#7FE7FF"        # 青色强调(同译文色)
ACCENT_DEEP = "#39B9D6"
DANGER = "#FF7A7A"

FONT = "Microsoft YaHei"

# 整窗 QSS。各页面 setStyleSheet(STYLESHEET) 即可。
STYLESHEET = f"""
* {{
    font-family: "{FONT}";
    color: {TEXT};
}}
QWidget#root {{
    background: {BG};
}}
/* 弹出对话框(选文件/设 Key/确认框)也走深色,避免白底突兀 */
QDialog, QMessageBox, QInputDialog, QFileDialog {{
    background: {BG};
}}
QDialog QLabel, QMessageBox QLabel {{ background: transparent; }}
QLabel#title {{
    font-size: 22px;
    font-weight: bold;
}}
QLabel#subtitle {{
    color: {SUBTEXT};
    font-size: 13px;
}}
QLabel#section {{
    color: {SUBTEXT};
    font-size: 12px;
    font-weight: bold;
}}
QLineEdit, QComboBox {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 7px 10px;
    font-size: 13px;
}}
QLineEdit:focus, QComboBox:focus {{
    border: 1px solid {ACCENT_DEEP};
}}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {CARD};
    border: 1px solid {BORDER};
    selection-background-color: {ACCENT_DEEP};
    outline: none;
}}
QPushButton {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    padding: 8px 16px;
    font-size: 13px;
}}
QPushButton:hover {{ background: {CARD_HOVER}; }}
QPushButton:disabled {{ color: {SUBTEXT}; }}
QPushButton#primary {{
    background: {ACCENT_DEEP};
    border: none;
    color: #08222A;
    font-weight: bold;
}}
QPushButton#primary:hover {{ background: {ACCENT}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {SUBTEXT}; }}
QCheckBox {{ font-size: 13px; spacing: 8px; }}
QCheckBox::indicator {{
    width: 16px; height: 16px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {CARD};
}}
QCheckBox::indicator:checked {{
    background: {ACCENT_DEEP};
    border: 1px solid {ACCENT_DEEP};
}}
QProgressBar {{
    background: {CARD};
    border: none;
    border-radius: 5px;
    height: 10px;
    text-align: center;
}}
QProgressBar::chunk {{
    background: {ACCENT_DEEP};
    border-radius: 5px;
}}
QPlainTextEdit, QTextEdit {{
    background: {CARD};
    border: 1px solid {BORDER};
    border-radius: 6px;
    font-family: "Consolas", "{FONT}";
    font-size: 12px;
}}
"""


def apply_theme(widget) -> None:
    """给顶层窗口套上深色主题。widget 应把 objectName 设为 'root'。"""
    widget.setObjectName("root")
    # 自绘背景:确保整个客户区都铺深色,消除系统默认浅色"白边"
    from PySide6.QtCore import Qt
    widget.setAttribute(Qt.WA_StyledBackground, True)
    widget.setStyleSheet(STYLESHEET)


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
    pal.setColor(QPalette.Highlight, c(ACCENT_DEEP))
    pal.setColor(QPalette.HighlightedText, c("#08222A"))
    pal.setColor(QPalette.PlaceholderText, c(SUBTEXT))
    pal.setColor(QPalette.Disabled, QPalette.Text, c(SUBTEXT))
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, c(SUBTEXT))
    app.setPalette(pal)
    app.setStyleSheet(STYLESHEET)
