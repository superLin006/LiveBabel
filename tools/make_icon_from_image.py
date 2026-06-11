"""把一张方形图片(如 assets/eye_logo.png)转成应用图标。

处理:居中裁成正方形 → 加圆角方形遮罩(标准 app 图标外形)→ 描一圈细边
(防浅色背景下边缘融掉)→ 输出多尺寸 assets/icon.ico + assets/logo.png。

用法:
    python tools/make_icon_from_image.py assets/eye_logo.png
"""
from __future__ import annotations
import os
import sys

from PIL import Image, ImageDraw, ImageFilter


def rounded_icon(src_img: Image.Image, size: int, radius_ratio: float = 0.22,
                 border: bool = True) -> Image.Image:
    """把 src_img 处理成 size×size 的圆角方形图标(RGBA)。"""
    im = src_img.convert("RGBA")
    # 居中裁成正方形
    w, h = im.size
    side = min(w, h)
    im = im.crop(((w - side) // 2, (h - side) // 2,
                  (w - side) // 2 + side, (h - side) // 2 + side))
    # 高质量缩放(放大用 LANCZOS)
    im = im.resize((size, size), Image.LANCZOS)

    # 圆角遮罩
    radius = int(size * radius_ratio)
    mask = Image.new("L", (size, size), 0)
    d = ImageDraw.Draw(mask)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=255)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    out.paste(im, (0, 0), mask)

    # 细边框(半透明白,提升浅背景下的边界感);小尺寸不描,避免糊
    if border and size >= 32:
        bd = ImageDraw.Draw(out)
        bw = max(1, size // 64)
        bd.rounded_rectangle([bw // 2, bw // 2, size - 1 - bw // 2, size - 1 - bw // 2],
                             radius=radius, outline=(255, 255, 255, 180), width=bw)
    return out


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "assets/eye_logo.png"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = src if os.path.isabs(src) else os.path.join(root, src)
    if not os.path.isfile(src_path):
        raise SystemExit(f"找不到源图: {src_path}")

    base = Image.open(src_path)
    out_dir = os.path.join(root, "assets")

    sizes = [16, 24, 32, 48, 64, 128, 256]
    # logo.png:512 大图(用 256 的两倍重采样,带圆角)
    big = rounded_icon(base, 512)
    big.save(os.path.join(out_dir, "logo.png"), "PNG")

    # icon.ico:从最大尺寸保存 + 列全部尺寸
    ico256 = rounded_icon(base, 256)
    ico_path = os.path.join(out_dir, "icon.ico")
    ico256.save(ico_path, format="ICO", sizes=[(n, n) for n in sizes])

    chk = Image.open(ico_path)
    print(f"已生成: {os.path.join(out_dir, 'logo.png')}")
    print(f"已生成: {ico_path}  (含尺寸: {sorted(chk.info.get('sizes', set()))})")


if __name__ == "__main__":
    main()
