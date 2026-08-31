import unittest

from livebabel.ui.launcher import resolve_api_key


class ApiKeyResolutionTests(unittest.TestCase):
    def test_saved_key_wins_over_environment(self):
        key, source = resolve_api_key(
            {"api_key": "  saved-key  "},
            {"DEEPSEEK_API_KEY": "environment-key"},
        )
        self.assertEqual((key, source), ("saved-key", "saved"))

    def test_environment_key_is_reported_as_external(self):
        key, source = resolve_api_key(
            {"api_key": ""},
            {"DEEPSEEK_API_KEY": " environment-key "},
        )
        self.assertEqual((key, source), ("environment-key", "environment"))

    def test_missing_key_is_not_configured(self):
        self.assertEqual(resolve_api_key({}, {}), ("", "missing"))


if __name__ == "__main__":
    unittest.main()
