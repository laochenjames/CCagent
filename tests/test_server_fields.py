"""Tests for v2.1: concurrent /fields updates, server_ms, no-LLM, and mtime cache."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.request
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm
import server
import store


class TestServerFieldsV21(unittest.TestCase):
    def test_mtime_cache(self):
        r1 = llm.load_fields_registry()
        r2 = llm.load_fields_registry()
        self.assertIs(r1, r2)

    def test_concurrent_fields_update_and_server_ms(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            sid = store.create_session("想做副业", "副业", {}, {"decision": "做副业"}, db_path=db_path)

            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()

            try:
                results = []
                errors = []

                def post_field(fid, val):
                    try:
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/sessions/{sid}/fields",
                            data=json.dumps({"fields": [{"id": fid, "value": val, "unsure": False}]}).encode("utf-8"),
                            headers={"Content-Type": "application/json"},
                        )
                        with urllib.request.urlopen(req, timeout=5) as resp:
                            results.append(json.loads(resp.read().decode("utf-8")))
                    except Exception as exc:
                        errors.append(exc)

                with patch.object(llm, "call_gemini", side_effect=AssertionError("LLM must not be called")):
                    t1 = threading.Thread(target=post_field, args=("paid_evidence", "paid_stranger"))
                    t2 = threading.Thread(target=post_field, args=("unit_price", 800))
                    t1.start()
                    t2.start()
                    t1.join()
                    t2.join()

                self.assertEqual(errors, [])
                self.assertEqual(len(results), 2)
                for r in results:
                    self.assertIn("server_ms", r)
                    self.assertIsInstance(r["server_ms"], int)

                sess = store.get_session(sid, db_path=db_path)
                self.assertIn("paid_evidence", sess["fields"])
                self.assertIn("unit_price", sess["fields"])
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
