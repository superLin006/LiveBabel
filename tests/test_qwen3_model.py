import tempfile
import unittest
from pathlib import Path

from livebabel.asr.qwen3_model import has_qwen_cuda_model, qwen_model_paths


class QwenModelSelectionTest(unittest.TestCase):
    def test_provider_selects_matching_graph(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertFalse(has_qwen_cuda_model(d))
            Path(d, "encoder.int8.onnx").touch()
            Path(d, "decoder.int8.onnx").touch()
            self.assertTrue(qwen_model_paths(d, "cpu")[1].endswith("encoder.int8.onnx"))
            Path(d, "encoder.fp16.onnx").touch()
            Path(d, "decoder.fp16.onnx").touch()
            self.assertTrue(has_qwen_cuda_model(d))
            self.assertTrue(qwen_model_paths(d, "cuda")[1].endswith("encoder.fp16.onnx"))


if __name__ == "__main__":
    unittest.main()
