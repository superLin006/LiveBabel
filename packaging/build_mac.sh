#!/usr/bin/env bash
# 在 macOS 上把 LiveBabel 打成 .app。须在 Mac、已装依赖的环境里跑(py2app 不跨平台)。
#
#   chmod +x packaging/build_mac.sh
#   ./packaging/build_mac.sh
#
# 产物:dist/LiveBabel.app。models/ 和 ffmpeg/ 会拷进 .app 内的 Resources。
set -e

cd "$(dirname "$0")/.."          # 切到项目根
ROOT="$(pwd)"
APP="dist/LiveBabel.app"
RES="$APP/Contents/Resources"

echo "[1/5] 安装 py2app ..."
pip install py2app >/dev/null

echo "[2/5] 清理旧产物 ..."
rm -rf build dist

echo "[3/5] py2app 打包 ..."
python packaging/setup_mac.py py2app

if [ ! -d "$APP" ]; then
  echo "✗ 打包失败:未生成 $APP。请把上面的报错发给我。"
  exit 1
fi

echo "[4/5] 拷 models/ 和 ffmpeg/ 进 .app ..."
if [ -d models ]; then
  mkdir -p "$RES/models"
  cp -R models/* "$RES/models/"
else
  echo "  警告:models/ 不存在,请先下载模型(运行 download_models 或手动放到 models/)。"
fi
if [ -d ffmpeg ]; then
  mkdir -p "$RES/ffmpeg"
  cp -R ffmpeg/* "$RES/ffmpeg/"
fi

echo "[5/5] 完成。"
echo "============================================================"
echo "  产物:$APP"
echo "  首次运行被 Gatekeeper 拦:右键 → 打开,或"
echo "    xattr -dr com.apple.quarantine \"$APP\""
echo "  会议模式录麦克风时,系统会弹麦克风权限,请允许。"
echo "  抓系统声音需先装 BlackHole(brew install blackhole-2ch)并配多输出设备。"
echo "============================================================"
