import contextlib
import io
import json
import os
import subprocess
import sys
import sysconfig
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from subpeeko import cli, config
from subpeeko.checkpoint import checkpoint_key
from subpeeko.config import Config
from subpeeko.model import ModelClient, ModelError
from subpeeko.rate_limit import RateLimiter
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
        expected = ASS.replace(
            r"{\an2}装置似乎发生故障\N{\rEng}The device had a malfunction.",
            r"{\rEng}The device had a malfunction (故障).\N{\rDefault}{\an2}malfunction: 故障",
        ).replace(r"Yes.\N是的", r"Yes.")
        self.assertEqual(result, b"\xef\xbb\xbf" + expected.encode("utf-8"))

    def test_empty_annotation_keeps_source_english_style(self):
        source = r"""[Script Info]
[V4+ Styles]
Format: Name, Fontname, Fontsize, MarginV
Style: Default,Chinese,180,-300
Style: Eng,English,100,0
[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
Dialogue: 0,0:00:01.00,0:00:03.00,Default,,0,0,0,,中文翻译\N{\rEng}The original English line.
""".replace("\n", "\r\n")
        output = AssFile(source.encode()).render({1: ""}).decode()
        self.assertIn(r"{\rEng}The original English line.", output)
        self.assertNotIn(r"{\rDefault\fnEnglish}", output)

    def test_inlines_short_meaning_and_keeps_full_annotation(self):
        output = AssFile(ASS.encode()).render({1: "malfunction: 故障（设备故障）", 2: ""}).decode()
        self.assertIn(r"{\rEng}The device had a malfunction (故障).", output)
        self.assertIn(r"\N{\rDefault}{\an2}malfunction: 故障（设备故障）", output)

    def test_swaps_font_sizes_only_when_chinese_is_larger(self):
        source = ASS.replace(
            "Format: Name, Fontname\r\nStyle: Default,Arial",
            "Format: Name, Fontname, Fontsize\r\nStyle: Default,Arial,130",
        ).replace(
            "[Events]",
            "Style: Eng,Arial,70\r\n[Events]",
        )
        subtitles = AssFile(source.encode("utf-8"))
        output = subtitles.render({1: "malfunction: 故障", 2: ""}).decode("utf-8")
        self.assertIn(
            r"{\rDefault\fnArial}{\fs130}The device had a malfunction (故障).\N{\rEng\fnArial}{\an2}{\fs70}malfunction: 故障",
            output,
        )

        larger_english = source.replace("Style: Default,Arial,130", "Style: Default,Arial,70")
        larger_english = larger_english.replace("Style: Eng,Arial,70", "Style: Eng,Arial,130")
        output = AssFile(larger_english.encode("utf-8")).render({1: "malfunction: 故障", 2: ""}).decode("utf-8")
        self.assertIn(r"{\rDefault\fnArial}{\fs130}The device had a malfunction (故障).\N{\rEng\fnArial}{\an2}{\fs70}malfunction: 故障", output)

    def test_swaps_style_attributes_but_keeps_each_language_font(self):
        source = ASS.replace(
            "Format: Name, Fontname\r\nStyle: Default,Arial",
            "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\r\n"
            "Style: Default,Chinese Font,130,&H00BFD1D5,&HF0000000,&H00000000,&H32000000,0,0,0,0,100,100,0,0,1,2,1,2,5,5,-300,134",
        ).replace(
            "[Events]",
            "Style: Eng,English Font,70,&H008CA3AA,&HF0000000,&H00000000,&H32000000,0,-1,0,0,100,100,0,0,1,0,0,2,5,5,0,134\r\n[Events]",
        )
        output = AssFile(source.encode("utf-8")).render({1: "malfunction: 故障", 2: ""}).decode("utf-8")
        self.assertIn(
            r"{\rDefault\fnEnglish Font}{\fs130}The device had a malfunction ({\fnChinese Font}故障{\fnEnglish Font}).\N{\rEng\fnChinese Font}{\an2}{\fs70}malfunction: 故障",
            output,
        )
        self.assertIn(r"malfunction ({\fnChinese Font}故障{\fnEnglish Font})", output)
        with_font = source.replace(
            r"{\rEng}The device had a malfunction.",
            r"{\rEng}The device {\fnInline Font}had a malfunction.",
        )
        output = AssFile(with_font.encode("utf-8")).render({1: "malfunction: 故障", 2: ""}).decode("utf-8")
        self.assertIn(r"malfunction ({\fnChinese Font}故障{\fnInline Font})", output)

    def test_english_first_input_stays_english_first(self):
        source = ASS.replace(
            r"{\an2}装置似乎发生故障\N{\rEng}The device had a malfunction.",
            r"{\rEng}The device had a malfunction.\N{\an2}装置似乎发生故障",
        )
        output = AssFile(source.encode()).render({1: "malfunction: 故障", 2: ""}).decode()
        self.assertIn(r"{\rEng}The device had a malfunction (故障).\N{\rDefault}{\an2}malfunction: 故障", output)

    def test_inline_font_sizes_are_used_when_style_sizes_are_missing(self):
        source = ASS.replace(
            r"{\an2}装置似乎发生故障\N{\rEng}The device had a malfunction.",
            r"{\fs130}装置似乎发生故障\N{\fs70}The device had a malfunction.",
        )
        output = AssFile(source.encode()).render({1: "malfunction: 故障", 2: ""}).decode()
        self.assertIn(r"{\fs70}{\fs130}The device had a malfunction (故障).\N{\rDefault}{\fs130}{\fs70}malfunction: 故障", output)

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
        self.assertIn(r"{\rEng}The device\Nhad a malfunction (故障).\N{\rDefault}{\an2}{\b1}malfunction: 故障", output)

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
    def test_simple_and_duplicate_dialogues_are_all_reviewed(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20, workers=1)
        records = [dialogue(i, "Yes!", "是的") for i in range(1, 8)]

        def respond(messages):
            payload = json.loads(messages[-1]["content"])
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(client, "_request", side_effect=respond) as request:
            result = client.analyze(records, "highschool")
        self.assertEqual(set(result), set(range(1, 8)))
        self.assertEqual(json.loads(request.call_args.args[0][-1]["content"])["target_ids"], list(range(1, 8)))

    def test_filters_levels_validates_spans_and_escapes_tags(self):
        expected = {1: dialogue(1, "The device had a malfunction.", "装置似乎发生故障")}
        body = json.dumps({"items": [{"id": 1, "notes": [
            {"span": "malfunction", "zh": r"{\pos(1,2)}故障", "level": "cet4", "kind": "word"}
        ]}]})
        note = ModelClient._parse(body, expected, "highschool")[1]
        self.assertEqual(note, "malfunction: 故障")
        self.assertIn("故障", note)
        self.assertNotIn("{", note)
        self.assertNotIn("\\", note)
        self.assertEqual(ModelClient._parse(body, expected, "cet4")[1], "")
        body = json.dumps({"items": [{"id": 1, "notes": [
            {"span": "malfunction", "zh": "故障（仅指设备故障）", "level": "cet4", "kind": "word"}
        ]}]})
        self.assertEqual(ModelClient._parse(body, expected, "highschool")[1], "malfunction: 故障（仅指设备故障）")
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
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20, workers=1)
        records = [dialogue(i, f"Unfamiliarword{i}", f"中文{i}") for i in range(1, 46)]
        payloads = []
        progress = []

        def respond(messages):
            payload = json.loads(messages[-1]["content"])
            payloads.append(payload)
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(client, "_request", side_effect=respond):
            result = client.analyze(records, "cet4", progress=lambda done, total: progress.append((done, total)))
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
            result = client.analyze(records, "cet4")
        self.assertEqual(set(result), {1, 2})
        self.assertEqual(len(json.loads(request.call_args.args[0][-1]["content"])["target_ids"]), 2)

    def test_large_failed_batch_is_split_and_recovered(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=20, workers=1)
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
            result = client.analyze(records, "cet4", on_retry=retries.append)
        self.assertEqual(set(result), set(range(1, 7)))
        self.assertEqual(sizes, [6, 3, 1, 2, 3, 1, 2])
        self.assertEqual(len(retries), 3)

    def test_failed_batch_does_not_shrink_later_batches(self):
        client = ModelClient(Config("https://example.test/v1", "model", "secret"), batch_size=5, workers=1)
        records = [dialogue(i, f"Sentence {i}", f"中文{i}") for i in range(1, 12)]
        sizes = []

        def respond(messages):
            ids = json.loads(messages[-1]["content"])["target_ids"]
            sizes.append(len(ids))
            if len(sizes) == 1:
                raise ModelError("timeout", split_batch=True)
            return json.dumps({"items": [{"id": i, "notes": []} for i in ids]})

        with patch.object(client, "_request", side_effect=respond):
            result = client.analyze(records, "cet4")
        self.assertEqual(set(result), set(range(1, 12)))
        self.assertEqual(sizes, [5, 2, 3, 5, 1])

    def test_request_disables_thinking_and_reserves_combined_tokens(self):
        requests, events = [], []

        class Response:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def read(self, limit):
                return json.dumps({"choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
                                   "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130,
                                             "completion_tokens_details": {"reasoning_tokens": 20}}}).encode()

        class Opener:
            def open(self, request, timeout):
                requests.append(json.loads(request.data))
                return Response()

        configs = [Config("https://example.test/v1", "generic", "secret"),
                   Config("https://example.cn-beijing.maas.aliyuncs.com/v1", "qwen3.8-flash", "secret")]
        with patch("subpeeko.model.build_opener", return_value=Opener()):
            for config_item in configs:
                client = ModelClient(config_item, on_request=events.append)
                self.assertEqual(client._request([{"role": "user", "content": "synthetic"}]), "OK")
        self.assertFalse(requests[0]["enable_thinking"])
        self.assertFalse(requests[1]["enable_thinking"])
        self.assertEqual(requests[0]["max_tokens"], 2048)
        self.assertEqual(requests[1]["max_completion_tokens"], 2048)
        self.assertEqual(events[1]["usage"]["reasoning_tokens"], 20)
        self.assertNotIn("secret", repr(events))

    def test_thinking_can_be_enabled_or_left_to_provider(self):
        bodies = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return b'{"choices":[{"message":{"content":"OK"}}]}'

        class Opener:
            def open(self, request, timeout):
                bodies.append(json.loads(request.data))
                return Response()

        with patch("subpeeko.model.build_opener", return_value=Opener()):
            for thinking in ("on", "auto"):
                client = ModelClient(Config("https://example.test/v1", "generic", "secret"), thinking=thinking)
                client._request([{"role": "user", "content": "synthetic"}])
        self.assertTrue(bodies[0]["enable_thinking"])
        self.assertNotIn("enable_thinking", bodies[1])

    def test_tpm_reservation_accounts_for_reasoning(self):
        requests = []

        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return b'{"choices":[{"message":{"content":"OK"}}]}'

        class Opener:
            def open(self, request, timeout):
                requests.append(request.data)
                return Response()

        configs = [Config("https://example.test/v1", "generic", "secret"),
                   Config("https://example.cn-beijing.maas.aliyuncs.com/v1", "qwen3.8-flash", "secret")]
        with patch("subpeeko.model.build_opener", return_value=Opener()):
            for config_item in configs:
                client = ModelClient(config_item, thinking="on")
                with patch.object(client.limiter, "acquire", return_value=[0, 0]) as reserve:
                    client._request([{"role": "user", "content": "synthetic"}])
                    extra = 8192 if config_item.model_name == "generic" else 0
                    self.assertEqual(reserve.call_args.args[0], len(requests[-1]) + 2048 + extra + 528)

    def test_truncated_response_is_not_accepted(self):
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, limit):
                return b'{"choices":[{"message":{"content":"{}"},"finish_reason":"length"}]}'

        class Opener:
            def open(self, request, timeout): return Response()

        client = ModelClient(Config("https://example.test/v1", "generic", "secret"))
        with patch("subpeeko.model.build_opener", return_value=Opener()):
            with self.assertRaises(ModelError) as error:
                client._request([{"role": "user", "content": "synthetic"}])
        self.assertTrue(error.exception.split_batch)

    def test_concurrent_batches_preserve_all_targets(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"), batch_size=1, workers=3)
        records = [dialogue(i, f"Sentence {i}", f"中文{i}") for i in range(1, 7)]
        lock = threading.Lock()
        active = maximum = 0

        def respond(messages):
            nonlocal active, maximum
            payload = json.loads(messages[-1]["content"])
            with lock:
                active += 1
                maximum = max(maximum, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(client, "_request", side_effect=respond):
            result = client.analyze(records, "cet4")
        self.assertEqual(set(result), set(range(1, 7)))
        self.assertGreaterEqual(maximum, 2)
        self.assertLessEqual(maximum, 3)

    def test_rate_limit_response_defers_all_workers_before_retry(self):
        client = ModelClient(Config("http://127.0.0.1/v1", "test", "secret"))
        client.limiter = unittest.mock.Mock()
        response = json.dumps({"items": [{"id": 1, "notes": []}]})
        error = ModelError("rate limited", retryable=True, rate_limited=True, retry_delay=4)
        with patch.object(client, "_request", side_effect=[error, response]) as request:
            self.assertEqual(client.analyze([dialogue(1, "Hi", "你好")], "cet4"), {1: ""})
        self.assertEqual(request.call_count, 2)
        client.limiter.defer.assert_called_once_with(4)


class RateLimitTests(unittest.TestCase):
    def test_cancelled_wait_does_not_start_another_request(self):
        limiter = RateLimiter(rpm=1, tpm=10000)
        limiter.acquire(100)
        waiting = threading.Event()

        class ObservableEvent(threading.Event):
            def wait(self, timeout=None):
                waiting.set()
                return super().wait(timeout)

        stopped = ObservableEvent()
        finished = threading.Event()
        errors = []

        def wait_for_permit():
            try:
                limiter.acquire(100, stopped)
            except InterruptedError as exc:
                errors.append(exc)
            finally:
                finished.set()

        thread = threading.Thread(target=wait_for_permit)
        thread.start()
        try:
            self.assertTrue(waiting.wait(1))
        finally:
            stopped.set()
        self.assertTrue(finished.wait(1))
        thread.join()
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(limiter.events), 1)

    def test_smooths_requests_and_respects_rolling_token_reservations(self):
        clock = [0.0]

        def advance(seconds):
            clock[0] += seconds

        with patch("subpeeko.rate_limit.monotonic", side_effect=lambda: clock[0]), patch("subpeeko.rate_limit.sleep", side_effect=advance):
            limiter = RateLimiter(rpm=120, tpm=1000, qps=2)
            limiter.acquire(300)
            limiter.acquire(300)
            self.assertEqual(clock[0], 22.5)
            limiter.acquire(300)
            self.assertEqual(clock[0], 60)
            limiter.defer(5)
            limiter.acquire(100)
            self.assertGreaterEqual(clock[0], 65)
            with self.assertRaises(ValueError):
                limiter.acquire(801)


class CheckpointTests(unittest.TestCase):
    def test_key_changes_when_input_or_model_settings_change(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "movie.ass"
            path.write_bytes(ASS.encode("utf-8"))
            source_hash = AssFile.read(path).source_hash
            base = Config("https://example.test/v1", "model", "secret")

            def key(config_item=base, level="cet4", thinking="off", digest=source_hash):
                return checkpoint_key(path, digest, config_item, level, batch_size=5,
                                      thinking=thinking, max_output_tokens=2048)

            self.assertNotEqual(key(), key(level="cet6"))
            self.assertNotEqual(key(), key(thinking="on"))
            self.assertNotEqual(key(), key(config_item=Config(base.base_url, "another", "secret")))
            self.assertNotEqual(key(), key(config_item=Config(base.base_url, "model", "another-key")))
            self.assertNotEqual(key(), key(digest=b"different content"))


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
    max_tokens = []
    invalid = False
    redirect = False
    redirected_requests = 0
    pause_target = None
    pause_started = None
    pause_release = None

    def do_POST(self):
        if type(self).redirect:
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/other")
            self.end_headers()
            return
        request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        type(self).max_tokens.append(request.get("max_tokens"))
        payload = json.loads(request["messages"][-1]["content"])
        type(self).calls.append((self.path, payload))
        if type(self).pause_target in payload["target_ids"]:
            type(self).pause_started.set()
            type(self).pause_release.wait(timeout=15)
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
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

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
        MockHandler.max_tokens = []
        MockHandler.invalid = False
        MockHandler.redirect = False
        MockHandler.redirected_requests = 0
        MockHandler.pause_target = None
        MockHandler.pause_started = None
        MockHandler.pause_release = None
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        cache = patch("subpeeko.checkpoint.cache_dir", return_value=self.root / ".checkpoints")
        cache.start()
        self.addCleanup(cache.stop)
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
        self.assertEqual(len(MockHandler.calls[0][1]["target_ids"]), 2)
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

    def test_installed_console_command_accepts_unicode_paths(self):
        source = self.root / "字幕 with spaces.ass"
        source.write_bytes(ASS.encode("utf-8"))
        executable = Path(sysconfig.get_path("scripts")) / ("subpeeko.exe" if os.name == "nt" else "subpeeko")
        self.assertTrue(executable.exists(), f"Missing installed command: {executable}")
        result = subprocess.run(
            [str(executable), str(source), "--level", "cet4", "--dry-run"],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30,
            env={**os.environ, "PYTHONIOENCODING": "ascii:strict"},
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(r"\u5b57\u5e55", result.stdout)
        self.assertIn("1 file(s)", result.stdout)
        self.assertFalse((self.root / "字幕 with spaces.cet4.subpeeko.ass").exists())

    def test_concurrent_cli_uses_shared_limits_and_output_reservation(self):
        source = self.root / "movie.ass"
        source.write_bytes(ASS.encode("utf-8"))
        status, output, error = self.run_cli([
            str(source), "--level", "highschool", "--batch-size", "1", "--concurrency", "2",
            "--rpm", "6000", "--tpm", "600000", "--qps", "100", "--max-output-tokens", "256",
        ])
        self.assertEqual(status, 0, error)
        self.assertIn("2 model request", output)
        self.assertEqual(MockHandler.max_tokens, [256, 256])
        self.assertEqual({item for _, payload in MockHandler.calls for item in payload["target_ids"]}, {1, 2})

    def test_default_cli_runs_concurrently_with_configured_budget(self):
        source = self.root / "movie.ass"
        source.write_bytes(ASS.encode("utf-8"))
        barrier = threading.Barrier(2)
        clients = []

        def respond(client, messages):
            clients.append(client)
            barrier.wait(timeout=3)
            payload = json.loads(messages[-1]["content"])
            return json.dumps({"items": [{"id": i, "notes": []} for i in payload["target_ids"]]})

        with patch.object(ModelClient, "_request", autospec=True, side_effect=respond):
            status, _, error = self.run_cli([str(source), "--level", "cet4", "--batch-size", "1"])
        self.assertEqual(status, 0, error)
        self.assertEqual(len(clients), 2)
        self.assertEqual(clients[0].workers, 4)
        self.assertEqual(clients[0].limiter.rpm, 48)
        self.assertEqual(clients[0].limiter.tpm, 4_000_000)
        self.assertEqual(clients[0].limiter.qps, 0.8)
        self.assertTrue((self.root / "movie.cet4.subpeeko.ass").exists())

    def test_individual_concurrency_and_quota_options_can_be_overridden(self):
        args = cli.parser().parse_args(["movie.ass", "--level", "cet4", "--concurrency", "1", "--tpm", "100000"])
        self.assertEqual((args.concurrency, args.rpm, args.tpm), (1, 60, 100_000))

    def test_interrupted_run_resumes_only_completed_dialogues(self):
        source = self.root / "movie.ass"
        source.write_bytes(ASS.encode("utf-8"))
        arguments = [str(source), "--level", "highschool", "--batch-size", "1", "--concurrency", "1"]
        sent = []

        def interrupted(client, messages):
            identifier = json.loads(messages[-1]["content"])["target_ids"][0]
            sent.append(identifier)
            if identifier == 2:
                raise KeyboardInterrupt()
            return json.dumps({"items": [{"id": identifier, "notes": []}]})

        with patch.object(ModelClient, "_request", autospec=True, side_effect=interrupted):
            status, _, _ = self.run_cli(arguments)
        self.assertEqual(status, 130)
        self.assertEqual(sent, [1, 2])
        self.assertFalse((self.root / "movie.highschool.subpeeko.ass").exists())

        sent.clear()
        def resume(client, messages):
            identifier = json.loads(messages[-1]["content"])["target_ids"][0]
            sent.append(identifier)
            return json.dumps({"items": [{"id": identifier, "notes": []}]})

        changed_concurrency = arguments[:-1] + ["2"]
        with patch.object(ModelClient, "_request", autospec=True, side_effect=resume):
            status, output, error = self.run_cli(changed_concurrency)
        self.assertEqual(status, 0, error)
        self.assertEqual(sent, [2])
        self.assertIn("Resuming: 1/2", output)
        self.assertTrue((self.root / "movie.highschool.subpeeko.ass").exists())
        self.assertEqual(source.read_bytes(), ASS.encode("utf-8"))
        for database in (self.root / ".checkpoints").glob("*.sqlite3"):
            self.assertNotIn(b"mock-secret", database.read_bytes())

        sent.clear()
        with patch.object(ModelClient, "_request", autospec=True, side_effect=resume):
            status, _, error = self.run_cli(arguments + ["--overwrite", "--no-resume"])
        self.assertEqual(status, 0, error)
        self.assertEqual(sent, [1, 2])

    def test_resume_survives_process_termination(self):
        source = self.root / "movie.ass"
        source.write_bytes(ASS.encode("utf-8"))
        env = {**os.environ, **self.env, "LOCALAPPDATA": str(self.root), "XDG_CACHE_HOME": str(self.root)}
        command = [sys.executable, "-m", "subpeeko", str(source), "--level", "highschool", "--batch-size", "1",
                   "--concurrency", "1", "--rpm", "6000", "--tpm", "600000", "--qps", "100"]
        MockHandler.pause_target = 2
        MockHandler.pause_started = threading.Event()
        MockHandler.pause_release = threading.Event()
        process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        try:
            self.assertTrue(MockHandler.pause_started.wait(timeout=15), "Second request did not start")
        finally:
            process.kill()
            process.communicate(timeout=10)
            MockHandler.pause_release.set()
            MockHandler.pause_target = None
        self.assertFalse((self.root / "movie.highschool.subpeeko.ass").exists())
        resumed = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env, timeout=20)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertIn("Resuming: 1/2", resumed.stdout)
        targets = [item for _, payload in MockHandler.calls for item in payload["target_ids"]]
        self.assertEqual(targets.count(1), 1)
        self.assertGreaterEqual(targets.count(2), 2)
        self.assertEqual(source.read_bytes(), ASS.encode("utf-8"))

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
        self.assertEqual(len(MockHandler.calls), 3)

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
