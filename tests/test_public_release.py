"""Low-cost regression checks for repository publication and entry points."""

from __future__ import annotations

import unittest
from pathlib import Path

from scripts.public_release_check import main as public_release_check

ROOT = Path(__file__).resolve().parent.parent


class PublicReleaseTests(unittest.TestCase):
    def test_private_artifacts_are_ignored(self):
        ignore_text = (ROOT / ".gitignore").read_text(encoding="utf-8")
        for required in (".env", "data/*.db", "data/*.ndjson", "data/*.csv"):
            self.assertIn(required, ignore_text)

    def test_public_files_have_no_known_credential_shapes(self):
        self.assertEqual(public_release_check(), 0)

    def test_backward_compatible_entry_points_exist(self):
        self.assertTrue((ROOT / "web_api.py").is_file())
        self.assertTrue((ROOT / "main.py").is_file())
        self.assertTrue((ROOT / "backend" / "web_api.py").is_file())
        self.assertTrue((ROOT / "backend" / "feishu_worker.py").is_file())
        self.assertTrue((ROOT / "scripts" / "manage.py").is_file())


if __name__ == "__main__":
    unittest.main()
