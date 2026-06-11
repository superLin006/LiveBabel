"""渲染几版「字母 B + 声波」图标候选,拼成一张对比图供挑选。

不改生产 make_logo.py;选定后再把对应 render 移植过去。
输出 docs/logo_candidates.png(每版渲染 256 大图 + 32/16 小图,看小尺寸是否清晰)。
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QPainter, QBrush, QPen,
                           QLinearGradient, QFont, QPainterPath)

BG1 = QColor("#22B5D6")
BG2 = QColor("#1565C0")   # 更深的蓝,提高对比
CYAN = QColor("#7FE7FF")
WHITE = QColor("#FFFFFF")


def _bg(p, s, c1=BG1, c2=BG2):
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, c1); grad.setColorAt(1, c2)
    m = s * 0.05
    p.setPen(Qt.NoPen); p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(m, m, s - 2 * m, s - 2 * m), s * 0.22, s * 0.22)


def _wave(p, s, cx, y, color, n=5, unit=None):
    """在 (cx,y) 居中画一组对称声波竖条。"""
    unit = unit or s * 0.045
    heights = [0.18, 0.34, 0.5, 0.34, 0.18]
    pen = QPen(color); pen.setWidthF(s * 0.03); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen)
    for i, h in enumerate(heights):
        x = cx + (i - n // 2) * unit
        hh = s * h
        p.drawLine(QPointF(x, y - hh / 2), QPointF(x, y + hh / 2))


def variant_a(s):
    """A: 大写 B(白) + 右侧小声波。经典首字母风。"""
    img = QImage(s, s, QImage.Format_ARGB32); img.fill(Qt.transparent)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing, True)
    _bg(p, s)
    f = QFont("Arial Black", int(s * 0.5)); f.setBold(True)
    p.setFont(f); p.setPen(WHITE)
    p.drawText(QRectF(s * 0.12, s * 0.18, s * 0.55, s * 0.64),
               Qt.AlignCenter, "B")
    _wave(p, s, s * 0.72, s * 0.5, CYAN, unit=s * 0.05)
    p.end(); return img


def variant_b(s):
    """B: B 居中,声波横穿底部(像字幕条)。"""
    img = QImage(s, s, QImage.Format_ARGB32); img.fill(Qt.transparent)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing, True)
    _bg(p, s)
    f = QFont("Arial Black", int(s * 0.46)); f.setBold(True)
    p.setFont(f); p.setPen(WHITE)
    p.drawText(QRectF(s * 0.0, s * 0.06, s, s * 0.62), Qt.AlignCenter, "B")
    # 底部一排声波(青)
    _wave(p, s, s * 0.5, s * 0.76, CYAN, unit=s * 0.07)
    p.end(); return img


def variant_c(s):
    """C: 青色圆底 + 白色 B,B 的两个肚子用声波点缀(极简几何)。"""
    img = QImage(s, s, QImage.Format_ARGB32); img.fill(Qt.transparent)
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing, True)
    # 圆形底
    grad = QLinearGradient(0, 0, s, s); grad.setColorAt(0, CYAN); grad.setColorAt(1, BG1)
    p.setPen(Qt.NoPen); p.setBrush(QBrush(grad))
    p.drawEllipse(QRectF(s * 0.06, s * 0.06, s * 0.88, s * 0.88))
    f = QFont("Georgia", int(s * 0.55)); f.setBold(True)
    p.setFont(f); p.setPen(QColor("#0B3D66"))
    p.drawText(QRectF(0, s * 0.02, s, s * 0.92), Qt.AlignCenter, "B")
    p.end(); return img


def label(img, text):
    p = QPainter(img); p.setPen(QColor("#333"))
    f = QFont("Arial", 16); p.setFont(f)
    p.drawText(QRectF(0, img.height() - 24, img.width(), 24), Qt.AlignCenter, text)
    p.end(); return img


def main():
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    variants = [("A: B+右声波", variant_a), ("B: B+底部字幕条", variant_b),
                ("C: 圆底衬线B", variant_c)]
    cell = 300
    canvas = QImage(cell * 3, cell + 120, QImage.Format_ARGB32)
    canvas.fill(QColor("#EEEEEE"))
    p = QPainter(canvas)
    for i, (name, fn) in enumerate(variants):
        big = fn(256)
        p.drawImage(i * cell + 22, 20, big)
        # 小尺寸预览
        for j, n in enumerate((48, 32, 16)):
            sm = fn(n)
            p.drawImage(i * cell + 22 + j * 60, 290, sm.scaled(n, n))
        p.setPen(QColor("#222")); f = QFont("Arial", 18); p.setFont(f)
        p.drawText(QRectF(i * cell, cell + 60, cell, 40), Qt.AlignCenter, name)
    p.end()
    out = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "docs", "logo_candidates.png")
    canvas.save(out, "PNG")
    print("saved", out)


if __name__ == "__main__":
    main()
