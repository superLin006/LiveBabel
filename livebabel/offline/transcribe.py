"""离线识别:用 faster-whisper(large-v3-turbo)把视频/音频转成带时间戳的句子。

faster-whisper 基于 CTranslate2,不依赖 torch,速度快、内存省,支持 99 种语言,
原生输出段级时间戳(每句的起止秒)。离线场景不需要消抖,直接整段识别即可。

输出:list[Sentence],每个含 start/end(秒)和 text(原文)。
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from typing import List, Optional


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

    探测靠 CTranslate2 自报 CUDA 设备数。Windows 上还需 cuBLAS/cuDNN 的 DLL
    可加载,否则虽有显卡也跑不起来(报 cublas64_12.dll not found)——所以先注册
    DLL 目录,有显卡时再粗略检查这些库在不在,缺则当作没 GPU。任何异常都安全回退 CPU。
    """
    # 纯 CPU 版打包用此开关强制 CPU(即使机器有 GPU 也不尝试,避免找没打包的 GPU 库)
    if os.environ.get("LIVEBABEL_CPU_ONLY", "").strip() in ("1", "true", "True"):
        return "cpu", "int8"
    try:
        import ctranslate2
        if ctranslate2.get_cuda_device_count() <= 0:
            return "cpu", "int8"
        # Windows:确保 cuBLAS/cuDNN DLL 能被找到,否则别误判为可用 GPU
        if sys.platform.startswith("win"):
            from livebabel.offline.cuda_dll import ensure_cuda_dlls
            added = ensure_cuda_dlls()
            if not _cublas_present(added):
                return "cpu", "int8"
        return "cuda", "float16"
    except Exception:
        return "cpu", "int8"


def _cublas_present(dll_dirs: list[str]) -> bool:
    """粗略判断 cublas64_12.dll 是否存在(注册目录里或系统里)。仅 Windows 用。"""
    import glob
    for d in dll_dirs:
        if glob.glob(os.path.join(d, "cublas64_*.dll")):
            return True
    # 也可能装在 CUDA Toolkit / 系统 PATH 里
    for p in os.environ.get("PATH", "").split(os.pathsep):
        if p and glob.glob(os.path.join(p, "cublas64_*.dll")):
            return True
    return False


def _extract_audio(video_path: str) -> str:
    """用 ffmpeg 把视频音轨提取成 16k mono wav(faster-whisper 喜欢的格式)到临时文件。"""
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

    # Windows 上先把 cuBLAS/cuDNN 的 DLL 目录注册进搜索路径(GPU 模式必须,否则
    # 报 "cublas64_12.dll is not found");Linux/WSL 无操作。
    if device == "cuda":
        from livebabel.offline.cuda_dll import ensure_cuda_dlls
        ensure_cuda_dlls()

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


# ---------- GPU 隔离:在子进程里转录 ----------
# 为什么:faster-whisper(CTranslate2)在 GPU 上加载后,同进程内不会彻底归还 CUDA
# 上下文/显存(del+gc 实测不够),导致之后实时/会议的 sherpa-onnx 初始化 CUDA 失败
# (Error 1114)被迫回退 CPU。把转录放独立子进程,进程退出时操作系统强制回收其全部
# CUDA 资源,主进程后续再开 GPU 就干净了。仅 GPU 路径需要;CPU 路径无此问题。

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
    model_size: str = "large-v3-turbo",
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
    import time

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
