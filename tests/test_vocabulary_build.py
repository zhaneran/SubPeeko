import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import unquote

import vocabulary_build


class VocabularyBuildTests(unittest.TestCase):
    def test_offline_check_keeps_bundled_vocabulary(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            source = {"repository": vocabulary_build.REPOSITORY, "revision": "a" * 40}
            (data / "vocabulary-source.json").write_text(json.dumps(source), encoding="utf-8")
            (data / "vocabulary.json").write_text('{"old":0}', encoding="utf-8")
            (data / "LICENSE-KyleBing.txt").write_text("license", encoding="utf-8")
            with patch.object(vocabulary_build, "_read", side_effect=OSError("offline")):
                with self.assertWarnsRegex(UserWarning, "using the bundled snapshot"):
                    vocabulary_build.refresh(data)
            self.assertEqual(json.loads((data / "vocabulary.json").read_text()), {"old": 0})
            self.assertEqual(json.loads((data / "vocabulary-source.json").read_text()), source)

    def test_updated_revision_is_bundled_and_license_change_keeps_snapshot(self):
        with tempfile.TemporaryDirectory() as temporary:
            data = Path(temporary)
            source = data / "vocabulary-source.json"
            source.write_text(json.dumps({"repository": vocabulary_build.REPOSITORY, "revision": "a" * 40}), encoding="utf-8")
            (data / "vocabulary.json").write_text('{"old":0}', encoding="utf-8")
            (data / "LICENSE-KyleBing.txt").write_bytes(b"license")

            def read(url):
                if url == vocabulary_build.API:
                    return json.dumps({"sha": "b" * 40}).encode()
                if url.endswith("/LICENSE"):
                    return b"license"
                filename = unquote(url).rsplit("/", 1)[-1]
                group = next(i for i, (name, _) in enumerate(vocabulary_build.SOURCES) if name == filename)
                words = []
                for i in range(250):
                    number = group * 250 + i
                    suffix = "".join(chr(97 + (number // divisor) % 26) for divisor in (676, 26, 1))
                    words.append("word" + suffix + "\tdefinition")
                words.append("common\tdefinition")
                return "\n".join(words).encode()

            with patch.object(vocabulary_build, "_read", side_effect=read):
                vocabulary_build.refresh(data)
            updated = json.loads((data / "vocabulary.json").read_text(encoding="utf-8"))
            self.assertEqual(len(updated), 1251)
            self.assertEqual(updated["common"], 0)
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["revision"], "b" * 40)

            source.write_text(json.dumps({"repository": vocabulary_build.REPOSITORY, "revision": "a" * 40}), encoding="utf-8")
            with patch.object(vocabulary_build, "_read", side_effect=lambda url: b"different" if url.endswith("/LICENSE") else read(url)):
                with self.assertWarnsRegex(UserWarning, "license changed"):
                    vocabulary_build.refresh(data)
            self.assertEqual(json.loads((data / "vocabulary.json").read_text(encoding="utf-8")), updated)
            self.assertEqual(json.loads(source.read_text(encoding="utf-8"))["revision"], "a" * 40)


if __name__ == "__main__":
    unittest.main()
