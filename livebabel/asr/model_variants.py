"""Provider-specific model file selection shared by ASR/TTS components."""

from __future__ import annotations

import os


def zipformer_model_paths(model_dir: str, provider: str = "cpu") -> dict[str, str]:
    """Return provider-safe Zipformer graph paths.

    CPU uses the validated hybrid graph (INT8 encoder/joiner + FP32 decoder).
    Quantizing the decoder as well can cause repeated draft tokens. CUDA uses
    the all-FP32 graphs, which are the known-good GPU configuration.
    """
    if provider == "cuda":
        suffix = ""
        decoder = "decoder-epoch-99-avg-1.onnx"
    else:
        suffix = ".int8"
        decoder = "decoder-epoch-99-avg-1.onnx"
    return {
        "encoder": os.path.join(model_dir, f"encoder-epoch-99-avg-1{suffix}.onnx"),
        "decoder": os.path.join(model_dir, decoder),
        "joiner": os.path.join(model_dir, f"joiner-epoch-99-avg-1{suffix}.onnx"),
    }


def chattts_model_paths(model_dir: str, provider: str) -> dict[str, str]:
    """Return the ChatTTS graph paths for CPU INT8 or CUDA FP16."""
    suffix = "fp16" if provider == "cuda" else "int8"
    paths = {
        "gpt_prefill": os.path.join(model_dir, f"gpt_prefill.{suffix}.onnx"),
        "decoder": os.path.join(model_dir, f"decoder.{suffix}.onnx"),
        "vocos": os.path.join(model_dir, f"vocos.{suffix}.onnx"),
    }
    missing = [p for p in paths.values() if not os.path.isfile(p)]
    if missing:
        raise FileNotFoundError("ChatTTS 模型文件不存在: " + ", ".join(missing))
    return paths
