"""翻译层:DeepSeek API。

只翻译已定稿(committed)的句子。要点:
  * 异步:放后台线程跑,不阻塞 ASR 主循环。
  * 带上下文:把最近几句已译内容作为上下文,保证术语/代词一致、措辞连贯。
  * 缓存:相同原文不重复请求,省钱省延迟。
  * 优雅降级:没有 API key 或请求失败时,返回占位串,不影响晃动验证。

key 从环境变量 DEEPSEEK_API_KEY 读,绝不硬编码。
"""

from __future__ import annotations

import os
import queue
import threading
from collections import OrderedDict, deque
from typing import Callable, Optional

import requests

API_URL = "https://api.deepseek.com/chat/completions"
MODEL = "deepseek-chat"


class Translator:
    def __init__(
        self,
        on_result: Callable[[int, str], None],
        target_lang: str = "英文",
        context_size: int = 3,
        api_key: str = "",
        cache_max: int = 2000,
    ) -> None:
        """on_result(seg_id, translation): 译文就绪时回调(在后台线程中)。

        api_key 优先用传入的(来自设置),否则回退到环境变量 DEEPSEEK_API_KEY。
        context_size: 给 LLM 的上下文只保留最近这么多句(deque 自动丢旧),
                      所以无论视频多长,每次请求 prompt 大小恒定,不会爆。
        cache_max: 译文缓存条数上限,超了丢最旧的,长视频也不会无限占内存。
        """
        self.on_result = on_result
        self.target_lang = target_lang
        self.enabled = True         # 「不翻译」模式置 False,submit 直接跳过
        self.api_key = (api_key or os.environ.get("DEEPSEEK_API_KEY", "")).strip()
        self._q: queue.Queue[Optional[tuple[int, str, bool]]] = queue.Queue()
        self._inflight = 0          # 已提交但未完成的翻译数(含请求中)
        self._inflight_lock = threading.Lock()
        self._cache: "OrderedDict[tuple[str, str], str]" = OrderedDict()
        self._cache_max = cache_max
        self._history: deque[tuple[str, str]] = deque(maxlen=context_size)
        self._worker = threading.Thread(target=self._run, daemon=True)
        self._worker.start()

    def submit(self, seg_id: int, text: str, quick: bool = False) -> None:
        """提交一句已定稿文本去翻译(立即返回)。

        临时和最终译文都带上下文以保证质量;quick=True(临时)仅表示"不写回历史"
        (因为临时文本会被 SenseVoice 最终版替换,不该污染后续上下文)。
        """
        if not self.enabled:
            return                  # 「不翻译」模式:不发起任何翻译请求
        with self._inflight_lock:
            self._inflight += 1
        self._q.put((seg_id, text, quick))

    def join(self, timeout: float = 30.0) -> None:
        """阻塞直到所有已提交的翻译真正完成(含正在请求中的),不会漏译也不会空等。"""
        import time
        deadline = time.time() + timeout
        while self._inflight > 0 and time.time() < deadline:
            time.sleep(0.05)

    def close(self) -> None:
        self._q.put(None)

    def _cache_put(self, key, value) -> None:
        """带上限的缓存写入:超出 cache_max 丢最旧的(LRU 式),防长视频内存膨胀。"""
        self._cache[key] = value
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_max:
            self._cache.popitem(last=False)

    # ---------- 后台线程 ----------

    def _run(self) -> None:
        while True:
            item = self._q.get()
            if item is None:
                break
            seg_id, text, quick = item
            try:
                translation = self._translate(text, quick=quick)
                self.on_result(seg_id, translation)
            except Exception:
                pass        # 单条翻译/回调出错不应杀死 worker 线程
            finally:
                with self._inflight_lock:
                    self._inflight -= 1

    def _translate(self, text: str, quick: bool = False) -> str:
        # 先把目标语种取到局部变量:整次翻译用同一个语种,避免中途被 GUI 改掉
        # 导致缓存键和实际译文语种不一致(英文 key 存了日文译文)。
        lang = self.target_lang
        key = (lang, text)
        if key in self._cache:
            return self._cache[key]
        if not self.api_key:
            return "[未设置 DEEPSEEK_API_KEY,跳过翻译]"
        try:
            result = self._call_api(text, lang, quick=quick)
        except Exception as e:  # 网络/限流等,降级不崩(不缓存,下次可重试)
            return f"[翻译失败: {type(e).__name__}]"
        self._cache_put(key, result)
        # 只有最终译文入历史(临时译文是 Pass1 草稿,不污染上下文)
        if not quick:
            self._history.append((text, result))
        return result

    SYSTEM_PROMPT = (
        "你是专业的实时字幕翻译。输入文本来自语音识别(ASR),可能含有"
        "同音字错误(如人名、地名、专有名词被识别成发音相近的字)。"
        "请结合上下文推断说话人的真实意思后再翻译,纠正明显的同音误识,"
        "不要把错字直译。译文要准确、口语化、简洁。"
    )

    def _call_api(self, text: str, lang: str, quick: bool = False) -> str:
        # 临时和最终译文都注入上下文(术语/语境一致);区别只在临时译文不写回历史。
        # 上下文只取 _history(deque 限长,最近几句),所以不随视频变长而膨胀。
        ctx = ""
        if self._history:
            lines = [f"原文:{s}\n译文:{t}" for s, t in self._history]
            ctx = (
                "【已翻译的上文,供理解语境、保持术语和风格一致】\n"
                + "\n".join(lines)
                + "\n\n"
            )
        prompt = (
            f"{ctx}请把下面这句(ASR 识别结果,可能有同音错字)翻译成"
            f"{lang}。只输出译文本身,不要任何解释、引号或前缀:\n{text}"
        )
        resp = requests.post(
            API_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": MODEL,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 1.3,
                "stream": False,
            },
            timeout=20,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
