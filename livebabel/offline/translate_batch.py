"""离线批量翻译:把识别出的句子分批(默认每批 10 句)翻译,带滚动上下文。

逐句翻译会发很多次 HTTP 请求(网络往返是大头),慢。一次发一批让模型整体翻译,
请求数降一个量级,且整体翻译上下文更完整、术语更一致,质量通常更好。
风险是模型返回的行数和输入对不齐 → 用编号约定 + 数量校验,不齐就回退逐句翻译这一批,
保证绝不串轴。复用与实时一致的 DeepSeek 调用方式。
"""

from __future__ import annotations

import os
import re
from collections import deque
from typing import List, Optional

import requests

from livebabel.offline.transcribe import Sentence

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是专业的字幕翻译。输入文本来自语音识别,可能含有同音字或识别错误,"
    "请结合上下文推断真实意思后翻译,纠正明显误识。译文准确、口语化、简洁,"
    "只输出译文本身。"
)

BATCH_SIZE = 10          # 每批句数;批量翻译可显著减少请求数


def translate_sentences(
    sentences: List[Sentence],
    target_lang: str = "中文",
    api_key: str = "",
    context_size: int = 3,
    batch_size: int = BATCH_SIZE,
    on_progress=None,
) -> None:
    """就地给每个 Sentence 填 translation。api_key 缺省读环境变量 DEEPSEEK_API_KEY。

    分批翻译:每 batch_size 句一次请求;某批数量对不齐时自动回退该批逐句翻译。
    on_progress(done, total) 按已完成句数回调。
    """
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    total = len(sentences)
    if not api_key:
        for s in sentences:
            s.translation = "[未设置 DEEPSEEK_API_KEY]"
        if on_progress:
            on_progress(total, total)
        return

    history: "deque[tuple[str, str]]" = deque(maxlen=context_size)
    done = 0
    for start in range(0, total, batch_size):
        batch = sentences[start : start + batch_size]
        texts = [s.text for s in batch]
        try:
            outs = _call_batch(texts, target_lang, api_key, history)
        except Exception:
            outs = None
        if not outs or len(outs) != len(batch):
            # 批量失败或数量对不齐 → 这一批逐句翻译,保证对齐不串轴
            outs = []
            for t in texts:
                try:
                    outs.append(_call_single(t, target_lang, api_key, history))
                except Exception as e:
                    outs.append(f"[翻译失败: {type(e).__name__}]")

        for s, tr in zip(batch, outs):
            s.translation = tr
            # 滚动上下文:只记成功译出的句子
            if tr and not tr.startswith("[翻译失败") and not tr.startswith("[未设置"):
                history.append((s.text, tr))
        done += len(batch)
        if on_progress:
            on_progress(done, total)


def _ctx_block(history) -> str:
    if not history:
        return ""
    lines = [f"原文:{a}\n译文:{b}" for a, b in history]
    return "【上文供参考,保持术语/风格一致】\n" + "\n".join(lines) + "\n\n"


def _post(messages, api_key: str) -> str:
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"model": MODEL, "messages": messages, "temperature": 1.3, "stream": False},
        timeout=60,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def _call_batch(texts: List[str], lang: str, api_key: str, history) -> Optional[List[str]]:
    """一次翻译多句,返回与输入等长的译文列表;解析失败返回 None。

    约定模型按 "序号. 译文" 逐行返回,便于按编号切回去。
    """
    numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
    prompt = (
        f"{_ctx_block(history)}"
        f"请把下面这 {len(texts)} 句逐句翻译成{lang}。"
        f"严格按「序号. 译文」的格式逐行输出,共 {len(texts)} 行,"
        f"序号与原文一一对应,不要合并/拆分/增减行,不要解释:\n{numbered}"
    )
    content = _post([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ], api_key)
    return _parse_numbered(content, len(texts))


def _parse_numbered(content: str, n: int) -> Optional[List[str]]:
    """把 "1. xxx\n2. yyy" 解析成列表;按序号归位,缺号/超量则判失败返回 None。"""
    out: List[Optional[str]] = [None] * n
    for line in content.splitlines():
        m = re.match(r"\s*(\d+)\s*[.、:：)]\s*(.*)", line)
        if not m:
            continue
        idx = int(m.group(1)) - 1
        if 0 <= idx < n:
            out[idx] = m.group(2).strip()
    if any(x is None for x in out):
        return None
    return out  # type: ignore[return-value]


def _call_single(text: str, lang: str, api_key: str, history) -> str:
    """单句翻译(批量对不齐时的回退路径)。"""
    prompt = (
        f"{_ctx_block(history)}"
        f"请把下面这句翻译成{lang},只输出译文,不要解释/引号/前缀:\n{text}"
    )
    return _post([
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": prompt},
    ], api_key)
