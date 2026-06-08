"""控制台显示层:用颜色直观展示"晃动消除"。

  * committed(已定稿):亮白原文 + 青色译文,稳定不再变。
  * volatile(未定稿):暗灰原文 + 闪烁光标,会不断变化(这就是被隔离的"晃动")。

用 rich.Live 原地刷新,模拟弹幕区。这是验证阶段的 UI,
正式版会换成 Windows 透明置顶窗口。
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console, Group
from rich.live import Live
from rich.panel import Panel
from rich.text import Text

from livebabel.commit_manager import CommitManager


class ConsoleDisplay:
    def __init__(self, manager: CommitManager, n_show: int = 4) -> None:
        self.manager = manager
        self.n_show = n_show
        self.console = Console()
        self._live = Live(console=self.console, refresh_per_second=12, screen=False)

    def __enter__(self):
        self._live.__enter__()
        return self

    def __exit__(self, *a):
        self.refresh()
        self._live.__exit__(*a)

    def refresh(self) -> None:
        committed, volatile = self.manager.recent(self.n_show)
        lines: list[Text] = []
        for seg in committed:
            lines.append(Text(f"  {seg.text}", style="bold white"))
            tr = seg.translation if seg.translation is not None else "翻译中…"
            lines.append(Text(f"  ↳ {tr}", style="cyan"))
            lines.append(Text(""))
        if volatile is not None:
            lines.append(Text(f"  {volatile.text} ▎", style="dim italic"))
        body = Group(*lines) if lines else Text("(等待语音…)", style="dim")
        self._live.update(
            Panel(body, title="实时双语字幕(白=定稿 灰=未定稿)", border_style="green")
        )
