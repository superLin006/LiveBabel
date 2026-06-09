"""离线识别:用 faster-whisper(large-v3-turbo)把视频/音频转成带时间戳的句子。

faster-whisper 基于 CTranslate2,不依赖 torch,速度快、内存省,支持 99 种语言,
原生输出段级时间戳(每句的起止秒)。离线场景不需要消抖,直接整段识别即可。

输出:list[Sentence],每个含 start/end(秒)和 text(原文)。
"""

from __future__ import annotations

import subprocess
import tempfile
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class Sentence:
    start: float          # 起始秒
    end: float            # 结束秒
    text: str             # 识别原文
    translation: Optional[str] = None   # 译文(翻译阶段填入)


def _extract_audio(video_path: str) -> str:
    """用 ffmpeg 把视频音轨提取成 16k mono wav(faster-whisper 喜欢的格式)到临时文件。"""
    from livebabel.ffmpeg_tool import find_ffmpeg
    ffmpeg = find_ffmpeg()
    tmp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    tmp.close()
    cmd = [
        ffmpeg, "-nostdin", "-y", "-loglevel", "error",
        "-i", video_path,
        "-vn", "-ac", "1", "-ar", "16000", "-f", "wav",
        tmp.name,
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise RuntimeError(
            f"ffmpeg 提取音轨失败:\n{proc.stderr.decode(errors='replace')}"
        )
    return tmp.name


def transcribe(
    video_path: str,
    model_size: str = "large-v3-turbo",
    language: Optional[str] = None,
    device: str = "cpu",
    compute_type: str = "int8",
    on_progress=None,
) -> List[Sentence]:
    """识别视频,返回带时间戳的句子列表。

    language: None=自动检测;也可指定如 "en"/"zh"/"ja" 加速并提高准确率。
    device/compute_type: cpu+int8 最省;有 N 卡可传 device="cuda", compute_type="float16"。
    on_progress(done_seconds, total_seconds): 可选进度回调。
    """
    import os
    from faster_whisper import WhisperModel

    # 优先用本地模型目录(models/faster-whisper-large-v3-turbo),没放才按名字自动下载
    model_ref = model_size
    try:
        from livebabel.paths import WHISPER_DIR
        if model_size == "large-v3-turbo" and os.path.isdir(WHISPER_DIR):
            model_ref = WHISPER_DIR
    except Exception:
        pass

    audio = _extract_audio(video_path)
    try:
        model = WhisperModel(model_ref, device=device, compute_type=compute_type)
        segments, info = model.transcribe(
            audio,
            language=language,
            vad_filter=True,                 # 内置 VAD 去静音,断句更干净
            beam_size=5,
        )
        total = info.duration
        out: List[Sentence] = []
        for seg in segments:
            text = seg.text.strip()
            if not text:
                continue
            out.append(Sentence(start=seg.start, end=seg.end, text=text))
            if on_progress:
                on_progress(seg.end, total)
        return out
    finally:
        import os
        try:
            os.remove(audio)
        except OSError:
            pass
