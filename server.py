"""HTTP server for the career investment checkup tool (v2)."""

import hashlib
import http.client
import http.cookies
import importlib.util
import io
import json
import os
import secrets
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

import engine
import llm
import providers
import quota
import ratelimit
import report
import score
import store
import verify

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(BASE_DIR, ".env")
ALLOWED_STATIC_FILES = {"index.html", "style.css", "app.js", "report.css", "favicon.ico", "favicon.png"}
SHARED_STATIC_FILES = {"nav.js", "thinking.css", "thinking.js"}
DISCLAIMER = "本评估基于你提供的信息做出的初步判断，不构成财务、法律或职业保证。AI 对具体职业的影响属判断，不是数据。"

_SESSION_LOCK_SHARDS = [threading.Lock() for _ in range(64)]
_RATE_LIMITER = ratelimit.TokenBucketLimiter(rate_per_min=120, capacity=120)
_TEST_CONN_LIMITER = ratelimit.TokenBucketLimiter(rate_per_min=10.0 / 60.0, capacity=10)
MAX_BODY_BYTES = 65536

_SUB_AGENTS_LOCK = threading.Lock()
_SUB_AGENT_PORTS = {}
SUB_AGENTS = {
    "agent2": {"handler": "TriageRequestHandler", "quota_paths": ("/api/triage",)},
    "agent3": {"handler": "HabitRequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent4": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent5": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent6": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent7": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent8": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent9": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
    "agent10": {"handler": "RequestHandler", "quota_paths": ("/api/extract", "/api/generate")},
}


def _get_sub_agent_port(agent_name):
    if agent_name in _SUB_AGENT_PORTS:
        return _SUB_AGENT_PORTS[agent_name]
    with _SUB_AGENTS_LOCK:
        if agent_name in _SUB_AGENT_PORTS:
            return _SUB_AGENT_PORTS[agent_name]
        spec_cfg = SUB_AGENTS[agent_name]
        srv_path = os.path.join(BASE_DIR, agent_name, "server.py")
        spec = importlib.util.spec_from_file_location(f"{agent_name}_server", srv_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        if hasattr(mod, "init_db"):
            mod.init_db()
        handler_cls = getattr(mod, spec_cfg["handler"])
        srv = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
        _SUB_AGENT_PORTS[agent_name] = srv.server_port
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        return _SUB_AGENT_PORTS[agent_name]


class _PayloadTooLarge(Exception):
    pass


def _get_session_lock(sid):
    idx = int(hashlib.md5((sid or "").encode("utf-8")).hexdigest(), 16) % 64
    return _SESSION_LOCK_SHARDS[idx]


def _is_hosted():
    return os.environ.get("HOSTED") == "1"


def _allowed_hosts():
    if not _is_hosted():
        return {"127.0.0.1", "localhost"}
    raw = os.environ.get("ALLOWED_HOSTS", "")
    return {h.strip().lower() for h in raw.split(",") if h.strip()}


def _quota_limits():
    return {
        "owner": int(os.environ.get("FREE_DAILY_LIMIT", "10")),
        "ip": int(os.environ.get("FREE_DAILY_LIMIT_IP", "30")),
        "global": int(os.environ.get("GLOBAL_DAILY_LIMIT", "300")),
    }


def _retention_days():
    return int(os.environ.get("RETENTION_DAYS", "30"))


def load_env():
    """Load .env key-value pairs."""
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def save_env(updates):
    """Persist .env updates without logging secrets."""
    current = load_env()
    current.update(updates)
    lines = ["# 职业投入体检工具配置文件"]
    for k, v in current.items():
        lines.append(f"{k}={v}")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def get_llm_config():
    """Return (api_key, model, fast_model, base_url, timeout_sec)."""
    env = load_env()
    api_key = os.environ.get("GEMINI_API_KEY") or env.get("GEMINI_API_KEY", "")
    model = os.environ.get("GEMINI_MODEL") or env.get("GEMINI_MODEL", "gemini-3.5-flash-lite")
    fast_model = os.environ.get("GEMINI_FAST_MODEL") or env.get("GEMINI_FAST_MODEL", "") or model
    base_url = os.environ.get("GEMINI_BASE_URL") or env.get("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com")
    timeout_raw = os.environ.get("GEMINI_TIMEOUT") or env.get("GEMINI_TIMEOUT", "120")
    try:
        timeout_sec = int(timeout_raw)
    except ValueError:
        timeout_sec = 120
    return api_key, model, fast_model, base_url, timeout_sec


def log_event(level, event, session="-", version="-", length=0, ms=0, category="-", **extra):
    """Privacy-safe server log: never logs user text or LLM content."""
    ts = store.utcnow_iso()
    extra_parts = []
    for k, v in extra.items():
        if isinstance(v, (bool, int, float)):
            extra_parts.append(f"{k}={v}")
    suffix = (" " + " ".join(extra_parts)) if extra_parts else ""
    print(f"[{ts}] [{level}] {event} session={session} version={version} len={length} ms={ms} cat={category}{suffix}", flush=True)


def _confirmed_numbers(fields_state, factors=None):
    """Collect numeric values from given fields and factor rule_notes for lint whitelist."""
    nums = []
    for f in fields_state.values():
        if f.get("status") == "given":
            v = f.get("value")
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                nums.append(v)
    for fac in (factors or []):
        for n in verify.extract_numbers(fac.get("rule_note", "")):
            nums.append(n)
    return nums


def _build_result_object(session_id, version, decision, fields_state, registry, clarify=None, dropped=None, analysis=None, analysis_stale=False):
    """Build v2 result object."""
    eng = engine.evaluate_fields(fields_state, registry)
    clarify_map = {c["field_id"]: c for c in (clarify or []) if isinstance(c, dict) and c.get("field_id")}
    for g in eng["groups"]:
        for fld in g["fields"]:
            fld["clarify"] = clarify_map.get(fld["id"])

    return {
        "session_id": session_id,
        "version": version,
        "rules_version": eng["rules_version"],
        "decision": decision or "",
        "score": eng["score"],
        "factors": eng["factors"],
        "synthesis": eng["synthesis"],
        "flags": eng["flags"],
        "groups": eng["groups"],
        "headline": eng["headline"],
        "clarify": clarify or [],
        "analysis": analysis,
        "analysis_stale": analysis_stale,
        "lint": {"dropped": dropped or [], "hidden_count": 0},
        "disclaimer": DISCLAIMER,
    }


class AppHandler(SimpleHTTPRequestHandler):
    """HTTP handler with Host/Origin checks and static file whitelist."""

    protocol_version = "HTTP/1.1"
    timeout = 30

    def setup(self):
        super().setup()
        self._new_owner_cookie = None

    def log_message(self, format, *args):
        pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "frame-ancestors 'self' chrome-extension://*")
        if getattr(self, "_new_owner_cookie", None):
            secure = "; Secure" if _is_hosted() else ""
            self.send_header(
                "Set-Cookie",
                f"cc_owner={self._new_owner_cookie}; HttpOnly; SameSite=Lax; Path=/; Max-Age=31536000{secure}",
            )
            self._new_owner_cookie = None
        super().end_headers()

    def _resolve_identity(self):
        cookie_hdr = self.headers.get("Cookie", "")
        raw_owner = None
        if cookie_hdr:
            c = http.cookies.SimpleCookie()
            try:
                c.load(cookie_hdr)
                if "cc_owner" in c and c["cc_owner"].value:
                    raw_owner = c["cc_owner"].value
            except Exception:
                raw_owner = None
        if not raw_owner:
            raw_owner = secrets.token_urlsafe(32)
            self._new_owner_cookie = raw_owner
        owner_hash = hashlib.sha256(raw_owner.encode("utf-8")).hexdigest()

        ip = self.client_address[0] if self.client_address else "127.0.0.1"
        if os.environ.get("TRUST_PROXY") == "1":
            xff = self.headers.get("X-Forwarded-For", "")
            parts = [p.strip() for p in xff.split(",") if p.strip()]
            if parts:
                ip = parts[-1]
        salt = os.environ.get("QUOTA_SALT", "")
        ip_hash = hashlib.sha256(f"{salt}{ip}".encode("utf-8")).hexdigest()
        return owner_hash, ip_hash

    def _check_rate_limit(self, path, ip_hash):
        if _is_hosted() and path.startswith("/api/"):
            if not _RATE_LIMITER.allow(ip_hash):
                self._send_json(429, {"error": "请求过于频繁，请稍后再试。", "category": "限流"})
                return False
        return True

    def _check_host_origin(self):
        allowed = _allowed_hosts()
        host = (self.headers.get("Host") or "").split(":")[0].lower()
        if host and host not in allowed:
            self._send_json(403, {"error": "Forbidden Host", "category": "安全校验失败"})
            return False
        origin = self.headers.get("Origin")
        if origin:
            parsed = urllib.parse.urlparse(origin)
            if parsed.scheme == "chrome-extension":
                return True
            if (parsed.hostname or "").lower() not in allowed:
                self._send_json(403, {"error": "Forbidden Origin", "category": "安全校验失败"})
                return False
        return True

    def _send_json(self, status_code, payload, cache_control=None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        origin = self.headers.get("Origin") or ""
        if origin.startswith("chrome-extension://"):
            self.send_header("Access-Control-Allow-Origin", origin)
        if cache_control:
            self.send_header("Cache-Control", cache_control)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", "0") or "0")
        if length < 0:
            raise ValueError("negative Content-Length")
        if length > MAX_BODY_BYTES:
            self.close_connection = True
            raise _PayloadTooLarge()
        raw = self.rfile.read(length) if length > 0 else b"{}"
        return json.loads(raw.decode("utf-8"))

    def _match_sub_agent(self, path):
        for name in SUB_AGENTS:
            if path == f"/{name}" or path.startswith(f"/{name}/"):
                return name
        return None

    def _proxy_sub_agent(self, agent_name, method, pre_read_body=None):
        prefix = f"/{agent_name}"
        if self.path == prefix:
            self.send_response(302)
            self.send_header("Location", prefix + "/")
            self.end_headers()
            return
        target_path = self.path[len(prefix):] or "/"
        if pre_read_body is not None:
            body = pre_read_body
        else:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length > 0 else None
        fwd_headers = {
            k: v for k, v in self.headers.items()
            if k.lower() not in ("host", "connection", "content-length", "origin", "referer")
        }
        if body is not None:
            fwd_headers["Content-Length"] = str(len(body))
        port = _get_sub_agent_port(agent_name)
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=120)
        try:
            conn.request(method, target_path, body=body, headers=fwd_headers)
            resp = conn.getresponse()
            data = resp.read()
            self.send_response(resp.status)
            for k, v in resp.getheaders():
                if k.lower() not in ("transfer-encoding", "connection", "content-length"):
                    self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            return resp.status
        finally:
            conn.close()

    def do_GET(self):
        if not self._check_host_origin():
            return
        owner_hash, ip_hash = self._resolve_identity()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._check_rate_limit(path, ip_hash):
            return
        sub_agent = self._match_sub_agent(path)
        if sub_agent:
            if path == f"/{sub_agent}":
                self.send_response(302)
                self.send_header("Location", f"/{sub_agent}/" + (f"?{parsed.query}" if parsed.query else ""))
                self.end_headers()
                return
            return self._proxy_sub_agent(sub_agent, "GET")

        if path == "/" or path == "/index.html":
            return self._serve_static("index.html")
        if path == "/privacy" or path == "/privacy.html":
            return self._serve_static("privacy.html")
        if path.startswith("/shared/"):
            rel_shared = path[len("/shared/"):]
            if rel_shared in SHARED_STATIC_FILES:
                return self._serve_static(os.path.join("shared", rel_shared))
        if path.lstrip("/") in ALLOWED_STATIC_FILES:
            return self._serve_static(path.lstrip("/"))

        if path == "/api/mode":
            return self._send_json(200, {
                "hosted": _is_hosted(),
                "free_limit": _quota_limits()["owner"],
                "retention_days": _retention_days(),
                "default_models": {p: providers.PROVIDER_PRESETS[p]["default_model"] for p in providers.SUPPORTED_PROVIDERS},
            })

        if path == "/api/quota":
            return self._send_json(200, quota.get_quota_status(owner_hash, ip_hash, limits=_quota_limits()))

        if path == "/api/sessions":
            return self._send_json(200, {"sessions": store.list_sessions(owner_hash=owner_hash, hosted=_is_hosted())})

        if path.startswith("/api/sessions/") and path.endswith("/report"):
            sid = path[len("/api/sessions/"):-len("/report")].strip("/")
            qs = urllib.parse.parse_qs(parsed.query)
            fmt = qs.get("format", ["fragment"])[0]
            return self._handle_report(sid, fmt, owner_hash=owner_hash)

        if path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):].strip("/")
            qs = urllib.parse.parse_qs(parsed.query)
            ver = qs.get("version", [None])[0]
            if ver is not None:
                try:
                    ver = int(ver)
                except ValueError:
                    return self._send_json(400, {"error": "version 参数必须为整数", "category": "参数错误"})
            data = store.get_session(sid, version=ver, owner_hash=owner_hash, hosted=_is_hosted())
            if not data:
                return self._send_json(404, {"error": "会话不存在", "category": "未找到"})
            res = data["result"]
            stale = data["analysis_stale"]
            if res.get("rules_version") != score.RULES_VERSION:
                registry = llm.load_fields_registry()
                res = _build_result_object(
                    sid,
                    data["version"],
                    res.get("decision", ""),
                    data["fields"],
                    registry,
                    clarify=res.get("clarify", []),
                    dropped=res.get("lint", {}).get("dropped", []),
                    analysis=data["analysis"],
                    analysis_stale=bool(data["analysis"]),
                )
                if data["analysis"]:
                    stale = True
            res["analysis"] = data["analysis"]
            res["analysis_stale"] = stale
            return self._send_json(200, res)

        if path == "/api/advisors":
            public_fields = ("id", "code", "seal", "name", "group", "order", "rated", "ask", "watch", "rule_public")
            advisors = [
                {k: a.get(k) for k in public_fields}
                for a in llm.load_advisors_library()
            ]
            return self._send_json(
                200,
                {"advisors": advisors, "disclaimer": "智囊是分析视角，不是持证顾问。"},
                cache_control="public, max-age=300",
            )

        if path == "/api/fields":
            return self._send_json(200, {"fields": llm.load_fields_registry()})

        if path == "/api/config":
            if _is_hosted():
                return self._send_json(404, {"error": "Not Found", "category": "未找到"})
            api_key, model, fast_model, base_url, _ = get_llm_config()
            masked = (api_key[:4] + "..." + api_key[-4:]) if len(api_key) >= 10 else ("已配置" if api_key else "")
            return self._send_json(200, {"has_key": bool(api_key), "masked_key": masked, "model": model, "fast_model": fast_model, "base_url": base_url})

        self._send_json(404, {"error": "Not Found", "category": "未找到"})

    def do_POST(self):
        if not self._check_host_origin():
            return
        owner_hash, ip_hash = self._resolve_identity()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._check_rate_limit(path, ip_hash):
            return
        sub_agent = self._match_sub_agent(path)
        if sub_agent:
            if _is_hosted() and path == f"/{sub_agent}/api/save-config":
                return self._send_json(403, {"error": "公网托管模式下不支持修改服务端配置。"})
            quota_targets = tuple(f"/{sub_agent}{p}" for p in SUB_AGENTS[sub_agent]["quota_paths"])
            if _is_hosted() and path in quota_targets:
                length = int(self.headers.get("Content-Length") or 0)
                raw_body = self.rfile.read(length) if length > 0 else b""
                user_key = ""
                try:
                    parsed_body = json.loads(raw_body.decode("utf-8")) if raw_body else {}
                    rk = (parsed_body.get("api_key") or "").strip()
                    if rk and rk != "server-configured" and "..." not in rk:
                        user_key = rk
                except Exception:
                    pass
                charged = False
                if not user_key:
                    ok, kind, _ = quota.reserve(owner_hash, ip_hash, limits=_quota_limits())
                    if not ok:
                        return self._send_json(429, {
                            "error": "免费体验次数已用完（10 次），请在右上角「设置」中填入你自己的 API Key 继续使用。",
                            "category": "额度已用完",
                        })
                    charged = True
                status = self._proxy_sub_agent(sub_agent, "POST", pre_read_body=raw_body)
                if charged and (status is None or status >= 400):
                    quota.refund(owner_hash, ip_hash)
                return
            return self._proxy_sub_agent(sub_agent, "POST")

        ct = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ct != "application/json":
            return self._send_json(415, {"error": "Content-Type 必须为 application/json", "category": "参数错误"})

        try:
            body = self._read_json_body()
        except _PayloadTooLarge:
            return self._send_json(413, {"error": "请求体超过 64 KB 上限", "category": "参数错误"})
        except Exception:
            return self._send_json(400, {"error": "请求体 JSON 格式错误", "category": "参数错误"})

        try:
            if path == "/api/evaluate":
                return self._handle_evaluate(body, owner_hash=owner_hash, ip_hash=ip_hash)

            if path.startswith("/api/sessions/") and path.endswith("/fields"):
                sid = path[len("/api/sessions/"):-len("/fields")].strip("/")
                return self._handle_fields_update(sid, body, owner_hash=owner_hash)

            if path.startswith("/api/sessions/") and path.endswith("/append-text"):
                sid = path[len("/api/sessions/"):-len("/append-text")].strip("/")
                return self._handle_append_text(sid, body, owner_hash=owner_hash, ip_hash=ip_hash)

            if path.startswith("/api/sessions/") and path.endswith("/analysis"):
                sid = path[len("/api/sessions/"):-len("/analysis")].strip("/")
                return self._handle_analysis(sid, owner_hash=owner_hash, ip_hash=ip_hash)

            if path == "/api/save-config":
                if _is_hosted():
                    return self._send_json(404, {"error": "Not Found", "category": "未找到"})
                updates = {}
                if body.get("api_key"):
                    updates["GEMINI_API_KEY"] = body["api_key"].strip()
                if body.get("model"):
                    updates["GEMINI_MODEL"] = llm.sanitize_model(body["model"])
                if body.get("fast_model") is not None:
                    updates["GEMINI_FAST_MODEL"] = llm.sanitize_model(body["fast_model"]) if body["fast_model"].strip() else ""
                if body.get("base_url"):
                    if not llm.validate_base_url(body["base_url"]):
                        return self._send_json(400, {"error": "Base URL 不合法", "category": "参数错误"})
                    updates["GEMINI_BASE_URL"] = body["base_url"].strip()
                save_env(updates)
                return self._send_json(200, {"ok": True})

            if path == "/api/test-connection":
                return self._handle_test_connection(body, ip_hash=ip_hash)

            if path == "/api/route":
                return self._handle_route(body)

            self._send_json(404, {"error": "Not Found", "category": "未找到"})
        except Exception as exc:
            log_event("ERROR", "unhandled_post_error", category=type(exc).__name__)
            err_msg = "服务器内部错误" if _is_hosted() else f"服务器内部错误: {type(exc).__name__}: {exc}"
            self._send_json(500, {"error": err_msg, "category": "服务异常"})

    def do_OPTIONS(self):
        self.send_response(204)
        origin = self.headers.get("Origin") or "*"
        self.send_header("Access-Control-Allow-Origin", origin)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_route(self, body):
        text = (body.get("text") or "").strip()
        if not text:
            return self._send_json(400, {"error": "请输入需要路由判断的内容"})

        agent_catalog = {
            "agent1": "职业投入体检（能力圈起点：招聘、副业、转行、行业机会、是否值得重注）",
            "agent2": "个人任务分诊（检查清单：待办流水账、多件事不知先做哪个、干货清单筛选）",
            "agent3": "原子习惯生成（复利飞轮：高手日常、健身学习方法、想养成的长期习惯）",
            "agent4": "第一性原理（马斯克：硬核技术、商业模式/成本质疑、打破行业惯例重构）",
            "agent5": "辩证抽象（矛盾论：宏观趋势、巨头博弈、复杂路线之争、抓主要矛盾）",
            "agent6": "一法多解（最大公约数：多条不同领域素材/案例合并、提炼通用底层规律）",
            "agent7": "双轨分析（芒格理性+误判：暴富神话、AI焦虑、大V晒单、带情绪的观点或决策）",
            "agent8": "反向思考（事前验尸：新项目、投资/融资机会、商业宏图、找失败路径和断裂点）",
            "agent9": "激励机制诊断（联邦快递法：大厂裁员、平台改规则、政策变动、利益与考核博弈）",
            "agent10": "Lollapalooza共振雷达（多力叠加：现象级爆款、集体狂热、泡沫还是超级复利）",
        }

        def fallback_route(t):
            s = t.lower()
            if "【素材 1】" in t or "【素材 2】" in t:
                return "agent6", "多条素材合并，最适合用「一法多解」提炼底层最大公约数。", "agent5"
            if any(k in s for k in ("暴富", "焦虑", "割韭菜", "fomo", "晒单", "月入", "财务自由", "千万别", "必须买", "梭哈")):
                return "agent7", "内容带有较强情绪或利益诱导，建议先用「双轨分析」算理性账并排查潜意识误判。", "agent10"
            if any(k in s for k in ("裁员", "kpi", "okr", "绩效", "考核", "政策", "规则", "抽成", "补贴", "管理层", "官僚")):
                return "agent9", "涉及组织考核与利益分配，最适合用「激励机制诊断」看清真实动机。", "agent5"
            if any(k in s for k in ("泡沫", "狂热", "爆款", "疯涨", "全民", "病毒式", "lollapalooza", "共振", "踩踏")):
                return "agent10", "呈现多力量同向叠加迹象，适合用「Lollapalooza」甄别真复利还是伪泡沫。", "agent7"
            if any(k in s for k in ("投资", "融资", "创业", "项目", "估值", "商业计划", "押注", "all in", "风险")):
                return "agent8", "面对机会与宏图，先用「反向思考」做事前验尸，排查断裂点和安全边际。", "agent7"
            if any(k in s for k in ("转行", "求职", "招聘", "副业", "职业", "跳槽", "薪资", "能力圈", "赛道")):
                return "agent1", "涉及个人职业与赛道投入，适合用「职业投入体检」校准能力圈起点。", "agent8"
            if any(k in s for k in ("待办", "todo", "任务", "清单", "今天要做", "忙不过来", "优先级", "安排")):
                return "agent2", "属于多事项排序与取舍，最适合用「个人任务分诊」快速做清单过滤。", "agent3"
            if any(k in s for k in ("习惯", "坚持", "早起", "健身", "背单词", "自律", "每天", "打卡", "复利")):
                return "agent3", "聚焦长期行为养成，适合用「原子习惯生成」拆成 2 分钟可启动的飞轮。", "agent2"
            if any(k in s for k in ("成本", "原理", "架构", "技术", "颠覆", "物理", "重构", "效率", "为什么必须")):
                return "agent4", "适合剥掉行业惯例，用「第一性原理」退回物理与成本底线重新推演。", "agent5"
            if any(k in s for k in ("趋势", "博弈", "巨头", "竞争", "格局", "宏观", "矛盾", "路线")):
                return "agent5", "属于复杂局势与多方博弈，适合用「辩证抽象」抓住当前主要矛盾。", "agent9"
            return "agent7", "通用信息与观点评估，默认推荐用「双轨分析」同时做理性推演与误判排查。", "agent4"

        primary, reason, secondary = fallback_route(text)
        engine = "rule"
        try:
            import thinking_core
            cfg = thinking_core.resolve_llm_config(body)
            if cfg.get("api_key"):
                catalog_str = "\n".join(f"- {k}: {v}" for k, v in agent_catalog.items())
                prompt = (
                    "你是 CCagent 的前置路由专家。请根据用户输入的内容，从下面 10 个思维模型 Agent 中，"
                    "选出最匹配的主推 Agent（primary）和备选 Agent（secondary），并用一句不超过 28 字的中文说明原因。\n\n"
                    f"可选 Agent：\n{catalog_str}\n\n"
                    f"用户输入：\n{text[:1200]}\n\n"
                    '严格返回 JSON：{"primary": "agent7", "secondary": "agent8", "reason": "一句话理由"}'
                )
                res = thinking_core.call_llm_json(prompt, cfg, temperature=0.1, max_tokens=220, tag="Router")
                p_id = (res.get("primary") or "").strip()
                s_id = (res.get("secondary") or "").strip()
                r_txt = (res.get("reason") or "").strip()
                if p_id in agent_catalog:
                    primary = p_id
                    if s_id in agent_catalog and s_id != p_id:
                        secondary = s_id
                    if r_txt:
                        reason = r_txt
                    engine = "ai"
        except Exception:
            pass

        return self._send_json(200, {
            "primary": primary,
            "secondary": secondary,
            "reason": reason,
            "engine": engine,
        })

    def do_PUT(self):
        return self._proxy_other("PUT")

    def do_PATCH(self):
        return self._proxy_other("PATCH")

    def _proxy_other(self, method):
        if not self._check_host_origin():
            return
        owner_hash, ip_hash = self._resolve_identity()
        path = urllib.parse.urlparse(self.path).path
        if not self._check_rate_limit(path, ip_hash):
            return
        sub_agent = self._match_sub_agent(path)
        if sub_agent and path.startswith(f"/{sub_agent}/"):
            return self._proxy_sub_agent(sub_agent, method)
        self._send_json(404, {"error": "not found"})

    def do_DELETE(self):
        if not self._check_host_origin():
            return
        owner_hash, ip_hash = self._resolve_identity()
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if not self._check_rate_limit(path, ip_hash):
            return
        sub_agent = self._match_sub_agent(path)
        if sub_agent:
            return self._proxy_sub_agent(sub_agent, "DELETE")

        if path.startswith("/api/sessions/"):
            sid = path[len("/api/sessions/"):].strip("/")
            ok = store.delete_session(sid, owner_hash=owner_hash, hosted=_is_hosted())
            if not ok:
                return self._send_json(404, {"error": "会话不存在", "category": "未找到"})
            log_event("INFO", "delete_session", session=sid)
            return self._send_json(200, {"ok": True})
        self._send_json(404, {"error": "Not Found", "category": "未找到"})

    def _serve_static(self, filename):
        fpath = os.path.join(BASE_DIR, filename)
        if not os.path.isfile(fpath):
            return self._send_json(404, {"error": "File Not Found", "category": "未找到"})
        ctype = "text/html; charset=utf-8"
        if filename.endswith(".css"):
            ctype = "text/css; charset=utf-8"
        elif filename.endswith(".js"):
            ctype = "application/javascript; charset=utf-8"
        elif filename.endswith(".png"):
            ctype = "image/png"
        elif filename.endswith(".ico"):
            ctype = "image/x-icon"
        with open(fpath, "rb") as f:
            data = f.read()
        cache_ctrl = "public, max-age=86400" if filename.endswith((".ico", ".png")) else "no-cache"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache_ctrl)
        self.end_headers()
        self.wfile.write(data)

    def _extract_byok_headers(self):
        byok_key = (self.headers.get("X-LLM-Key") or "").strip()
        if not byok_key:
            return False, "gemini", None, None, None
        prov = (self.headers.get("X-LLM-Provider") or "gemini").strip().lower()
        if prov not in providers.SUPPORTED_PROVIDERS:
            return None, None, None, None, f"不支持的模型厂商: {prov}"
        raw_model = (self.headers.get("X-LLM-Model") or "").strip()
        model = llm.sanitize_model(raw_model) if raw_model else providers.PROVIDER_PRESETS[prov]["default_model"]
        return True, prov, byok_key, model, None

    def _handle_test_connection(self, body, ip_hash=None):
        if _is_hosted() and not _TEST_CONN_LIMITER.allow(ip_hash or "local"):
            return self._send_json(429, {"error": "自测次数过多，请一小时后再试。", "category": "限流"})
        using_byok, prov, byok_key, byok_model, err = self._extract_byok_headers()
        if err:
            return self._send_json(400, {"error": err, "category": "参数错误"})
        if using_byok:
            api_key, model, base_url, timeout_sec = byok_key, byok_model, None, 30
        else:
            if _is_hosted():
                return self._send_json(400, {"error": "请先填写你自己的 API Key。", "category": "参数错误"})
            api_key, model, _, base_url, timeout_sec = get_llm_config()
            if body.get("api_key"):
                api_key = body["api_key"].strip()
            if body.get("model"):
                model = llm.sanitize_model(body["model"])
            if body.get("base_url"):
                base_url = body["base_url"].strip()
            prov = "gemini"

        try:
            if prov == "gemini":
                import urllib.request
                effective_base = (base_url or "https://generativelanguage.googleapis.com").rstrip("/")
                endpoint = f"{effective_base}/v1beta/models/{model}:generateContent"
                probe_payload = json.dumps({"contents": [{"parts": [{"text": "Pong"}]}]}).encode("utf-8")
                req = urllib.request.Request(
                    endpoint,
                    data=probe_payload,
                    headers={"Content-Type": "application/json", "x-goog-api-key": api_key},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=min(timeout_sec, 30)) as resp:
                    resp.read()
                return self._send_json(200, {"ok": True, "parsed_ok": True, "extracted_ok": True, "message": f"连接成功（{model}）"})
            if prov in ("xai", "deepseek"):
                providers.verify_openai_models(prov, api_key, model, timeout_sec=min(timeout_sec, 15))
            probe_text = "想业余做技能陪跑，单价800元，自己能拿7成"
            res = llm.call_model(prov, api_key, model, "extract", probe_text, base_url=base_url, timeout_sec=min(timeout_sec, 30))
            parsed_ok = isinstance(res, dict) and all(k in res for k in ("decision", "extracted", "clarify"))
            extracted_ok = False
            if parsed_ok and isinstance(res.get("extracted"), list):
                for item in res["extracted"]:
                    if isinstance(item, dict) and item.get("id") == "unit_price":
                        try:
                            if float(item.get("value")) == 800:
                                extracted_ok = True
                        except Exception:
                            pass
            if not parsed_ok:
                return self._send_json(200, {"ok": False, "parsed_ok": False, "extracted_ok": False, "message": "模型返回格式异常"})
            if not extracted_ok:
                return self._send_json(200, {"ok": True, "parsed_ok": True, "extracted_ok": False, "message": "该模型可用，但抽取质量不足，建议换模型"})
            return self._send_json(200, {"ok": True, "parsed_ok": True, "extracted_ok": True, "message": "连接与抽取自测通过"})
        except llm.GeminiAPIError as ge:
            return self._send_json(400, {"error": ge.message, "category": ge.category})
        except TimeoutError:
            return self._send_json(400, {"error": "请求超时，请检查网络或代理设置。", "category": "请求超时"})
        except urllib.error.HTTPError as he:
            detail = ""
            try:
                detail = he.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            return self._send_json(400, {"error": f"HTTP {he.code}: {detail or he.reason}", "category": "API错误"})
        except urllib.error.URLError as ue:
            return self._send_json(400, {"error": f"网络错误: {ue.reason}", "category": "网络异常"})

    def _reserve_hosted_quota(self, owner_hash, ip_hash):
        if not _is_hosted():
            return True, None
        ok, kind, q_status = quota.reserve(owner_hash, ip_hash, limits=_quota_limits())
        if not ok:
            kind_label = {"owner": "个人", "ip": "IP", "global": "全站"}.get(kind, "个人")
            self._send_json(429, {
                "error": f"今日{kind_label}免费额度已用完，将于次日 00:00（新加坡时间）恢复。",
                "category": "额度用完",
                "quota": q_status,
            })
            return False, None
        return True, q_status

    def _send_llm_error(self, ge, is_byok):
        if _is_hosted() and not is_byok:
            return self._send_json(
                503,
                {"error": "免费服务暂时不可用，请稍后再试，或在设置中使用你自己的 Key。", "category": "服务暂不可用"},
            )
        return self._send_json(502, {"error": ge.message, "category": ge.category})

    def _handle_evaluate(self, body, owner_hash=None, ip_hash=None):
        raw_text = (body.get("text") or "").strip()
        if not raw_text:
            return self._send_json(400, {"error": "请输入你想做的事", "category": "参数错误"})
        if len(raw_text) > 2000:
            return self._send_json(400, {"error": "输入内容过长（最多 2000 字）", "category": "参数错误"})

        using_byok, prov, byok_key, byok_model, err = self._extract_byok_headers()
        if err:
            return self._send_json(400, {"error": err, "category": "参数错误"})

        q_status = None
        if not using_byok:
            ok_q, q_status = self._reserve_hosted_quota(owner_hash, ip_hash)
            if not ok_q:
                return

        t0 = time.monotonic()
        if using_byok:
            api_key, fast_model, base_url, timeout_sec = byok_key, byok_model, None, 60
        else:
            api_key, _, fast_model, base_url, timeout_sec = get_llm_config()
            if _is_hosted():
                base_url = "https://generativelanguage.googleapis.com"
        registry = llm.load_fields_registry()

        charged = _is_hosted() and not using_byok
        try:
            try:
                llm_raw = llm.call_model(prov, api_key, fast_model, "extract", raw_text, base_url=base_url, timeout_sec=min(timeout_sec, 60))
            except llm.GeminiAPIError as ge:
                ms = int((time.monotonic() - t0) * 1000)
                log_event("ERROR", "evaluate_fail", length=len(raw_text), ms=ms, category=ge.category, provider=prov)
                return self._send_llm_error(ge, using_byok)

            fields_state, dropped = verify.verify_extracted(raw_text, llm_raw.get("extracted", []), registry)
            sid = store.generate_session_id()
            decision = llm_raw.get("decision", "")
            result = _build_result_object(sid, 1, decision, fields_state, registry, clarify=llm_raw.get("clarify", []), dropped=dropped)

            title = decision.strip() or raw_text[:20]
            actual_sid = store.create_session(raw_text, title, fields_state, result, owner_hash=owner_hash)
            result["session_id"] = actual_sid
            if q_status is not None:
                result["quota"] = q_status

            ms = int((time.monotonic() - t0) * 1000)
            log_event("INFO", "evaluate_ok", session=actual_sid, version=1, length=len(raw_text), ms=ms, provider=prov)
            charged = False
            return self._send_json(200, result)
        finally:
            if charged:
                quota.refund(owner_hash, ip_hash)

    def _handle_fields_update(self, sid, body, owner_hash=None):
        """Pure-code field update: NEVER calls LLM."""
        t0 = time.monotonic()
        with _get_session_lock(sid):
            sess = store.get_session(sid, owner_hash=owner_hash, hosted=_is_hosted())
            if not sess:
                return self._send_json(404, {"error": "会话不存在", "category": "未找到"})

            registry = llm.load_fields_registry()
            reg_map = {f["id"]: f for f in registry}
            fields_state = sess["fields"]

            for item in (body.get("fields") or []):
                fid = item.get("id")
                if fid not in reg_map:
                    continue
                fdef = reg_map[fid]
                if item.get("clear"):
                    fields_state[fid] = {
                        "id": fid,
                        "value": None,
                        "unit": fdef.get("unit", ""),
                        "category": "自报",
                        "quote": "",
                        "status": "missing",
                        "readings": [],
                        "source": "form",
                    }
                    continue
                val = item.get("value")
                if val is None or val == "":
                    continue
                ftype = fdef.get("type", "string")
                if ftype in ("number", "int", "float"):
                    try:
                        num = float(val)
                    except (TypeError, ValueError):
                        return self._send_json(400, {"error": f"字段 {fdef.get('label', fid)} 必须是数字", "category": "参数错误"})
                    if fdef.get("min") is not None and num < fdef["min"]:
                        return self._send_json(400, {"error": f"字段 {fdef.get('label', fid)} 不能小于 {fdef['min']}", "category": "参数错误"})
                    if fdef.get("max") is not None and num > fdef["max"]:
                        return self._send_json(400, {"error": f"字段 {fdef.get('label', fid)} 不能大于 {fdef['max']}", "category": "参数错误"})
                    if fid == "take_home_ratio" and (num < 0 or num > 1):
                        return self._send_json(400, {"error": "到手比例必须在 0 到 1 之间（如 0.6 表示 60%）", "category": "参数错误"})
                elif ftype in ("enum", "single_choice", "select"):
                    raw_opts = fdef.get("choices") or fdef.get("options") or []
                    opts = [o["value"] if isinstance(o, dict) else o for o in raw_opts]
                    if opts and val not in opts:
                        return self._send_json(400, {"error": f"字段 {fdef.get('label', fid)} 的值不合法", "category": "参数错误"})
                unsure = bool(item.get("unsure", False))
                cat = "猜测" if unsure else "自报"
                fields_state[fid] = {
                    "id": fid,
                    "value": val,
                    "unit": fdef.get("unit", ""),
                    "category": cat,
                    "quote": "",
                    "status": "given",
                    "readings": [],
                    "source": "form",
                }

            for fid in (body.get("skip") or []):
                if fid in reg_map:
                    fields_state[fid] = {
                        "id": fid,
                        "value": None,
                        "unit": reg_map[fid].get("unit", ""),
                        "category": "自报",
                        "quote": "",
                        "status": "skipped",
                        "readings": [],
                        "source": "form",
                    }

            for fid in (body.get("unskip") or []):
                if fid in reg_map and fields_state.get(fid, {}).get("status") == "skipped":
                    fields_state[fid]["status"] = "missing"

            prev_res = sess["result"]
            result = _build_result_object(
                sid,
                sess["version"],
                prev_res.get("decision", ""),
                fields_state,
                registry,
                clarify=prev_res.get("clarify", []),
                dropped=prev_res.get("lint", {}).get("dropped", []),
                analysis=sess["analysis"],
            )
            stale = store.update_latest_evaluation(sid, fields_state, result)
            result["analysis_stale"] = stale

        ms = int((time.monotonic() - t0) * 1000)
        result["server_ms"] = ms
        log_event("INFO", "fields_update", session=sid, version=sess["version"], ms=ms)
        return self._send_json(200, result)

    def _handle_append_text(self, sid, body, owner_hash=None, ip_hash=None):
        """Append free text, extract without overwriting locked fields, create new version."""
        sess = store.get_session(sid, owner_hash=owner_hash, hosted=_is_hosted())
        if not sess:
            return self._send_json(404, {"error": "会话不存在", "category": "未找到"})

        extra = (body.get("text") or "").strip()
        if not extra:
            return self._send_json(400, {"error": "请输入要补充的内容", "category": "参数错误"})
        if len(extra) > 2000:
            return self._send_json(400, {"error": "补充内容过长（最多 2000 字）", "category": "参数错误"})

        using_byok, prov, byok_key, byok_model, err = self._extract_byok_headers()
        if err:
            return self._send_json(400, {"error": err, "category": "参数错误"})

        q_status = None
        if not using_byok:
            ok_q, q_status = self._reserve_hosted_quota(owner_hash, ip_hash)
            if not ok_q:
                return

        t0 = time.monotonic()
        if using_byok:
            api_key, fast_model, base_url, timeout_sec = byok_key, byok_model, None, 60
        else:
            api_key, _, fast_model, base_url, timeout_sec = get_llm_config()
            if _is_hosted():
                base_url = "https://generativelanguage.googleapis.com"
        registry = llm.load_fields_registry()
        fields_snapshot = dict(sess["fields"])
        combined_text = sess["session"]["raw_text"] + "\n\n补充说明：\n" + extra

        charged = _is_hosted() and not using_byok
        try:
            try:
                llm_raw = llm.call_model(
                    prov, api_key, fast_model, "extract", combined_text,
                    base_url=base_url, locked_fields=fields_snapshot, timeout_sec=min(timeout_sec, 60),
                )
            except llm.GeminiAPIError as ge:
                ms = int((time.monotonic() - t0) * 1000)
                log_event("ERROR", "append_text_fail", session=sid, length=len(extra), ms=ms, category=ge.category, provider=prov)
                return self._send_llm_error(ge, using_byok)

            with _get_session_lock(sid):
                latest_sess = store.get_session(sid, owner_hash=owner_hash, hosted=_is_hosted()) or sess
                fields_state = dict(latest_sess["fields"])
                new_verified, dropped = verify.verify_extracted(combined_text, llm_raw.get("extracted", []), registry, existing_fields=fields_state)
                for fid, nf in new_verified.items():
                    if fields_state.get(fid, {}).get("source") != "form":
                        fields_state[fid] = nf

                new_ver = latest_sess["version"] + 1
                decision = llm_raw.get("decision") or latest_sess["result"].get("decision", "")
                result = _build_result_object(sid, new_ver, decision, fields_state, registry, clarify=llm_raw.get("clarify", []), dropped=dropped)
                store.add_evaluation(sid, new_ver, fields_state, result, title=decision, raw_text=combined_text)

            usage = llm_raw.get("_usage") or {}
            ms = int((time.monotonic() - t0) * 1000)
            log_event("INFO", "append_text_ok", session=sid, version=new_ver, length=len(extra), ms=ms, provider=prov, tokens=usage.get("total_tokens", 0))
            if q_status is not None:
                result["quota"] = q_status
            charged = False
            return self._send_json(200, result)
        finally:
            if charged:
                quota.refund(owner_hash, ip_hash)

    def _handle_analysis(self, sid, owner_hash=None, ip_hash=None):
        """On-demand detailed analysis via LLM + lint."""
        sess = store.get_session(sid, owner_hash=owner_hash, hosted=_is_hosted())
        if not sess:
            return self._send_json(404, {"error": "会话不存在", "category": "未找到"})

        using_byok, prov, byok_key, byok_model, err = self._extract_byok_headers()
        if err:
            return self._send_json(400, {"error": err, "category": "参数错误"})

        q_status = None
        if not using_byok:
            ok_q, q_status = self._reserve_hosted_quota(owner_hash, ip_hash)
            if not ok_q:
                return

        t0 = time.monotonic()
        if using_byok:
            api_key, model, base_url, timeout_sec = byok_key, byok_model, None, 120
        else:
            api_key, model, _, base_url, timeout_sec = get_llm_config()
            if _is_hosted():
                base_url = "https://generativelanguage.googleapis.com"
        raw_text = sess["session"]["raw_text"]
        fields_state = dict(sess["fields"])
        fp_before = json.dumps(fields_state, sort_keys=True, ensure_ascii=False)
        registry = llm.load_fields_registry()
        res = _build_result_object(
            sid,
            sess["version"],
            sess["result"].get("decision", ""),
            fields_state,
            registry,
            clarify=sess["result"].get("clarify", []),
            dropped=sess["result"].get("lint", {}).get("dropped", []),
            analysis=sess.get("analysis"),
        )
        factors = res.get("factors", [])
        flags = res.get("flags", [])

        charged = _is_hosted() and not using_byok
        try:
            try:
                llm_raw = llm.call_model(
                    prov,
                    api_key,
                    model,
                    "analysis",
                    "请根据以上信息进行详细会诊分析。",
                    base_url=base_url,
                    analysis_ctx={
                        "raw_text": raw_text,
                        "fields_state": fields_state,
                        "factors": factors,
                        "flags": flags,
                        "synthesis": res.get("synthesis"),
                    },
                    timeout_sec=timeout_sec,
                )
            except llm.GeminiAPIError as ge:
                if charged:
                    quota.refund(owner_hash, ip_hash)
                    charged = False
                ms = int((time.monotonic() - t0) * 1000)
                log_event("ERROR", "analysis_fail", session=sid, ms=ms, category=ge.category, provider=prov)
                return self._send_llm_error(ge, using_byok)

            confirmed_nums = _confirmed_numbers(fields_state, factors)
            linted, _, hidden_count = verify.lint_output(raw_text, confirmed_nums, llm_raw, allow_hide=True)
            advisors_lib = llm.load_advisors_library()
            registry = llm.load_fields_registry()
            reg_map = {f["id"]: f for f in registry}
            llm_adv_map = {a.get("id"): a for a in linted.get("advisors", []) if isinstance(a, dict)}
            fac_map = {f["id"]: f for f in factors}
            excl_ids = {e["id"] for e in res.get("score", {}).get("excluded", [])}

            advisors_out = []
            for a in advisors_lib:
                aid = a["id"]
                la = llm_adv_map.get(aid, {})
                rated = bool(a.get("rated", True))
                if not rated:
                    rating, rule_note = "不参与", ""
                elif aid in excl_ids:
                    rating, rule_note = "不适用", ""
                else:
                    finfo = fac_map.get(aid, {})
                    rating = finfo.get("rating", "不适用")
                    rule_note = finfo.get("rule_note", "")

                missing_labels = []
                for fid in a.get("reads_fields", []):
                    fdef = reg_map.get(fid)
                    if not fdef or not fdef.get("ui_show", False):
                        continue
                    if not engine.is_field_applicable(fdef, fields_state):
                        continue
                    if fields_state.get(fid, {}).get("status") != "given":
                        missing_labels.append(fdef.get("ui_label") or fdef.get("label") or fid)
                    if len(missing_labels) >= 3:
                        break

                advisors_out.append({
                    "id": aid,
                    "name": a["name"],
                    "dimension": a.get("dimension", ""),
                    "rated": rated,
                    "rating": rating,
                    "rule_note": rule_note,
                    "insight": la.get("insight", ""),
                    "next_step": la.get("next_step", ""),
                    "missing": missing_labels,
                })

            analysis_obj = {
                "advisors": advisors_out,
                "critique": linted.get("critique", []),
                "two_week_checks": linted.get("two_week_checks", []),
                "validation_design": linted.get("validation_design", {"supply": [], "demand": [], "threshold": []}),
                "hidden_count": hidden_count,
                "generated_at": store.utcnow_iso(),
                "model": f"{prov} / {model}",
                "rules_version": score.RULES_VERSION,
            }
            with _get_session_lock(sid):
                latest_sess = store.get_session(sid) or sess
                fp_after = json.dumps(latest_sess["fields"], sort_keys=True, ensure_ascii=False)
                stale = fp_after != fp_before
                store.save_analysis(sid, analysis_obj)
                if stale:
                    store.update_latest_evaluation(sid, latest_sess["fields"], latest_sess["result"])

            usage = llm_raw.get("_usage") or {}
            ms = int((time.monotonic() - t0) * 1000)
            log_event("INFO", "analysis_ok", session=sid, ms=ms, stale=stale, provider=prov, tokens=usage.get("total_tokens", 0))
            resp_payload = {"analysis": analysis_obj, "stale": stale}
            if q_status is not None:
                resp_payload["quota"] = q_status
            charged = False
            return self._send_json(200, resp_payload)
        finally:
            if charged:
                quota.refund(owner_hash, ip_hash)

    def _handle_report(self, sid, fmt, owner_hash=None):
        sess = store.get_session(sid, owner_hash=owner_hash, hosted=_is_hosted())
        if not sess:
            return self._send_json(404, {"error": "会话不存在", "category": "未找到"})
        analysis = sess.get("analysis")
        if not analysis:
            return self._send_json(409, {"error": "尚未生成详细分析", "category": "未生成"})

        registry = llm.load_fields_registry()
        advisors = llm.load_advisors_library()
        result = sess["result"]
        stale = bool(sess.get("analysis_stale", False))

        if fmt == "fragment":
            frag = report.build_fragment(result, analysis, registry, advisors)
            return self._send_json(200, {
                "html": frag,
                "stale": stale,
                "generated_at": analysis.get("generated_at", "—"),
                "model": analysis.get("model", "—"),
            })

        now_str = time.strftime("%Y-%m-%d %H:%M")
        dt_file = time.strftime("%Y%m%d-%H%M")
        title = result.get("decision") or sess["session"].get("title") or "未命名"
        meta = {
            "title": title,
            "generated_at": now_str,
            "stale": stale,
            "raw_text": sess["session"].get("raw_text", ""),
            "fields_state": sess.get("fields", {}),
        }

        if fmt == "html":
            css_path = os.path.join(BASE_DIR, "report.css")
            with open(css_path, "r", encoding="utf-8") as f:
                css_text = f.read()
            body = report.build_full_html(result, analysis, registry, advisors, meta, css_text).encode("utf-8")
            ctype = "text/html; charset=utf-8"
            ext = "html"
        elif fmt == "md":
            body = report.build_markdown(result, analysis, registry, advisors, meta).encode("utf-8")
            ctype = "text/markdown; charset=utf-8"
            ext = "md"
        else:
            return self._send_json(400, {"error": "不支持的格式", "category": "参数错误"})

        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Disposition", report.safe_filename(title, dt_file, ext))
        self.end_headers()
        self.wfile.write(body)


class QuietThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True


def _cleanup_loop():
    while True:
        try:
            store.cleanup_expired_sessions(_retention_days())
            quota.cleanup_old_usage(30)
        except Exception:
            pass
        time.sleep(6 * 3600)


def validate_advisors_library(advisors):
    """Validate advisors library fields, uniqueness, and alignment with score constants."""
    import re
    import score as _score
    errors = []
    codes, seals, pinyins = set(), set(), set()
    rated_ids = set()
    valid_groups = set(_score.FACTOR_NAMES.values())
    html_re = re.compile(r"</?[a-zA-Z][^>]*>")
    for a in advisors:
        aid = a.get("id", "")
        for key, seen in (("code", codes), ("seal", seals), ("pinyin", pinyins)):
            val = a.get(key, "")
            if not val:
                errors.append(f"advisor {aid} missing {key}")
            elif val in seen:
                errors.append(f"duplicate {key}: {val}")
            seen.add(val)
        for text_key in ("code", "seal", "name", "ask", "watch", "rule_public"):
            val = a.get(text_key, "")
            if html_re.search(str(val)):
                errors.append(f"advisor {aid} {text_key} contains HTML")
        if a.get("rated"):
            rated_ids.add(aid)
            grp = a.get("group", "")
            if grp not in valid_groups:
                errors.append(f"advisor {aid} invalid group: {grp}")
            if not a.get("rule_public"):
                errors.append(f"advisor {aid} missing rule_public")
        for text_key in ("ask", "watch"):
            if not a.get(text_key):
                errors.append(f"advisor {aid} missing {text_key}")
    w_keys = set(_score.FACTOR_WEIGHTS.keys())
    kf_keys = set(_score.FACTOR_KEY_FIELDS.keys())
    fn_keys = set(_score.FACTOR_NAMES.keys())
    if rated_ids != w_keys or rated_ids != kf_keys or rated_ids != fn_keys:
        errors.append(f"rated_ids mismatch: {rated_ids} vs {w_keys}")
    return errors


def main():
    if _is_hosted() and not os.environ.get("QUOTA_SALT"):
        log_event("ERROR", "missing_quota_salt_in_hosted_mode")
        sys.exit(1)
    if _is_hosted() and not _allowed_hosts():
        log_event("ERROR", "missing_allowed_hosts_in_hosted_mode")
        sys.exit(1)
    if _is_hosted() and os.environ.get("TRUST_PROXY") != "1":
        log_event("WARN", "hosted_mode_without_trust_proxy_all_users_may_share_proxy_ip")
    store.init_db()
    if _is_hosted() or os.environ.get("RETENTION_DAYS"):
        threading.Thread(target=_cleanup_loop, daemon=True).start()
    reg_ids = {f["id"] for f in llm.load_fields_registry()}
    advisors_lib = llm.load_advisors_library()
    for err in validate_advisors_library(advisors_lib):
        log_event("WARN", f"advisor_validation {err}")
    for a in advisors_lib:
        for fid in a.get("reads_fields", []):
            if fid not in reg_ids:
                log_event("WARN", f"unknown_reads_field advisor={a.get('id')} field={fid}")
    env = load_env()
    host = os.environ.get("HOST") or env.get("HOST", "127.0.0.1")
    port = int(os.environ.get("PORT") or env.get("PORT", "8100"))
    server = QuietThreadingHTTPServer((host, port), AppHandler)
    log_event("INFO", f"server_started http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
