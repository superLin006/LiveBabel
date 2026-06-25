"""把一张方形图片生成 macOS 应用图标 assets/icon.icns(py2app 用)。

复用 make_icon_from_image 的圆角处理(居中裁方 → 圆角遮罩 → 细边),按苹果规范
铺多套尺寸(16/32/128/256/512 及各自 @2x),用 Pillow 直接写出 .icns —— 纯 Python,
不依赖 macOS 的 iconutil,所以在 Windows/Linux 上也能预生成成品 .icns。

用法:
    python tools/make_icns.py                 # 默认用 assets/eye_logo.png
    python tools/make_icns.py assets/logo.png

注:Pillow 的 ICNS 编码需要 6.0+(本仓库为 12.x)。在 Mac 真机上若想用系统
iconutil 重新生成更"原生"的 .icns,可用本脚本顺带导出的 assets/icon.iconset/。
"""
from __future__ import annotations

import os
import sys

from PIL import Image

# 复用已有的圆角图标处理,风格与 .ico 保持一致
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from make_icon_from_image import rounded_icon  # noqa: E402


# 苹果 .iconset 规范:(文件名, 像素边长)。@2x 是同名高分屏版本。
ICONSET = [
    ("icon_16x16.png", 16),
    ("icon_16x16@2x.png", 32),
    ("icon_32x32.png", 32),
    ("icon_32x32@2x.png", 64),
    ("icon_128x128.png", 128),
    ("icon_128x128@2x.png", 256),
    ("icon_256x256.png", 256),
    ("icon_256x256@2x.png", 512),
    ("icon_512x512.png", 512),
    ("icon_512x512@2x.png", 1024),
]


def main() -> None:
    src = sys.argv[1] if len(sys.argv) > 1 else "assets/eye_logo.png"
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    src_path = src if os.path.isabs(src) else os.path.join(root, src)
    if not os.path.isfile(src_path):
        raise SystemExit(f"找不到源图: {src_path}")

    base = Image.open(src_path)
    assets = os.path.join(root, "assets")

    # 1) 导出标准 .iconset 目录(Mac 上可用 `iconutil -c icns assets/icon.iconset` 复跑)
    iconset_dir = os.path.join(assets, "icon.iconset")
    os.makedirs(iconset_dir, exist_ok=True)
    for name, px in ICONSET:
        rounded_icon(base, px).save(os.path.join(iconset_dir, name), "PNG")

    # 2) 用 Pillow 直接写 .icns(纯 Python,不依赖 iconutil)。
    #    Pillow 从单张大图按内部规则降采样出各尺寸;给 1024 的圆角大图即可。
    icns_path = os.path.join(assets, "icon.icns")
    big = rounded_icon(base, 1024)
    big.save(icns_path, format="ICNS")

    chk = Image.open(icns_path)
    print(f"已生成: {iconset_dir}/  ({len(ICONSET)} 张)")
    print(f"已生成: {icns_path}  (size={chk.size}, mode={chk.mode})")
    print("setup_mac.py 会自动检测 assets/icon.icns 并设为 .app 图标。")


if __name__ == "__main__":
    main()
