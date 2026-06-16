"""把带时间戳的双语句子写成字幕文件。

  * SRT:纯文本,最兼容(视频网站、所有播放器)。双语为原文一行 + 译文一行。
  * ASS:带样式,原文白色、译文青色,可控字体/描边/位置。双语配色更好看。

输入是 transcribe.Sentence 列表(已填 translation)。
"""

from __future__ import annotations

from typing import List

from livebabel.offline.transcribe import Sentence


# ---------- 时间戳格式 ----------

def _srt_ts(sec: float) -> str:
    """SRT 时间戳 HH:MM:SS,mmm"""
    if sec < 0:
        sec = 0
    ms = int(round((sec - int(sec)) * 1000))
    s = int(sec)
    return f"{s // 3600:02d}:{(s % 3600) // 60:02d}:{s % 60:02d},{ms:03d}"


def _ass_ts(sec: float) -> str:
    """ASS 时间戳 H:MM:SS.cc(厘秒)"""
    if sec < 0:
        sec = 0
    cs = int(round((sec - int(sec)) * 100))
    s = int(sec)
    return f"{s // 3600:d}:{(s % 3600) // 60:02d}:{s % 60:02d}.{cs:02d}"


# ---------- SRT ----------

def write_srt(sentences: List[Sentence], path: str, bilingual: bool = True) -> None:
    lines: List[str] = []
    for i, s in enumerate(sentences, 1):
        lines.append(str(i))
        lines.append(f"{_srt_ts(s.start)} --> {_srt_ts(s.end)}")
        lines.append(s.text)
        if bilingual and s.translation:
            lines.append(s.translation)
        lines.append("")          # 空行分隔
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------- ASS ----------

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; 原文:白色,稍大;译文:青色,稍小。&H..& 是 ASS 颜色,格式 AABBGGRR。
; 两行都底部居中(Alignment=2),靠 MarginV 上下错开:译文在底(30),原文在其上(95)。
; 间距 65px 容得下 48~54 号字,不重叠。描边 3px 保证压在视频原有字幕上也看得清。
Style: Source,Microsoft YaHei,54,&H00FFFFFF,&H00000000,&H80000000,0,0,1,3,1,2,40,40,95,1
Style: Trans,Microsoft YaHei,48,&H00FFE77F,&H00000000,&H80000000,0,0,1,3,1,2,40,40,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""


def _ass_escape(text: str) -> str:
    # ASS 里换行是 \N,大括号是控制符,做基本转义
    return text.replace("{", "(").replace("}", ")").replace("\n", " ")


def write_ass(sentences: List[Sentence], path: str, bilingual: bool = True) -> None:
    rows: List[str] = [_ASS_HEADER]
    for s in sentences:
        start, end = _ass_ts(s.start), _ass_ts(s.end)
        # 译文用 Trans 样式(靠下),原文用 Source 样式(在译文上方)
        if bilingual and s.translation:
            rows.append(f"Dialogue: 0,{start},{end},Trans,,0,0,0,,{_ass_escape(s.translation)}")
        rows.append(f"Dialogue: 0,{start},{end},Source,,0,0,0,,{_ass_escape(s.text)}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(rows) + "\n")
