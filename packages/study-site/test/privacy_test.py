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


    def test_a_podcast_mp3_may_carry_only_title_and_album_and_no_private_text(self):
        def frame(name, text):
            body = b"\x03" + text.encode()
            return name.encode() + len(body).to_bytes(4, "big") + b"\0\0" + body

        def tag(*frames):
            data = b"".join(frames)
            size = len(data)
            synchsafe = bytes([(size >> 21) & 0x7f, (size >> 14) & 0x7f, (size >> 7) & 0x7f, size & 0x7f])
            return b"ID3\x03\0\0" + synchsafe + data + b"\xff\xfb\x90\0" + b"\0" * 200

        cases = {
            "ok.mp3": (tag(frame("TIT2", "Az első téma"), frame("TALB", "Képben vagy?")), []),
            "extra.mp3": (tag(frame("TIT2", "Cím"), frame("TPE1", "Valaki")), ["unexpected MP3 tag: TPE1"]),
            "path.mp3": (tag(frame("TIT2", "sources/proba/p0001.jpg")), ["\\bsources/", "\\bp\\d{4}\\b"]),
        }
        for name, (data, expected) in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / "payload.json").write_text(json.dumps({"mode": "public"}))
                (root / "site" / "media").mkdir(parents=True)
                (root / "site" / "media" / name).write_bytes(data)
                self.assertEqual(privacy.main(root), 1 if expected else 0)
                report = json.loads((root / "privacy-report.json").read_text())
                self.assertEqual([e["pattern"] for e in report["errors"]], expected)


if __name__ == "__main__":
    unittest.main()
