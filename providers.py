"""Multi-provider LLM adapter for Gemini, Grok (xAI), and DeepSeek."""

import json
import logging
import time
import urllib.error
import urllib.request

import llm

SUPPORTED_PROVIDERS = ("gemini", "xai", "deepseek")

PROVIDER_PRESETS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com",
        "default_model": "gemini-3.5-flash-lite",
        "structured": "gemini",
    },
    "xai": {
        "base_url": "https://api.x.ai/v1",
        "default_model": "grok-3-mini-fast",  # 待核实
        "structured": "json_schema",
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-flash",
        "structured": "json_object",
    },
}

MAX_TOKENS_EXTRACT = 2048
MAX_TOKENS_ANALYSIS = 6000

_DEEPSEEK_THINKING_UNSUPPORTED = False


def gemini_schema_to_json_schema(schema):
    """Convert Gemini-style uppercase schema to strict JSON Schema."""
    if not isinstance(schema, dict):
        return schema
    out = {}
    t = schema.get("type")
    if isinstance(t, str):
        out["type"] = t.lower()
    if "enum" in schema:
        out["enum"] = list(schema["enum"])
    if out.get("type") == "object" or "properties" in schema:
        props = schema.get("properties", {})
        conv_props = {k: gemini_schema_to_json_schema(v) for k, v in props.items()}
        out["type"] = "object"
        out["properties"] = conv_props
        out["additionalProperties"] = False
        out["required"] = list(conv_props.keys())
    if "items" in schema:
        out["items"] = gemini_schema_to_json_schema(schema["items"])
    return out


def schema_to_json_example(schema):
    """Build a minimal JSON example from a Gemini-style schema."""
    if not isinstance(schema, dict):
        return ""
    t = (schema.get("type") or "").upper()
    if t == "OBJECT" or "properties" in schema:
        return {k: schema_to_json_example(v) for k, v in schema.get("properties", {}).items()}
    if t == "ARRAY":
        return [schema_to_json_example(schema.get("items", {}))]
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    if t in ("NUMBER", "INTEGER"):
        return 0
    if t == "BOOLEAN":
        return False
    return "..."


def _strip_fences(text):
    clean = (text or "").strip()
    if clean.startswith("```json"):
        clean = clean[7:]
    elif clean.startswith("```"):
        clean = clean[3:]
    if clean.endswith("```"):
        clean = clean[:-3]
    return clean.strip()


def _extract_4xx_detail(he, api_key=""):
    """Extract sanitized 4xx vendor message (max 200 chars, API key masked)."""
    try:
        raw = he.read().decode("utf-8", errors="replace").strip()
    except Exception:
        return ""
    if not raw:
        return ""
    msg = raw
    try:
        obj = json.loads(raw)
        if isinstance(obj, dict):
            err = obj.get("error")
            if isinstance(err, dict) and err.get("message"):
                msg = str(err["message"])
            elif obj.get("message"):
                msg = str(obj["message"])
    except Exception:
        pass
    if api_key:
        msg = msg.replace(api_key, "***")
    msg = msg.strip()[:200]
    return f"（厂商返回：{msg}）" if msg else ""


def verify_openai_models(provider, api_key, model, timeout_sec=15):
    """Verify key and model via GET {base}/models without consuming tokens."""
    preset = PROVIDER_PRESETS.get(provider)
    if not preset:
        raise llm.GeminiAPIError("不支持的模型厂商", f"不支持的厂商: {provider}")
    url = f"{preset['base_url']}/models"
    req = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {api_key}",
            "User-Agent": "CCagent/1.0",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            ids = [m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id")]
            if ids and model and model not in ids:
                sample = ", ".join(sorted(ids)[:8])
                raise llm.GeminiAPIError("模型名不存在", f"模型 {model} 不在可用列表中，可用模型：{sample}", 404)
            return True
    except urllib.error.HTTPError as he:
        code = he.code
        detail = _extract_4xx_detail(he, api_key) if 400 <= code < 500 else ""
        if code in (401, 403):
            raise llm.GeminiAPIError("Key 无效或无权限", f"API Key 无效或无权限。{detail}", code)
        if code == 402:
            raise llm.GeminiAPIError("余额不足", f"账户余额不足（402）。{detail}", code)
        if code == 404:
            raise llm.GeminiAPIError("模型名不存在", f"模型或接口不存在（404）。{detail}", code)
        raise llm.GeminiAPIError("请求失败", f"HTTP 错误 {code}{detail}", code)
    except TimeoutError:
        raise llm.GeminiAPIError("请求超时", "请求超时，请检查网络。")
    except urllib.error.URLError as ue:
        raise llm.GeminiAPIError("网络异常", f"网络连接失败: {ue.reason}")


def call_openai_compat(
    provider,
    api_key,
    model,
    task,
    user_message,
    locked_fields=None,
    analysis_ctx=None,
    timeout_sec=None,
):
    """Call xAI (Grok) or DeepSeek OpenAI-compatible Chat Completions API."""
    global _DEEPSEEK_THINKING_UNSUPPORTED
    if not api_key:
        raise llm.GeminiAPIError("Key 无效或无权限", "尚未配置 API Key。")
    preset = PROVIDER_PRESETS.get(provider)
    if not preset:
        raise llm.GeminiAPIError("不支持的模型厂商", f"不支持的厂商: {provider}")

    model = llm.sanitize_model(model or preset["default_model"])
    endpoint = f"{preset['base_url']}/chat/completions"

    if task == "analysis":
        ctx = analysis_ctx or {}
        system_inst = llm.build_analysis_prompt(
            ctx.get("raw_text", ""),
            ctx.get("fields_state", {}),
            ctx.get("factors", []),
            ctx.get("flags", []),
            ctx.get("synthesis"),
        )
        schema = llm.ANALYSIS_SCHEMA
        max_tokens = MAX_TOKENS_ANALYSIS
        timeout_sec = timeout_sec or 120
    else:
        system_inst = llm.build_extract_prompt(locked_fields)
        schema = llm.EXTRACT_SCHEMA
        max_tokens = MAX_TOKENS_EXTRACT
        timeout_sec = timeout_sec or 60

    if preset["structured"] == "json_schema":
        response_format = {
            "type": "json_schema",
            "json_schema": {
                "name": "response",
                "strict": True,
                "schema": gemini_schema_to_json_schema(schema),
            },
        }
    else:
        example = json.dumps(schema_to_json_example(schema), ensure_ascii=False)
        system_inst = f"{system_inst}\n\n请严格输出合法的 json 对象，示例结构：\n{example}"
        response_format = {"type": "json_object"}

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_inst},
            {"role": "user", "content": user_message},
        ],
        "temperature": 0.2,
        "max_tokens": max_tokens,
        "response_format": response_format,
    }
    sent_thinking = False
    if provider == "deepseek" and not _DEEPSEEK_THINKING_UNSUPPORTED:
        payload["thinking"] = {"type": "disabled"}
        sent_thinking = True

    def _make_req():
        return urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "User-Agent": "CCagent/1.0",
            },
        )

    req = _make_req()
    retries_left = 1
    thinking_retried = False
    parse_retried = False

    while True:
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if thinking_retried and provider == "deepseek":
                    _DEEPSEEK_THINKING_UNSUPPORTED = True
                choices = data.get("choices", [])
                if not choices:
                    raise llm.GeminiAPIError("模型输出格式异常", "模型未返回候选内容。")
                choice = choices[0]
                if choice.get("finish_reason") == "length":
                    raise llm.GeminiAPIError("输出被截断", "输出被截断，请缩短输入或换模型。")
                content = (choice.get("message") or {}).get("content") or ""
                clean = _strip_fences(content)
                if not clean:
                    if not parse_retried:
                        parse_retried = True
                        continue
                    raise llm.GeminiAPIError("模型输出格式异常", "模型返回内容为空。")
                try:
                    parsed = json.loads(clean)
                except Exception as exc:
                    if not parse_retried:
                        parse_retried = True
                        continue
                    raise llm.GeminiAPIError("模型输出格式异常", f"JSON 解析失败: {exc}")
                usage = data.get("usage")
                if isinstance(parsed, dict) and isinstance(usage, dict):
                    parsed["_usage"] = {
                        "prompt_tokens": usage.get("prompt_tokens", 0),
                        "output_tokens": usage.get("completion_tokens", 0),
                        "total_tokens": usage.get("total_tokens", 0),
                    }
                return parsed
        except urllib.error.HTTPError as he:
            code = he.code
            if code in (400, 422) and not thinking_retried and sent_thinking and "thinking" in payload:
                thinking_retried = True
                logging.warning("Provider %s model %s rejected thinking param (HTTP %s); retrying without it.", provider, model, code)
                payload.pop("thinking", None)
                req = _make_req()
                continue
            detail = _extract_4xx_detail(he, api_key) if 400 <= code < 500 else ""
            if code in (401, 403):
                raise llm.GeminiAPIError("Key 无效或无权限", f"API Key 无效或无权限，请检查配置。{detail}", code)
            if code == 402:
                raise llm.GeminiAPIError("余额不足", f"账户余额不足（402），请检查账单。{detail}", code)
            if code == 404:
                raise llm.GeminiAPIError("模型名不存在", f"模型 {model} 不存在（404）。{detail}", code)
            if code in (400, 422):
                raise llm.GeminiAPIError("请求被拒绝", f"请求被模型服务拒绝（{code}）。{detail}", code)
            if code == 429:
                if retries_left > 0:
                    retries_left -= 1
                    time.sleep(2)
                    continue
                raise llm.GeminiAPIError("限流", "请求过于频繁（429），请稍后再试。", code)
            if 500 <= code < 600:
                if retries_left > 0:
                    retries_left -= 1
                    time.sleep(2)
                    continue
                raise llm.GeminiAPIError("服务繁忙", f"模型服务繁忙（{code}），请稍后再试。", code)
            raise llm.GeminiAPIError("请求失败", f"HTTP 错误 {code}", code)
        except TimeoutError:
            raise llm.GeminiAPIError("请求超时", "请求超时，请检查网络。")
        except urllib.error.URLError as ue:
            if "timed out" in str(ue.reason).lower():
                raise llm.GeminiAPIError("请求超时", "请求超时，请检查网络。")
            if retries_left > 0:
                retries_left -= 1
                time.sleep(2)
                continue
            raise llm.GeminiAPIError("网络异常", f"网络连接失败: {ue.reason}")
    raise llm.GeminiAPIError("请求失败", "多次重试后仍失败")


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
    """Unified entry point for gemini, xai, and deepseek."""
    prov = (provider or "gemini").strip().lower()
    if prov not in SUPPORTED_PROVIDERS:
        raise llm.GeminiAPIError("不支持的模型厂商", f"不支持的厂商: {prov}")
    if prov == "gemini":
        url = base_url or PROVIDER_PRESETS["gemini"]["base_url"]
        return llm.call_gemini(
            api_key,
            model or PROVIDER_PRESETS["gemini"]["default_model"],
            url,
            user_message,
            task=task,
            locked_fields=locked_fields,
            analysis_ctx=analysis_ctx,
            timeout_sec=timeout_sec,
        )
    return call_openai_compat(
        prov,
        api_key,
        model,
        task,
        user_message,
        locked_fields=locked_fields,
        analysis_ctx=analysis_ctx,
        timeout_sec=timeout_sec,
    )

