import os
import tempfile
import unittest

from livebabel.asr.model_variants import (
    chattts_model_paths,
    sensevoice_model_path,
    zipformer_model_paths,
)


class ModelVariantTests(unittest.TestCase):
    def test_zipformer_prefers_provider_variant(self):
        with tempfile.TemporaryDirectory() as d:
            for name in ("tokens.txt", "bpe.model", "bpe.vocab",
                         "encoder-epoch-99-avg-1.int8.onnx",
                         "decoder-epoch-99-avg-1.int8.onnx",
                         "joiner-epoch-99-avg-1.int8.onnx",
                         "encoder-epoch-99-avg-1.fp16.onnx",
                         "decoder-epoch-99-avg-1.fp16.onnx",
                         "joiner-epoch-99-avg-1.fp16.onnx"):
                open(os.path.join(d, name), "wb").close()
            self.assertTrue(zipformer_model_paths(d, "cpu")[1].endswith(".int8.onnx"))
            self.assertTrue(zipformer_model_paths(d, "cuda")[1].endswith(".fp16.onnx"))

    def test_sensevoice_and_chattts_variants(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "model.int8.onnx"), "wb").close()
            open(os.path.join(d, "model.fp16.onnx"), "wb").close()
            self.assertTrue(sensevoice_model_path(d, "cpu").endswith("model.int8.onnx"))
            self.assertTrue(sensevoice_model_path(d, "cuda").endswith("model.fp16.onnx"))
            for name in (
                "default_speaker.bin", "homophones_map.json", "vocab.txt",
                "decoder.int8.onnx", "gpt_decode.int8.onnx",
                "gpt_prefill.int8.onnx", "vocos.int8.onnx",
                "decoder.fp16.onnx", "gpt_decode.fp16.onnx",
                "gpt_prefill.fp16.onnx", "vocos.fp16.onnx",
            ):
                open(os.path.join(d, name), "wb").close()
            self.assertTrue(chattts_model_paths(d, "cpu")["gpt_prefill"].endswith("int8.onnx"))
            self.assertTrue(chattts_model_paths(d, "cuda")["gpt_prefill"].endswith("fp16.onnx"))

    def test_gpu_does_not_silently_use_cpu_sensevoice_or_chattts(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, "model.int8.onnx"), "wb").close()
            with self.assertRaises(FileNotFoundError):
                sensevoice_model_path(d, "cuda")


if __name__ == "__main__":
    unittest.main()
