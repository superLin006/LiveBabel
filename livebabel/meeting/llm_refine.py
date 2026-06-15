"""LLM 辅助优化会议转录(声纹分离之后的增强层)。

声纹负责"谁说的"(它有声音信息,是强项);LLM 负责它擅长、声纹做不到的事:
  1. 给说话人起名/角色:把抽象的"发言人1/2"识别成"面试官/应聘者",或从对话里
     认出自报的真名(如有人说"我叫小林"),输出 标签→显示名 映射。
  2. 纠正 ASR 同音错字 / 人名术语:结合上下文把识别错的字纠回(追蜜→追觅),
     只做"等长/近义"的小修,不重写句子。
  3. 仅在声纹归属与对话逻辑【明显矛盾】处轻量改归属(不全量重判——声纹通常更准)。

返回结构化结果,各项都做严格校验后由调用方择优应用。无 key/失败返回空结果
(不动声纹结果),不影响主流程。
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Dict, List, Tuple

import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


@dataclass
class RefineResult:
    names: Dict[str, str] = field(default_factory=dict)      # 说话人标签 -> 显示名/角色
    fixes: Dict[int, str] = field(default_factory=dict)      # 序号 -> 纠错后文本
    reassign: Dict[int, str] = field(default_factory=dict)   # 序号 -> 改后的说话人标签


SYSTEM_PROMPT = (
    "你是会议/面试转录的优化助手。输入是按时间排序的逐句转录,每行带【序号】和"
    "【说话人标签】(标签来自声纹聚类,一般可信)。请完成三件事并只输出 JSON:\n"
    "1. names:为每个出现的说话人标签起一个贴切的显示名或角色"
    "(如 面试官/应聘者/主持人;若某人自报姓名则用姓名)。键必须是输入里出现过的标签。\n"
    "2. fixes:挑出明显的语音识别同音错字/人名/术语错误,给出纠正后的整句。"
    "只做小幅纠错(意思和长度基本不变),不要改写、扩写、润色。键是序号。\n"
    "3. reassign:仅当某句的说话人标签与对话逻辑【明显矛盾】(例如明显是提问却标成"
    "应聘者)时,改其标签;不确定就不要改。键是序号,值必须是输入出现过的标签。\n"
    "输出严格 JSON:{\"names\":{...},\"fixes\":{\"序号\":\"整句\"},"
    "\"reassign\":{\"序号\":\"标签\"}}。无需改动的项不要列。不要输出 JSON 之外的任何内容。"
)


def refine(items: List[Tuple[int, str, str]], api_key: str = "",
           timeout: int = 120) -> RefineResult:
    """items: [(序号, 说话人标签, 文本)]。返回 RefineResult(已校验)。

    无 key / 请求失败 / 解析失败 → 返回空 RefineResult。
    """
    res = RefineResult()
    api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
    if not api_key or not items:
        return res

    valid_labels = {spk for _, spk, _ in items}
    by_idx = {idx: text for idx, _, text in items}
    lines = [f"{idx}\t{spk}\t{text}" for idx, spk, text in items]
    user = ("每行格式「序号<TAB>说话人<TAB>文本」:\n\n" + "\n".join(lines))
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
        return res

    m = re.search(r"\{.*\}", content, re.S)
    if not m:
        return res
    try:
        raw = json.loads(m.group(0))
    except Exception:
        return res

    # —— names:键必须是合法标签,值非空且不太长 ——
    for k, v in (raw.get("names") or {}).items():
        k = str(k).strip()
        v = str(v).strip()
        if k in valid_labels and 0 < len(v) <= 20:
            res.names[k] = v

    # —— fixes:只接受"小幅纠错"(长度变化不超过 ±30% 且 ≥0.6 相似),防 LLM 改写 ——
    for k, v in (raw.get("fixes") or {}).items():
        try:
            idx = int(k)
        except Exception:
            continue
        orig = by_idx.get(idx)
        new = str(v).strip()
        if not orig or not new or new == orig:
            continue
        if abs(len(new) - len(orig)) > max(3, int(len(orig) * 0.3)):
            continue                         # 长度变化过大 → 疑似改写,丢弃
        if _char_overlap(orig, new) < 0.6:
            continue                         # 和原文重合太低 → 疑似乱改,丢弃
        res.fixes[idx] = new

    # —— reassign:值必须是合法标签 ——
    for k, v in (raw.get("reassign") or {}).items():
        try:
            idx = int(k)
        except Exception:
            continue
        spk = str(v).strip()
        if idx in by_idx and spk in valid_labels:
            res.reassign[idx] = spk
    return res


def _char_overlap(a: str, b: str) -> float:
    """两串的字符集合 Jaccard 相似度(粗判是否只是小改而非乱写)。"""
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)
