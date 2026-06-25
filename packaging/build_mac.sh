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

# 架构自检:确认运行打包的 python 架构 = 机器架构。Apple Silicon 上若误用
# Rosetta 终端里的 Intel(x86_64)python,会装错架构的 onnxruntime/ctranslate2
# wheel,打出的 .app 在 arm64 上加载动态库时崩溃。这里提前显眼提示。
PY_ARCH="$(python -c 'import platform; print(platform.machine())')"
HW_ARCH="$(uname -m)"
echo "[arch] 机器=$HW_ARCH  python=$PY_ARCH"
if [ "$PY_ARCH" != "$HW_ARCH" ]; then
  echo "⚠ 警告:python 架构($PY_ARCH)与机器($HW_ARCH)不一致!"
  echo "  你很可能在 Rosetta 终端里用了 Intel 版 python。打出来的包会是 $PY_ARCH,"
  echo "  在 $HW_ARCH 上可能因架构不符而无法加载 sherpa/ctranslate2 动态库。"
  echo "  建议:用原生 $HW_ARCH 的 python 重建虚拟环境后再打包。"
  # CI(GitHub Actions)里无人交互,且 runner 架构已锁定,跳过确认直接继续。
  if [ -z "$CI" ]; then
    read -p "  仍要继续?(y/N) " ans
    [ "$ans" = "y" ] || [ "$ans" = "Y" ] || { echo "已中止。"; exit 1; }
  fi
fi

echo "[1/6] 安装 py2app ..."
pip install py2app >/dev/null

echo "[2/6] 清理旧产物 ..."
rm -rf build dist

echo "[3/6] py2app 打包 ..."
python packaging/setup_mac.py py2app

if [ ! -d "$APP" ]; then
  echo "✗ 打包失败:未生成 $APP。请把上面的报错发给我。"
  exit 1
fi

echo "[4/6] 裁剪 PySide6(py2app 的 excludes 排不掉 Qt framework,在此手动删)..."
# LiveBabel 只用 QtCore/QtGui/QtWidgets。py2app 会把整个 Qt 收进来,其中
# QtWebEngineCore.framework 内嵌 Chromium 就近 600MB,加上 QtQuick/Qt3D/QtPdf/
# 一堆 QML 模块,白白撑到 1.5GB。这里用"白名单保留"删掉用不到的,体积可降 ~2/3。
PYSIDE="$RES/lib/python3.11/PySide6"
if [ -d "$PYSIDE" ]; then
  before=$(du -sm "$PYSIDE" | cut -f1)
  # 必保留的 framework:三大件 + 其运行时依赖(DBus/Network/Svg/OpenGL/PrintSupport)。
  KEEP="QtCore QtGui QtWidgets QtDBus QtNetwork QtSvg QtOpenGL QtOpenGLWidgets QtPrintSupport"
  if [ -d "$PYSIDE/Qt/lib" ]; then
    for fw in "$PYSIDE/Qt/lib/"*.framework; do
      name="$(basename "$fw" .framework)"
      keep=0
      for k in $KEEP; do [ "$name" = "$k" ] && keep=1 && break; done
      [ "$keep" = "0" ] && rm -rf "$fw"
    done
  fi
  # 对应删掉 PySide6 顶层的 .abi3.so 绑定(只留保留的那几个 + Qt 基础设施)
  KEEP_SO="QtCore QtGui QtWidgets QtDBus QtNetwork QtSvg QtOpenGL QtOpenGLWidgets QtPrintSupport"
  for so in "$PYSIDE/"Qt*.abi3.so "$PYSIDE/"Qt*.pyi; do
    [ -e "$so" ] || continue
    b="$(basename "$so")"; mod="${b%%.*}"
    keep=0
    for k in $KEEP_SO; do [ "$mod" = "$k" ] && keep=1 && break; done
    [ "$keep" = "0" ] && rm -f "$so"
  done
  # 大块无用资源:QML(我们不用)/翻译/类型元数据/Qt 开发工具
  rm -rf "$PYSIDE/Qt/qml" "$PYSIDE/Qt/translations" "$PYSIDE/Qt/metatypes" \
         "$PYSIDE/Qt/libexec" \
         "$PYSIDE/Assistant.app" "$PYSIDE/Linguist.app" "$PYSIDE/Designer.app" \
         "$PYSIDE/qmlls" "$PYSIDE/qmlformat" "$PYSIDE/qmllint" "$PYSIDE/lupdate" \
         "$PYSIDE/lrelease" "$PYSIDE/qmlimportscanner" "$PYSIDE/qmlcachegen" \
         "$PYSIDE/qmltyperegistrar" "$PYSIDE/qmlsc" 2>/dev/null || true
  # plugins:只留 GUI 必需的几类,其余删(platforms 删了 Qt 直接起不来,务必保留)
  if [ -d "$PYSIDE/Qt/plugins" ]; then
    KEEP_PLUG="platforms imageformats styles iconengines tls generic platforminputcontexts"
    for d in "$PYSIDE/Qt/plugins/"*/; do
      name="$(basename "$d")"
      keep=0
      for k in $KEEP_PLUG; do [ "$name" = "$k" ] && keep=1 && break; done
      [ "$keep" = "0" ] && rm -rf "$d"
    done
  fi
  after=$(du -sm "$PYSIDE" | cut -f1)
  echo "  PySide6: ${before}MB → ${after}MB"
fi

echo "[5/6] 拷 models/ 和 ffmpeg/ 进 .app ..."
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

echo "[6/6] 完成。"
echo "============================================================"
echo "  产物:$APP  ($(du -sh "$APP" | cut -f1))"
echo "  首次运行被 Gatekeeper 拦:右键 → 打开,或"
echo "    xattr -dr com.apple.quarantine \"$APP\""
echo "  会议模式录麦克风时,系统会弹麦克风权限,请允许。"
echo "  抓系统声音需先装 BlackHole(brew install blackhole-2ch)并配多输出设备。"
echo "============================================================"
