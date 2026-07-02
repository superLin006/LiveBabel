# 功能 1：语音输入听写 — 实现方案

> 全局热键触发：说话 → ASR 整段识别 → 文字自动注入当前焦点输入框（任意应用）。
> 本文档为设计稿，供审阅；不含最终代码。

## 决策汇总（已与用户确认）

| 项 | 决策 |
|---|---|
| 触发 | PTT（按住说话，松开识别）+ 切换式（双击/长按开关），两者都做 |
| 注入 | 剪贴板+模拟粘贴（默认）+ 逐字键入（备选开关），两种可选 |
| 翻译 | 先纯听写，翻译留后（后续复用 `core/translator.py`） |
| 形态 | 后台常驻 + 系统托盘开关（不必开窗口） |
| 平台 | **Windows 先行**；macOS 留接口，后续用 pynput 补 |
| ASR | **两阶段**：说话时流式 zipformer 出草稿（浮窗实时反馈），松开后 SenseVoice 整段高精度重识再注入。复用实时模式的 `TwoPassAsr` |

## 新增依赖

```
# requirements.txt(按平台标记,沿用 pyaudiowpatch 的 PEP 508 写法)
keyboard ; platform_system == "Windows"   # 全局热键 + 模拟粘贴按键(Win 普通权限可用)
# macOS 后续:pynput ; platform_system == "Darwin"
```

- 剪贴板、托盘用 **PySide6 自带**（QClipboard / QSystemTrayIcon），不新增库。
- `keyboard` 纯 Python、体积小，不拖 torch，符合轻量原则。
- ⚠️ `keyboard` 在 Linux 需 root → **WSL 无法端到端测**，逻辑正确性可保证，实际效果需 Windows 真机验证。

## 模块结构

```
livebabel/dictation/
├── __init__.py
├── hotkey.py        # 全局热键监听 + PTT/切换两种模式的状态机
├── stream_asr.py    # 两阶段识别:复用 TwoPassAsr,边喂边出草稿,结束拿最终定稿
├── injector.py      # 把文字注入当前输入框(剪贴板粘贴 / 逐字键入,平台抽象)
└── service.py       # 编排:热键事件 → 边录边识别(草稿浮窗) → 松开定稿注入;后台常驻
livebabel/ui/
├── tray.py          # QSystemTrayIcon:开关听写、切热键、退出
└── dictation_overlay.py  # 听写草稿小浮窗(说话时实时显示流式草稿,松开后淡出)
```

## 各模块职责与接口

### stream_asr.py — 两阶段识别引擎
```python
class StreamDictationEngine:
    """两阶段听写引擎。复用实时模式的 TwoPassAsr:边喂麦克风帧边出流式草稿,
    结束时拿 SenseVoice 高精度定稿。on_draft 回调用于更新草稿浮窗。"""
    def __init__(self, on_draft): ...  # on_draft(text:str) 每出一版草稿调一次
    def start(self) -> None: ...
        # 起工作线程跑 MicrophoneSource.frames();每帧 twopass.feed() →
        # 回调 on_draft(volatile_text) 更新草稿浮窗
    def stop(self) -> str: ...
        # 停采集 → twopass.finalize() 拿最后一句高精度定稿 → 返回最终文本(给注入)
```
- 复用 `livebabel/asr/asr_engine.py` 的 `TwoPassAsr`（流式 zipformer + 非流式 SenseVoice）
  和 `audio_source_mic.py` 的 `MicrophoneSource`（已产 16k mono float32）。
- 复用 `paths.FIRST_DIR/SECOND_DIR`、`detect_provider()`。
- **模型懒加载 + 常驻复用**：首次听写时才建 `TwoPassAsr`，之后复用（建模型慢，不能每次重建）。
- 两阶段流程：
  - 说话中：每帧 `feed()` → `AsrEvent.volatile_text`（流式草稿）→ 推给草稿浮窗实时显示。
  - 松开键：`finalize()` → 取该段 `committed`（SenseVoice 高精度）→ 注入。
- 听写通常一两句，按键界定起止;若用户说很长触发了中途 endpoint,`feed()` 已能拿到
  `committed_text`,可累积拼接(service 负责把多句 committed 串起来)。
- 上限保护：超过 N 秒（如 60s）自动 stop，防忘松手。

### injector.py — 文字注入（平台抽象）
```python
class TextInjector:                    # 抽象基类
    def inject(self, text: str) -> None: ...

class ClipboardPasteInjector(TextInjector):
    """写剪贴板 → 模拟 Ctrl+V → 恢复原剪贴板内容。中文最稳。"""

class TypeInjector(TextInjector):
    """逐字键入(keyboard.write)。不污染剪贴板,但中文易错,作为备选。"""

def make_injector(mode: str) -> TextInjector:  # mode: "paste"|"type"
```
- Windows：剪贴板用 QClipboard，粘贴按键用 `keyboard.send("ctrl+v")`。
- 恢复剪贴板：注入前存原内容，粘贴后延时恢复（注意时序，粘贴需先完成）。

### hotkey.py — 全局热键状态机
```python
class HotkeyManager:
    """注册全局热键,区分 PTT 与切换式,回调 on_start/on_stop。"""
    # PTT: 按下→on_start,松开→on_stop
    # 切换: 双击(或长按)→翻转录音状态
```
- Windows 用 `keyboard.hook` / `keyboard.add_hotkey`。
- 默认热键：PTT = 按住 `ctrl+alt`；切换 = 双击 `ctrl+alt`（可在托盘里改）。

### service.py — 编排
```python
class DictationService:
    """常驻。热键按下→engine.start()(草稿浮窗显示流式草稿);热键松开→
    engine.stop() 拿最终定稿→injector 注入→浮窗淡出。
    线程模型:热键回调在监听线程只发信号,采集/识别在 engine 工作线程,不阻塞热键。"""
    def enable(self) / disable(self): ...
    def set_hotkey(...) / set_inject_mode("paste"|"type"): ...
```
- 两阶段时序:start 即弹草稿浮窗、边说边刷新(volatile);stop 后浮窗显示最终定稿
  一瞬→注入→淡出,让用户看到"注入的就是这句"。
- 草稿浮窗与注入解耦:浮窗只读 on_draft/最终文本;注入只在 stop 拿到 committed 后做。
- 跨线程更新 UI:engine 在工作线程,浮窗在 Qt 主线程 → 用信号(Signal)投递草稿,
  不可在工作线程直接动 widget。

### ui/tray.py — 托盘开关
- QSystemTrayIcon：菜单含「启用听写 ✓」「热键设置」「注入方式：粘贴/键入」「退出」。
- 主页 launcher 加一个入口卡片「语音输入」→ 点开即启用并最小化到托盘（或直接在 launcher 放一个开关）。

### ui/dictation_overlay.py — 草稿小浮窗
- 无边框、置顶、半透明小窗，跟随屏幕底部居中（或鼠标附近）。说话时实时显示流式草稿。
- 接口:`show_draft(text)` / `show_final(text)` / `fade_out()`,均在 Qt 主线程调用。
- 复用实时模式 overlay 的字体/样式取向(正体、苹果风浅色),但**轻量得多**:单行、无翻译行。
- 视觉态:录音中=草稿(灰)+ 麦克风角标;松开=最终文本(黑)一闪→淡出。

## 线程与稳定性要点
- 热键监听线程**只发事件**，不做重活（采集/识别在 engine 工作线程），否则热键卡顿。
- `TwoPassAsr` 懒加载 + 复用，单例，加锁防并发听写（一次只跑一段）。
- 草稿更新跨线程：工作线程发信号，Qt 主线程刷浮窗，禁止跨线程直接动 widget。
- 录音上限自动停；正在听写时再次触发热键要忽略（防叠加）。

## 打包注意
- `keyboard` 要进 PyInstaller hiddenimports（验证能收进去）。
- 托盘图标复用 `assets/icon.png`（find_icon()）。

## 验证计划（Windows 真机）
1. 装 keyboard，源码跑 → 按住热键说中文 → 看草稿浮窗是否边说边出字 → 松开后输入框是否出现最终文本。
2. 对比草稿(zipformer)与最终(SenseVoice)文本，确认两阶段都正常、定稿更准。
3. 切换注入方式（粘贴 vs 键入）对比中文准确性。
4. 切换式触发测长段口述（含中途 endpoint 多句拼接）。
5. 打包后验证热键、浮窗与注入仍工作。

## 不在本期范围
- 翻译注入（说中→注英）：留后，复用 translator。
- macOS 实现：留后，injector/hotkey 已抽象，补 pynput 实现 + 辅助功能权限引导。
