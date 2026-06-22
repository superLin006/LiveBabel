"""把实时模式识别到的内容做摘要(DeepSeek)。

实时字幕窗点「总结」时,取本场已定稿的原文,整段发给 DeepSeek 出会议/内容摘要。
不区分说话人。两种风格:结构化纪要 / 简洁要点。同步调用(放后台线程跑,别卡 UI)。

key 从设置或环境变量 DEEPSEEK_API_KEY 读,绝不硬编码。
"""

from __future__ import annotations

import os
from typing import List

import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是专业的会议/内容纪要助手。输入是一段连续语音识别(ASR)文本,"
    "可能有同音字或断句错误,请结合上下文理解真实意思后再总结,纠正明显误识。"
)

# 两种摘要风格的用户指令
PROMPTS = {
    "structured": (
        "请把下面这段内容整理成结构化纪要,用 Markdown 输出,包含这些小节"
        "(没有的小节可省略,不要编造):\n"
        "## 摘要(2-3 句话概述)\n"
        "## 关键讨论点(分条)\n"
        "## 结论 / 决策\n"
        "## 待办事项(若有,标明事项)\n"
        "只输出纪要本身,不要寒暄。\n\n内容如下:\n"
    ),
    "brief": (
        "请用 Markdown 列出下面这段内容的核心要点(5 条以内的 bullet),"
        "最后加一句话总结。只输出要点,不要寒暄。\n\n内容如下:\n"
    ),
}


def summarize(
    transcript: List[str],
    style: str = "structured",
    api_key: str = "",
    timeout: int = 120,
) -> str:
    """把 transcript(每句一条)合并后请求 DeepSeek,返回 Markdown 摘要。

    style: "structured"(结构化纪要)/ "brief"(简洁要点)。
    无 key 或失败抛 RuntimeError,调用方(后台线程)捕获后回报 UI。
    """
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("未设置 DeepSeek API Key,无法生成摘要。")

    text = "\n".join(s.strip() for s in transcript if s.strip())
    if not text:
        raise RuntimeError("还没有可总结的内容。")

    prompt = PROMPTS.get(style, PROMPTS["structured"]) + text
    resp = requests.post(
        API_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "model": MODEL,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.3,      # 摘要要稳定,低温度
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()
