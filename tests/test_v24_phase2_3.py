import io
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from contextlib import redirect_stdout
from unittest.mock import patch

import llm
import providers
import quota
import server
import store


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


class TestV24Phase2And3(unittest.TestCase):
    def setUp(self):
        providers._DEEPSEEK_THINKING_UNSUPPORTED = False

    def test_schema_conversion_nested_object_array_enum(self):
        src = {
            "type": "OBJECT",
            "properties": {
                "items": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {
                            "status": {"type": "STRING", "enum": ["given", "ambiguous"]},
                            "score": {"type": "NUMBER"},
                        },
                    },
                },
            },
        }
        conv = providers.gemini_schema_to_json_schema(src)
        self.assertEqual(conv["type"], "object")
        self.assertFalse(conv["additionalProperties"])
        self.assertEqual(conv["required"], ["items"])
        self.assertEqual(conv["properties"]["items"]["type"], "array")
        item_obj = conv["properties"]["items"]["items"]
        self.assertEqual(item_obj["type"], "object")
        self.assertFalse(item_obj["additionalProperties"])
        self.assertEqual(set(item_obj["required"]), {"status", "score"})
        self.assertEqual(item_obj["properties"]["status"]["enum"], ["given", "ambiguous"])

    def test_xai_and_deepseek_request_formats(self):
        calls = []

        def fake_urlopen(req, timeout=60):
            calls.append((req.full_url, json.loads(req.data.decode("utf-8"))))
            return _FakeResp({
                "choices": [{"finish_reason": "stop", "message": {"content": '{"decision":"ok","extracted":[],"clarify":[]}'}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            })

        with patch("providers.urllib.request.urlopen", side_effect=fake_urlopen):
            out_xai = providers.call_model("xai", "xai-key", "grok-3-mini-fast", "extract", "hi")
            out_ds = providers.call_model("deepseek", "ds-key", "deepseek-v4-flash", "extract", "hi")

        self.assertEqual(out_xai["_usage"]["total_tokens"], 15)
        self.assertEqual(out_ds["_usage"]["total_tokens"], 15)

        url_xai, body_xai = calls[0]
        self.assertTrue(url_xai.startswith("https://api.x.ai/v1/"))
        self.assertEqual(body_xai["response_format"]["type"], "json_schema")
        self.assertFalse(body_xai["response_format"]["json_schema"]["schema"]["additionalProperties"])

        url_ds, body_ds = calls[1]
        self.assertTrue(url_ds.startswith("https://api.deepseek.com/"))
        self.assertEqual(body_ds["response_format"]["type"], "json_object")
        self.assertIn("json", body_ds["messages"][0]["content"].lower())
        self.assertEqual(body_ds["thinking"], {"type": "disabled"})

    def test_openai_error_mapping_and_content_edge_cases(self):
        # finish_reason == length
        with patch("providers.urllib.request.urlopen", return_value=_FakeResp({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]})):
            with self.assertRaises(llm.LLMError) as ctx:
                providers.call_openai_compat("xai", "k", "m", "extract", "hi")
            self.assertEqual(ctx.exception.category, "输出被截断")

        # empty & whitespace -> retry once -> fail
        with patch("providers.urllib.request.urlopen", side_effect=[
            _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": ""}}]}),
            _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": "   "}}]}),
        ]):
            with self.assertRaises(llm.LLMError) as ctx2:
                providers.call_openai_compat("deepseek", "k", "m", "extract", "hi")
            self.assertEqual(ctx2.exception.category, "模型输出格式异常")

        # invalid JSON -> retry once -> fail
        with patch("providers.urllib.request.urlopen", side_effect=[
            _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": "not json"}}]}),
            _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": "{bad"}}]}),
        ]):
            with self.assertRaises(llm.LLMError) as ctx3:
                providers.call_openai_compat("xai", "k", "m", "extract", "hi")
            self.assertEqual(ctx3.exception.category, "模型输出格式异常")

        # 401, 402, 404, 429, 500
        for code, expected_cat in [(401, "Key 无效或无权限"), (402, "余额不足"), (404, "模型名不存在"), (429, "限流"), (500, "服务繁忙")]:
            seq = [_http_err(code), _http_err(code)] if code in (429, 500) else [_http_err(code)]
            with patch("providers.time.sleep"), patch("providers.urllib.request.urlopen", side_effect=seq):
                with self.assertRaises(llm.LLMError) as ctx_e:
                    providers.call_openai_compat("deepseek", "k", "m", "extract", "hi")
                self.assertEqual(ctx_e.exception.category, expected_cat)

    def test_deepseek_thinking_unsupported_only_set_on_success(self):
        # [400, 400] -> raises, does NOT set _DEEPSEEK_THINKING_UNSUPPORTED
        with patch("providers.urllib.request.urlopen", side_effect=[_http_err(400), _http_err(400)]):
            with self.assertRaises(llm.LLMError):
                providers.call_openai_compat("deepseek", "k", "m", "extract", "hi")
        self.assertFalse(providers._DEEPSEEK_THINKING_UNSUPPORTED)

        # [400, 200] -> succeeds, sets _DEEPSEEK_THINKING_UNSUPPORTED = True
        with patch("providers.urllib.request.urlopen", side_effect=[
            _http_err(400),
            _FakeResp({"choices": [{"finish_reason": "stop", "message": {"content": '{"decision":"ok","extracted":[],"clarify":[]}'}}]}),
        ]):
            out = providers.call_openai_compat("deepseek", "k", "m", "extract", "hi")
        self.assertEqual(out["decision"], "ok")
        self.assertTrue(providers._DEEPSEEK_THINKING_UNSUPPORTED)

    def test_byok_no_quota_no_fallback_no_key_in_logs_and_test_connection(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "byok.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            env_patch = {
                "HOSTED": "1",
                "ALLOWED_HOSTS": "127.0.0.1,localhost",
                "QUOTA_SALT": "salt_byok",
                "FREE_DAILY_LIMIT": "1",
                "GEMINI_API_KEY": "HOSTED_SECRET_KEY",
            }
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                buf = io.StringIO()
                with patch.dict(os.environ, env_patch), redirect_stdout(buf):
                    # 1. Invalid provider -> 400
                    req_bad_p = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/evaluate",
                        data=json.dumps({"text": "测试"}).encode("utf-8"),
                        headers={"Content-Type": "application/json", "X-LLM-Key": "USER_SECRET_KEY", "X-LLM-Provider": "openai"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx_p:
                        urllib.request.urlopen(req_bad_p, timeout=5)
                    self.assertEqual(ctx_p.exception.code, 400)

                    # 2. BYOK does not consume quota, ignores base_url
                    with patch.object(llm, "call_model", return_value={"decision": "ok", "extracted": [], "clarify": []}) as m_call:
                        req_ok = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "副业", "base_url": "https://evil.com"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "X-LLM-Key": "USER_SECRET_KEY", "X-LLM-Provider": "xai"},
                        )
                        with urllib.request.urlopen(req_ok, timeout=5) as r:
                            d = json.loads(r.read().decode("utf-8"))
                            self.assertNotIn("quota", d)
                        self.assertEqual(m_call.call_args[0][0], "xai")
                        self.assertEqual(m_call.call_args[0][1], "USER_SECRET_KEY")

                    # Quota is still 0/1
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/quota", timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # 3. Invalid BYOK key errors directly, never falls back to HOSTED_SECRET_KEY
                    with patch.object(llm, "call_model", side_effect=llm.LLMError("Key 无效或无权限", "无效")):
                        req_fail = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "副业"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "X-LLM-Key": "BAD_USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_f:
                            urllib.request.urlopen(req_fail, timeout=5)
                        self.assertEqual(ctx_f.exception.code, 502)
                        err_body = ctx_f.exception.read().decode("utf-8")
                        self.assertNotIn("BAD_USER_KEY", err_body)

                    # 4. /api/test-connection: extracted_ok True and False
                    with patch.object(providers, "verify_openai_models", return_value=True), patch.object(
                        llm, "call_model", return_value={"decision": "陪跑", "extracted": [{"id": "unit_price", "value": 800}], "clarify": []}
                    ):
                        req_tc = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/test-connection",
                            data=b"{}",
                            headers={"Content-Type": "application/json", "X-LLM-Key": "USER_SECRET_KEY", "X-LLM-Provider": "deepseek"},
                        )
                        with urllib.request.urlopen(req_tc, timeout=5) as rtc:
                            dtc = json.loads(rtc.read().decode("utf-8"))
                            self.assertTrue(dtc["ok"])
                            self.assertTrue(dtc["extracted_ok"])

                    with patch.object(llm, "call_model", return_value={"decision": "陪跑", "extracted": [], "clarify": []}):
                        req_tc2 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/test-connection",
                            data=b"{}",
                            headers={"Content-Type": "application/json", "X-LLM-Key": "USER_SECRET_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with urllib.request.urlopen(req_tc2, timeout=5) as rtc2:
                            dtc2 = json.loads(rtc2.read().decode("utf-8"))
                            self.assertTrue(dtc2["ok"])
                            self.assertFalse(dtc2["extracted_ok"])

                logs = buf.getvalue()
                self.assertNotIn("USER_SECRET_KEY", logs)
                self.assertNotIn("BAD_USER_KEY", logs)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

    def test_v244_defaults_4xx_detail_and_user_agent(self):
        import io
        from unittest.mock import MagicMock
        self.assertEqual(providers.PROVIDER_PRESETS["gemini"]["default_model"], "gemini-3.5-flash-lite")
        self.assertEqual(providers.PROVIDER_PRESETS["deepseek"]["default_model"], "deepseek-flash")

        # verify_openai_models lists available models when model not found
        models_resp = json.dumps({"data": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}).encode("utf-8")
        seen_uas = []

        def fake_models_open(req, timeout=30):
            seen_uas.append(req.get_header("User-agent"))
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = models_resp
            return cm

        with patch("urllib.request.urlopen", side_effect=fake_models_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx:
                providers.verify_openai_models("deepseek", "SK_TEST", "bad-model")
        self.assertIn("m1", str(ctx.exception))
        self.assertIn("m2", str(ctx.exception))
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

        # 403 with vendor message, key masking, and 200-char truncation
        long_msg = "your team has no credits with key SK_SECRET_123 " + ("x" * 250)
        err_body = json.dumps({"error": {"message": long_msg}}).encode("utf-8")

        def fake_403_open(req, timeout=30):
            seen_uas.append(req.get_header("User-agent"))
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(err_body))

        with patch("urllib.request.urlopen", side_effect=fake_403_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx403:
                providers.call_openai_compat("xai", "SK_SECRET_123", "grok-3-mini-fast", "extract", "usr", {})
        msg403 = str(ctx403.exception)
        self.assertIn("your team has no credits", msg403)
        self.assertNotIn("SK_SECRET_123", msg403)
        self.assertIn("***", msg403)
        # Vendor detail part is truncated to <= 200 chars
        detail_part = msg403.split("厂商返回：", 1)[1].rstrip("）")
        self.assertLessEqual(len(detail_part), 200)
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

        # call_gemini also sends User-Agent: CCagent/1.0
        with patch("urllib.request.urlopen", side_effect=fake_403_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx_g:
                llm.call_gemini("SK_SECRET_123", "gemini-3.5-flash", "https://generativelanguage.googleapis.com", "sys", "usr", {})
        self.assertIn("your team has no credits", str(ctx_g.exception))
        self.assertNotIn("SK_SECRET_123", str(ctx_g.exception))
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

    def test_v241_frontend_static_and_server_fixes(self):
        import re
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        with open(os.path.join(base_dir, "app.js"), "r", encoding="utf-8") as f:
            js = f.read()
        self.assertIn("function api(", js)
        self.assertIn("function postJson(", js)
        self.assertEqual(len(re.findall(r"X-LLM-Key", js)), 1)
        # No raw fetch with method: "POST" without Content-Type (outside postJson)
        for m in re.finditer(r"fetch\([^)]*method\s*:\s*['\"]POST['\"][^)]*\)", js, re.S):
            snippet = m.group(0)
            if "fetch(path," not in snippet:
                self.assertIn("Content-Type", snippet)

        # v2.4.2 1.5: all LLM endpoints must go through postJson(..., { llm: true })
        for ep in ('"/api/evaluate"', "`/api/sessions/${currentSessionId}/append-text`", "`/api/sessions/${currentSessionId}/analysis`", '"/api/test-connection"'):
            self.assertIn(ep, js)
        # No raw fetch for evaluate, append-text, analysis, or test-connection
        self.assertIsNone(re.search(r"fetch\([^)]*(/api/evaluate|append-text|/analysis|/api/test-connection)", js))
        self.assertIn("postJson(\"/api/evaluate\"", js)
        self.assertIn("postJson(`/api/sessions/${currentSessionId}/append-text`", js)
        self.assertIn("postJson(`/api/sessions/${currentSessionId}/analysis`", js)
        self.assertIn("postJson(\"/api/test-connection\"", js)

        # v2.4.2 1.5: BYOK DOM ids exist in index.html and are referenced in app.js
        with open(os.path.join(base_dir, "index.html"), "r", encoding="utf-8") as f:
            html = f.read()
        for el_id in ("server-cfg-wrap", "byok-provider", "byok-key", "byok-model", "byok-remember", "btn-byok-test", "btn-byok-clear"):
            self.assertIn(f'id="{el_id}"', html)
            self.assertIn(el_id, js)

        # v2.4.2 1.5: localStorage cc_byok setItem & removeItem, X-LLM-Key only once
        self.assertIn('localStorage.setItem("cc_byok"', js)
        self.assertIn('localStorage.removeItem("cc_byok")', js)
        self.assertEqual(len(re.findall(r"X-LLM-Key", js)), 1)

    def test_v241_analysis_byok_415_refund_and_validation(self):
        import verify
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v241.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            env_patch = {
                "HOSTED": "1",
                "ALLOWED_HOSTS": "127.0.0.1,localhost",
                "QUOTA_SALT": "salt_241",
                "FREE_DAILY_LIMIT": "5",
                "GEMINI_API_KEY": "HOSTED_KEY",
            }
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with patch.dict(os.environ, env_patch):
                    ck = "cc_owner=v241_test_cookie"
                    # Create session via BYOK
                    with patch.object(llm, "call_model", return_value={"decision": "副业", "extracted": [], "clarify": []}):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "副业"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "K1", "X-LLM-Provider": "xai"},
                        )
                        sid = json.loads(urllib.request.urlopen(req, timeout=5).read().decode("utf-8"))["session_id"]

                    # 1.1: POST /analysis without Content-Type -> 415
                    req_415 = urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions/{sid}/analysis", data=b"", method="POST", headers={"Cookie": ck})
                    with self.assertRaises(urllib.error.HTTPError) as ctx_415:
                        urllib.request.urlopen(req_415, timeout=5)
                    self.assertEqual(ctx_415.exception.code, 415)

                    # 3.3: GET ?version=abc -> 400
                    with self.assertRaises(urllib.error.HTTPError) as ctx_ver:
                        urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions/{sid}?version=abc", headers={"Cookie": ck}), timeout=5)
                    self.assertEqual(ctx_ver.exception.code, 400)

                    # 1.2: BYOK analysis for xai, deepseek, gemini
                    ana_payload = {"advisors": [], "critique": [], "two_week_checks": [], "validation_design": {}}
                    for prov in ("xai", "deepseek", "gemini"):
                        with patch.object(llm, "call_model", return_value=dict(ana_payload)) as m_ana:
                            req_a = urllib.request.Request(
                                f"http://127.0.0.1:{port}/api/sessions/{sid}/analysis",
                                data=b"{}",
                                headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "K1", "X-LLM-Provider": prov},
                            )
                            d_a = json.loads(urllib.request.urlopen(req_a, timeout=5).read().decode("utf-8"))
                            self.assertTrue(d_a["analysis"]["model"].startswith(f"{prov} / "))
                            self.assertEqual(m_ana.call_args[0][0], prov)

                    # 4: BYOK append-text succeeds and does not consume quota
                    with patch.object(llm, "call_model", return_value={"decision": "副业", "extracted": [], "clarify": []}):
                        req_ap = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/sessions/{sid}/append-text",
                            data=json.dumps({"text": "补充"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "K1", "X-LLM-Provider": "deepseek"},
                        )
                        self.assertEqual(urllib.request.urlopen(req_ap, timeout=5).status, 200)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # v2.4.2 Section 2: hosted unhandled exception must not leak path/exception text
                    with patch.object(server.AppHandler, "_handle_evaluate", side_effect=RuntimeError("C:\\secret\\path\\boom.py")):
                        req_500 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_500:
                            urllib.request.urlopen(req_500, timeout=5)
                        self.assertEqual(ctx_500.exception.code, 500)
                        body_500 = ctx_500.exception.read().decode("utf-8")
                        self.assertNotIn("secret", body_500)
                        self.assertNotIn("boom.py", body_500)
                        self.assertIn("服务器内部错误", body_500)

                    # 1.3: Quota refund on /analysis LLM error
                    with patch.object(llm, "call_model", side_effect=llm.LLMError("err", "err")):
                        req_af = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/sessions/{sid}/analysis",
                            data=b"{}",
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError):
                            urllib.request.urlopen(req_af, timeout=5)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # v2.4.2 Section 2: hosted unhandled exception must not leak path/exception text
                    with patch.object(server.AppHandler, "_handle_evaluate", side_effect=RuntimeError("C:\\secret\\path\\boom.py")):
                        req_500 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_500:
                            urllib.request.urlopen(req_500, timeout=5)
                        self.assertEqual(ctx_500.exception.code, 500)
                        body_500 = ctx_500.exception.read().decode("utf-8")
                        self.assertNotIn("secret", body_500)
                        self.assertNotIn("boom.py", body_500)
                        self.assertIn("服务器内部错误", body_500)

                    # 1.3: Quota refund on /evaluate verify_extracted exception
                    with patch.object(llm, "call_model", return_value={"decision": "x", "extracted": [], "clarify": []}), patch.object(
                        verify, "verify_extracted", side_effect=RuntimeError("boom")
                    ):
                        req_ef = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError):
                            urllib.request.urlopen(req_ef, timeout=5)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # v2.4.2 Section 2: hosted unhandled exception must not leak path/exception text
                    with patch.object(server.AppHandler, "_handle_evaluate", side_effect=RuntimeError("C:\\secret\\path\\boom.py")):
                        req_500 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_500:
                            urllib.request.urlopen(req_500, timeout=5)
                        self.assertEqual(ctx_500.exception.code, 500)
                        body_500 = ctx_500.exception.read().decode("utf-8")
                        self.assertNotIn("secret", body_500)
                        self.assertNotIn("boom.py", body_500)
                        self.assertIn("服务器内部错误", body_500)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

    def test_v244_defaults_4xx_detail_and_user_agent(self):
        import io
        from unittest.mock import MagicMock
        self.assertEqual(providers.PROVIDER_PRESETS["gemini"]["default_model"], "gemini-3.5-flash-lite")
        self.assertEqual(providers.PROVIDER_PRESETS["deepseek"]["default_model"], "deepseek-flash")

        # verify_openai_models lists available models when model not found
        models_resp = json.dumps({"data": [{"id": "m1"}, {"id": "m2"}, {"id": "m3"}]}).encode("utf-8")
        seen_uas = []

        def fake_models_open(req, timeout=30):
            seen_uas.append(req.get_header("User-agent"))
            cm = MagicMock()
            cm.__enter__.return_value.read.return_value = models_resp
            return cm

        with patch("urllib.request.urlopen", side_effect=fake_models_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx:
                providers.verify_openai_models("deepseek", "SK_TEST", "bad-model")
        self.assertIn("m1", str(ctx.exception))
        self.assertIn("m2", str(ctx.exception))
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

        # 403 with vendor message, key masking, and 200-char truncation
        long_msg = "your team has no credits with key SK_SECRET_123 " + ("x" * 250)
        err_body = json.dumps({"error": {"message": long_msg}}).encode("utf-8")

        def fake_403_open(req, timeout=30):
            seen_uas.append(req.get_header("User-agent"))
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(err_body))

        with patch("urllib.request.urlopen", side_effect=fake_403_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx403:
                providers.call_openai_compat("xai", "SK_SECRET_123", "grok-3-mini-fast", "extract", "usr", {})
        msg403 = str(ctx403.exception)
        self.assertIn("your team has no credits", msg403)
        self.assertNotIn("SK_SECRET_123", msg403)
        self.assertIn("***", msg403)
        # Vendor detail part is truncated to <= 200 chars
        detail_part = msg403.split("厂商返回：", 1)[1].rstrip("）")
        self.assertLessEqual(len(detail_part), 200)
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

        # call_gemini also sends User-Agent: CCagent/1.0
        with patch("urllib.request.urlopen", side_effect=fake_403_open):
            with self.assertRaises(llm.GeminiAPIError) as ctx_g:
                llm.call_gemini("SK_SECRET_123", "gemini-3.5-flash", "https://generativelanguage.googleapis.com", "sys", "usr", {})
        self.assertIn("your team has no credits", str(ctx_g.exception))
        self.assertNotIn("SK_SECRET_123", str(ctx_g.exception))
        self.assertEqual(seen_uas[-1], "CCagent/1.0")

    def test_v245_hosted_key_error_masked_503_and_refund(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "v245.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                ck = "cc_owner=v245_cookie"
                err = llm.LLMError("Key 无效或无权限", "API Key 无效或无权限（厂商返回：secret detail）", 403)
                env_hosted = {
                    "HOSTED": "1",
                    "ALLOWED_HOSTS": "127.0.0.1,localhost",
                    "QUOTA_SALT": "salt_245",
                    "FREE_DAILY_LIMIT": "5",
                    "GEMINI_API_KEY": "HOSTED_KEY",
                }
                with patch.dict(os.environ, env_hosted):
                    # Hosted without BYOK -> 503, fixed message, no secret detail, quota refunded
                    with patch.object(llm, "call_model", side_effect=err):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 503)
                        body = json.loads(ctx.exception.read().decode("utf-8"))
                        self.assertEqual(body["category"], "服务暂不可用")
                        self.assertNotIn("secret detail", body["error"])
                    import time
                    time.sleep(0.05)
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/quota", headers={"Cookie": ck}), timeout=5) as rq:
                        self.assertEqual(json.loads(rq.read().decode("utf-8"))["used"], 0)

                    # Hosted WITH BYOK -> preserves secret detail
                    with patch.object(llm, "call_model", side_effect=err):
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": ck, "X-LLM-Key": "USER_KEY", "X-LLM-Provider": "gemini"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertIn("secret detail", ctx_b.exception.read().decode("utf-8"))

                # Non-hosted -> preserves secret detail
                with patch.dict(os.environ, {"HOSTED": "0", "GEMINI_API_KEY": "LOCAL_KEY"}):
                    with patch.object(llm, "call_model", side_effect=err):
                        req_l = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "测试"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_l:
                            urllib.request.urlopen(req_l, timeout=5)
                        self.assertIn("secret detail", ctx_l.exception.read().decode("utf-8"))
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()

