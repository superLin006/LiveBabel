"""离线识别:用 Qwen3-ASR-0.6B 把视频/音频转成带时间戳的句子。

Qwen3-ASR 在 sherpa-onnx 中是离线模型。这里使用同一套 Silero VAD 做句段
切分，再对每个纯语音段进行 Qwen 识别；CPU 使用 INT8，CUDA 使用 FP16。

输出:list[Sentence],每个含 start/end(秒)和 text(原文)。
"""

from __future__ import annotations

import os
import tempfile
import wave
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class Sentence:
    start: float          # 起始秒
    end: float            # 结束秒
    text: str             # 识别原文
    translation: Optional[str] = None   # 译文(翻译阶段填入)


def detect_device() -> tuple[str, str]:
    """自动探测识别设备:有可用 CUDA 显卡且运行时库齐全就用 GPU,否则回退 CPU。

    返回 (device, compute_type):
      * GPU 可用 → ("cuda", "float16")
      * 否则     → ("cpu", "int8")

    Qwen3-ASR 的推理由 ONNX Runtime 提供，不依赖 CTranslate2。
    """
    # 纯 CPU 版打包用此开关强制 CPU(即使机器有 GPU 也不尝试,避免找没打包的 GPU 库)
    if os.environ.get("LIVEBABEL_CPU_ONLY", "").strip() in ("1", "true", "True"):
        return "cpu", "int8"
    try:
        from livebabel.asr.vad_engine import detect_provider
        if detect_provider() == "cuda":
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _extract_audio(video_path: str) -> str:
    """用 ffmpeg 把视频音轨提取成 16k mono WAV 到临时文件。"""
    from livebabel.ffmpeg_tool import find_ffmpeg, run_hidden
    ffmpeg = find_ffmpeg()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        ffmpeg, "-nostdin", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
        tmp.name,
    ]
    proc = run_hidden(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 提取音轨失败:\n{proc.stderr.decode(errors='replace')}"
        )
    return tmp.name


def _read_wav(path: str) -> np.ndarray:
    """读取 _extract_audio 生成的 PCM WAV，返回 float32 [-1, 1]。"""
    with wave.open(path, "rb") as f:
        channels = f.getnchannels()
        width = f.getsampwidth()
        frames = f.readframes(f.getnframes())
    if width == 2:
        audio = np.frombuffer(frames, dtype="<i2").astype(np.float32) / 32768.0
    elif width == 4:
        audio = np.frombuffer(frames, dtype="<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"不支持的 WAV 位宽: {width * 8} bit")
    if channels > 1:
        audio = audio[: len(audio) // channels * channels].reshape(-1, channels).mean(axis=1)
    return audio


def _build_qwen(provider: str, num_threads: int = 2):
    import sherpa_onnx
    from livebabel.asr.qwen3_model import has_qwen_cuda_model, qwen_model_paths
    from livebabel.paths import SECOND_DIR, VAD_MODEL

    if provider == "cuda" and not has_qwen_cuda_model(SECOND_DIR):
        raise RuntimeError("Qwen3-ASR FP16 模型不存在，无法使用 GPU")
    conv, encoder, decoder = qwen_model_paths(SECOND_DIR, provider)
    recognizer = sherpa_onnx.OfflineRecognizer.from_qwen3_asr(
        conv_frontend=conv, encoder=encoder, decoder=decoder,
        tokenizer=os.path.join(SECOND_DIR, "tokenizer"),
        num_threads=num_threads, provider=provider, feature_dim=128,
        max_total_len=512, max_new_tokens=128,
    )
    cfg = sherpa_onnx.VadModelConfig()
    cfg.silero_vad.model = VAD_MODEL
    cfg.silero_vad.threshold = 0.5
    cfg.silero_vad.min_silence_duration = 0.5
    cfg.silero_vad.min_speech_duration = 0.25
    cfg.silero_vad.max_speech_duration = 12.0
    cfg.sample_rate = 16000
    cfg.num_threads = num_threads
    cfg.provider = provider
    vad = sherpa_onnx.VoiceActivityDetector(cfg, buffer_size_in_seconds=30)
    return recognizer, vad


def _decode_qwen(recognizer, audio: np.ndarray) -> str:
    if len(audio) < 16000 * 0.2:
        return ""
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, audio.astype(np.float32, copy=False))
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def transcribe(
    video_path: str,
    model_size: str = "qwen3-asr-0.6b",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress=None,
) -> List[Sentence]:
    """用 Qwen3-ASR 识别视频,返回按 VAD 切分且带时间戳的句子列表。

    ``model_size`` 和 ``language`` 保留为兼容参数；Qwen 当前自动检测语言。
    ``device`` 使用 ``cpu`` 或 ``cuda``，分别对应 INT8 与 FP16 图。
    """
    if device == "cuda":
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        ensure_cuda_dlls()

    audio = _extract_audio(video_path)
    try:
        waveform = _read_wav(audio)
        total = len(waveform) / 16000.0
        recognizer, vad = _build_qwen(device)
        out: List[Sentence] = []
        chunk_size = 1600  # 100 ms

        def consume() -> None:
            while not vad.empty():
                seg = vad.front
                seg_audio = np.asarray(seg.samples, dtype=np.float32)
                start = seg.start / 16000.0
                end = (seg.start + len(seg_audio)) / 16000.0
                vad.pop()
                text = _decode_qwen(recognizer, seg_audio)
                if text:
                    out.append(Sentence(start=start, end=end, text=text))
                if on_progress:
                    on_progress(min(end, total), total)

        for start in range(0, len(waveform), chunk_size):
            vad.accept_waveform(waveform[start:start + chunk_size])
            consume()
        vad.flush()
        consume()
        # VAD may reject an unusually short clip; still return its transcript.
        if not out and len(waveform) >= 16000 * 0.2:
            text = _decode_qwen(recognizer, waveform)
            if text:
                out.append(Sentence(start=0.0, end=total, text=text))
        if on_progress:
            on_progress(total, total)
        return out
    finally:
        try:
            os.remove(audio)
        except OSError:
            pass


# ---------- GPU 隔离:在子进程里转录 ----------
# 离线 Qwen 与实时/会议 ASR 共享 ONNX Runtime CUDA。放在独立进程中可在
# 任务结束后彻底回收显存，避免后续实时模型初始化被旧 session 占用。

def _subprocess_worker(q, kwargs: dict) -> None:
    """子进程入口(必须是模块顶层函数,spawn 模式才能 pickle)。

    跑 transcribe(),通过队列回传进度与结果;异常也回传。进程结束即释放 GPU。
    """
    try:
        def _prog(done, total):
            try:
                q.put(("progress", float(done), float(total)))
            except Exception:
                pass
        sents = transcribe(on_progress=_prog, **kwargs)
        # Sentence 是 dataclass,可 pickle 跨进程传回
        q.put(("ok", sents))
    except BaseException as e:   # 子进程任何失败都回传,避免父进程空等
        q.put(("err", f"{type(e).__name__}: {e}"))


def transcribe_subprocess(
    video_path: str,
    model_size: str = "qwen3-asr-0.6b",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress=None,
    should_cancel=None,
) -> List[Sentence]:
    """在【独立子进程】里转录,结束后 GPU 被操作系统彻底回收。

    接口与 transcribe() 基本一致,额外 should_cancel():返回 True 则终止子进程并抛
    RuntimeError("cancelled")。进度通过 on_progress(done, total) 回调(父进程线程内)。
    """
    import multiprocessing as mp

    ctx = mp.get_context("spawn")   # Windows 必然 spawn;显式指定保证跨平台一致
    q = ctx.Queue()
    kwargs = dict(video_path=video_path, model_size=model_size, language=language,
                  device=device, compute_type=compute_type)
    proc = ctx.Process(target=_subprocess_worker, args=(q, kwargs), daemon=True)
    proc.start()

    result: List[Sentence] = []
    err: Optional[str] = None
    try:
        while True:
            if should_cancel is not None and should_cancel():
                proc.terminate()
                raise RuntimeError("cancelled")
            try:
                kind, *payload = q.get(timeout=0.2)
            except Exception:
                # 队列暂时空:检查子进程是否已意外退出(崩溃且没回传)
                if not proc.is_alive() and q.empty():
                    err = "转录子进程异常退出(可能 GPU 驱动崩溃)"
                    break
                continue
            if kind == "progress":
                if on_progress:
                    on_progress(payload[0], payload[1])
            elif kind == "ok":
                result = payload[0]
                break
            elif kind == "err":
                err = payload[0]
                break
    finally:
        proc.join(timeout=10)
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=5)

    if err is not None:
        raise RuntimeError(err)
    return result
