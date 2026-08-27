"""Qwen3-ASR ONNX model file selection.

The application uses Qwen3-ASR for Pass2 re-recognition and offline subtitle
transcription.  This module keeps provider-specific file selection in one
place without carrying an experimental Qwen streaming implementation.
"""

from __future__ import annotations

import os


def qwen_model_paths(model_dir: str, provider: str) -> tuple[str, str, str]:
    """Return ``(conv_frontend, encoder, decoder)`` for *provider*.

    CPU uses the INT8 graphs.  CUDA uses the native FP16 graphs when present,
    with the un-suffixed ONNX names accepted for older exports.  The final
    fallback keeps existing FP32 exports usable for diagnostics.
    """
    conv = os.path.join(model_dir, "conv_frontend.onnx")
    enc_fp32 = os.path.join(model_dir, "encoder.onnx")
    dec_fp32 = os.path.join(model_dir, "decoder.onnx")

    if provider == "cuda":
        for enc, dec in (
            (os.path.join(model_dir, "encoder.fp16.onnx"),
             os.path.join(model_dir, "decoder.fp16.onnx")),
            (enc_fp32, dec_fp32),
        ):
            if os.path.isfile(enc) and os.path.isfile(dec):
                return conv, enc, dec

    enc_i8 = os.path.join(model_dir, "encoder.int8.onnx")
    dec_i8 = os.path.join(model_dir, "decoder.int8.onnx")
    if os.path.isfile(enc_i8) and os.path.isfile(dec_i8):
        return conv, enc_i8, dec_i8

    return conv, enc_fp32, dec_fp32


def has_qwen_cuda_model(model_dir: str) -> bool:
    """Whether native floating-point graphs suitable for CUDA are present."""
    return (
        os.path.isfile(os.path.join(model_dir, "encoder.fp16.onnx"))
        and os.path.isfile(os.path.join(model_dir, "decoder.fp16.onnx"))
    ) or (
        os.path.isfile(os.path.join(model_dir, "encoder.onnx"))
        and os.path.isfile(os.path.join(model_dir, "decoder.onnx"))
    )


# Kept as a compatibility name for callers outside LiveBabel.
has_qwen_fp16 = has_qwen_cuda_model
