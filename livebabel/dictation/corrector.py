"""Optional DeepSeek post-correction for voice input.

Correction runs only after the user releases the hotkey. Draft text is never
sent to the network, so enabling it does not add latency to live ASR.
"""

from __future__ import annotations

import os

import requests


API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是语音输入文本校正助手。输入来自中文或中英混合语音识别，"
    "可能包含无意义的语气词、同音错字、漏字和明显的识别错误。"
    "只在有充分把握时修正，不要改变原意，不要补充输入中没有的事实，"
    "不要总结、翻译或解释。尽量保留用户的口吻和分段。"
)


def correct_text(text: str, api_key: str = "", timeout: int = 30) -> str:
    """Correct one finished dictation result and return plain text."""
    text = (text or "").strip()
    if not text:
        return ""
    key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not key:
        raise RuntimeError("未设置 DeepSeek API Key，无法进行 AI 矫正")
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": "请只输出校正后的文本，不要加引号、说明或 Markdown。\n\n原始听写：\n" + text},
            ],
            "temperature": 0.0,
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    try:
        out = resp.json()["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError, AttributeError) as exc:
        raise RuntimeError("DeepSeek AI 矫正返回格式异常") from exc
    if not out:
        raise RuntimeError("DeepSeek AI 矫正返回空文本")
    return out
