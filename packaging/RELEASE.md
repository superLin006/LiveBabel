# 发布 Release 操作清单

把打包好的程序作为 GitHub Release 和 ModelScope 镜像发布。模型不随包（用户首次运行按需下载），发布包只含程序本体。

## 发布渠道约定(v1.4.1 起)

| 渠道 | 文件 | 用途 |
|---|---|---|
| GitHub Release | `LiveBabel-CPU-vX.Y.Z-win64.zip` | 官方稳定 CPU 下载入口，避免 GitHub 限额和 GPU 包过大 |
| ModelScope `LiveBabel-sherpa-onnx-wheels` | `app/vX.Y.Z/LiveBabel-CPU-vX.Y.Z-win64.zip` + `app/vX.Y.Z/LiveBabel-GPU-vX.Y.Z-win64.zip` | 国内镜像，同时提供 CPU/GPU 应用包 |

ModelScope 的应用包与模型仓库职责分离：应用包放在
[`LiveBabel-sherpa-onnx-wheels`](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-sherpa-onnx-wheels)，模型仍放在
[`LiveBabel-Models`](https://www.modelscope.cn/models/XHxiehuan/LiveBabel-Models)。不要把两种精度的模型复制进 exe 发布包；程序会按 provider 下载一套所需模型。

由于该仓库名称历史上用于 wheel，应用包统一放在 `app/` 子目录，避免与 wheel 混淆。每次上传都同时生成 `.sha256`，并在 ModelScope 使用版本目录（例如 `app/v1.4.1/`）。同一版本只保留一份 CPU 和一份 GPU 包，重传时覆盖同路径，避免重复发布。

## 一、准备发布包(每个版本各做一份)

GPU 版在 `main` 分支打包,CPU 版在 `cpu-edition` 分支打包。v1.4.1 的构建脚本默认使用 `subtitle-new` conda 环境。打完后:

```cmd
REM 在 dist\ 下,从打包产物复制出一份"干净发布副本"(去模型 + 去隐私文件)
REM GPU 版产物目录是 LiveBabel\,CPU 版是 LiveBabel-CPU\

REM 例(CPU 版):
mkdir dist\LiveBabel-CPU-release
xcopy /E /I dist\LiveBabel-CPU\LiveBabel-CPU.exe  dist\LiveBabel-CPU-release\
xcopy /E /I dist\LiveBabel-CPU\_internal          dist\LiveBabel-CPU-release\_internal\
```

**务必排除(隐私!):** `settings.json`(含你的 API Key)、`history\`(你的记录)、
`log\`、`models\`(太大,用户自己下)。只保留 `exe` + `_internal\`。

往发布副本里放给用户的两个文件(本仓库 dist 准备时已生成,可复用):
- `下载模型.bat` — 用户首次双击下模型到 models\
- `使用说明.txt` — 给最终用户的简明说明

## 二、压缩(在 Windows 上压,保证中文文件名不乱码)

右键 `LiveBabel-CPU-release` 文件夹 → 压缩成 ZIP,或 PowerShell:

```powershell
Compress-Archive -Path dist\LiveBabel-CPU-release\* -DestinationPath dist\LiveBabel-CPU-v1.0.0-win64.zip
# GPU 版同理 → LiveBabel-GPU-v1.0.0-win64.zip
```

确认每个 zip < 2GB(GitHub 单文件上限)。约 ~500-600M,没问题。

## 三、打 tag

在确定的发布提交上打(确保该提交已 push):

```cmd
git checkout main
git pull
git tag -a v1.0.0 -m "LiveBabel v1.0.0:实时字幕 / 离线字幕 / 会议纪要"
git push origin v1.0.0
```

## 四、创建 GitHub Release 并上传 CPU 包

用 gh CLI(已装):

```cmd
gh release create v1.4.1 ^
  dist\LiveBabel-CPU-v1.4.1-win64.zip ^
  dist\LiveBabel-CPU-v1.4.1-win64.zip.sha256 ^
  --title "LiveBabel v1.4.1 (CPU)" ^
  --notes-file packaging\release_notes_v1.4.1.md
```

或在 GitHub 网页:仓库 → Releases → Draft a new release → 选 tag v1.4.1 →
只拖入 CPU zip 和 SHA256 → 填说明 → Publish。

## 五、上传 ModelScope(CPU + GPU)

先在 Windows 本地完成 GPU/CPU 两次构建和启动冒烟测试，再上传同一版本的两个 zip。不要把 token 写入仓库、脚本或命令历史；使用 ModelScope Hub CLI 登录后上传：

```bash
python -m pip install -U modelscope_hub
ms-hub login                         # 交互式输入 token
ms-hub upload XHxiehuan/LiveBabel-sherpa-onnx-wheels \
  dist/LiveBabel-CPU-v1.4.1-win64.zip app/v1.4.1/LiveBabel-CPU-v1.4.1-win64.zip
ms-hub upload XHxiehuan/LiveBabel-sherpa-onnx-wheels \
  dist/LiveBabel-GPU-v1.4.1-win64.zip app/v1.4.1/LiveBabel-GPU-v1.4.1-win64.zip
```

上传后在仓库 README/文件列表确认两个文件均可下载，并把 SHA256 一并上传到 `app/v1.4.1/`。ModelScope 模型卡只介绍包用途和 CUDA 要求，不要在卡片中嵌入访问凭证。若后续应用包成为主用途，建议新建 `LiveBabel-Releases` 仓库，将 wheel 和应用包彻底分开。

## 六、发布说明要点(release notes)

- 三种模式简介(实时/离线/会议)
- 两个包的区别:GPU 版开箱即用要 N 卡(~xxxM)/ CPU 版任何电脑可用(~550M)
- 首次使用两步:双击「下载模型.bat」→ 双击 exe
- 翻译需 DeepSeek API Key(主页设置)
- 已知:无数字签名,杀软可能误报,选信任即可

## 注意

- 发布包**绝不能含** settings.json / history / log(隐私)。
- 同一个 Release 可以陆续补传附件(先发 CPU,GPU 打好再 `gh release upload v1.0.0 xxx.zip`)。
- 测试媒体 test-*.mp4 永远不要进仓库或发布包。
