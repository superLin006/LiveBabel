"""离线批量翻译:把识别出的句子逐句翻译,带滚动上下文。

离线场景不需要实时/异步,直接顺序翻译即可,简单可靠。每句翻译时把前几句的
(原文,译文)作为上下文,保证术语/代词一致。复用与实时一致的 DeepSeek 调用方式。
"""

from __future__ import annotations

import os
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


def translate_sentences(
    sentences: List[Sentence],
    target_lang: str = "中文",
    api_key: str = "",
    context_size: int = 3,
    on_progress=None,
) -> None:
    """就地给每个 Sentence 填 translation。api_key 缺省读环境变量 DEEPSEEK_API_KEY。"""
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    history: "deque[tuple[str, str]]" = deque(maxlen=context_size)

    for i, s in enumerate(sentences):
        if not api_key:
            s.translation = "[未设置 DEEPSEEK_API_KEY]"
            continue
        try:
            s.translation = _call(s.text, target_lang, api_key, history)
            history.append((s.text, s.translation))
        except Exception as e:
            s.translation = f"[翻译失败: {type(e).__name__}]"
        if on_progress:
            on_progress(i + 1, len(sentences))


def _call(text: str, lang: str, api_key: str, history) -> str:
    ctx = ""
    if history:
        lines = [f"原文:{a}\n译文:{b}" for a, b in history]
        ctx = "【上文供参考,保持术语/风格一致】\n" + "\n".join(lines) + "\n\n"
    prompt = (
        f"{ctx}请把下面这句翻译成{lang},只输出译文,不要解释/引号/前缀:\n{text}"
    )
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 1.3,
            "stream": False,
        },
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
