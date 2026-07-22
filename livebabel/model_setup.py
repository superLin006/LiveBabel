"""首次启动自动下载语音模型。

从 ModelScope 统一仓库按需下载,不依赖 modelscope SDK(纯 requests 请求)。

模型分两组:
  * 核心模型(启动时下载):VAD / zipformer / SenseVoice / 声纹 / whisper
  * ChatTTS(点击朗读时按需下载):chattts/{decoder,gpt_*,vocos,...}

模型仓库: https://modelscope.cn/models/XHxiehuan/LiveBabel-Models
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, List, Optional, Tuple

from livebabel.paths import CHATTTS_DIR, MODELS_DIR

# ModelScope 统一仓库
_MS_REPO = "XHxiehuan/LiveBabel-Models"
_MS_BASE = f"https://www.modelscope.cn/api/v1/models/{_MS_REPO}/resolve/master"

# ChatTTS 独立按需下载(不在核心 MANIFEST 中,点击朗读时才触发)
CHATTTS_REPO = os.environ.get("LIVEBABEL_CHATTTS_REPO", _MS_REPO)
CHATTTS_APPROX_MB = 470
_CHATTTS_FILES = (
    "decoder.int8.onnx",
    "default_speaker.bin",
    "gpt_decode.int8.onnx",
    "gpt_prefill.int8.onnx",
    "homophones_map.json",
    "vocab.txt",
    "vocos.int8.onnx",
)


@dataclass
class ModelItem:
    """一组相关模型文件的下载单元。

    每个 item 包含若干 (远程相对路径, 本地相对路径) 对,
    ready() 检查所有本地文件是否存在,下载时逐个获取。
    """
    name: str                              # 给用户看的名字
    files: List[Tuple[str, str]] = field(default_factory=list)
    approx_mb: int = 0

    def ready(self) -> bool:
        return all(
            os.path.exists(os.path.join(MODELS_DIR, local))
            for _, local in self.files
        )


# ---- 核心模型清单(启动时下载,不含 ChatTTS)----
MANIFEST: List[ModelItem] = [
    ModelItem(
        name="silero VAD(语音分段)",
        files=[("vad/silero_vad.onnx", "vad/silero_vad.onnx")],
        approx_mb=1,
    ),
    ModelItem(
        name="流式 zipformer(实时识别)",
        files=[
            ("zipformer/tokens.txt", "zipformer/tokens.txt"),
            ("zipformer/encoder-epoch-99-avg-1.onnx", "zipformer/encoder-epoch-99-avg-1.onnx"),
            ("zipformer/decoder-epoch-99-avg-1.onnx", "zipformer/decoder-epoch-99-avg-1.onnx"),
            ("zipformer/joiner-epoch-99-avg-1.onnx", "zipformer/joiner-epoch-99-avg-1.onnx"),
            ("zipformer/bpe.model", "zipformer/bpe.model"),
            ("zipformer/bpe.vocab", "zipformer/bpe.vocab"),
        ],
        approx_mb=341,
    ),
    ModelItem(
        name="SenseVoice(高精度识别)",
        files=[
            ("sense-voice/model.int8.onnx", "sense-voice/model.int8.onnx"),
            ("sense-voice/tokens.txt", "sense-voice/tokens.txt"),
        ],
        approx_mb=229,
    ),
    ModelItem(
        name="声纹 campplus(会议区分说话人, 主力)",
        files=[("speaker/campplus.onnx", "speaker/campplus.onnx")],
        approx_mb=27,
    ),
    ModelItem(
        name="声纹 eres2net(会议区分说话人, 回退)",
        files=[("speaker/eres2net_sv_zh.onnx", "speaker/eres2net_sv_zh.onnx")],
        approx_mb=38,
    ),
]


def missing_items() -> List[ModelItem]:
    """返回尚未就绪的核心模型项(空列表 = 全齐,不含 ChatTTS)。"""
    return [m for m in MANIFEST if not m.ready()]


def models_ready() -> bool:
    return not missing_items()


# ---- whisper 按需(文件名固定,不存在时由程序提示下载)----
_WHISPER_FILES = (
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
)
WHISPER_APPROX_MB = 1600


def chattts_ready() -> bool:
    """返回 ChatTTS 模型目录是否包含全部必需文件。"""
    return all(os.path.isfile(os.path.join(CHATTTS_DIR, name)) for name in _CHATTTS_FILES)


def whisper_ready() -> bool:
    """返回 whisper 模型目录是否包含全部必需文件。"""
    from livebabel.paths import WHISPER_DIR
    return all(os.path.isfile(os.path.join(WHISPER_DIR, name)) for name in _WHISPER_FILES)


def download_whisper(
    log: Callable[[str], None],
    on_progress: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """从统一仓库下载 whisper 模型到本地(独立按需,不在启动时下载)。"""
    import requests
    from livebabel.paths import WHISPER_DIR

    os.makedirs(WHISPER_DIR, exist_ok=True)
    total = len(_WHISPER_FILES)
    for index, name in enumerate(_WHISPER_FILES, 1):
        if is_cancelled():
            raise DownloadCancelled()
        url = f"{_MS_BASE}/whisper/{name}"
        dest = os.path.join(WHISPER_DIR, name)
        part = dest + ".part"
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        log(f"[{index}/{total}] 下载 {name} …")
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60) as response:
                if have and response.status_code == 200:
                    have = 0
                response.raise_for_status()
                mode = "ab" if have else "wb"
                with open(part, mode) as output:
                    for block in response.iter_content(chunk_size=1 << 20):
                        if is_cancelled():
                            raise DownloadCancelled()
                        if block:
                            output.write(block)
            os.replace(part, dest)
        except DownloadCancelled:
            raise
        except Exception:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            raise RuntimeError(f"下载后文件为空: {name}")
        on_progress(index, total)
    if not whisper_ready():
        raise RuntimeError("下载后缺少 whisper 模型文件")
    log("whisper 离线转录模型已就绪。")


def download_chattts(
    log: Callable[[str], None],
    on_progress: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """从统一仓库下载 ChatTTS 模型到本地(独立按需,不在启动时下载)。"""
    import requests

    os.makedirs(CHATTTS_DIR, exist_ok=True)
    total = len(_CHATTTS_FILES)
    for index, name in enumerate(_CHATTTS_FILES, 1):
        if is_cancelled():
            raise DownloadCancelled()
        url = f"{_MS_BASE}/chattts/{name}"
        dest = os.path.join(CHATTTS_DIR, name)
        part = dest + ".part"
        have = os.path.getsize(part) if os.path.isfile(part) else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        log(f"[{index}/{total}] 下载 {name} …")
        try:
            with requests.get(url, headers=headers, stream=True, timeout=60) as response:
                if have and response.status_code == 200:
                    have = 0
                response.raise_for_status()
                mode = "ab" if have else "wb"
                with open(part, mode) as output:
                    for block in response.iter_content(chunk_size=1 << 20):
                        if is_cancelled():
                            raise DownloadCancelled()
                        if block:
                            output.write(block)
            os.replace(part, dest)
        except DownloadCancelled:
            raise
        except Exception:
            try:
                os.remove(part)
            except OSError:
                pass
            raise
        if not os.path.isfile(dest) or os.path.getsize(dest) == 0:
            raise RuntimeError(f"下载后文件为空: {name}")
        on_progress(index, total)
    if not chattts_ready():
        raise RuntimeError("下载后缺少 ChatTTS 模型文件")
    log("ChatTTS 朗读模型已就绪。")


# ---- 通用下载实现 ----

class DownloadCancelled(Exception):
    pass


def _download_one(
    item: ModelItem,
    log: Callable[[str], None],
    on_bytes: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """下载单个模型项的所有文件。每个文件独立请求,支持断点续传。"""

    total_files = len(item.files)
    for idx, (remote, local) in enumerate(item.files, 1):
        url = f"{_MS_BASE}/{remote}"
        dest = os.path.join(MODELS_DIR, local)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        log(f"  [{idx}/{total_files}] {os.path.basename(local)} …")
        _stream_to_file(url, dest, on_bytes, is_cancelled, log)


def _stream_to_file(
    url: str,
    dest: str,
    on_bytes: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
    log: Callable[[str], None],
) -> None:
    """流式下载到 dest;支持断点续传(.part 临时文件 + Range)。"""
    import requests

    part = dest + ".part"
    have = os.path.getsize(part) if os.path.exists(part) else 0
    headers = {"Range": f"bytes={have}-"} if have else {}

    with requests.get(url, headers=headers, stream=True, timeout=30,
                      allow_redirects=True) as r:
        # 续传请求若返回 200(服务器不支持 Range),从头来
        if have and r.status_code == 200:
            have = 0
        elif have and r.status_code != 206:
            r.raise_for_status()
        else:
            r.raise_for_status()

        total = int(r.headers.get("Content-Length", 0))
        if total:
            total += have  # Content-Length 是剩余量,加上已有的才是总量

        mode = "ab" if have else "wb"
        downloaded = have
        with open(part, mode) as f:
            for chunk in r.iter_content(chunk_size=1 << 18):  # 256KB
                if is_cancelled():
                    raise DownloadCancelled()
                if not chunk:
                    continue
                f.write(chunk)
                downloaded += len(chunk)
                on_bytes(downloaded, total)

    os.replace(part, dest)  # 完整下完才落到正式文件名


def download_missing(
    log: Callable[[str], None],
    on_progress: Callable[[int, int, int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """下载所有缺失的核心模型(不含 ChatTTS)。

    on_progress(idx, count, downloaded, total): 第 idx/count 个 item,
    当前文件已下/总字节。
    全部成功正常返回;被取消抛 DownloadCancelled;失败抛 RuntimeError。
    """
    items = missing_items()
    n = len(items)
    for i, item in enumerate(items, 1):
        log(f"[{i}/{n}] {item.name}(约 {item.approx_mb}MB)…")
        _download_one(
            item, log,
            lambda d, t, _i=i, _n=n: on_progress(_i, _n, d, t),
            is_cancelled,
        )
        log(f"  ✓ 完成")
    log("全部模型已就绪。")
