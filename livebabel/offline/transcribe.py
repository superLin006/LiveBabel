"""离线识别:用 SenseVoice 把视频/音频转成带时间戳的句子。

Whisper 仍保留在 ModelScope 供旧版 LiveBabel 使用，但 v1.4.1 的离线
字幕统一使用 SenseVoice。Silero VAD 负责切分，SenseVoice 负责每段识别；
CPU 使用 INT8，NVIDIA CUDA 使用 FP16。
"""

from __future__ import annotations

import multiprocessing as mp
import os
import tempfile
import wave
from dataclasses import dataclass
from typing import List, Optional

import numpy as np


@dataclass
class Sentence:
    start: float
    end: float
    text: str
    translation: Optional[str] = None


def detect_device() -> tuple[str, str]:
    """返回 ``(device, compute_type)``，保持旧 CLI 参数兼容。"""
    if os.environ.get("LIVEBABEL_CPU_ONLY", "").strip().lower() in ("1", "true"):
        return "cpu", "int8"
    try:
        from livebabel.asr.vad_engine import detect_provider
        if detect_provider() == "cuda":
            return "cuda", "float16"
    except Exception:
        pass
    return "cpu", "int8"


def _extract_audio(video_path: str) -> str:
    from livebabel.ffmpeg_tool import find_ffmpeg, run_hidden
    ffmpeg = find_ffmpeg()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    proc = run_hidden([
        ffmpeg, "-nostdin", "-y", "-loglevel", "error", "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", tmp.name,
    ], capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg 提取音轨失败:\n{proc.stderr.decode(errors='replace')}")
    return tmp.name


def _read_wav(path: str) -> np.ndarray:
    with wave.open(path, "rb") as f:
        channels, width = f.getnchannels(), f.getsampwidth()
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


def _build_sensevoice(provider: str, num_threads: int = 2):
    import sherpa_onnx
    from livebabel.asr.model_variants import sensevoice_model_path
    from livebabel.paths import SECOND_DIR, VAD_MODEL

    recognizer = sherpa_onnx.OfflineRecognizer.from_sense_voice(
        model=sensevoice_model_path(SECOND_DIR, provider),
        tokens=os.path.join(SECOND_DIR, "tokens.txt"),
        num_threads=num_threads,
        use_itn=True,
        provider=provider,
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


def _decode_sensevoice(recognizer, audio: np.ndarray) -> str:
    if len(audio) < 16000 * 0.2:
        return ""
    stream = recognizer.create_stream()
    stream.accept_waveform(16000, audio.astype(np.float32, copy=False))
    recognizer.decode_stream(stream)
    return stream.result.text.strip()


def transcribe(
    video_path: str,
    model_size: str = "sensevoice",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress=None,
) -> List[Sentence]:
    """使用 SenseVoice + VAD 生成带 VAD 时间戳的句子列表。"""
    del model_size, language, compute_type
    if device == "cuda":
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        ensure_cuda_dlls()

    audio_path = _extract_audio(video_path)
    try:
        waveform = _read_wav(audio_path)
        total = len(waveform) / 16000.0
        recognizer, vad = _build_sensevoice(device)
        out: List[Sentence] = []
        chunk_size = 1600  # 100 ms

        def consume() -> None:
            while not vad.empty():
                seg = vad.front
                samples = np.asarray(seg.samples, dtype=np.float32)
                start = seg.start / 16000.0
                end = (seg.start + len(samples)) / 16000.0
                vad.pop()
                text = _decode_sensevoice(recognizer, samples)
                if text:
                    out.append(Sentence(start=start, end=end, text=text))
                if on_progress:
                    on_progress(min(end, total), total)

        for start in range(0, len(waveform), chunk_size):
            vad.accept_waveform(waveform[start:start + chunk_size])
            consume()
        vad.flush()
        consume()
        if not out and len(waveform) >= 16000 * 0.2:
            text = _decode_sensevoice(recognizer, waveform)
            if text:
                out.append(Sentence(start=0.0, end=total, text=text))
        if on_progress:
            on_progress(total, total)
        return out
    finally:
        try:
            os.remove(audio_path)
        except OSError:
            pass


def _subprocess_worker(q, kwargs: dict) -> None:
    try:
        def _progress(done, total):
            try:
                q.put(("progress", float(done), float(total)))
            except Exception:
                pass
        q.put(("ok", transcribe(on_progress=_progress, **kwargs)))
    except BaseException as e:
        q.put(("err", f"{type(e).__name__}: {e}"))


def transcribe_subprocess(
    video_path: str,
    model_size: str = "sensevoice",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress=None,
    should_cancel=None,
) -> List[Sentence]:
    """在独立进程运行离线转录，GPU 任务结束后显存由系统回收。"""
    ctx = mp.get_context("spawn")
    q = ctx.Queue()
    proc = ctx.Process(
        target=_subprocess_worker,
        args=(q, dict(video_path=video_path, model_size=model_size,
                      language=language, device=device, compute_type=compute_type)),
        daemon=True,
    )
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
