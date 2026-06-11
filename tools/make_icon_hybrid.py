"""混合图标:大尺寸用高清眼睛图(精致),小尺寸用极简手绘版(清晰)。

Windows 的 .ico 可在一个文件里放多套不同尺寸的画面,系统按显示大小自动挑:
  * >=64px:用 assets/eye_logo.png(高清眼睛+声波,圆角方形+细边)
  * <=48px:用 QPainter 画的极简眼睛(粗轮廓+3根粗声波),16px 也认得出

输出 assets/icon.ico(多尺寸混合)+ assets/logo.png(大图用高清)。
用法: python tools/make_icon_hybrid.py
"""
from __future__ import annotations
import io
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PIL import Image, ImageDraw


# ---------- 高清图 -> 圆角方形(大尺寸用) ----------

def photo_icon(src: Image.Image, size: int, radius_ratio=0.22, border=True) -> Image.Image:
    im = src.convert("RGBA")
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2,
                  (w - side) // 2 + side, (h - side) // 2 + side))
    im = im.resize((size, size), Image.LANCZOS)
    radius = int(size * radius_ratio)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)
    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)
    if border:
        bw = max(1, size // 64)
        ImageDraw.Draw(out).rounded_rectangle(
            [bw // 2, bw // 2, size - 1 - bw // 2, size - 1 - bw // 2],
            radius=radius, outline=(255, 255, 255, 170), width=bw)
    return out


# ---------- 极简手绘(小尺寸用,用 Qt 画矢量再转 PIL) ----------

def minimal_icon(size: int) -> Image.Image:
    from PySide6.QtCore import Qt, QRectF, QPointF
    from PySide6.QtGui import (QImage, QPainter, QColor, QBrush, QPen,
                               QLinearGradient, QGuiApplication)
    _ = QGuiApplication.instance() or QGuiApplication(sys.argv)
    s = size
    img = QImage(s, s, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)
    # 圆角方形蓝渐变底
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, QColor("#3AA9E0"))
    grad.setColorAt(1, QColor("#1565C0"))
    p.setPen(Qt.NoPen); p.setBrush(QBrush(grad))
    p.drawRoundedRect(QRectF(s*0.04, s*0.04, s*0.92, s*0.92), s*0.22, s*0.22)
    # 极简眼睛轮廓(两条粗弧,用椭圆近似)
    pen = QPen(QColor("#FFFFFF")); pen.setWidthF(max(1.2, s*0.05)); pen.setCapStyle(Qt.RoundCap)
    p.setPen(pen); p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(s*0.16, s*0.30, s*0.68, s*0.40))   # 眼睛外形(横椭圆)
    # 瞳孔(深色实心圆)
    p.setPen(Qt.NoPen); p.setBrush(QBrush(QColor("#0B3D8C")))
    p.drawEllipse(QRectF(s*0.37, s*0.34, s*0.26, s*0.32))
    # 瞳孔里 3 根粗声波(白)
    pen2 = QPen(QColor("#FFFFFF")); pen2.setWidthF(max(1.0, s*0.035)); pen2.setCapStyle(Qt.RoundCap)
    p.setPen(pen2)
    cx, cy = s*0.5, s*0.5
    for i, hh in enumerate((0.10, 0.16, 0.10)):
        x = cx + (i-1)*s*0.06
        p.drawLine(QPointF(x, cy-s*hh), QPointF(x, cy+s*hh))
    p.end()
    # QImage -> PIL
    from PySide6.QtCore import QBuffer, QByteArray
    ba = QByteArray(); qb = QBuffer(ba); qb.open(QBuffer.WriteOnly)
    img.save(qb, "PNG")
    return Image.open(io.BytesIO(bytes(ba))).convert("RGBA")


def main() -> None:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = os.path.join(root, "assets")
    src = Image.open(os.path.join(out_dir, "eye_logo.png"))

    # logo.png 用高清(512)
    photo_icon(src, 512).save(os.path.join(out_dir, "logo.png"), "PNG")

    # 混合各尺寸:小用极简,大用高清
    frames = {}
    for n in (16, 24, 32, 48):
        frames[n] = minimal_icon(n)
    for n in (64, 128, 256):
        frames[n] = photo_icon(src, n)

    sizes = sorted(frames)
    # Pillow 写多帧 ico:用 append_images 显式塞入每一帧(各帧画面不同)
    base = frames[256]
    base.save(os.path.join(out_dir, "icon.ico"), format="ICO",
              sizes=[(n, n) for n in sizes],
              append_images=[frames[n] for n in sizes if n != 256])

    chk = Image.open(os.path.join(out_dir, "icon.ico"))
    print("已生成 logo.png + icon.ico")
    print("ico 含尺寸:", sorted(chk.info.get("sizes", set())))


if __name__ == "__main__":
    main()
