"""Gemini API client, prompt assembly, schemas, error classification, and retry."""

import json
import logging
import os
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PROMPTS_DIR = os.path.join(BASE_DIR, "prompts")
EXTRACT_PROMPT_FILE = os.path.join(PROMPTS_DIR, "extract_prompt.md")
ANALYSIS_PROMPT_FILE = os.path.join(PROMPTS_DIR, "analysis_prompt.md")
ADVISORY_FILE = os.path.join(PROMPTS_DIR, "advisory_career.json")
FIELDS_FILE = os.path.join(PROMPTS_DIR, "fields_career.json")


class GeminiAPIError(Exception):
    """Structured error for Gemini API calls."""

    def __init__(self, category, message, status_code=None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code


LLMError = GeminiAPIError


_FIELDS_CACHE = {"mtime": None, "data": None}
_ADVISORS_CACHE = {"mtime": None, "data": None}


def load_fields_registry():
    """Load fields_career.json with mtime-based memory cache."""
    mtime = os.path.getmtime(FIELDS_FILE)
    if _FIELDS_CACHE["data"] is not None and _FIELDS_CACHE["mtime"] == mtime:
        return _FIELDS_CACHE["data"]
    with open(FIELDS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    _FIELDS_CACHE["mtime"] = mtime
    _FIELDS_CACHE["data"] = data
    return data


def load_advisors_library():
    """Load advisory_career.json with mtime-based memory cache."""
    mtime = os.path.getmtime(ADVISORY_FILE)
    if _ADVISORS_CACHE["data"] is not None and _ADVISORS_CACHE["mtime"] == mtime:
        return _ADVISORS_CACHE["data"]
    with open(ADVISORY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    _ADVISORS_CACHE["mtime"] = mtime
    _ADVISORS_CACHE["data"] = data
    return data


def sanitize_model(model):
    """Sanitize model name."""
    m = (model or "gemini-3.5-flash").strip()
    return "".join(c for c in m if c.isalnum() or c in "-._") or "gemini-3.5-flash"


def validate_base_url(url):
    """Allow https:// or local http://127.0.0.1 / localhost."""
    u = (url or "").strip()
    if u.startswith("https://"):
        return True
    if u.startswith("http://127.0.0.1") or u.startswith("http://localhost"):
        return True
    return False


def build_fields_index(registry):
    """Format fields registry for {{FIELDS_INDEX}}."""
    lines = []
    for f in registry:
        choices = ""
        if f.get("choices"):
            choices = ",".join(f"{c['value']}({c['label']})" for c in f["choices"])
        elif f.get("item_fields"):
            choices = ",".join(f"{it['key']}:{it['type']}" for it in f["item_fields"])
        lines.append(f"{f['id']}｜{f['label']}｜{f['type']}｜{f.get('unit', '')}｜{choices}")
    return "\n".join(lines)


def build_advisors_index(advisors):
    """Format advisors library for {{ADVISORS_INDEX}}."""
    lines = []
    for a in advisors:
        lines.append(
            f"{a['id']}｜{a['name']}｜{a['dimension']}｜{a['common_pitfall']}｜{a['advice_style']}"
        )
    return "\n".join(lines)


def build_locked_fields_text(locked_fields):
    """Format locked fields for {{LOCKED_FIELDS}}."""
    if not locked_fields:
        return "（无）"
    lines = []
    for fid, f in locked_fields.items():
        if f.get("source") == "form" and f.get("status") == "given":
            lines.append(f"{fid}={f.get('value')}（{f.get('category', '自报')}）")
    return "\n".join(lines) if lines else "（无）"


def build_extract_prompt(locked_fields=None):
    """Assemble system prompt for fast extraction."""
    with open(EXTRACT_PROMPT_FILE, "r", encoding="utf-8") as f:
        tpl = f.read()
    registry = load_fields_registry()
    prompt = tpl.replace("{{FIELDS_INDEX}}", build_fields_index(registry))
    prompt = prompt.replace("{{LOCKED_FIELDS}}", build_locked_fields_text(locked_fields))
    return prompt


def build_analysis_prompt(raw_text, fields_state, factors, flags, synthesis=None):
    """Assemble system prompt for on-demand detailed analysis."""
    with open(ANALYSIS_PROMPT_FILE, "r", encoding="utf-8") as f:
        tpl = f.read()
    registry = load_fields_registry()
    advisors = load_advisors_library()

    facts_lines = []
    for fdef in registry:
        fid = fdef["id"]
        st = fields_state.get(fid, {})
        if st.get("status") == "given":
            facts_lines.append(f"{fid}｜{fdef['label']}｜{st.get('value')}｜{st.get('category', '自报')}")
        else:
            facts_lines.append(f"{fid}｜{fdef['label']}｜未提供｜-")

    factors_lines = [
        f"{f['id']}｜{f['name']}｜{f['rating']}｜{f['rule_note']}"
        for f in factors
    ]
    flags_lines = [f"[{fl['level']}] {fl['text']}" for fl in flags] or ["（无）"]

    syn = synthesis or {}
    syn_parts = []
    if syn.get("strongest"):
        syn_parts.append(f"最强项：{syn['strongest']['name']}（{syn['strongest']['rating']}）")
    if syn.get("weakest"):
        syn_parts.append(f"最大短板：{syn['weakest']['name']}（{syn['weakest']['rating']}），分组：{syn.get('group', '')}")
    syn_text = "；".join(syn_parts) if syn_parts else "无"

    prompt = tpl.replace("{{RAW_TEXT}}", raw_text or "")
    prompt = prompt.replace("{{FACTS}}", "\n".join(facts_lines))
    prompt = prompt.replace("{{FACTORS}}", "\n".join(factors_lines))
    prompt = prompt.replace("{{FLAGS}}", "\n".join(flags_lines))
    prompt = prompt.replace("{{SYNTHESIS}}", syn_text)
    prompt = prompt.replace("{{ADVISORS_INDEX}}", build_advisors_index(advisors))
    return prompt


EXTRACT_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "decision": {"type": "STRING"},
        "extracted": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "value": {"type": "STRING"},
                    "unit": {"type": "STRING"},
                    "category": {"type": "STRING", "enum": ["事实", "自报", "估计", "猜测"]},
                    "quote": {"type": "STRING"},
                    "status": {"type": "STRING", "enum": ["given", "ambiguous"]},
                    "readings": {"type": "ARRAY", "items": {"type": "STRING"}},
                },
                "required": ["id", "value", "unit", "category", "quote", "status", "readings"],
            },
        },
        "clarify": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "field_id": {"type": "STRING"},
                    "question": {"type": "STRING"},
                    "why": {"type": "STRING"},
                },
                "required": ["field_id", "question", "why"],
            },
        },
    },
    "required": ["decision", "extracted", "clarify"],
}

ANALYSIS_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "advisors": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "id": {"type": "STRING"},
                    "insight": {"type": "STRING"},
                    "next_step": {"type": "STRING"},
                },
                "required": ["id", "insight", "next_step"],
            },
        },
        "critique": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "target": {"type": "STRING"},
                    "text": {"type": "STRING"},
                },
                "required": ["target", "text"],
            },
        },
        "two_week_checks": {
            "type": "ARRAY",
            "items": {
                "type": "OBJECT",
                "properties": {
                    "side": {"type": "STRING", "enum": ["supply", "demand"]},
                    "text": {"type": "STRING"},
                },
                "required": ["side", "text"],
            },
        },
        "validation_design": {
            "type": "OBJECT",
            "properties": {
                "supply": {"type": "ARRAY", "items": {"type": "STRING"}},
                "demand": {"type": "ARRAY", "items": {"type": "STRING"}},
                "threshold": {"type": "ARRAY", "items": {"type": "STRING"}},
            },
            "required": ["supply", "demand", "threshold"],
        },
    },
    "required": ["advisors", "critique", "two_week_checks", "validation_design"],
}


_THINKING_UNSUPPORTED = False


def call_gemini(
    api_key,
    model,
    base_url,
    user_message,
    task="extract",
    locked_fields=None,
    analysis_ctx=None,
    timeout_sec=None,
):
    """Call Gemini generateContent for 'extract' or 'analysis'."""
    global _THINKING_UNSUPPORTED
    if not api_key:
        raise GeminiAPIError("Key 无效或无权限", "尚未配置 Gemini API Key，请先在设置中填写。")
    if not validate_base_url(base_url):
        raise GeminiAPIError("模型名或 Base URL 不存在", "Base URL 不合法，仅允许 https:// 或本机 http://127.0.0.1 / localhost。")

    model = sanitize_model(model)
    endpoint = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"

    if task == "analysis":
        ctx = analysis_ctx or {}
        system_inst = build_analysis_prompt(
            ctx.get("raw_text", ""),
            ctx.get("fields_state", {}),
            ctx.get("factors", []),
            ctx.get("flags", []),
            ctx.get("synthesis"),
        )
        schema = ANALYSIS_SCHEMA
        timeout_sec = timeout_sec or 120
    else:
        system_inst = build_extract_prompt(locked_fields)
        schema = EXTRACT_SCHEMA
        timeout_sec = timeout_sec or 60

    gen_cfg = {
        "temperature": 0.2,
        "response_mime_type": "application/json",
        "response_schema": schema,
    }
    if not _THINKING_UNSUPPORTED:
        gen_cfg["thinkingConfig"] = {"thinkingBudget": 0}

    payload = {
        "system_instruction": {"parts": [{"text": system_inst}]},
        "contents": [{"role": "user", "parts": [{"text": user_message}]}],
        "generationConfig": gen_cfg,
    }

    def _make_req():
        return urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": api_key,
                "User-Agent": "CCagent/1.0",
            },
        )

    req = _make_req()
    retries_left = 1
    thinking_retried = False
    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if thinking_retried:
                    _THINKING_UNSUPPORTED = True
                candidates = data.get("candidates", [])
                if not candidates:
                    raise GeminiAPIError("模型输出格式异常", "模型未返回候选内容。")
                raw_text = candidates[0].get("content", {}).get("parts", [{}])[0].get("text", "{}")
                clean = raw_text.strip()
                if clean.startswith("```json"):
                    clean = clean[7:]
                elif clean.startswith("```"):
                    clean = clean[3:]
                if clean.endswith("```"):
                    clean = clean[:-3]
                try:
                    parsed = json.loads(clean.strip())
                    usage = data.get("usageMetadata")
                    if isinstance(parsed, dict) and isinstance(usage, dict):
                        parsed["_usage"] = {
                            "prompt_tokens": usage.get("promptTokenCount", 0),
                            "output_tokens": usage.get("candidatesTokenCount", 0),
                            "total_tokens": usage.get("totalTokenCount", 0),
                        }
                    return parsed
                except Exception as exc:
                    raise GeminiAPIError("模型输出格式异常", f"JSON 解析失败: {exc}")
        except urllib.error.HTTPError as he:
            code = he.code
            if code == 400 and not thinking_retried and "thinkingConfig" in payload.get("generationConfig", {}):
                thinking_retried = True
                logging.warning("Model %s rejected thinkingConfig (HTTP 400); retrying without it.", model)
                payload["generationConfig"].pop("thinkingConfig", None)
                req = _make_req()
                continue
            detail = ""
            if 400 <= code < 500:
                import providers
                detail = providers._extract_4xx_detail(he, api_key)
            if code in (401, 403):
                raise GeminiAPIError("Key 无效或无权限", f"API Key 无效或无权限，请检查配置。{detail}", code)
            if code == 400:
                raise GeminiAPIError("请求被拒绝（可能是结构化输出参数）", f"请求被模型服务拒绝（400）。{detail}", code)
            if code == 404:
                raise GeminiAPIError("模型名或 Base URL 不存在", f"模型 {model} 或 Base URL 不存在（404）。{detail}", code)
            if code == 429:
                if retries_left > 0:
                    retries_left -= 1
                    time.sleep(2)
                    continue
                raise GeminiAPIError("限流", "请求过于频繁（429），请稍后再试。", code)
            if 500 <= code < 600:
                if retries_left > 0:
                    retries_left -= 1
                    time.sleep(2)
                    continue
                raise GeminiAPIError("服务繁忙", f"模型服务繁忙（{code}），请稍后再试。", code)
            raise GeminiAPIError("请求失败", f"HTTP 错误 {code}", code)
        except TimeoutError:
            raise GeminiAPIError("请求超时", "请求超时，请检查网络或增大 GEMINI_TIMEOUT。")
        except urllib.error.URLError as ue:
            if "timed out" in str(ue.reason).lower():
                raise GeminiAPIError("请求超时", "请求超时，请检查网络或增大 GEMINI_TIMEOUT。")
            if retries_left > 0:
                retries_left -= 1
                time.sleep(2)
                continue
            raise GeminiAPIError("网络异常", f"网络连接失败: {ue.reason}")
    raise GeminiAPIError("请求失败", "多次重试后仍失败")


def call_model(
    provider,
    api_key,
    model,
    task,
    user_message,
    base_url=None,
    locked_fields=None,
    analysis_ctx=None,
    timeout_sec=None,
):
    """Unified model call entry point dispatching to Gemini, xAI, or DeepSeek."""
    import providers
    return providers.call_model(
        provider,
        api_key,
        model,
        task,
        user_message,
        base_url=base_url,
        locked_fields=locked_fields,
        analysis_ctx=analysis_ctx,
        timeout_sec=timeout_sec,
    )
