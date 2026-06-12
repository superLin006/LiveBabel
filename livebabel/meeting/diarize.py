"""离线说话人分离(声纹聚类),用 sherpa-onnx 内置的 OfflineSpeakerDiarization。

会议结束后,对某一路(通常是"远端")的整段音频做声纹聚类,把它细分成
"发言人1/2/3…",再据此把该路的转录按时间重新归属到具体发言人。

纯 ONNX,不依赖 torch。需要两个模型(放 models/,见 paths):
  * segmentation 模型(pyannote 格式)
  * speaker embedding 模型(3D-Speaker ECAPA)
模型缺失时 available() 返回 False,UI 据此禁用「区分说话人」。
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


def _seg_model() -> str:
    from livebabel.paths import MODELS_DIR
    return os.path.join(MODELS_DIR, "sherpa-onnx-pyannote-segmentation-3-0", "model.onnx")


def _emb_model() -> str:
    from livebabel.paths import MODELS_DIR
    return os.path.join(MODELS_DIR, "3dspeaker_eres2net_sv_zh.onnx")


def available() -> bool:
    """两个模型都在才可用。"""
    return os.path.isfile(_seg_model()) and os.path.isfile(_emb_model())


def diarize(samples, sample_rate: int = 16000, num_speakers: int = -1,
            cluster_threshold: float = 0.7, on_progress=None) -> List[SpkSegment]:
    """对整段音频做说话人分离。

    samples: float32 mono numpy 数组(16k)。
    num_speakers: 已知人数则传正整数(最准);-1 表示自动聚类(用 cluster_threshold)。
    cluster_threshold: 自动模式的聚类阈值。实测 0.5 太敏感(单人会被切成多人),
        默认 0.7 更稳;能指定人数就尽量指定,比自动准得多。
    返回按时间排序的 [SpkSegment]。无模型/失败抛 RuntimeError。
    """
    import numpy as np
    import sherpa_onnx

    if not available():
        raise RuntimeError("缺少说话人分离模型(segmentation / embedding)。")

    # 有 GPU 就用 GPU(声纹嵌入提取是大头,GPU 能快很多);先注册 CUDA DLL
    from livebabel.asr.vad_engine import detect_provider
    prov = detect_provider()
    if prov == "cuda":
        try:
            from livebabel.offline.cuda_dll import ensure_cuda_dlls
            ensure_cuda_dlls()
        except Exception:
            pass

    def _make_cfg(provider):
        return sherpa_onnx.OfflineSpeakerDiarizationConfig(
            segmentation=sherpa_onnx.OfflineSpeakerSegmentationModelConfig(
                pyannote=sherpa_onnx.OfflineSpeakerSegmentationPyannoteModelConfig(
                    model=_seg_model()),
                provider=provider, num_threads=2,
            ),
            embedding=sherpa_onnx.SpeakerEmbeddingExtractorConfig(
                model=_emb_model(), provider=provider, num_threads=2),
            clustering=sherpa_onnx.FastClusteringConfig(
                num_clusters=int(num_speakers), threshold=float(cluster_threshold)),
            min_duration_on=0.3,
            min_duration_off=0.5,
        )

    cfg = _make_cfg(prov)
    if not cfg.validate():
        raise RuntimeError("说话人分离配置无效(模型路径/格式不对)。")

    # GPU 构建失败(缺库等)自动回退 CPU
    try:
        sd = sherpa_onnx.OfflineSpeakerDiarization(cfg)
    except Exception:
        if prov == "cuda":
            sd = sherpa_onnx.OfflineSpeakerDiarization(_make_cfg("cpu"))
        else:
            raise
    audio = np.ascontiguousarray(samples, dtype=np.float32)

    if on_progress:
        def _cb(done, total):
            try:
                on_progress(done, total)
            except Exception:
                pass
            return 0
        result = sd.process(audio, callback=_cb)
    else:
        result = sd.process(audio)

    out: List[SpkSegment] = []
    for seg in result.sort_by_start_time():
        out.append(SpkSegment(start=seg.start, end=seg.end, speaker=seg.speaker))
    return out


def speaker_at(segments: List[SpkSegment], t: float) -> Optional[int]:
    """给定一个时间点,返回它落在哪个说话人段(找不到返回 None)。

    用于把转录条(带时间戳)归属到 diarization 的说话人。取与该时间点重叠的段;
    没有精确重叠则取最近的段。
    """
    if not segments:
        return None
    for s in segments:
        if s.start <= t <= s.end:
            return s.speaker
    # 没落在任何段内:取中心最近的
    best = min(segments, key=lambda s: abs((s.start + s.end) / 2 - t))
    return best.speaker
