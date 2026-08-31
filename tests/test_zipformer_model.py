import unittest

from livebabel.asr.model_variants import zipformer_model_paths
from livebabel.model_setup import MANIFEST


class ZipformerModelSelectionTest(unittest.TestCase):
    def test_cpu_uses_hybrid_and_cuda_uses_fp32_graphs(self):
        cpu = zipformer_model_paths("models/zipformer", "cpu")
        cuda = zipformer_model_paths("models/zipformer", "cuda")
        self.assertTrue(cpu["encoder"].endswith("encoder-epoch-99-avg-1.int8.onnx"))
        self.assertTrue(cpu["decoder"].endswith("decoder-epoch-99-avg-1.onnx"))
        self.assertTrue(cpu["joiner"].endswith("joiner-epoch-99-avg-1.int8.onnx"))
        self.assertTrue(cuda["encoder"].endswith("encoder-epoch-99-avg-1.onnx"))
        self.assertTrue(cuda["decoder"].endswith("decoder-epoch-99-avg-1.onnx"))
        self.assertTrue(cuda["joiner"].endswith("joiner-epoch-99-avg-1.onnx"))

    def test_manifest_downloads_cpu_hybrid_graphs(self):
        item = next(m for m in MANIFEST if "Zipformer" in m.name)
        cpu_names = [remote for remote, _ in item.files_for("cpu")]
        self.assertIn("zipformer/encoder-epoch-99-avg-1.int8.onnx", cpu_names)
        self.assertIn("zipformer/decoder-epoch-99-avg-1.onnx", cpu_names)
        self.assertIn("zipformer/joiner-epoch-99-avg-1.int8.onnx", cpu_names)
        self.assertNotIn("zipformer/decoder-epoch-99-avg-1.int8.onnx", cpu_names)


if __name__ == "__main__":
    unittest.main()
