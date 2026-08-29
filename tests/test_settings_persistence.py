import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from livebabel.ui import overlay


class SettingsPersistenceTests(unittest.TestCase):
    def test_single_field_update_preserves_newer_api_key(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "settings.json")
            with patch.object(overlay, "SETTINGS_PATH", path):
                overlay.save_settings({"api_key": "new-key", "lang": "中文"})

                # Simulate an old overlay saving geometry after the launcher
                # has already written a newer API key.
                latest = overlay.persist_setting("geometry", [1, 2, 3, 4])
                self.assertEqual(latest["api_key"], "new-key")
                with open(path, encoding="utf-8") as f:
                    stored = json.load(f)
                self.assertEqual(stored["api_key"], "new-key")
                self.assertEqual(stored["geometry"], [1, 2, 3, 4])

    def test_api_key_can_still_be_cleared_explicitly(self):
        with tempfile.TemporaryDirectory() as td:
            path = str(Path(td) / "settings.json")
            with patch.object(overlay, "SETTINGS_PATH", path):
                overlay.save_settings({"api_key": "old-key"})
                overlay.persist_setting("api_key", "")
                self.assertEqual(overlay.load_settings()["api_key"], "")


if __name__ == "__main__":
    unittest.main()
