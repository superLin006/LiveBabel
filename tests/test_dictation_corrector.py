import unittest
from unittest.mock import patch

from livebabel.dictation.corrector import correct_text


class _Response:
    def raise_for_status(self):
        return None

    def json(self):
        return {"choices": [{"message": {"content": "你好，今天开会。"}}]}


class DictationCorrectorTests(unittest.TestCase):
    def test_missing_key_is_explicit(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "未设置 DeepSeek"):
                correct_text("嗯你好")

    @patch("livebabel.dictation.corrector.requests.post", return_value=_Response())
    def test_returns_plain_corrected_text(self, post):
        self.assertEqual(correct_text("嗯 你好", api_key="test-key"), "你好，今天开会。")
        post.assert_called_once()
        self.assertIn("Bearer test-key", post.call_args.kwargs["headers"]["Authorization"])


if __name__ == "__main__":
    unittest.main()
