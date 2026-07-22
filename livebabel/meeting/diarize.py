"""离线说话人分离(声纹聚类)。

会议结束后对某一路(通常"远端")整段音频做声纹聚类,细分成"发言人1/2/3…"。

实现:VAD 切语音段 → sherpa speaker-embedding 逐段提声纹 → 球面 K-means 聚类。
不用 sherpa 内置的 OfflineSpeakerDiarization——实测它对中文多人对话会把清晰可分的
段全压成一个人(282:23)。改用「逐段 embedding + 自家 K-means」:实测同一人句内聚
0.7+、不同人 0.15~0.35,K-means(cosine 质心)能稳定分开,凝聚聚类则因雪球效应失败。

纯 ONNX + numpy,不依赖 torch / scipy(打包友好)。需要两个模型(models/):
  * silero VAD(已用于实时 ASR)
  * speaker embedding(3D-Speaker campplus,实测对中文真人区分最好)
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class SpkSegment:
    start: float       # 秒
    end: float
    speaker: int       # 聚类得到的说话人编号(0,1,2…)


def _emb_model() -> str:
    from livebabel.paths import SPEAKER_CAMPPLUS, SPEAKER_ERES2NET
    # 优先 campplus(实测中文真人区分最好);回退 eres2net base
    for p in (SPEAKER_CAMPPLUS, SPEAKER_ERES2NET):
        if os.path.isfile(p):
            return p
    return SPEAKER_CAMPPLUS


def available() -> bool:
    """embedding 模型 + VAD 模型都在才可用。"""
    from livebabel.paths import VAD_MODEL
    return os.path.isfile(_emb_model()) and os.path.isfile(VAD_MODEL)


# ---------- 纯 numpy 球面 K-means(cosine)----------

def _spherical_kmeans(E, k, iters=50, restarts=8):
    """E: (n,d) 已 L2 归一化的 embedding。返回 labels(长度 n)。

    多次随机初始化取最优(总相似度最大),避免局部最优。
    """
    import numpy as np
    n = len(E)
    if k <= 1 or n <= k:
        return [0] * n if k <= 1 else list(range(n))
    best_lab, best_score = None, -1e9
    for seed in range(restarts):
        rng = np.random.RandomState(seed)
        C = E[rng.choice(n, k, replace=False)].copy()
        lab = None
        for _ in range(iters):
            sims = E @ C.T                      # (n,k) cosine(已归一化)
            new_lab = np.argmax(sims, axis=1)
            newC = np.zeros_like(C)
            for j in range(k):
                m = new_lab == j
                newC[j] = E[m].mean(0) if m.any() else C[j]
            norm = np.linalg.norm(newC, axis=1, keepdims=True)
            newC = newC / (norm + 1e-9)
            if lab is not None and np.array_equal(new_lab, lab):
                C = newC
                lab = new_lab
                break
            C, lab = newC, new_lab
        score = float(np.sum(np.max(E @ C.T, axis=1)))
        if score > best_score:
            best_score, best_lab = score, lab
    return best_lab.tolist()


def _estimate_k(E, kmax=6):
    """没给人数时估说话人数:对 K=2..kmax 算质心间最大相似度,质心足够分开
    (相似度低)才认为真有这么多人。E 已归一化。

    用质心区分度而非簇内相似度:K-means 把单人样本强行分两簇时,两质心仍很像
    (cos 高);真有两人时两质心明显不像(cos 低)。以此判断 K 是否成立。
    """
    import numpy as np
    n = len(E)
    kmax = min(kmax, n)
    if n <= 3:
        return 1

    def centroids(lab, k):
        C = []
        for j in range(k):
            m = np.array(lab) == j
            if m.any():
                c = E[m].mean(0)
                C.append(c / (np.linalg.norm(c) + 1e-9))
        return np.array(C)

    best_k = 1
    for k in range(2, kmax + 1):
        lab = _spherical_kmeans(E, k)
        C = centroids(lab, k)
        if len(C) < k:
            break
        # 任意两质心的最大相似度:越低说明簇越分得开
        sims = C @ C.T
        np.fill_diagonal(sims, -1)
        max_inter = float(sims.max())
        # 质心间相似度 < 0.55 才认为是真的不同人(实测同人误分两簇时 >0.7)
        if max_inter < 0.55:
            best_k = k
        else:
            break
    return best_k


def _segment_windows(audio, sr, vad_model, sherpa_onnx,
                     win_s=2.5, hop_s=1.25, rms_gate=0.005):
    """把音频切成短窗 (start,end,samples),供逐段提声纹。

    先用 silero VAD 找语音区(连续对话里 VAD 段可能很长,无所谓),再在每个语音区
    内按固定 win/hop 切;静音窗(RMS 低)丢弃。窗短(~2.5s)保证基本单说话人。
    若 VAD 不可用,退化为对全程按固定窗切。
    """
    import numpy as np
    win = int(win_s * sr)
    hop = int(hop_s * sr)

    def cut_region(a0_samp, region):
        out = []
        # 门限取「绝对值」与「该区自身音量的 30%」的较小者:笔记本麦远场收音
        # 整体音量可能很低(实测低于 0.005 的绝对门限,导致所有窗被当静音丢光、
        # 一段都切不出来),相对门限保证安静录音也能过,同时仍能丢掉区内静音窗。
        region_rms = float(np.sqrt(np.mean(region ** 2))) if len(region) else 0.0
        gate = min(rms_gate, max(1e-4, 0.3 * region_rms))
        for st in range(0, max(1, len(region) - win + 1), hop):
            seg = region[st:st + win]
            if len(seg) < int(0.8 * sr):
                continue
            if float(np.sqrt(np.mean(seg ** 2))) < gate:
                continue
            s0 = (a0_samp + st) / sr
            out.append((s0, s0 + len(seg) / sr, seg))
        # 区域尾部不足一个 hop 的残余也补一段
        if len(region) >= int(0.8 * sr):
            tail = region[-win:] if len(region) >= win else region
            s0 = (a0_samp + len(region) - len(tail)) / sr
            if not out or s0 > out[-1][0] + 0.3:
                if float(np.sqrt(np.mean(tail ** 2))) >= gate:
                    out.append((s0, s0 + len(tail) / sr, tail))
        return out

    regions = []  # (start_samp, samples)
    try:
        v = sherpa_onnx.VadModelConfig()
        v.silero_vad.model = vad_model
        v.silero_vad.threshold = 0.5
        v.silero_vad.min_silence_duration = 0.3
        v.silero_vad.min_speech_duration = 0.3
        v.silero_vad.max_speech_duration = 600.0
        v.sample_rate = sr
        vad = sherpa_onnx.VoiceActivityDetector(v, buffer_size_in_seconds=600)
        i = 0
        while i < len(audio):
            vad.accept_waveform(audio[i:i + sr])
            i += sr
            while not vad.empty():
                s = vad.front
                regions.append((s.start, np.array(s.samples, dtype=np.float32)))
                vad.pop()
        vad.flush()
        while not vad.empty():
            s = vad.front
            regions.append((s.start, np.array(s.samples, dtype=np.float32)))
            vad.pop()
    except Exception:
        regions = []
    if not regions:                       # VAD 不可用:全程当一个区
        regions = [(0, audio)]

    segs = []
    for a0_samp, region in regions:
        segs.extend(cut_region(a0_samp, region))
    return segs


def diarize(samples, sample_rate: int = 16000, num_speakers: int = -1,
            cluster_threshold: float = 0.7, on_progress=None,
            return_centroids: bool = False):
    """对整段音频做说话人分离。

    samples: float32 mono numpy(16k)。num_speakers: 正整数=已知人数(最准);
    -1=自动估计。返回按时间排序的 [SpkSegment]。
    return_centroids=True 时返回 (segments, {聚类号: L2 归一化质心向量}),
    供声纹库登记/比对(每个说话人一个代表声纹)。
    """
    import numpy as np
    import sherpa_onnx
    from livebabel.paths import VAD_MODEL

    if not available():
        raise RuntimeError("缺少说话人分离模型(embedding / VAD)。")

    audio = np.ascontiguousarray(samples, dtype=np.float32)

    # GPU 探测(embedding 提取可走 GPU)
    from livebabel.asr.vad_engine import detect_provider
    prov = detect_provider()
    if prov == "cuda":
        try:
            from livebabel.offline.cuda_dll import ensure_cuda_dlls
            ensure_cuda_dlls()
        except Exception:
            pass

    # 1) 切成短窗。不用 silero VAD 的静音分段——实测连续对话里它会把几十秒连成
    #    一个巨段(一个 embedding 混多人 → 分不开)。改用 silero 只做"语音/静音"门控,
    #    在语音区内按固定窗(2.5s,1.25s hop)切,保证每段足够短、基本单说话人。
    segs = _segment_windows(audio, sample_rate, VAD_MODEL, sherpa_onnx)
    if not segs:
        # 注意保持返回形状和正常路径一致,调用方是按 return_centroids 解包的
        return ([], {}) if return_centroids else []

    # 2) 逐段提 embedding(GPU 失败回退 CPU)
    def _make_ext(p):
        return sherpa_onnx.SpeakerEmbeddingExtractor(
            sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=_emb_model(), provider=p, num_threads=2))
    try:
        ext = _make_ext(prov)
    except Exception:
        ext = _make_ext("cpu")

    def _vec(au):
        st = ext.create_stream()
        st.accept_waveform(sample_rate, np.ascontiguousarray(au))
        st.input_finished()
        v = np.array(ext.compute(st), dtype=np.float32)
        return v / (np.linalg.norm(v) + 1e-9)

    embs = []
    total = len(segs)
    for n, (a0, a1, sa) in enumerate(segs):
        embs.append(_vec(sa))
        if on_progress:
            on_progress(n + 1, total)
    E = np.array(embs)

    # 3) 聚类:指定人数走 K-means(最准,推荐)。num_speakers<=0 时用 _estimate_k
    #    粗估——但实测自动估 K 不可靠(真人两人共性高、单人会被切两半),所以
    #    会议 UI 默认引导用户【指定人数】,自动仅作兜底。
    k = int(num_speakers) if num_speakers and num_speakers > 0 else _estimate_k(E)
    labels = _spherical_kmeans(E, k) if k > 1 else [0] * len(segs)

    # 4) 按时间排序,合并相邻同说话人的重叠窗为连续区间(干净输出)
    triples = sorted(zip([s[0] for s in segs], [s[1] for s in segs], labels),
                     key=lambda x: x[0])
    out: List[SpkSegment] = []
    for a0, a1, lab in triples:
        if out and out[-1].speaker == lab and a0 <= out[-1].end + 0.6:
            out[-1].end = max(out[-1].end, a1)   # 同人且相邻/重叠 → 合并
        else:
            out.append(SpkSegment(start=a0, end=a1, speaker=int(lab)))

    if not return_centroids:
        return out
    # 每个聚类的质心(该聚类所有窗 embedding 的平均,再 L2 归一化)→ 代表声纹
    centroids = {}
    labs = np.asarray(labels)
    for lab in set(int(l) for l in labels):
        m = labs == lab
        if m.any():
            c = E[m].mean(0)
            centroids[lab] = (c / (np.linalg.norm(c) + 1e-9)).astype(np.float32)
    return out, centroids


def speaker_at(segments: List[SpkSegment], t: float) -> Optional[int]:
    """给定时间点,返回它所属说话人段(找不到取最近段)。"""
    if not segments:
        return None
    for s in segments:
        if s.start <= t <= s.end:
            return s.speaker
    best = min(segments, key=lambda s: abs((s.start + s.end) / 2 - t))
    return best.speaker
