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
    # utf-8-sig 写入 BOM:很多 Windows 播放器(PotPlayer 等)对无 BOM 文本默认按
    # GBK/ANSI 解码,会把 UTF-8 中文显示成乱码。带 BOM 后所有播放器都能正确识别。
    with open(path, "w", encoding="utf-8-sig") as f:
        f.write("\n".join(lines))


# ---------- ASS ----------

_ASS_HEADER = """[Script Info]
ScriptType: v4.00+
PlayResX: 1920
PlayResY: 1080
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
; 完整 V4+ 字段。&H..& 颜色格式 AABBGGRR。原文白(大)在上,译文青(小)在下,
; 靠 MarginV(距底距离)错开:译文在底(30),原文在其上(125)。距底差 95px,
; 减去 54 号字实际字高(~70px)后净行间空隙 ~25px,上下分明又不脱节。
; Spacing=字符间距:之前字母挤在一起,原文设 1、译文(常含英文)设 2 撑开,更舒服。
Style: Source,Microsoft YaHei,54,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,0,0,0,0,100,100,1,0,1,3,1,2,40,40,125,1
Style: Trans,Microsoft YaHei,48,&H00FFE77F,&H00FFE77F,&H00000000,&H80000000,0,0,0,0,100,100,2,0,1,3,1,2,40,40,30,1

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
    with open(path, "w", encoding="utf-8-sig") as f:   # BOM:防播放器按 GBK 读成乱码
        f.write("\n".join(rows) + "\n")
