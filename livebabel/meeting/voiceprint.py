"""声纹库:登记认识的人(姓名 + 声纹向量),会后说话人分离时自动比对认人。

从历史会议里登记——开完会、分好说话人、确认"发言人2 就是张三",把那个聚类的
代表声纹(质心向量)以"张三"存入库。下次开会 diarize 后,拿每个聚类的质心和库里
每个人比 cosine,够像(≥阈值)才自动标真名,不够像就保留"发言人N"(宁可不认不认错)。

存于 history/voiceprints.json(L2 归一化向量),纯 numpy,无额外依赖。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# 自动认人的相似度阈值:cosine ≥ 此值才标真名。实测同人 0.7+、不同人 0.15~0.35,
# 取 0.6 偏保守(宁可漏认不误认)。可按实际微调。
MATCH_THRESHOLD = 0.6


def _store_path() -> str:
    from livebabel.paths import HISTORY_DIR
    os.makedirs(HISTORY_DIR, exist_ok=True)
    return os.path.join(HISTORY_DIR, "voiceprints.json")


@dataclass
class Voiceprint:
    name: str
    vec: list           # L2 归一化的 embedding(list[float],便于 JSON)
    enrolled: float     # 登记时间(epoch 秒)
    samples: int = 1    # 累积登记次数(同名多次登记取平均)


def _load() -> Dict[str, Voiceprint]:
    path = _store_path()
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        out = {}
        for name, d in raw.items():
            out[name] = Voiceprint(name=name, vec=d["vec"],
                                   enrolled=d.get("enrolled", 0.0),
                                   samples=d.get("samples", 1))
        return out
    except Exception:
        return {}


def _save(db: Dict[str, Voiceprint]) -> None:
    path = _store_path()
    data = {n: {"vec": vp.vec, "enrolled": vp.enrolled, "samples": vp.samples}
            for n, vp in db.items()}
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    os.replace(tmp, path)            # 原子替换,防写一半损坏


def _normalize(vec) -> list:
    import numpy as np
    v = np.asarray(vec, dtype=np.float32)
    n = float(np.linalg.norm(v))
    return (v / (n + 1e-9)).tolist()


def list_names() -> List[str]:
    return sorted(_load().keys())


def enroll(name: str, vec) -> None:
    """登记/更新一个人的声纹。同名已存在则与旧向量加权平均(增量,越登越稳)。"""
    name = (name or "").strip()
    if not name:
        raise ValueError("姓名不能为空")
    import numpy as np
    nv = np.asarray(_normalize(vec), dtype=np.float32)
    db = _load()
    if name in db:
        old = np.asarray(db[name].vec, dtype=np.float32)
        s = db[name].samples
        merged = (old * s + nv) / (s + 1)
        merged = (merged / (np.linalg.norm(merged) + 1e-9))
        db[name] = Voiceprint(name=name, vec=merged.tolist(),
                              enrolled=time.time(), samples=s + 1)
    else:
        db[name] = Voiceprint(name=name, vec=nv.tolist(),
                              enrolled=time.time(), samples=1)
    _save(db)


def remove(name: str) -> None:
    db = _load()
    if name in db:
        del db[name]
        _save(db)


def match(vec, threshold: float = MATCH_THRESHOLD) -> Optional[Tuple[str, float]]:
    """拿一个声纹向量和库里每个人比 cosine,返回 (最像的人名, 相似度);
    最高相似度 < threshold 则返回 None(不够像,不认)。"""
    db = _load()
    if not db:
        return None
    import numpy as np
    q = np.asarray(_normalize(vec), dtype=np.float32)
    best_name, best_sim = None, -1.0
    for name, vp in db.items():
        sim = float(np.dot(q, np.asarray(vp.vec, dtype=np.float32)))
        if sim > best_sim:
            best_name, best_sim = name, sim
    if best_sim >= threshold:
        return best_name, best_sim
    return None
