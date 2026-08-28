"""Provider-specific ASR/TTS model file selection.

The v1.4.1 model store keeps CPU INT8 and NVIDIA CUDA FP16 graphs side by
side.  A single installation downloads only the variant selected by the
active provider, while the legacy unsuffixed files remain valid as a
backward-compatible fallback for existing v1.4.0 installations.
"""

from __future__ import annotations

import os
from typing import Dict, Tuple


def _all_files(paths: Tuple[str, ...]) -> bool:
    return all(os.path.isfile(p) for p in paths)


def _variant(provider: str) -> str:
    return "fp16" if provider == "cuda" else "int8"


def zipformer_model_paths(model_dir: str, provider: str = "cpu") -> Tuple[str, str, str, str]:
    """Return ``(tokens, encoder, decoder, joiner)`` for Zipformer.

    INT8 is selected on CPU and FP16 on CUDA.  Unsuffixed FP32 graphs are
    accepted only as a migration fallback so an already-installed v1.4.0
    copy can still start while the new graph is downloading.
    """
    suffix = _variant(provider)
    stem = "epoch-99-avg-1"
    selected = (
        os.path.join(model_dir, "tokens.txt"),
        os.path.join(model_dir, f"encoder-{stem}.{suffix}.onnx"),
        os.path.join(model_dir, f"decoder-{stem}.{suffix}.onnx"),
        os.path.join(model_dir, f"joiner-{stem}.{suffix}.onnx"),
    )
    if _all_files(selected):
        return selected

    legacy = (
        os.path.join(model_dir, "tokens.txt"),
        os.path.join(model_dir, f"encoder-{stem}.onnx"),
        os.path.join(model_dir, f"decoder-{stem}.onnx"),
        os.path.join(model_dir, f"joiner-{stem}.onnx"),
    )
    if _all_files(legacy):
        return legacy
    missing = [p for p in selected if not os.path.isfile(p)]
    raise FileNotFoundError("Zipformer 模型缺少文件: " + ", ".join(missing))


def sensevoice_model_path(model_dir: str, provider: str = "cpu") -> str:
    """Return SenseVoice graph path, preferring provider-specific precision."""
    suffix = _variant(provider)
    preferred = os.path.join(model_dir, f"model.{suffix}.onnx")
    if os.path.isfile(preferred):
        return preferred
    legacy = os.path.join(model_dir, "model.int8.onnx")
    if provider != "cuda" and os.path.isfile(legacy):
        return legacy
    raise FileNotFoundError(f"SenseVoice 模型不存在: {preferred}")


def chattts_model_paths(model_dir: str, provider: str = "cpu") -> Dict[str, str]:
    """Return ChatTTS graph paths for the selected provider.

    ``gpt_decode`` is downloaded as part of the model set for runtimes that
    expose it separately; the current C++ API consumes ``gpt_prefill`` as the
    GPT entry point.  All three graphs must use the same precision variant.
    """
    suffix = _variant(provider)
    names = {
        "gpt_decode": f"gpt_decode.{suffix}.onnx",
        "gpt_prefill": f"gpt_prefill.{suffix}.onnx",
        "decoder": f"decoder.{suffix}.onnx",
        "vocos": f"vocos.{suffix}.onnx",
    }
    paths = {key: os.path.join(model_dir, name) for key, name in names.items()}
    if all(os.path.isfile(p) for p in paths.values()):
        return paths

    # Backward compatibility with v1.3/v1.4.0's CPU-only ChatTTS bundle is
    # intentionally limited to CPU.  A CUDA request must never silently run
    # an INT8 graph and claim that GPU FP16 is active.
    if provider != "cuda":
        legacy_names = {
            key: os.path.join(model_dir, f"{key}.int8.onnx")
            for key in names
        }
        if all(os.path.isfile(p) for p in legacy_names.values()):
            return legacy_names
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    raise FileNotFoundError("ChatTTS 模型缺少文件: " + ", ".join(missing))
