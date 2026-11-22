"""Shared backend core for CCagent thinking-model agents (agent4, agent5, agent6)."""

import json
import os
import re
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler

PARENT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(PARENT_DIR, ".env")

_ENV_KEYS = (
    "LLM_PROVIDER",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FAST_MODEL", "GEMINI_BASE_URL", "GEMINI_TIMEOUT",
    "XAI_API_KEY", "XAI_MODEL", "XAI_BASE_URL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL",
    "HOSTED", "ALLOWED_ORIGINS",
)


def utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_env_file():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    env[k.strip()] = v.strip()
    return env


def load_env():
    env = _read_env_file()
    for k in _ENV_KEYS:
        val = os.environ.get(k)
        if val:
            env[k] = val
    return env


def save_env(updates):
    current = _read_env_file()
    current.update(updates)
    lines = ["# CCagent 配置文件"]
    for k, v in current.items():
        lines.append(f"{k}={v}")
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def resolve_llm_config(body=None):
    body = body or {}
    env = load_env()
    provider = (body.get("provider") or env.get("LLM_PROVIDER") or "gemini").strip().lower()
    if provider not in ("gemini", "xai", "deepseek"):
        provider = "gemini"

    raw_key = (body.get("api_key") or "").strip()
    if raw_key and raw_key != "server-configured" and "..." not in raw_key:
        api_key = raw_key
    else:
        key_map = {
            "gemini": "GEMINI_API_KEY",
            "xai": "XAI_API_KEY",
            "deepseek": "DEEPSEEK_API_KEY",
        }
        api_key = env.get(key_map[provider], "").strip()

    default_models = {
        "gemini": env.get("GEMINI_MODEL") or "gemini-3.5-flash-lite",
        "xai": env.get("XAI_MODEL") or "grok-3-mini",
        "deepseek": env.get("DEEPSEEK_MODEL") or "deepseek-chat",
    }
    default_urls = {
        "gemini": env.get("GEMINI_BASE_URL") or "https://generativelanguage.googleapis.com",
        "xai": env.get("XAI_BASE_URL") or "https://api.x.ai",
        "deepseek": env.get("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    }

    model = (body.get("model") or default_models[provider]).strip()
    base_url = (body.get("base_url") or default_urls[provider]).strip().rstrip("/")
    timeout = int(env.get("GEMINI_TIMEOUT") or 60)
    return {
        "provider": provider,
        "api_key": api_key,
        "model": model,
        "base_url": base_url,
        "timeout": timeout,
    }


def extract_json_block(text):
    text = (text or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*```$", "", text)
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{[\s\S]*\}", text)
        if m:
            return json.loads(m.group(0))
        raise ValueError("模型未返回合法 JSON")


def call_llm_json(prompt, cfg, temperature=0.3, max_tokens=2000, tag="ThinkingAgent"):
    if not cfg["api_key"]:
        raise RuntimeError("未配置 API Key")

    provider = cfg["provider"]
    model = cfg["model"]
    base_url = cfg["base_url"]
    timeout = cfg["timeout"]

    if provider == "gemini":
        url = f"{base_url}/v1beta/models/{model}:generateContent?key={urllib.parse.quote(cfg['api_key'])}"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            },
        }
        headers = {"Content-Type": "application/json"}
    else:
        url = f"{base_url}/v1/chat/completions" if not base_url.endswith("/v1") else f"{base_url}/chat/completions"
        if provider == "deepseek" and "/v1" not in base_url:
            url = f"{base_url}/chat/completions"
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg['api_key']}",
        }

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    last_err = None
    for attempt in range(3):
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
            obj = json.loads(raw)
            if provider == "gemini":
                text = obj["candidates"][0]["content"]["parts"][0]["text"]
            else:
                text = obj["choices"][0]["message"]["content"]
            return extract_json_block(text)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_err = RuntimeError(f"HTTP {e.code}: {err_body}")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                print(f"[{tag}Retry] {provider} HTTP {e.code}, retry {attempt + 1}", flush=True)
                time.sleep(1.8 * (attempt + 1))
                continue
            print(f"[{tag}Error] {provider} HTTP {e.code}: {err_body}", flush=True)
            raise last_err
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5)
                continue
            print(f"[{tag}Error] {provider}: {e}", flush=True)
            raise last_err
    raise last_err


def init_sqlite(db_path):
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            raw_text TEXT DEFAULT '',
            fields_json TEXT DEFAULT '{}',
            result_json TEXT NOT NULL,
            engine TEXT DEFAULT 'ai',
            model TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def make_handler(
    *,
    base_dir,
    db_path,
    tag,
    advisors,
    fields_schema,
    extract_fn,
    fallback_extract_fn,
    generate_fn,
    fallback_generate_fn,
):
    allowed_static = {"index.html", "style.css", "app.js"}

    class ThinkingRequestHandler(SimpleHTTPRequestHandler):
        def log_message(self, format, *args):
            pass

        def _send_json(self, status_code, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status_code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _read_json(self):
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0:
                return {}
            return json.loads(self.rfile.read(length).decode("utf-8"))

        def _serve_static(self, filename):
            filepath = os.path.join(base_dir, filename)
            if not os.path.isfile(filepath):
                self.send_error(404, "Not Found")
                return
            ext = os.path.splitext(filename)[1].lower()
            ctype = {
                ".html": "text/html; charset=utf-8",
                ".css": "text/css; charset=utf-8",
                ".js": "application/javascript; charset=utf-8",
            }.get(ext, "application/octet-stream")
            with open(filepath, "rb") as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html"):
                return self._serve_static("index.html")
            if path.lstrip("/") in allowed_static:
                return self._serve_static(path.lstrip("/"))

            if path == "/api/config":
                env = load_env()
                cfg = resolve_llm_config()
                return self._send_json(200, {
                    "hosted": env.get("HOSTED") == "1",
                    "provider": cfg["provider"],
                    "model": cfg["model"],
                    "base_url": cfg["base_url"],
                    "has_key": bool(cfg["api_key"]),
                })

            if path == "/api/council":
                return self._send_json(200, {
                    "advisors": advisors,
                    "fields_schema": fields_schema,
                })

            if path == "/api/history":
                conn = sqlite3.connect(db_path)
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT id, title, summary, raw_text, fields_json, result_json, engine, model, created_at "
                    "FROM records ORDER BY id DESC LIMIT 30"
                ).fetchall()
                conn.close()
                items = [
                    {
                        "id": r["id"],
                        "title": r["title"],
                        "summary": r["summary"],
                        "raw_text": r["raw_text"],
                        "fields": json.loads(r["fields_json"] or "{}"),
                        "result": json.loads(r["result_json"] or "{}"),
                        "engine": r["engine"],
                        "model": r["model"],
                        "created_at": r["created_at"],
                    }
                    for r in rows
                ]
                return self._send_json(200, {"items": items})

            return self._send_json(404, {"error": "Not Found"})

        def do_DELETE(self):
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/api/history/"):
                raw_id = path[len("/api/history/"):].strip("/")
                if raw_id.isdigit():
                    conn = sqlite3.connect(db_path)
                    conn.execute("DELETE FROM records WHERE id = ?", (int(raw_id),))
                    conn.commit()
                    conn.close()
                    return self._send_json(200, {"ok": True})
            return self._send_json(404, {"error": "Not Found"})

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            try:
                body = self._read_json()
            except Exception:
                return self._send_json(400, {"error": "请求体 JSON 格式错误"})

            if path == "/api/save-config":
                env = load_env()
                if env.get("HOSTED") == "1":
                    return self._send_json(403, {"error": "公网托管模式下不支持修改服务端配置。"})
                provider = (body.get("provider") or "gemini").strip().lower()
                updates = {"LLM_PROVIDER": provider}
                key = (body.get("api_key") or "").strip()
                model = (body.get("model") or "").strip()
                base_url = (body.get("base_url") or "").strip()
                prefix = {"gemini": "GEMINI", "xai": "XAI", "deepseek": "DEEPSEEK"}.get(provider, "GEMINI")
                if key:
                    updates[f"{prefix}_API_KEY"] = key
                if model:
                    updates[f"{prefix}_MODEL"] = model
                if base_url:
                    updates[f"{prefix}_BASE_URL"] = base_url
                save_env(updates)
                return self._send_json(200, {"ok": True})

            if path == "/api/test-connection":
                cfg = resolve_llm_config(body)
                if not cfg["api_key"]:
                    return self._send_json(400, {"ok": False, "error": "未配置 API Key"})
                try:
                    res = call_llm_json('请返回JSON：{"ok": true, "msg": "connected"}', cfg, temperature=0, max_tokens=60, tag=tag)
                    return self._send_json(200, {"ok": True, "provider": cfg["provider"], "model": cfg["model"], "reply": res})
                except Exception as e:
                    return self._send_json(200, {"ok": False, "error": str(e)})

            if path == "/api/extract":
                raw_text = (body.get("raw_text") or "").strip()
                if not raw_text:
                    return self._send_json(400, {"error": "请先输入要分析的内容"})
                cfg = resolve_llm_config(body)
                engine_used = "ai"
                fallback_reason = ""
                try:
                    extracted = extract_fn(raw_text, cfg)
                except Exception as e:
                    engine_used = "fallback"
                    fallback_reason = "服务繁忙，已使用本地结构化模板" if "503" in str(e) or "429" in str(e) else f"AI暂不可用（{e}）"
                    extracted = fallback_extract_fn(raw_text)
                return self._send_json(200, {
                    **extracted,
                    "engine": engine_used,
                    "model": cfg["model"],
                    "fallback_reason": fallback_reason,
                })

            if path == "/api/generate":
                raw_text = (body.get("raw_text") or "").strip()
                fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
                if not raw_text and not any((v or "").strip() for v in fields.values()):
                    return self._send_json(400, {"error": "请至少填写核心分析对象"})
                cfg = resolve_llm_config(body)
                engine_used = "ai"
                fallback_reason = ""
                try:
                    result = generate_fn(raw_text, fields, cfg)
                except Exception as e:
                    engine_used = "fallback"
                    fallback_reason = "服务繁忙，已启用规则保底分析" if "503" in str(e) or "429" in str(e) else f"AI暂不可用（{e}）"
                    result = fallback_generate_fn(raw_text, fields)

                now = utc_now_iso()
                conn = sqlite3.connect(db_path)
                cur = conn.cursor()
                cur.execute(
                    "INSERT INTO records (title, summary, raw_text, fields_json, result_json, engine, model, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        result.get("title", "思维模型分析"),
                        result.get("summary", ""),
                        raw_text,
                        json.dumps(fields, ensure_ascii=False),
                        json.dumps(result, ensure_ascii=False),
                        engine_used,
                        cfg["model"],
                        now,
                    ),
                )
                rec_id = cur.lastrowid
                conn.commit()
                conn.close()

                return self._send_json(200, {
                    "id": rec_id,
                    "result": result,
                    "engine": engine_used,
                    "model": cfg["model"],
                    "fallback_reason": fallback_reason,
                    "created_at": now,
                })

            return self._send_json(404, {"error": "Not Found"})

    return ThinkingRequestHandler
