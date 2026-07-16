"""把纪要/字幕文本切成适合朗读的"段"(不是逐句):按目标字数攒够整句再切,
在段内交给 ChatTTS 做一次连续的流式合成(段内音色/韵律连贯、无缝),只在
段与段之间(必要的独立 GPT 调用)才有起势的成本。

为什么不逐句切:ChatTTS 的 GPT 每次独立调用都要重新"起势"(prefill 阶段
的语调状态从头采样),逐句切会让每句话都短促生硬、句间听感割裂。攒到
一定长度再合成,段内部靠真流式(见 chattts_engine.py 的 on_chunk 回调)
边生成边播放,消除人为分句造成的割裂,只保留物理上必要的长文本分段。
"""

from __future__ import annotations

import re

# 中英文句末标点(含配对的右引号/括号,允许标点紧跟其后不被切开)
_SENT_END = re.compile(r'([。！？!?])(["\')\]]*)')
_MD_STRIP = re.compile(r'^#{1,6}\s*|^[-*]\s+|\*\*|__|`')

# 目标段长和硬上限都按字符计;硬上限避免单个超长句触发模型长度截断。
TARGET_CHARS = 100
MAX_CHARS = 180
MIN_CHARS = 24


def _clean_line(line: str) -> str:
    """去掉 Markdown 标题/列表/加粗/代码符号,保留纯文字内容供朗读。"""
    line = _MD_STRIP.sub("", line.strip())
    return line.strip()


def _split_raw_sentences(text: str) -> list[str]:
    """按句末标点切出原始句子列表(逐行处理,过滤 Markdown 符号)。"""
    sentences: list[str] = []
    for raw_line in text.splitlines():
        line = _clean_line(raw_line)
        if not line:
            continue
        parts = _SENT_END.split(line)
        buf = ""
        i = 0
        while i < len(parts):
            buf += parts[i]
            if i + 1 < len(parts) and parts[i + 1] in ("。", "！", "？", "!", "?"):
                buf += parts[i + 1]
                if i + 2 < len(parts):
                    buf += parts[i + 2]  # 配对引号/括号
                sentences.append(buf.strip())
                buf = ""
                i += 3
            else:
                i += 1
        if buf.strip():
            sentences.append(buf.strip())
    return [s for s in sentences if s]


def _split_long_sentence(sentence: str, max_chars: int) -> list[str]:
    if len(sentence) <= max_chars:
        return [sentence]
    parts: list[str] = []
    rest = sentence
    while len(rest) > max_chars:
        cut = max_chars
        for mark in ("，", "、", "：", ",", ":", " "):
            pos = rest.rfind(mark, 0, max_chars + 1)
            if pos >= max_chars // 2:
                cut = pos + 1
                break
        parts.append(rest[:cut].strip())
        rest = rest[cut:].strip()
    if rest:
        parts.append(rest)
    return parts


def split_into_chunks(text: str, target_chars: int = TARGET_CHARS) -> list[str]:
    """按语义边界合并句子,短句不单独起势,超长句在停顿处硬切。"""
    sentences = _split_raw_sentences(text)
    expanded: list[str] = []
    for sentence in sentences:
        expanded.extend(_split_long_sentence(sentence, MAX_CHARS))

    chunks: list[str] = []
    buf = ""
    for sentence in expanded:
        if not buf:
            buf = sentence
            continue
        if len(buf) + len(sentence) <= target_chars:
            buf += sentence
        elif len(buf) < MIN_CHARS:
            buf += sentence
        else:
            chunks.append(buf)
            buf = sentence
    if buf:
        chunks.append(buf)
    return chunks


def split_sentences(text: str, min_len: int = 4) -> list[str]:
    """按句末标点切句(逐句,不合并到目标长度)。保留供需要逐句颗粒度的场景用;
    朗读主流程用 split_into_chunks(见上)按目标字数分段,避免逐句割裂。"""
    sentences = _split_raw_sentences(text)
    merged: list[str] = []
    for s in sentences:
        if merged and len(s) < min_len:
            merged[-1] = merged[-1] + s
        else:
            merged.append(s)
    return merged
