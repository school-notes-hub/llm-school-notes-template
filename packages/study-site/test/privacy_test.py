"""The final public gate also covers private JSON files and hidden markers."""

import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location("privacy", Path(__file__).parents[1] / "check-public.py")
privacy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(privacy)


class PrivacyTests(unittest.TestCase):
    def test_private_files_and_marker_canaries_for_two_synthetic_learners(self):
        for learner in ("learner-a", "learner-b"):
            with self.subTest(learner=learner), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "payload.json").write_text(json.dumps({"mode": "public"}))
                site = root / "site"
                for name, text in {
                    "index.html": "Tananyag",
                    "docs/review/report.json": "{}",
                    "sources/private.json": "{}",
                    "marker.html": "<!-- figure-request: secret -->",
                    "metadata.json": '{"decisions": []}',
                }.items():
                    path = site / name
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(text)
                self.assertEqual(privacy.main(root), 1)
                report = json.loads((root / "privacy-report.json").read_text())
                self.assertEqual({e["file"] for e in report["errors"]}, {
                    "docs/review/report.json", "sources/private.json", "marker.html", "metadata.json"})


if __name__ == "__main__":
    unittest.main()
