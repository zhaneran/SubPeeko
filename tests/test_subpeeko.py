import contextlib
import io
import json
import os
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from subpeeko import cli, config
from subpeeko.config import Config
from subpeeko.model import ModelClient, ModelError, local_simple
from subpeeko.subtitles import AssFile, Dialogue, SubtitleError
from subpeeko.vocabulary import ambiguous_words, vocabulary_hints


ASS = r"""[Script Info]
Title: Example
[V4+ Styles]
Format: Name, Fontname
Style: Default,Arial
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,{\an2}装置似乎发生故障\N{\rEng}The device had a malfunction.
Dialogue: 0,0:00:03.50,0:00:04.00,Default,,0,0,0,,Yes.\N是的
Dialogue: 1,0:00:04.00,0:00:06.00,Note,,0,0,0,,{\pos(10,20)}FM标识\N广播设备文字
[Aegisub Extradata]
Data: 0,a-mo,opaque data
""".replace("\n", "\r\n")


def dialogue(identifier, english, chinese):
    return Dialogue(identifier, identifier, 0, 0, 0, english, chinese, float(identifier))


class SubtitleTests(unittest.TestCase):
    def test_preserves_english_style_timing_other_events_and_extradata(self):
        original = b"\xef\xbb\xbf" + ASS.encode("utf-8")
        subtitles = AssFile(original)
        self.assertEqual(len(subtitles.dialogues), 2)
        result = subtitles.render({1: "malfunction: 故障", 2: ""})
        expected = ASS.replace("装置似乎发生故障", "malfunction: 故障").replace("Yes.\\N是的", "Yes.\\N")
        self.assertEqual(result, b"\xef\xbb\xbf" + expected.encode("utf-8"))

    def test_utf16_and_gb18030_round_trip(self):
        for encoding in ("utf-16", "gb18030"):
            with self.subTest(encoding=encoding):
                source = ASS.encode(encoding)
                subtitles = AssFile(source)
                output = subtitles.render({1: "malfunction: 故障", 2: ""})
                self.assertIn("malfunction: 故障", output.decode(encoding))
                if encoding == "utf-16":
                    self.assertEqual(output[:2], source[:2])

    def test_unknown_layout_is_left_alone(self):
        source = ASS.replace("Yes.\\N是的", "English and 中文 on one line")
        subtitles = AssFile(source.encode())
        self.assertEqual(len(subtitles.dialogues), 1)
        output = subtitles.render({1: "malfunction: 故障"}).decode()
        self.assertIn("English and 中文 on one line", output)

    def test_multi_line_english_and_chinese_are_processed_as_one_event(self):
        source = ASS.replace(
            r"装置似乎发生故障\N{\rEng}The device had a malfunction.",
            r"{\b1}装置似乎\N发生故障\N{\rEng}The device\Nhad a malfunction.",
        )
        subtitles = AssFile(source.encode())
        self.assertEqual(subtitles.dialogues[0].english, "The device had a malfunction.")
        output = subtitles.render({1: "malfunction: 故障", 2: ""}).decode()
        self.assertIn(r"{\b1}malfunction: 故障\N{\rEng}The device\Nhad a malfunction.", output)

    def test_rejects_unsupported_event_format(self):
        source = ASS.replace("MarginV, Effect, Text", "MarginV, Text, Effect")
        with self.assertRaises(SubtitleError):
            AssFile(source.encode())

    def test_invalid_bom_encoding_is_reported_cleanly(self):
        with self.assertRaises(SubtitleError):
            AssFile(b"\xff\xfe\x00")


class VocabularyTests(unittest.TestCase):
    def test_levels_and_inflected_words(self):
        hints = vocabulary_hints("They took it; a malfunction.", "highschool")
        levels = {item["word"].casefold(): item["level"] for item in hints}
        self.assertNotIn("took", levels)
        self.assertEqual(levels["malfunction"], "cet4")
        self.assertNotIn("malfunction", {x["word"].casefold() for x in vocabulary_hints("malfunction", "cet4")})
        self.assertIn("tabled", ambiguous_words("They tabled the proposal."))


class ModelTests(unittest.TestCase):
    def test_local_simple_is_deliberately_narrow(self):
        self.assertTrue(local_simple(dialogue(1, "Yes!", "是的"), "highschool"))
        self.assertFalse(local_simple(dialogue(2, "You really pulled it off.", "你居然做到了"), "highschool"))
        self.assertFalse(local_simple(dialogue(3, "Yes.", "我没事"), "highschool"))
        self.assertFalse(local_simple(dialogue(4, "Okay.", "好的"), "highschool"))
        self.assertTrue(local_simple(dialogue(4, "Okay.", "好的"), "cet4"))

    def test_filters_levels_validates_spans_and_escapes_tags(self):
        expected = {1: dialogue(1, "The device had a malfunction.", "装置似乎发生故障")}
        body = json.dumps({"items": [{"id": 1, "notes": [
            {"span": "malfunction", "zh": r"{\pos(1,2)}故障", "level": "cet4", "kind": "word"}
        ]}]})
        note = ModelClient._parse(body, expected, "highschool")[1]
        self.assertIn("故障", note)
        self.assertNotIn("{", note)
        self.assertNotIn("\\", note)
        self.assertEqual(ModelClient._parse(body, expected, "cet4")[1], "")
        with self.assertRaises(ModelError):
            ModelClient._parse(body.replace("malfunction", "hallucination"), expected, "highschool")
        with self.assertRaises(ModelError):
            ModelClient._parse('{"items": []}', expected, "highschool")

    def test_known_standalone_words_are_filtered_but_advanced_senses_are_kept(self):
        expected = {1: dialogue(1, "They left the room.", "他们离开了房间")}
        data = {"items": [{"id": 1, "notes": [{"span": "left", "zh": "离开", "level": "cet6", "kind": "word"}]}]}
        self.assertEqual(ModelClient._parse(json.dumps(data), expected, "cet4")[1], "")
        data["items"][0]["notes"][0]["kind"] = "sense"
        self.assertIn("离开", ModelClient._parse(json.dumps(data), expected, "cet4")[1])

    def test_batches_and_preserves_individual_target_identity(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20)
        records = [dialogue(i, f"Unfamiliarword{i}", f"中文{i}") for i in range(1, 46)]
        payloads = []
        progress = []

        def respond(messages):
            payload = json.loads(messages[-1]["content"])
            payloads.append(payload)
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(client, "_request", side_effect=respond):
            result = client.analyze(records, "cet4", all_model=True, progress=lambda done, total: progress.append((done, total)))
        self.assertEqual(len(result), 45)
        self.assertEqual(len(payloads), 3)
        self.assertTrue(all(len(item["target_ids"]) <= 20 for item in payloads))
        self.assertEqual(len({i for p in payloads for i in p["target_ids"]}), 45)
        self.assertEqual(progress, [(0, 45), (20, 45), (40, 45), (45, 45)])

    def test_distinct_targets_with_same_neighbor_window_are_not_deduplicated(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20)
        records = [dialogue(1, "One thing", "一件事"), dialogue(2, "Other thing", "另一件事")]

        def respond(messages):
            payload = json.loads(messages[-1]["content"])
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(client, "_request", side_effect=respond) as request:
            result = client.analyze(records, "cet4", all_model=True)
        self.assertEqual(set(result), {1, 2})
        self.assertEqual(client.cached_count, 0)
        self.assertEqual(len(json.loads(request.call_args.args[0][-1]["content"])["target_ids"]), 2)

    def test_large_failed_batch_is_split_and_recovered(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20)
        records = [dialogue(i, f"Unfamiliarword{i}", f"中文{i}") for i in range(1, 7)]
        sizes = []
        retries = []

        def respond(messages):
            payload = json.loads(messages[-1]["content"])
            ids = payload["target_ids"]
            sizes.append(len(ids))
            if len(ids) > 2:
                raise ModelError("timed out", split_batch=True, retryable=True)
            return json.dumps({"items": [{"id": i, "notes": []} for i in ids]})

        with patch.object(client, "_request", side_effect=respond):
            result = client.analyze(records, "cet4", all_model=True, on_retry=retries.append)
        self.assertEqual(set(result), set(range(1, 7)))
        self.assertEqual(sizes, [6, 3, 1, 2, 3, 1, 2])
        self.assertEqual(len(retries), 3)


class ConfigTests(unittest.TestCase):
    def test_environment_overrides_saved_configuration_and_key_is_not_displayed(self):
        secret = "never-print-this-secret"
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            path.write_text(json.dumps({"base_url": "https://saved.example/v1", "model_name": "saved"}))
            env = {"SUBPEEKO_BASE_URL": "https://override.example/v1", "SUBPEEKO_MODEL_NAME": "chosen", "SUBPEEKO_API_KEY": secret}
            with patch.object(config, "config_path", return_value=path), patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as output:
                result = config.load_config()
                config.show_config()
            self.assertEqual(result.base_url, env["SUBPEEKO_BASE_URL"])
            self.assertEqual(result.model_name, "chosen")
            self.assertNotIn(secret, repr(result))
            self.assertNotIn(secret, output.getvalue())

    def test_invalid_url_does_not_display_embedded_credentials(self):
        with patch.object(config, "_read_saved", return_value={}), patch.object(config, "_stored_key", return_value=""), patch.dict(os.environ, {"SUBPEEKO_BASE_URL": "https://user:secret@example.com/v1"}), contextlib.redirect_stdout(io.StringIO()) as output:
            config.show_config()
        self.assertNotIn("secret", output.getvalue())
        self.assertIn("invalid URL", output.getvalue())

    def test_credential_store_failure_does_not_fall_back_to_plaintext(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "config.json"
            with patch.object(config, "config_path", return_value=path), patch.object(config, "_keyring", return_value=None), patch("builtins.input", side_effect=["https://example.com/v1", "model"]), contextlib.redirect_stdout(io.StringIO()) as output:
                config.configure()
            self.assertEqual(json.loads(path.read_text()), {"base_url": "https://example.com/v1", "model_name": "model"})
            self.assertIn("SUBPEEKO_API_KEY", output.getvalue())


class MockHandler(BaseHTTPRequestHandler):
    calls = []
    invalid = False
    redirect = False
    redirected_requests = 0

    def do_POST(self):
        if type(self).redirect:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/other")
            self.end_headers()
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        payload = json.loads(request["messages"][-1]["content"])
        type(self).calls.append((self.path, payload))
        if type(self).invalid:
            content = '{"items": []}'
        else:
            by_id = {row["id"]: row for row in payload["dialogue"]}
            items = []
            for identifier in payload["target_ids"]:
                row = by_id[identifier]
                notes = ([{"span": "malfunction", "zh": "故障", "level": "cet4", "kind": "word"}]
                         if "malfunction" in row["english"] else [])
                items.append({"id": identifier, "notes": notes})
            content = json.dumps({"items": items}, ensure_ascii=False)
        body = json.dumps({"choices": [{"message": {"content": content}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).redirected_requests += 1
        self.send_response(200)
        self.end_headers()

    def log_message(self, *args):
        pass


class CliIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), MockHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def setUp(self):
        MockHandler.calls = []
        MockHandler.invalid = False
        MockHandler.redirect = False
        MockHandler.redirected_requests = 0
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = {
            "SUBPEEKO_BASE_URL": f"http://127.0.0.1:{self.server.server_port}/v1",
            "SUBPEEKO_MODEL_NAME": "mock-model",
            "SUBPEEKO_API_KEY": "mock-secret",
        }

    def run_cli(self, arguments):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.dict(os.environ, self.env), patch.object(config, "_read_saved", return_value={}), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = cli.main(arguments)
        self.assertNotIn("mock-secret", stdout.getvalue() + stderr.getvalue())
        return result, stdout.getvalue(), stderr.getvalue()

    def test_single_file_full_api_flow_and_no_overwrite(self):
        source = self.root / "电影.ass"
        source.write_bytes(ASS.encode("utf-8-sig"))
        original = source.read_bytes()
        status, output, _ = self.run_cli([str(source), "--level", "highschool"])
        target = self.root / "电影.highschool.subpeeko.ass"
        self.assertEqual(status, 0)
        self.assertTrue(target.exists())
        self.assertEqual(source.read_bytes(), original)
        generated = target.read_bytes().decode("utf-8-sig")
        self.assertIn("malfunction: 故障", generated)
        self.assertIn(r"{\rEng}The device had a malfunction.", generated)
        self.assertIn("[Aegisub Extradata]", generated)
        self.assertEqual(MockHandler.calls[0][0], "/v1/chat/completions")
        self.assertEqual(len(MockHandler.calls[0][1]["target_ids"]), 1)
        self.assertIn("1 model request", output)
        status, _, error = self.run_cli([str(source), "--level", "highschool"])
        self.assertEqual(status, 1)
        self.assertIn("already exists", error)
        self.assertEqual(len(MockHandler.calls), 1)

    def test_directory_recursive_dry_run_and_generated_outputs_are_excluded(self):
        (self.root / "one.ASS").write_text(ASS, encoding="utf-8")
        nested = self.root / "nested"
        nested.mkdir()
        (nested / "two.ass").write_text(ASS, encoding="utf-8")
        (self.root / "old.cet4.subpeeko.ass").write_text(ASS, encoding="utf-8")
        status, output, _ = self.run_cli([str(self.root), "--level", "cet4", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("1 file(s)", output)
        self.assertNotIn("old.cet4.subpeeko", output)
        status, output, _ = self.run_cli([str(self.root), "--level", "cet4", "--recursive", "--dry-run"])
        self.assertEqual(status, 0)
        self.assertIn("2 file(s)", output)
        self.assertEqual(MockHandler.calls, [])

    def test_recursive_batch_continues_after_a_bad_file(self):
        first = self.root / "one.ass"
        first.write_bytes(ASS.encode("utf-8"))
        (self.root / "broken.ass").write_text("not an ASS file", encoding="utf-8")
        nested = self.root / "nested"
        nested.mkdir()
        second = nested / "two.ASS"
        second.write_bytes(ASS.encode("utf-8"))
        status, output, error = self.run_cli([str(self.root), "--level", "highschool", "--recursive"])
        self.assertEqual(status, 1)
        self.assertIn("2 created, 1 failed", output)
        self.assertIn("[Events]", error)
        self.assertTrue((self.root / "one.highschool.subpeeko.ass").exists())
        self.assertTrue((nested / "two.highschool.subpeeko.ass").exists())
        self.assertFalse((self.root / "broken.highschool.subpeeko.ass").exists())
        self.assertEqual(first.read_bytes(), ASS.encode("utf-8"))
        self.assertEqual(len(MockHandler.calls), 2)

    def test_invalid_model_result_never_creates_output(self):
        source = self.root / "bad.ass"
        source.write_text(ASS, encoding="utf-8")
        MockHandler.invalid = True
        status, _, error = self.run_cli([str(source), "--level", "highschool"])
        self.assertEqual(status, 1)
        self.assertIn("invalid annotations", error)
        self.assertFalse((self.root / "bad.highschool.subpeeko.ass").exists())
        self.assertEqual(len(MockHandler.calls), 2)

    def test_overwrite_preserves_existing_output_if_model_fails(self):
        source = self.root / "movie.ass"
        source.write_bytes(ASS.encode("utf-8"))
        target = self.root / "movie.highschool.subpeeko.ass"
        target.write_bytes(b"existing result")
        MockHandler.invalid = True
        status, _, _ = self.run_cli([str(source), "--level", "highschool", "--overwrite"])
        self.assertEqual(status, 1)
        self.assertEqual(target.read_bytes(), b"existing result")
        MockHandler.invalid = False
        status, _, _ = self.run_cli([str(source), "--level", "highschool", "--overwrite"])
        self.assertEqual(status, 0)
        self.assertIn("malfunction: 故障", target.read_text(encoding="utf-8"))

    def test_model_redirect_is_not_followed_with_api_key(self):
        MockHandler.redirect = True
        client = ModelClient(Config(self.env["SUBPEEKO_BASE_URL"], "mock", "mock-secret"))
        with self.assertRaises(ModelError):
            client.test_connection()
        self.assertEqual(MockHandler.redirected_requests, 0)


if __name__ == "__main__":
    unittest.main()
