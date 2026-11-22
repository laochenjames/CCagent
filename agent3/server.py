"""HTTP server for CCagent Agent3: 原子习惯生成 (Atomic Habit Generator)."""

import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
ENV_FILE = os.path.join(PARENT_DIR, ".env")
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "habit.db")

ALLOWED_STATIC_FILES = {"index.html", "style.css", "app.js"}

_ENV_KEYS = (
    "LLM_PROVIDER",
    "GEMINI_API_KEY", "GEMINI_MODEL", "GEMINI_FAST_MODEL", "GEMINI_BASE_URL", "GEMINI_TIMEOUT",
    "XAI_API_KEY", "XAI_MODEL", "XAI_BASE_URL",
    "DEEPSEEK_API_KEY", "DEEPSEEK_MODEL", "DEEPSEEK_BASE_URL",
    "HOSTED", "ALLOWED_ORIGINS",
)

COUNCIL_ADVISORS = [
    {
        "id": "trigger",
        "name": "触发设计师",
        "tag": "两分钟法则 · 环境提示",
        "principle": "第一步必须小到“完全没有理由拒绝”，先建立环境与触发锚点，再要求行为。",
        "focus": "把模糊意愿绑定到每天必做的已有动作上，并将启动阻力压缩到 2 分钟以内。",
    },
    {
        "id": "ladder",
        "name": "阶梯架构师",
        "tag": "3~5 步递进 · 心流爬坡",
        "principle": "难度递进要小，让大脑在每次打卡时都能获得确定、可持续的成就感。",
        "focus": "把大目标拆成 3~5 个清晰递进的原子节点，每个节点说清做什么、怎么算完成、为什么。",
    },
    {
        "id": "resilience",
        "name": "防崩盘顾问",
        "tag": "低电量保底 · 永不连续断签",
        "principle": "放弃往往发生在最累的那一天，而不是最难的那一步；保底动作决定习惯寿命。",
        "focus": "提前识别最容易断签的场景，设计状态极差时也能 100% 完成的最小保底版本。",
    },
    {
        "id": "identity",
        "name": "身份教练",
        "tag": "身份投票 · 正向反馈",
        "principle": "摆脱“全有或全无”的强迫思维，哪怕只完成第一步，也是对新身份的一次投票。",
        "focus": "用清晰的完成标准替代模糊的自律口号，把外部强迫转化为内在身份认同。",
    },
]

FORM_FIELDS_SCHEMA = [
    {"key": "habit_goal", "group": "场景与触发", "label": "核心习惯目标", "placeholder": "例如：每天晨间阅读、坚持有氧运动、睡前复盘"},
    {"key": "trigger_anchor", "group": "场景与触发", "label": "触发锚点（已有习惯）", "placeholder": "例如：早起刷完牙后、晚饭洗完碗后、合上电脑时"},
    {"key": "time_window", "group": "场景与触发", "label": "固定时间与可用时长", "placeholder": "例如：早上 7:00–7:20，最多 20 分钟"},
    {"key": "environment", "group": "场景与触发", "label": "执行环境与准备物品", "placeholder": "例如：睡前把书翻开放在书桌上 / 门口放好跑鞋"},
    {"key": "current_level", "group": "阻力与身份", "label": "当前基础/现状", "placeholder": "例如：几乎没开始过 / 之前坚持过一周但断了"},
    {"key": "main_obstacle", "group": "阻力与身份", "label": "最大阻碍/断签原因", "placeholder": "例如：下班太累只想刷手机 / 一起步定太高"},
    {"key": "identity", "group": "阻力与身份", "label": "想成为的身份", "placeholder": "例如：一个每天保持输入和思考的终身学习者"},
    {"key": "fallback_action", "group": "阻力与身份", "label": "低电量保底动作（2分钟）", "placeholder": "例如：实在太累时，只翻开书读 1 段话也算完成"},
]


def _utc_now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def init_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT DEFAULT '',
            raw_text TEXT DEFAULT '',
            fields_json TEXT DEFAULT '{}',
            plan_json TEXT NOT NULL,
            engine TEXT DEFAULT 'ai',
            model TEXT DEFAULT '',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


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


def _resolve_llm_config(body=None):
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


def _extract_json_block(text):
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


def _call_llm_json(prompt, cfg, temperature=0.3, max_tokens=1600):
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
            return _extract_json_block(text)
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8", errors="replace")[:300]
            except Exception:
                pass
            last_err = RuntimeError(f"HTTP {e.code}: {err_body}")
            if e.code in (429, 500, 502, 503, 504) and attempt < 2:
                print(f"[Agent3Retry] {provider} HTTP {e.code}, retry {attempt + 1}", flush=True)
                time.sleep(1.8 * (attempt + 1))
                continue
            print(f"[Agent3Error] {provider} HTTP {e.code}: {err_body}", flush=True)
            raise last_err
        except Exception as e:
            last_err = e
            if attempt < 2:
                time.sleep(1.5)
                continue
            print(f"[Agent3Error] {provider}: {e}", flush=True)
            raise last_err
    raise last_err


def _compute_completeness(fields):
    keys = [f["key"] for f in FORM_FIELDS_SCHEMA]
    filled = sum(1 for k in keys if (fields.get(k) or "").strip())
    pct = round(filled * 100 / len(keys))
    missing = [f["label"] for f in FORM_FIELDS_SCHEMA if not (fields.get(f["key"]) or "").strip()]
    return pct, missing


def _fallback_extract(raw_text):
    clean = (raw_text or "").strip()
    first_line = clean.splitlines()[0].strip() if clean else "每日微习惯"
    goal = first_line[:24]
    fields = {
        "habit_goal": goal,
        "trigger_anchor": "",
        "time_window": "",
        "environment": "",
        "current_level": "",
        "main_obstacle": "",
        "identity": "",
        "fallback_action": "",
    }
    pct, missing = _compute_completeness(fields)
    return {
        "fields": fields,
        "completeness": pct,
        "missing_hints": missing[:3],
        "summary_note": "已提取基础目标，请补充下方空白项（尤其是触发锚点和最大阻碍），智囊团会据此生成更贴合你的原子习惯。",
    }


def _fallback_generate(raw_text, fields):
    goal = (fields.get("habit_goal") or raw_text or "每日微习惯").strip()[:10] or "每日微习惯"
    anchor = (fields.get("trigger_anchor") or "每天固定完成一个日常动作后").strip()
    fallback_act = (fields.get("fallback_action") or f"用 2 分钟完成「{goal}」的最小准备动作").strip()
    identity = (fields.get("identity") or f"一个持续践行「{goal}」的人").strip()
    return {
        "name": goal,
        "description": f"以两分钟极低阻力启动，逐步建立「{goal}」的稳定节律。",
        "identity_statement": f"每一次完成起步动作，都是对「{identity}」身份的一次投票。",
        "trigger_formula": f"当「{anchor}」时，我立刻执行第 1 步启动动作。",
        "fallback_plan": fallback_act,
        "subNodes": [
            {
                "name": "两分钟启动",
                "level": "启动层",
                "description": f"在「{anchor}」后立刻准备好所需物品并进入状态，做完即算完成，目的是把启动阻力降到零。",
            },
            {
                "name": "微动作3分钟",
                "level": "微动作",
                "description": f"围绕「{goal}」执行最轻松的 3 分钟核心动作，不追求完美，只让大脑熟悉切换节奏。",
            },
            {
                "name": "专注10分钟",
                "level": "稳定层",
                "description": f"设定 10 分钟计时器专注推进「{goal}」，时间到即可停下，用于建立固定时间窗口。",
            },
            {
                "name": "完整执行25分钟",
                "level": "进阶层",
                "description": f"进入稳定心流状态，完成一轮完整的「{goal}」练习并简单记录完成感，巩固长期习惯。",
            },
        ],
        "council_synthesis": {
            "consensus": f"先用「{anchor}」把启动阻力压到两分钟以内，前两周只追求不断签，不追求单次满配。",
            "tension": "阶梯架构师希望两周后稳步拉升时长，防崩盘顾问则提醒遇到高负荷日必须立刻降级保底。",
        },
        "council_notes": [
            {
                "id": "trigger",
                "name": "触发设计师",
                "role": "环境与启动设计",
                "stance": "强化触发",
                "verdict": f"把触发点锁死在「{anchor}」，避免靠意志力临时决定。",
                "action": "今晚就把明天第 1 步要用的物品放到触手可及的位置。",
            },
            {
                "id": "ladder",
                "name": "阶梯架构师",
                "role": "难度阶梯规划",
                "stance": "渐进爬坡",
                "verdict": "前两周只求稳稳完成第 1~2 层，不要一上来就冲刺满配时长。",
                "action": "连续完成 7 天第 1~2 层后，再尝试进入下一阶。",
            },
            {
                "id": "resilience",
                "name": "防崩盘顾问",
                "role": "断签风险与保底",
                "stance": "风险预警",
                "verdict": f"状态差时直接切到保底动作：{fallback_act}，绝不连续两天中断。",
                "action": "把 2 分钟保底动作写进打卡备注，低电量日直接执行。",
            },
            {
                "id": "identity",
                "name": "身份教练",
                "role": "身份认同与反馈",
                "stance": "正向锚定",
                "verdict": f"哪怕今天只完成了第 1 步，也在为「{identity}」投下真实一票。",
                "action": "每次打卡后默念一句身份宣言，强化正向心理闭环。",
            },
        ],
    }


def _extract_fields_with_ai(raw_text, cfg):
    prompt = f"""你是原子习惯结构化抽取助手。请根据用户的原始输入，提取出能帮助设计原子习惯的关键字段。
只提取用户明确提到或能合理直接归纳的内容，未提到的字段务必留空字符串 ""，不要编造。

用户输入：
{raw_text}

请只返回 JSON，格式如下：
{{
  "fields": {{
    "habit_goal": "核心习惯目标（简短明确，如：每天晨间阅读）",
    "trigger_anchor": "触发锚点（在什么已有日常行为之后做，未提及则留空）",
    "time_window": "固定时间与可用时长（未提及则留空）",
    "environment": "执行环境与准备物品（未提及则留空）",
    "current_level": "当前基础或现状（未提及则留空）",
    "main_obstacle": "最大阻碍或过去放弃的原因（未提及则留空）",
    "identity": "想成为的身份或深层动机（未提及则留空）",
    "fallback_action": "状态差时的2分钟保底动作（未提及则留空）"
  }},
  "summary_note": "一句话温和提示用户最值得补充哪 1~2 项信息（35字以内）"
}}"""
    parsed = _call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900)
    raw_fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(raw_fields.get(f["key"]) or "").strip() for f in FORM_FIELDS_SCHEMA}
    pct, missing = _compute_completeness(fields)
    return {
        "fields": fields,
        "completeness": pct,
        "missing_hints": missing[:3],
        "summary_note": str(parsed.get("summary_note") or "").strip() or "信息已初步提取，补充空白项后分解效果会更精准。",
    }


def _generate_plan_with_ai(raw_text, fields, cfg):
    field_lines = []
    for f in FORM_FIELDS_SCHEMA:
        val = (fields.get(f["key"]) or "").strip()
        field_lines.append(f"- {f['label']}：{val if val else '（未填写，请合理建议）'}")
    fields_text = "\n".join(field_lines)

    prompt = f"""你是 CCagent 的「原子习惯智囊团」，由 4 位专家组成：
1. 触发设计师（两分钟法则、环境与触发锚点、启动阻力归零）
2. 阶梯架构师（3~5 个难度递进的原子节点）
3. 防崩盘顾问（识别断签风险、低电量保底动作）
4. 身份教练（身份投票、清晰完成标准、正向反馈）

请结合用户原始描述与完善后的表单，生成一套极易上手、可直接打卡的原子习惯方案。

用户原始输入：
{raw_text}

用户完善的习惯信息表：
{fields_text}

核心要求（必须严格遵守）：
- 忠实结合用户填写的场景、时间、阻碍与现状，不要空泛说教
- subNodes 数量为 3~5 个，难度严格递进（从极易启动到稳定心流）
- 第 1 个节点必须是启动阻力最低的准备/触发动作（两分钟法则，小到“完全没有理由拒绝”）
- 每个节点的 description 必须说清楚：做什么、怎么算完成、为什么（30~60字）
- 4 位智囊各给出 1 句针对该用户具体情况的犀利建议（25~45字）

只返回 JSON，不要任何多余文字，格式如下：
{{
  "name": "习惯名称，10字以内",
  "description": "一句话核心思路，25字以内",
  "identity_statement": "一句身份投票宣言，30字以内",
  "trigger_formula": "当[具体锚点]时，我立刻[第1步微动作]",
  "fallback_plan": "状态最差时的2分钟防崩盘保底动作（30字以内）",
  "subNodes": [
    {{
      "name": "节点名称，10字以内",
      "level": "启动层",
      "description": "详细说明：做什么、怎么算完成、为什么（30~60字）"
    }}
  ],
  "council_synthesis": {{
    "consensus": "4 位智囊围绕该习惯达成的核心共识（30~50字）",
    "tension": "智囊之间最关键的张力或提醒（如稳步进阶 vs 防止断签，30~50字）"
  }},
  "council_notes": [
    {{ "id": "trigger", "name": "触发设计师", "role": "环境与启动设计", "stance": "强化触发", "verdict": "一句话核心判断（25~45字）", "action": "今天即可落地的具体微动作（20~35字）" }},
    {{ "id": "ladder", "name": "阶梯架构师", "role": "难度阶梯规划", "stance": "渐进爬坡", "verdict": "...", "action": "..." }},
    {{ "id": "resilience", "name": "防崩盘顾问", "role": "断签风险与保底", "stance": "风险预警", "verdict": "...", "action": "..." }},
    {{ "id": "identity", "name": "身份教练", "role": "身份认同与反馈", "stance": "正向锚定", "verdict": "...", "action": "..." }}
  ]
}}"""
    parsed = _call_llm_json(prompt, cfg, temperature=0.35, max_tokens=1800)
    if not parsed.get("name") or not isinstance(parsed.get("subNodes"), list) or len(parsed["subNodes"]) == 0:
        raise ValueError("模型返回的原子习惯结构不完整")
    return parsed


class HabitRequestHandler(SimpleHTTPRequestHandler):
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
        raw = self.rfile.read(length)
        return json.loads(raw.decode("utf-8"))

    def _serve_static(self, filename):
        filepath = os.path.join(BASE_DIR, filename)
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
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path

        if path in ("/", "/index.html"):
            return self._serve_static("index.html")
        if path.lstrip("/") in ALLOWED_STATIC_FILES:
            return self._serve_static(path.lstrip("/"))

        if path == "/api/config":
            env = load_env()
            cfg = _resolve_llm_config()
            return self._send_json(200, {
                "hosted": env.get("HOSTED") == "1",
                "provider": cfg["provider"],
                "model": cfg["model"],
                "base_url": cfg["base_url"],
                "has_key": bool(cfg["api_key"]),
            })

        if path == "/api/council":
            return self._send_json(200, {
                "advisors": COUNCIL_ADVISORS,
                "fields_schema": FORM_FIELDS_SCHEMA,
            })

        if path == "/api/history":
            conn = sqlite3.connect(DB_PATH)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, name, description, raw_text, fields_json, plan_json, engine, model, created_at "
                "FROM plans ORDER BY id DESC LIMIT 30"
            ).fetchall()
            conn.close()
            items = []
            for r in rows:
                items.append({
                    "id": r["id"],
                    "name": r["name"],
                    "description": r["description"],
                    "raw_text": r["raw_text"],
                    "fields": json.loads(r["fields_json"] or "{}"),
                    "plan": json.loads(r["plan_json"] or "{}"),
                    "engine": r["engine"],
                    "model": r["model"],
                    "created_at": r["created_at"],
                })
            return self._send_json(200, {"items": items})

        return self._send_json(404, {"error": "Not Found"})

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        if path.startswith("/api/history/"):
            raw_id = path[len("/api/history/"):].strip("/")
            if raw_id.isdigit():
                conn = sqlite3.connect(DB_PATH)
                conn.execute("DELETE FROM plans WHERE id = ?", (int(raw_id),))
                conn.commit()
                conn.close()
                return self._send_json(200, {"ok": True})
        return self._send_json(404, {"error": "Not Found"})

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
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
            if provider == "gemini":
                if key:
                    updates["GEMINI_API_KEY"] = key
                if model:
                    updates["GEMINI_MODEL"] = model
                if base_url:
                    updates["GEMINI_BASE_URL"] = base_url
            elif provider == "xai":
                if key:
                    updates["XAI_API_KEY"] = key
                if model:
                    updates["XAI_MODEL"] = model
                if base_url:
                    updates["XAI_BASE_URL"] = base_url
            elif provider == "deepseek":
                if key:
                    updates["DEEPSEEK_API_KEY"] = key
                if model:
                    updates["DEEPSEEK_MODEL"] = model
                if base_url:
                    updates["DEEPSEEK_BASE_URL"] = base_url
            save_env(updates)
            return self._send_json(200, {"ok": True})

        if path == "/api/test-connection":
            cfg = _resolve_llm_config(body)
            if not cfg["api_key"]:
                return self._send_json(400, {"ok": False, "error": "未配置 API Key"})
            try:
                res = _call_llm_json('请返回JSON：{"ok": true, "msg": "connected"}', cfg, temperature=0, max_tokens=60)
                return self._send_json(200, {"ok": True, "provider": cfg["provider"], "model": cfg["model"], "reply": res})
            except Exception as e:
                return self._send_json(200, {"ok": False, "error": str(e)})

        if path == "/api/extract":
            raw_text = (body.get("raw_text") or "").strip()
            if not raw_text:
                return self._send_json(400, {"error": "请先输入你想养成的习惯或目标"})
            cfg = _resolve_llm_config(body)
            engine_used = "ai"
            fallback_reason = ""
            try:
                result = _extract_fields_with_ai(raw_text, cfg)
            except Exception as e:
                engine_used = "fallback"
                fallback_reason = "服务繁忙，已使用本地结构化模板" if "503" in str(e) or "429" in str(e) else f"AI暂不可用（{e}）"
                result = _fallback_extract(raw_text)
            return self._send_json(200, {
                **result,
                "engine": engine_used,
                "model": cfg["model"],
                "fallback_reason": fallback_reason,
            })

        if path == "/api/generate":
            raw_text = (body.get("raw_text") or "").strip()
            fields = body.get("fields") if isinstance(body.get("fields"), dict) else {}
            if not raw_text and not any((v or "").strip() for v in fields.values()):
                return self._send_json(400, {"error": "请至少填写核心习惯目标"})
            cfg = _resolve_llm_config(body)
            engine_used = "ai"
            fallback_reason = ""
            try:
                plan = _generate_plan_with_ai(raw_text, fields, cfg)
            except Exception as e:
                engine_used = "fallback"
                fallback_reason = "服务繁忙，已启用规则保底拆解" if "503" in str(e) or "429" in str(e) else f"AI暂不可用（{e}）"
                plan = _fallback_generate(raw_text, fields)

            now = _utc_now_iso()
            conn = sqlite3.connect(DB_PATH)
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO plans (name, description, raw_text, fields_json, plan_json, engine, model, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    plan.get("name", "原子习惯"),
                    plan.get("description", ""),
                    raw_text,
                    json.dumps(fields, ensure_ascii=False),
                    json.dumps(plan, ensure_ascii=False),
                    engine_used,
                    cfg["model"],
                    now,
                ),
            )
            plan_id = cur.lastrowid
            conn.commit()
            conn.close()

            return self._send_json(200, {
                "id": plan_id,
                "plan": plan,
                "engine": engine_used,
                "model": cfg["model"],
                "fallback_reason": fallback_reason,
                "created_at": now,
            })

        return self._send_json(404, {"error": "Not Found"})


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", "8103"))
    srv = ThreadingHTTPServer(("127.0.0.1", port), HabitRequestHandler)
    print(f"Agent3 running at http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
