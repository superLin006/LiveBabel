"""生成 LiveBabel 的 logo / 应用图标(不依赖外部素材,用 QPainter 画矢量再导出)。

概念:圆角方形深色底 + 青色对话气泡 + 气泡里两条字幕线(上白下青,呼应双语字幕),
左下角一个小三角"播放"缺口暗示视频。导出多尺寸 PNG 合成 .ico,供窗口图标和打包用。

运行(在 subtitle 环境):
    python tools/make_logo.py
产物:assets/logo.png(512)、assets/icon.ico(多尺寸)
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import (
    QColor, QGuiApplication, QImage, QPainter, QPainterPath, QPen, QBrush,
)

# 与 GUI 主题一致的配色
BG1 = QColor("#22B5D6")     # 渐变青(深)
BG2 = QColor("#7FE7FF")     # 渐变青(亮)
CARD = QColor("#1E1F26")    # 气泡内深色
WHITE = QColor("#FFFFFF")
CYAN = QColor("#7FE7FF")


def render(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing, True)

    s = size
    # 圆角方形背景(青色渐变),留一点边距
    from PySide6.QtGui import QLinearGradient
    grad = QLinearGradient(0, 0, s, s)
    grad.setColorAt(0, BG1)
    grad.setColorAt(1, BG2)
    m = s * 0.06
    bg = QRectF(m, m, s - 2 * m, s - 2 * m)
    radius = s * 0.22
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(grad))
    p.drawRoundedRect(bg, radius, radius)

    # 对话气泡(深色),带左下小尾巴
    bx, by = s * 0.20, s * 0.22
    bw, bh = s * 0.60, s * 0.42
    bubble = QRectF(bx, by, bw, bh)
    path = QPainterPath()
    path.addRoundedRect(bubble, s * 0.08, s * 0.08)
    # 尾巴
    tail = QPainterPath()
    tx = bx + bw * 0.22
    ty = by + bh
    tail.moveTo(tx, ty - s * 0.02)
    tail.lineTo(tx - s * 0.02, ty + s * 0.12)
    tail.lineTo(tx + s * 0.16, ty - s * 0.02)
    tail.closeSubpath()
    path = path.united(tail)
    p.setBrush(QBrush(CARD))
    p.drawPath(path)

    # 气泡里两条字幕线:上白(原文)下青(译文)
    line_h = s * 0.055
    lx = bx + bw * 0.16
    lw1 = bw * 0.68
    lw2 = bw * 0.50
    ly1 = by + bh * 0.30
    ly2 = by + bh * 0.58
    p.setBrush(QBrush(WHITE))
    p.drawRoundedRect(QRectF(lx, ly1, lw1, line_h), line_h / 2, line_h / 2)
    p.setBrush(QBrush(CYAN))
    p.drawRoundedRect(QRectF(lx, ly2, lw2, line_h), line_h / 2, line_h / 2)

    p.end()
    return img


def main() -> None:
    app = QGuiApplication.instance() or QGuiApplication(sys.argv)
    out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    os.makedirs(out_dir, exist_ok=True)

    # 主 PNG(512)
    big = render(512)
    png_path = os.path.join(out_dir, "logo.png")
    big.save(png_path, "PNG")

    # 多尺寸合成 .ico(Windows 图标 / 任务栏 / exe)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    imgs = [render(n) for n in sizes]
    ico_path = os.path.join(out_dir, "icon.ico")
    # QImage 不能直接写多帧 ico;用 Pillow 合成(若无 Pillow 则退化为单尺寸 png 重命名提示)
    try:
        from PIL import Image
        import io
        pil_imgs = []
        for im in imgs:
            # QImage -> bytes(PNG) -> PIL
            from PySide6.QtCore import QBuffer, QByteArray
            ba = QByteArray()
            qb = QBuffer(ba)
            qb.open(QBuffer.WriteOnly)
            im.save(qb, "PNG")
            pil_imgs.append(Image.open(io.BytesIO(bytes(ba))).convert("RGBA"))
        pil_imgs[0].save(ico_path, format="ICO",
                         sizes=[(n, n) for n in sizes],
                         append_images=pil_imgs[1:])
        print(f"已生成: {png_path}")
        print(f"已生成: {ico_path}")
    except ImportError:
        print(f"已生成: {png_path}")
        print("提示: 未装 Pillow,跳过 .ico 生成(pip install pillow 后重跑可出图标)")


if __name__ == "__main__":
    main()
