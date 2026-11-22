import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import llm


class _FakeResp:
    def __init__(self, body_dict):
        self._raw = json.dumps(body_dict).encode("utf-8")

    def read(self):
        return self._raw

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_err(code):
    return urllib.error.HTTPError("https://example.com", code, f"HTTP {code}", {}, io.BytesIO(b"{}"))


class TestLLM(unittest.TestCase):
    def setUp(self):
        if hasattr(llm, "_THINKING_UNSUPPORTED"):
            llm._THINKING_UNSUPPORTED = False

    def test_429_then_400_thinking_then_200(self):
        calls = []
        seq = [
            _http_err(429),
            _http_err(400),
            _FakeResp({"candidates": [{"content": {"parts": [{"text": '{"decision":"ok","extracted":[],"clarify":[]}'}]}}]}),
        ]

        def fake_urlopen(req, timeout=60):
            calls.append(json.loads(req.data.decode("utf-8")))
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("llm.time.sleep"), patch("llm.urllib.request.urlopen", side_effect=fake_urlopen):
            out = llm.call_gemini("k", "gemini-2.5-flash", "https://generativelanguage.googleapis.com", "hi")
        self.assertEqual(out["decision"], "ok")
        self.assertEqual(len(calls), 3)
        self.assertIn("thinkingConfig", calls[0]["generationConfig"])
        self.assertIn("thinkingConfig", calls[1]["generationConfig"])
        self.assertNotIn("thinkingConfig", calls[2]["generationConfig"])

    def test_500_twice_raises(self):
        seq = [_http_err(500), _http_err(500)]

        def fake_urlopen(req, timeout=60):
            raise seq.pop(0)

        with patch("llm.time.sleep"), patch("llm.urllib.request.urlopen", side_effect=fake_urlopen):
            with self.assertRaises(llm.GeminiAPIError):
                llm.call_gemini("k", "gemini-2.5-flash", "https://generativelanguage.googleapis.com", "hi")

    def test_400_thinking_remembered_across_calls(self):
        calls = []
        seq = [
            _http_err(400),
            _FakeResp({"candidates": [{"content": {"parts": [{"text": '{"decision":"a","extracted":[],"clarify":[]}'}]}}]}),
            _FakeResp({"candidates": [{"content": {"parts": [{"text": '{"decision":"b","extracted":[],"clarify":[]}'}]}}]}),
        ]

        def fake_urlopen(req, timeout=60):
            calls.append(json.loads(req.data.decode("utf-8")))
            item = seq.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        with patch("llm.time.sleep"), patch("llm.urllib.request.urlopen", side_effect=fake_urlopen):
            out1 = llm.call_gemini("k", "gemini-2.5-flash", "https://generativelanguage.googleapis.com", "hi1")
            out2 = llm.call_gemini("k", "gemini-2.5-flash", "https://generativelanguage.googleapis.com", "hi2")
        self.assertEqual(out1["decision"], "a")
        self.assertEqual(out2["decision"], "b")
        self.assertIn("thinkingConfig", calls[0]["generationConfig"])
        self.assertNotIn("thinkingConfig", calls[1]["generationConfig"])
        self.assertNotIn("thinkingConfig", calls[2]["generationConfig"])


if __name__ == "__main__":
    unittest.main()
