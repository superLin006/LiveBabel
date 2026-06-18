# 发布 Release 操作清单

把打包好的程序作为 GitHub Release 附件发布。模型不随包(2.2G,超 GitHub 单文件 2GB
限制),用户首次运行下模型 → 发布包只含程序本体(~550M)。

## 一、准备发布包(每个版本各做一份)

GPU 版在 `main` 分支打包,CPU 版在 `cpu-edition` 分支打包。打完后:

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

## 四、创建 Release 并上传

用 gh CLI(已装):

```cmd
gh release create v1.0.0 ^
  dist\LiveBabel-GPU-v1.0.0-win64.zip ^
  dist\LiveBabel-CPU-v1.0.0-win64.zip ^
  --title "LiveBabel v1.0.0" ^
  --notes-file packaging\release_notes_v1.0.0.md
```

或在 GitHub 网页:仓库 → Releases → Draft a new release → 选 tag v1.0.0 →
拖入两个 zip → 填说明 → Publish。

## 五、发布说明要点(release notes)

- 三种模式简介(实时/离线/会议)
- 两个包的区别:GPU 版开箱即用要 N 卡(~xxxM)/ CPU 版任何电脑可用(~550M)
- 首次使用两步:双击「下载模型.bat」→ 双击 exe
- 翻译需 DeepSeek API Key(主页设置)
- 已知:无数字签名,杀软可能误报,选信任即可

## 注意

- 发布包**绝不能含** settings.json / history / log(隐私)。
- 同一个 Release 可以陆续补传附件(先发 CPU,GPU 打好再 `gh release upload v1.0.0 xxx.zip`)。
- 测试媒体 test-*.mp4 永远不要进仓库或发布包。
