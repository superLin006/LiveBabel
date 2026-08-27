"""首次启动自动下载语音模型。

从 ModelScope 统一仓库按需下载,不依赖 modelscope SDK(纯 requests 请求)。

模型分两组:
  * 核心模型(启动时下载):VAD / Zipformer / Qwen3-ASR / 声纹
  * 按需下载:ChatTTS(朗读时)

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

# 旧版 Whisper 清单保留用于兼容已有安装，不再被离线模式使用或自动下载。
_WHISPER_FILES = (
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
)
WHISPER_APPROX_MB = 1600


@dataclass
class ModelItem:
    """一组相关模型文件的下载单元。

    每个 item 包含若干 (远程相对路径, 本地相对路径) 对,
    ready() 检查所有本地文件是否存在,下载时逐个获取。

    alt_files: 旧版备选文件组(保留字段以兼容其他模型清单项)。
    """
    name: str                              # 给用户看的名字
    files: List[Tuple[str, str]] = field(default_factory=list)
    alt_files: List[Tuple[str, str]] = field(default_factory=list)
    # Optional provider-specific files.  When set, exactly one variant is
    # required instead of treating both variants as a single download set.
    variant_files: dict[str, List[Tuple[str, str]]] = field(default_factory=dict)
    variant_mb: dict[str, int] = field(default_factory=dict)
    approx_mb: int = 0

    @staticmethod
    def _all_exist(group: List[Tuple[str, str]]) -> bool:
        return all(
            os.path.exists(os.path.join(MODELS_DIR, local))
            for _, local in group
        )

    def files_for(self, provider: Optional[str] = None) -> List[Tuple[str, str]]:
        if not self.variant_files:
            return self.files
        provider = provider or active_asr_provider()
        variant = "fp16" if provider == "cuda" else "int8"
        return self.files + self.variant_files[variant]

    def approx_for(self, provider: Optional[str] = None) -> int:
        if not self.variant_mb:
            return self.approx_mb
        provider = provider or active_asr_provider()
        variant = "fp16" if provider == "cuda" else "int8"
        return self.variant_mb.get(variant, self.approx_mb)

    def ready(self, provider: Optional[str] = None) -> bool:
        if self.variant_files:
            return self._all_exist(self.files_for(provider))
        if self._all_exist(self.files):
            return True
        if self.alt_files:
            return self._all_exist(self.alt_files)
        return False


# ---- 核心模型清单(启动时下载,不含 whisper/ChatTTS)----
MANIFEST: List[ModelItem] = [
    ModelItem(
        name="silero VAD(语音分段)",
        files=[("vad/silero_vad.onnx", "vad/silero_vad.onnx")],
        approx_mb=1,
    ),
    ModelItem(
        name="流式 Zipformer(实时识别)",
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
        name="Qwen3-ASR(高精度识别)",
        # frontend/tokenizer 是公共文件；encoder/decoder 按当前后端只选
        # INT8 或 FP16 一组，避免一台机器同时保存两套约 GB 级权重。
        files=[
            ("qwen3-asr/conv_frontend.onnx", "qwen3-asr/conv_frontend.onnx"),
            ("qwen3-asr/tokenizer/vocab.json", "qwen3-asr/tokenizer/vocab.json"),
            ("qwen3-asr/tokenizer/merges.txt", "qwen3-asr/tokenizer/merges.txt"),
            ("qwen3-asr/tokenizer/tokenizer_config.json", "qwen3-asr/tokenizer/tokenizer_config.json"),
        ],
        variant_files={
            "int8": [
                ("qwen3-asr/encoder.int8.onnx", "qwen3-asr/encoder.int8.onnx"),
                ("qwen3-asr/decoder.int8.onnx", "qwen3-asr/decoder.int8.onnx"),
            ],
            "fp16": [
                ("qwen3-asr/encoder.fp16.onnx", "qwen3-asr/encoder.fp16.onnx"),
                ("qwen3-asr/encoder.fp16.onnx.data", "qwen3-asr/encoder.fp16.onnx.data"),
                ("qwen3-asr/decoder.fp16.onnx", "qwen3-asr/decoder.fp16.onnx"),
                ("qwen3-asr/decoder.fp16.onnx.data", "qwen3-asr/decoder.fp16.onnx.data"),
            ],
        },
        # 以当前 ModelScope 导出物的实际大小向上取整，UI 仅作下载提示。
        variant_mb={"int8": 1000, "fp16": 1800},
        approx_mb=1000,
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


def active_asr_provider() -> str:
    """Return the provider that will be used by the production ASR path."""
    try:
        from livebabel.asr.vad_engine import detect_provider
        return detect_provider()
    except Exception:
        # Model download must remain usable even before sherpa-onnx is
        # installed (for example in a first-run setup helper).
        return "cpu"


def missing_items(provider: Optional[str] = None) -> List[ModelItem]:
    """返回尚未就绪的核心模型项(空列表 = 全齐,不含可选 ChatTTS)。"""
    provider = provider or active_asr_provider()
    return [m for m in MANIFEST if not m.ready(provider)]


def models_ready(provider: Optional[str] = None) -> bool:
    return not missing_items(provider)


def cleanup_inactive_qwen_variant(provider: Optional[str] = None,
                                  log: Optional[Callable[[str], None]] = None) -> List[str]:
    """Remove the Qwen graph variant that the current provider will not use.

    The common frontend/tokenizer stay untouched.  Keeping only INT8 on CPU
    or FP16 on CUDA avoids shipping roughly 0.6--1.3 GB of duplicate weights
    in the user's model directory.  The function is intentionally limited to
    the known Qwen files and returns the removed paths for diagnostics.
    """
    # An explicit development directory is outside the managed model store;
    # never delete files from the packaged/exported directory by accident.
    if os.environ.get("LIVEBABEL_QWEN_MODEL_DIR", "").strip():
        return []
    provider = provider or active_asr_provider()
    inactive = "fp16" if provider != "cuda" else "int8"
    names = (
        ("encoder.fp16.onnx", "encoder.fp16.onnx.data",
         "decoder.fp16.onnx", "decoder.fp16.onnx.data")
        if inactive == "fp16" else
        ("encoder.int8.onnx", "decoder.int8.onnx")
    )
    root = os.path.join(MODELS_DIR, "qwen3-asr")
    removed: List[str] = []
    for name in names:
        for suffix in ("", ".part"):
            path = os.path.join(root, name + suffix)
            if os.path.isfile(path):
                os.remove(path)
                removed.append(path)
    if removed and log:
        log(f"已清理未使用的 Qwen3-ASR {inactive.upper()} 模型文件({len(removed)} 个)。")
    return removed


def chattts_ready() -> bool:
    """返回 ChatTTS 模型目录是否包含全部必需文件。"""
    return all(os.path.isfile(os.path.join(CHATTTS_DIR, name)) for name in _CHATTTS_FILES)


def whisper_ready() -> bool:
    """返回 whisper 模型目录是否包含全部必需文件。"""
    from livebabel.paths import WHISPER_DIR
    return all(os.path.isfile(os.path.join(WHISPER_DIR, name)) for name in _WHISPER_FILES)


# ---- 通用下载实现 ----

class DownloadCancelled(Exception):
    pass


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
        if have and r.status_code == 200:
            have = 0
        elif have and r.status_code != 206:
            r.raise_for_status()
        else:
            r.raise_for_status()

        total = int(r.headers.get("Content-Length", 0))
        if total:
            total += have

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

    os.replace(part, dest)


def _download_file_list(
    files: List[Tuple[str, str]],            # (repo_path, local_dest_path)
    log: Callable[[str], None],
    on_progress: Callable[[int, int, int, int], None],
    is_cancelled: Callable[[], bool],
    ready_check: Callable[[], bool],
    done_msg: str,
) -> None:
    """下载一组文件,复用 _stream_to_file。失败抛 RuntimeError。

    on_progress(idx, count, downloaded_bytes, total_bytes): 同一下载模式。
    """
    total = len(files)
    for idx, (remote, dest) in enumerate(files, 1):
        if is_cancelled():
            raise DownloadCancelled()
        url = f"{_MS_BASE}/{remote}"
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        log(f"  [{idx}/{total}] {os.path.basename(dest)} …")
        _stream_to_file(
            url, dest,
            on_bytes=lambda d, t, _i=idx, _n=total: on_progress(_i, _n, d, t),
            is_cancelled=is_cancelled,
            log=log,
        )
    if not ready_check():
        raise RuntimeError(f"下载后校验未通过")
    log(done_msg)


# ---- 对外下载接口 ----

def download_chattts(
    log: Callable[[str], None],
    on_progress: Callable[[int, int, int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """从统一仓库下载 ChatTTS 模型(字节级进度)。"""
    files = [
        (f"chattts/{name}", os.path.join(CHATTTS_DIR, name))
        for name in _CHATTTS_FILES
    ]
    _download_file_list(files, log, on_progress, is_cancelled,
                        ready_check=chattts_ready,
                        done_msg="ChatTTS 朗读模型已就绪。")


def download_whisper(
    log: Callable[[str], None],
    on_progress: Callable[[int, int, int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """从统一仓库下载 whisper 模型(字节级进度)。"""
    from livebabel.paths import WHISPER_DIR
    files = [
        (f"whisper/{name}", os.path.join(WHISPER_DIR, name))
        for name in _WHISPER_FILES
    ]
    _download_file_list(files, log, on_progress, is_cancelled,
                        ready_check=whisper_ready,
                        done_msg="whisper 离线转录模型已就绪。")


def _download_one(
    item: ModelItem,
    provider: str,
    log: Callable[[str], None],
    on_bytes: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """下载单个模型项的所有文件。"""
    files = item.files_for(provider)
    total_files = len(files)
    for idx, (remote, local) in enumerate(files, 1):
        url = f"{_MS_BASE}/{remote}"
        dest = os.path.join(MODELS_DIR, local)
        os.makedirs(os.path.dirname(dest), exist_ok=True)

        log(f"  [{idx}/{total_files}] {os.path.basename(local)} …")
        _stream_to_file(url, dest, on_bytes, is_cancelled, log)


def download_missing(
    log: Callable[[str], None],
    on_progress: Callable[[int, int, int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """下载所有缺失的核心模型(不含 whisper/ChatTTS)。

    on_progress(idx, count, downloaded, total): 第 idx/count 个 item,
    当前文件已下/总字节。
    """
    provider = active_asr_provider()
    # Remove the inactive variant before downloading, so switching from GPU
    # to CPU (or vice versa) does not require both large graphs to coexist.
    cleanup_inactive_qwen_variant(provider, log=log)
    items = missing_items(provider)
    n = len(items)
    for i, item in enumerate(items, 1):
        log(f"[{i}/{n}] {item.name}(约 {item.approx_for(provider)}MB, {provider})…")
        _download_one(
            item, provider, log,
            lambda d, t, _i=i, _n=n: on_progress(_i, _n, d, t),
            is_cancelled,
        )
        log(f"  ✓ 完成")
    log("全部模型已就绪。")
