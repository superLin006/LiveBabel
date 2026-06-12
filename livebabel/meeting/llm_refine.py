"""LLM 兜底矫正说话人归属。

声纹分离(diarize)给出初步归属后,把「带序号+当前说话人标签的转录」交给 DeepSeek,
让它根据对话逻辑(谁在提问、谁在回答、话题连贯性、人称等)重新判断每条该归谁,
**只改说话人归属,不改任何文字**。声纹偶尔归错的句子由此纠正。

返回 {序号: 新说话人标签},调用方据此改 speaker。无 key / 失败时返回 {}(不矫正,
保留声纹结果),不影响主流程。
"""

from __future__ import annotations

import json
import os
import re
from typing import Dict, List, Tuple

import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"

SYSTEM_PROMPT = (
    "你是会议转录的说话人校正助手。输入是带序号和【初步说话人标签】的逐句转录"
    "(标签来自声纹聚类,可能有错)。请只根据对话逻辑(提问/回答、话题连贯、人称、"
    "称呼、语气)重新判断每一句真正是谁说的。\n"
    "规则:\n"
    "1. 只调整说话人归属,绝不修改、增删任何文字。\n"
    "2. 说话人标签沿用输入里出现过的那些(如 远端-发言人1 / 远端-发言人2),不要新造。\n"
    "3. 人数保持和输入一致,不要凭空增加说话人。\n"
    "4. 严格输出 JSON:{\"序号\": \"说话人标签\", ...},只含需要【改动】的序号,"
    "没改的不用列。不要输出任何解释。"
)


def refine_with_llm(items: List[Tuple[int, str, str]], api_key: str = "",
                    timeout: int = 120) -> Dict[int, str]:
    """items: [(序号, 当前说话人, 文本)]。返回 {序号: 新说话人}(只含改动项)。

    无 key / 请求失败 / 解析失败 → 返回 {}(不矫正)。
    """
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key or not items:
        return {}

    # 收集合法标签集合(LLM 不得超出)
    valid = {spk for _, spk, _ in items}
    lines = [f"{idx}\t{spk}\t{text}" for idx, spk, text in items]
    user = (
        "下面每行格式为「序号<TAB>初步说话人<TAB>文本」。请重新判断归属,"
        "只输出改动项的 JSON({序号:说话人}):\n\n" + "\n".join(lines)
    )
    try:
        resp = requests.post(
            API_URL,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user},
                ],
                "temperature": 0.2,
                "stream": False,
            },
            timeout=timeout,
        )
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return {}

    # 提取 JSON(模型可能包了 ```json```)
    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return {}
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return {}

    out: Dict[int, str] = {}
    for k, v in raw.items():
        try:
            idx = int(k)
        except Exception:
            continue
        spk = str(v).strip()
        if spk in valid:          # 只接受输入里出现过的合法标签
            out[idx] = spk
    return out
