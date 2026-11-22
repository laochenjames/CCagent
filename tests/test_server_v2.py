"""Server & store v2 tests: no-LLM fields update, analysis_stale, DB migration."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm
import server
import store


class TestServerV2(unittest.TestCase):
    def test_db_migration_from_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "old.db")
            conn = sqlite3.connect(db_path)
            conn.executescript(
                """
                CREATE TABLE sessions (id TEXT PRIMARY KEY, title TEXT, raw_text TEXT, created_at TEXT, updated_at TEXT, status TEXT);
                CREATE TABLE evaluations (id TEXT PRIMARY KEY, session_id TEXT, version INTEGER, fields_json TEXT, result_json TEXT, created_at TEXT);
                INSERT INTO sessions VALUES ('s_1', 'old', 'hello', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'active');
                INSERT INTO evaluations VALUES ('e_1', 's_1', 1, '{}', '{"score":{"label":"偏高","confidence_pct":80}}', '2026-01-01T00:00:00Z');
                """
            )
            conn.commit()
            conn.close()

            store.init_db(db_path)
            sess = store.get_session("s_1", db_path=db_path)
            self.assertIsNotNone(sess)
            self.assertIsNone(sess["analysis"])
            self.assertFalse(sess["analysis_stale"])

    def test_fields_update_no_llm_and_sets_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            sid = store.create_session("想做副业", "副业", {}, {"decision": "做副业"}, db_path=db_path)
            store.save_analysis(sid, {"advisors": []}, db_path=db_path)

            with patch.object(llm, "call_gemini", side_effect=AssertionError("LLM must not be called")):
                stale = store.update_latest_evaluation(sid, {"paid_evidence": {"id": "paid_evidence", "value": "paid", "status": "given", "category": "自报"}}, {"score": {"label": "偏高"}}, db_path=db_path)
                self.assertTrue(stale)

    def test_v231_endpoints_validation_clear_and_logging(self):
        import io
        import threading
        import urllib.error
        import urllib.request
        from contextlib import redirect_stdout
        import server

        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            sid = store.create_session("秘密测试原文_不应进日志", "测试标题", {}, {"decision": "测试", "score": {"label": "还看不出来", "confidence_pct": 0, "low": 15, "high": 95}, "factors": [], "groups": [], "flags": []}, db_path=db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                # 1.2 enum validation: invalid -> 400, valid -> 200
                req_bad = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/sessions/{sid}/fields",
                    data=json.dumps({"fields": [{"id": "paid_evidence", "value": "xxx"}]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with self.assertRaises(urllib.error.HTTPError) as ctx:
                    urllib.request.urlopen(req_bad, timeout=5)
                self.assertEqual(ctx.exception.code, 400)

                req_ok = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/sessions/{sid}/fields",
                    data=json.dumps({"fields": [{"id": "paid_evidence", "value": "paid_stranger"}, {"id": "unit_price", "value": ""}]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req_ok, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                sess = store.get_session(sid, db_path=db_path)
                self.assertEqual(sess["fields"]["paid_evidence"]["status"], "given")
                self.assertNotIn("unit_price", sess["fields"])

                # 1.3 clear: true -> missing
                req_clr = urllib.request.Request(
                    f"http://127.0.0.1:{port}/api/sessions/{sid}/fields",
                    data=json.dumps({"fields": [{"id": "paid_evidence", "clear": True}]}).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req_clr, timeout=5) as resp:
                    self.assertEqual(resp.status, 200)
                sess2 = store.get_session(sid, db_path=db_path)
                self.assertEqual(sess2["fields"]["paid_evidence"]["status"], "missing")

                # 1.7 DELETE /report -> 404
                req_del = urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions/{sid}/report", method="DELETE")
                with self.assertRaises(urllib.error.HTTPError) as ctx_del:
                    urllib.request.urlopen(req_del, timeout=5)
                self.assertEqual(ctx_del.exception.code, 404)

                # 1.1 mocked /analysis and /append-text -> 200, no user raw text in logs
                buf = io.StringIO()
                with redirect_stdout(buf):
                    with patch.object(llm, "call_gemini", return_value={"advisors": [], "critique": [], "two_week_checks": [], "validation_design": {"supply": [], "demand": [], "threshold": []}, "_usage": {"total_tokens": 123}}):
                        req_ana = urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions/{sid}/analysis", data=b"{}", headers={"Content-Type": "application/json"})
                        with urllib.request.urlopen(req_ana, timeout=5) as r_ana:
                            self.assertEqual(r_ana.status, 200)
                            d_ana = json.loads(r_ana.read().decode("utf-8"))
                            self.assertIn("analysis", d_ana)
                            self.assertIn("stale", d_ana)

                    with patch.object(llm, "call_gemini", return_value={"decision": "新决策", "extracted": [], "clarify": [], "_usage": {"total_tokens": 45}}):
                        req_app = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/sessions/{sid}/append-text",
                            data=json.dumps({"text": "秘密补充内容_不应进日志"}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req_app, timeout=5) as r_app:
                            self.assertEqual(r_app.status, 200)
                            d_app = json.loads(r_app.read().decode("utf-8"))
                            self.assertEqual(d_app["version"], 2)

                logs = buf.getvalue()
                self.assertNotIn("秘密测试原文_不应进日志", logs)
                self.assertNotIn("秘密补充内容_不应进日志", logs)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

    def test_list_sessions_red_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            s1 = store.create_session("A", "A", {}, {"score": {"label": "偏低", "action": "不建议投入", "red_line": True, "confidence_pct": 20}}, db_path=db_path)
            s2 = store.create_session("B", "B", {}, {"score": {"label": "偏低", "action": "暂不建议", "red_line": False, "confidence_pct": 40}}, db_path=db_path)
            s3 = store.create_session("C", "C", {}, {"score": {"label": "偏低", "action": "不建议投入", "confidence_pct": 25}}, db_path=db_path)
            items = {it["id"]: it for it in store.list_sessions(db_path=db_path)}
            self.assertTrue(items[s1]["red_line"])
            self.assertFalse(items[s2]["red_line"])
            self.assertTrue(items[s3]["red_line"])

    def test_input_length_limit_2000(self):
        import threading
        import urllib.error
        import urllib.request
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with patch.object(llm, "call_gemini", return_value={"decision": "测试", "extracted": [], "clarify": []}):
                    # 2001 chars -> 400 on /api/evaluate
                    req_2001 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/evaluate",
                        data=json.dumps({"text": "字" * 2001}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx1:
                        urllib.request.urlopen(req_2001, timeout=5)
                    self.assertEqual(ctx1.exception.code, 400)

                    # 2000 chars -> 200 on /api/evaluate
                    req_2000 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/evaluate",
                        data=json.dumps({"text": "字" * 2000}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req_2000, timeout=5) as r_ok:
                        self.assertEqual(r_ok.status, 200)
                        sid = json.loads(r_ok.read().decode("utf-8"))["session_id"]

                    # 2001 chars -> 400 on /append-text
                    req_app_2001 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/sessions/{sid}/append-text",
                        data=json.dumps({"text": "字" * 2001}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx2:
                        urllib.request.urlopen(req_app_2001, timeout=5)
                    self.assertEqual(ctx2.exception.code, 400)

                    # 2000 chars -> 200 on /append-text
                    req_app_2000 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/sessions/{sid}/append-text",
                        data=json.dumps({"text": "字" * 2000}).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                    )
                    with urllib.request.urlopen(req_app_2000, timeout=5) as r_app_ok:
                        self.assertEqual(r_app_ok.status, 200)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()

