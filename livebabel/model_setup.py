"""首次启动自动下载语音模型。

把原先「下载模型.bat」的逻辑搬进程序:检测 models/ 缺哪个 → 流式下载(带镜像回退 +
重试 + 断点续传)→ tar 包自动解压。GUI 进度窗见 model_download_dialog.py。

只下三种模式实际会用到的【核心模型】(pyannote-segmentation 代码里没用到,不下;
离线 whisper 由 faster-whisper 用时自动下,也不在这里):
  - silero_vad.onnx                                 实时 VAD + 会议分段
  - sherpa-onnx-streaming-zipformer-...             实时识别
  - sherpa-onnx-sense-voice-...                     高精度识别
  - 3dspeaker_eres2net_sv_zh.onnx                   会议声纹区分
"""

from __future__ import annotations

import os
import tarfile
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from livebabel.paths import MODELS_DIR

# GitHub release 直链;下载时按顺序在前面拼镜像前缀,任一成功即用。
_GH = "https://github.com/k2-fsa/sherpa-onnx/releases/download"
_ASR = f"{_GH}/asr-models"
_SV = f"{_GH}/speaker-recongition-models"

# 国内加速镜像 → 官方直连(空前缀)兜底。镜像站域名偶尔变,失败会自动落到下一个。
MIRRORS = ("https://ghfast.top/", "https://gh-proxy.com/", "")


@dataclass
class ModelItem:
    name: str                       # 给用户看的名字
    url: str                        # 官方 github 直链
    # 下载落地的文件名(相对 models/)
    filename: str
    # tar.bz2 解压后应出现的目录名;非压缩包则为空
    extract_dir: str = ""
    # 判定"已就绪"要存在的相对路径(目录里的关键文件 / 单文件本身)
    check: List[str] = field(default_factory=list)
    approx_mb: int = 0

    def dest(self) -> str:
        return os.path.join(MODELS_DIR, self.filename)

    def ready(self) -> bool:
        return all(os.path.exists(os.path.join(MODELS_DIR, c)) for c in self.check)


# ---- 核心模型清单(4 项)----
MANIFEST: List[ModelItem] = [
    ModelItem(
        name="silero VAD(语音分段)",
        url=f"{_ASR}/silero_vad.onnx",
        filename="silero_vad.onnx",
        check=["silero_vad.onnx"],
        approx_mb=2,
    ),
    ModelItem(
        name="流式 zipformer(实时识别)",
        url=f"{_ASR}/sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2",
        filename="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20.tar.bz2",
        extract_dir="sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20",
        check=["sherpa-onnx-streaming-zipformer-bilingual-zh-en-2023-02-20/tokens.txt"],
        approx_mb=300,
    ),
    ModelItem(
        name="SenseVoice(高精度识别)",
        url=f"{_ASR}/sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
        filename="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17.tar.bz2",
        extract_dir="sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17",
        check=["sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17/tokens.txt"],
        approx_mb=230,
    ),
    ModelItem(
        name="声纹模型(会议区分说话人)",
        url=f"{_SV}/3dspeaker_speech_eres2net_base_sv_zh-cn_3dspeaker_16k.onnx",
        filename="3dspeaker_eres2net_sv_zh.onnx",
        check=["3dspeaker_eres2net_sv_zh.onnx"],
        approx_mb=39,
    ),
]


def missing_items() -> List[ModelItem]:
    """返回尚未就绪的核心模型项(空列表 = 全齐)。"""
    return [m for m in MANIFEST if not m.ready()]


def models_ready() -> bool:
    return not missing_items()


# ---- 下载实现 ----

class DownloadCancelled(Exception):
    pass


def _download_one(
    item: ModelItem,
    log: Callable[[str], None],
    on_bytes: Callable[[int, int], None],
    is_cancelled: Callable[[], bool],
) -> None:
    """下载并(如需要)解压单个模型。镜像逐个尝试,失败抛 RuntimeError。

    on_bytes(downloaded, total): total 为 0 表示未知。断点续传:已有部分文件则带 Range 续传。
    """
    import requests

    dest = item.dest()
    os.makedirs(MODELS_DIR, exist_ok=True)

    last_err: Optional[Exception] = None
    for prefix in MIRRORS:
        url = prefix + item.url
        src = "官方 github.com" if not prefix else prefix.split("//")[-1].rstrip("/")
        log(f"  尝试镜像:{src}")
        try:
            _stream_to_file(url, dest, on_bytes, is_cancelled, log)
            break  # 这个镜像成功
        except DownloadCancelled:
            raise
        except Exception as e:  # 网络/HTTP 错误 → 换下一个镜像
            last_err = e
            log(f"    ✗ {type(e).__name__}: {e}")
            continue
    else:
        raise RuntimeError(f"全部镜像都失败:{last_err}")

    # tar.bz2 → 解压
    if item.extract_dir:
        log(f"  解压 {item.filename} …")
        try:
            with tarfile.open(dest, "r:bz2") as tf:
                tf.extractall(MODELS_DIR)
        except Exception as e:
            try:
                os.remove(dest)  # 损坏包删掉,下次重下
            except OSError:
                pass
            raise RuntimeError(f"解压失败(包可能不完整):{e}")
        if not item.ready():
            raise RuntimeError("解压后仍缺关键文件,包可能不完整")
        os.remove(dest)  # 解压成功删掉压缩包省空间

    if not item.ready():
        raise RuntimeError("下载后校验未通过")


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
    """下载所有缺失的核心模型。

    on_progress(idx, count, downloaded, total): 第 idx/count 个,当前文件已下/总字节。
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
    log("全部核心模型已就绪。")
