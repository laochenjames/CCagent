import datetime
import hashlib
import http.cookies
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from unittest.mock import patch

import llm
import quota
import ratelimit
import server
import store


class TestV24Phase1(unittest.TestCase):
    def test_quota_concurrent_limits_refund_and_sgt_rollover(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "q.db")
            store.init_db(db_path)
            limits = {"owner": 10, "ip": 30, "global": 300}
            now = datetime.datetime(2026, 11, 17, 23, 50, tzinfo=quota.SGT)

            results = []
            lock = threading.Lock()

            def worker():
                ok, kind, _ = quota.reserve("o1", "ip1", db_path=db_path, limits=limits, now=now)
                with lock:
                    results.append((ok, kind))

            threads = [threading.Thread(target=worker) for _ in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(sum(1 for ok, _ in results if ok), 10)
            self.assertEqual(sum(1 for ok, kind in results if not ok and kind == "owner"), 10)

            # Refund allows 1 more
            quota.refund("o1", "ip1", db_path=db_path, now=now)
            ok, _, st = quota.reserve("o1", "ip1", db_path=db_path, limits=limits, now=now)
            self.assertTrue(ok)
            self.assertEqual(st["used"], 10)

            # IP limit
            ok_ip, kind_ip, _ = quota.reserve("o2", "ip1", db_path=db_path, limits={"owner": 10, "ip": 10, "global": 300}, now=now)
            self.assertFalse(ok_ip)
            self.assertEqual(kind_ip, "ip")

            # Global limit
            ok_gl, kind_gl, _ = quota.reserve("o2", "ip2", db_path=db_path, limits={"owner": 10, "ip": 30, "global": 10}, now=now)
            self.assertFalse(ok_gl)
            self.assertEqual(kind_gl, "global")

            # SGT midnight rollover (23:50 -> 00:05 next day)
            next_day = datetime.datetime(2026, 11, 18, 0, 5, tzinfo=quota.SGT)
            ok_next, _, st_next = quota.reserve("o1", "ip1", db_path=db_path, limits=limits, now=next_day)
            self.assertTrue(ok_next)
            self.assertEqual(st_next["used"], 1)

    def test_rate_limiter(self):
        lim = ratelimit.TokenBucketLimiter(rate_per_min=120, capacity=3)
        t = 100.0
        self.assertTrue(lim.allow("ip1", now=t))
        self.assertTrue(lim.allow("ip1", now=t))
        self.assertTrue(lim.allow("ip1", now=t))
        self.assertFalse(lim.allow("ip1", now=t))
        self.assertTrue(lim.allow("ip2", now=t))

    def test_retention_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "ret.db")
            store.init_db(db_path)
            s_old = store.create_session("old", "old", {}, {"score": {"label": "偏低"}}, db_path=db_path, owner_hash="h1")
            s_new = store.create_session("new", "new", {}, {"score": {"label": "偏高"}}, db_path=db_path, owner_hash="h1")
            conn = store.get_db(db_path)
            try:
                old_ts = (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=31)).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                conn.execute("UPDATE sessions SET updated_at = ? WHERE id = ?", (old_ts, s_old))
                conn.commit()
            finally:
                conn.close()

            deleted = store.cleanup_expired_sessions(30, db_path=db_path)
            self.assertEqual(deleted, 1)
            self.assertIsNone(store.get_session(s_old, db_path=db_path))
            self.assertIsNotNone(store.get_session(s_new, db_path=db_path))

    def test_hosted_isolation_security_and_quota_endpoints(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "hosted.db")
            store.init_db(db_path)
            orig_db = store.DB_PATH
            store.DB_PATH = db_path

            env_patch = {
                "HOSTED": "1",
                "ALLOWED_HOSTS": "127.0.0.1,localhost",
                "QUOTA_SALT": "test_salt_123",
                "FREE_DAILY_LIMIT": "2",
                "FREE_DAILY_LIMIT_IP": "10",
                "GLOBAL_DAILY_LIMIT": "100",
                "GEMINI_API_KEY": "server-key-secret",
            }
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                with patch.dict(os.environ, env_patch):
                    # 1. /api/mode
                    with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/mode", timeout=5) as r:
                        mode = json.loads(r.read().decode("utf-8"))
                        self.assertTrue(mode["hosted"])
                        self.assertEqual(mode["free_limit"], 2)
                        sc_header = r.headers.get("Set-Cookie", "")
                        self.assertIn("HttpOnly", sc_header)
                        self.assertIn("Secure", sc_header)
                        self.assertIn("SameSite=Lax", sc_header)
                        self.assertEqual(r.headers.get("X-Content-Type-Options"), "nosniff")
                        self.assertEqual(r.headers.get("Referrer-Policy"), "no-referrer")
                        self.assertEqual(r.headers.get("X-Frame-Options"), "DENY")

                    # Extract cookie A
                    c = http.cookies.SimpleCookie()
                    c.load(sc_header)
                    cookie_a = f"cc_owner={c['cc_owner'].value}"
                    raw_cookie_a = c["cc_owner"].value

                    # 2. Hosted 404 on server config endpoints
                    for ep in ("/api/config", "/api/save-config"):
                        req = urllib.request.Request(
                            f"http://127.0.0.1:{port}{ep}",
                            data=b"{}" if ep != "/api/config" else None,
                            headers={"Content-Type": "application/json"} if ep != "/api/config" else {},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx:
                            urllib.request.urlopen(req, timeout=5)
                        self.assertEqual(ctx.exception.code, 404)

                    # 3. Host whitelist 403
                    req_bad_host = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/mode",
                        headers={"Host": "evil.example.com"},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx_h:
                        urllib.request.urlopen(req_bad_host, timeout=5)
                    self.assertEqual(ctx_h.exception.code, 403)

                    # 4. 415 non-JSON
                    req_415 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/evaluate",
                        data=b"text=hi",
                        headers={"Content-Type": "text/plain", "Cookie": cookie_a},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx_415:
                        urllib.request.urlopen(req_415, timeout=5)
                    self.assertEqual(ctx_415.exception.code, 415)

                    # 5. 413 > 64KB
                    req_413 = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/evaluate",
                        data=b'{"text":"' + b"a" * 70000 + b'"}',
                        headers={"Content-Type": "application/json", "Cookie": cookie_a},
                    )
                    with self.assertRaises(urllib.error.HTTPError) as ctx_413:
                        urllib.request.urlopen(req_413, timeout=5)
                    self.assertEqual(ctx_413.exception.code, 413)

                    # 6. Create session as A, verify DB doesn't store raw cookie
                    with patch.object(llm, "call_gemini", return_value={"decision": "测试", "extracted": [], "clarify": []}):
                        req_eval = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "我想做副业"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": cookie_a},
                        )
                        with urllib.request.urlopen(req_eval, timeout=5) as r_ev:
                            d_ev = json.loads(r_ev.read().decode("utf-8"))
                            sid = d_ev["session_id"]
                            self.assertEqual(d_ev["quota"]["used"], 1)
                            self.assertEqual(d_ev["quota"]["remaining"], 1)

                    conn = store.get_db(db_path)
                    try:
                        row = conn.execute("SELECT owner_hash FROM sessions WHERE id = ?", (sid,)).fetchone()
                        self.assertEqual(row["owner_hash"], hashlib.sha256(raw_cookie_a.encode("utf-8")).hexdigest())
                        self.assertNotEqual(row["owner_hash"], raw_cookie_a)
                    finally:
                        conn.close()

                    # 7. User B cannot access A's session (all 404)
                    cookie_b = "cc_owner=user_b_secret_cookie_value"
                    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/api/sessions", headers={"Cookie": cookie_b}), timeout=5) as r_lb:
                        self.assertEqual(json.loads(r_lb.read().decode("utf-8"))["sessions"], [])

                    for method, path, body in [
                        ("GET", f"/api/sessions/{sid}", None),
                        ("POST", f"/api/sessions/{sid}/fields", {"updates": {}}),
                        ("POST", f"/api/sessions/{sid}/append-text", {"text": "补充"}),
                        ("POST", f"/api/sessions/{sid}/analysis", {}),
                        ("GET", f"/api/sessions/{sid}/report?format=fragment", None),
                        ("GET", f"/api/sessions/{sid}/report?format=html", None),
                        ("GET", f"/api/sessions/{sid}/report?format=md", None),
                        ("DELETE", f"/api/sessions/{sid}", None),
                    ]:
                        req_b = urllib.request.Request(
                            f"http://127.0.0.1:{port}{path}",
                            data=json.dumps(body).encode("utf-8") if body is not None else None,
                            method=method,
                            headers={"Cookie": cookie_b, "Content-Type": "application/json"} if body is not None else {"Cookie": cookie_b},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_b:
                            urllib.request.urlopen(req_b, timeout=5)
                        self.assertEqual(ctx_b.exception.code, 404)

                    # 8. Quota exhausted -> 429 with quota, fields update still works
                    with patch.object(llm, "call_gemini", return_value={"decision": "测试2", "extracted": [], "clarify": []}):
                        req_eval2 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "第二个"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": cookie_a},
                        )
                        urllib.request.urlopen(req_eval2, timeout=5).read()

                        req_eval3 = urllib.request.Request(
                            f"http://127.0.0.1:{port}/api/evaluate",
                            data=json.dumps({"text": "第三个"}).encode("utf-8"),
                            headers={"Content-Type": "application/json", "Cookie": cookie_a},
                        )
                        with self.assertRaises(urllib.error.HTTPError) as ctx_q:
                            urllib.request.urlopen(req_eval3, timeout=5)
                        self.assertEqual(ctx_q.exception.code, 429)
                        q_err = json.loads(ctx_q.exception.read().decode("utf-8"))
                        self.assertEqual(q_err["category"], "额度用完")
                        self.assertIn("quota", q_err)

                    # Fields update still works when quota is 0
                    req_f = urllib.request.Request(
                        f"http://127.0.0.1:{port}/api/sessions/{sid}/fields",
                        data=json.dumps({"fields": [{"id": "cash_free", "value": 50000}]}).encode("utf-8"),
                        headers={"Content-Type": "application/json", "Cookie": cookie_a},
                    )
                    with urllib.request.urlopen(req_f, timeout=5) as r_f:
                        self.assertEqual(r_f.status, 200)
                    self.assertEqual(store.get_session(sid, db_path=db_path)["fields"]["cash_free"]["value"], 50000)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db


if __name__ == "__main__":
    unittest.main()
