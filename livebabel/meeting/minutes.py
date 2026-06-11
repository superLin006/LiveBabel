"""会议纪要:把带说话人的转录交 DeepSeek 生成结构化纪要,并导出 Markdown/TXT。

与实时模式的 summarizer 区别:输入带「说话人:」前缀,提示 LLM 按发言人归纳立场/职责,
这样"决策""待办"能落到具体人。无 key 或失败抛 RuntimeError。
"""

from __future__ import annotations

import os
import time
from typing import List

import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是专业的会议纪要助手。输入是带说话人标注和时间戳的语音识别转录,"
    "可能有同音字/断句错误,请结合上下文理解真实意思,纠正明显误识。"
    "注意区分不同说话人的立场与职责。"
)

PROMPTS = {
    "structured": (
        "请把下面这场会议整理成结构化纪要,用 Markdown 输出,包含(没有的小节可省略,不编造):\n"
        "## 会议摘要(2-3 句话)\n"
        "## 参会人(根据转录里出现的说话人)\n"
        "## 关键讨论点(分条,可注明是谁提出)\n"
        "## 结论 / 决策\n"
        "## 待办事项(尽量标明负责人)\n"
        "只输出纪要本身,不要寒暄。\n\n会议转录如下:\n"
    ),
    "brief": (
        "请用 Markdown 列出下面这场会议的核心要点(6 条以内 bullet,涉及谁说的可注明),"
        "最后加一句话总结。只输出要点。\n\n会议转录如下:\n"
    ),
}


def make_minutes(
    transcript_lines: List[str],
    style: str = "structured",
    api_key: str = "",
    timeout: int = 180,
) -> str:
    """transcript_lines: 形如 "[00:12] 我:……" 的行。返回 Markdown 纪要。"""
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key:
        raise RuntimeError("未设置 DeepSeek API Key,无法生成纪要。")
    text = "\n".join(l for l in transcript_lines if l.strip())
    if not text:
        raise RuntimeError("还没有可总结的会议内容。")

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
            "temperature": 0.3,
            "stream": False,
        },
        timeout=timeout,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def export_markdown(transcript_lines: List[str], minutes_md: str, path: str,
                    title: str = "会议纪要") -> None:
    """导出:标题 + 纪要 + 完整转录。Markdown。"""
    ts = time.strftime("%Y-%m-%d %H:%M")
    parts = [f"# {title}", f"*{ts}*", ""]
    if minutes_md:
        parts += [minutes_md, "", "---", ""]
    parts += ["## 完整转录", "```", *transcript_lines, "```"]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))


def export_txt(transcript_lines: List[str], minutes_md: str, path: str,
               title: str = "会议纪要") -> None:
    ts = time.strftime("%Y-%m-%d %H:%M")
    parts = [title, ts, ""]
    if minutes_md:
        parts += ["【纪要】", minutes_md, "", "-" * 30, ""]
    parts += ["【完整转录】", *transcript_lines]
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(parts))
