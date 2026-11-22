"""Real-key verification for Gemini / Grok (xAI) / DeepSeek.

Keys are read from environment variables only and are never printed:
  GEMINI_API_KEY, XAI_API_KEY, DEEPSEEK_API_KEY

Usage (PowerShell):
  $env:XAI_API_KEY="..."; $env:DEEPSEEK_API_KEY="..."; $env:GEMINI_API_KEY="..."
  python tools/verify_providers.py --list-models
  python tools/verify_providers.py --model gemini=gemini-3.5-flash --model deepseek=deepseek-flash --model xai=<model-id>

Providers whose key variable is not set are skipped.
When an xai/deepseek step fails, raw HTTP diagnostics (status + first 300 chars of the
provider's error body, with the key redacted) are printed, including a comparison of the
default Python User-Agent against a custom one.
Output is a markdown table: paste it (and the diagnostics) into the stage report.
"""

import argparse
import json
import logging
import os
import sys
import time
import urllib.error
import urllib.request

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, BASE_DIR)

import llm  # noqa: E402
import providers  # noqa: E402
import server  # noqa: E402
import verify  # noqa: E402

SAMPLE = "想业余做技能陪跑，单价800元，自己能拿7成，我的底线是每单不低于500元，已经有两个陌生人付过钱了。"
KEY_ENV = {"gemini": "GEMINI_API_KEY", "xai": "XAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
ANALYSIS_KEYS = ("advisors", "critique", "two_week_checks", "validation_design")
CUSTOM_UA = "CCagent-verify/1.0"


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _redact(text, key):
    text = str(text)
    return text.replace(key, "***") if key else text


def _step(fn, key):
    t0 = time.monotonic()
    try:
        out = fn()
        return True, out, int((time.monotonic() - t0) * 1000), ""
    except llm.GeminiAPIError as e:
        ms = int((time.monotonic() - t0) * 1000)
        return False, None, ms, _redact(f"{e.category}: {e.message}", key)
    except Exception as e:  # noqa: BLE001
        ms = int((time.monotonic() - t0) * 1000)
        return False, None, ms, _redact(f"{type(e).__name__}: {e}", key)


def raw_probe(provider, key, path, method="GET", payload=None, ua=None, timeout=20):
    """Return (status, body_text) without raising; used only for diagnostics."""
    preset = providers.PROVIDER_PRESETS[provider]
    headers = {"Authorization": f"Bearer {key}"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if ua:
        headers["User-Agent"] = ua
    req = urllib.request.Request(preset["base_url"] + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as he:
        return he.code, he.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001
        return 0, f"{type(e).__name__}: {e}"


def diagnose(provider, key, model):
    print(f"\n--- [{provider}] 原始 HTTP 诊断（Key 已打码）---")
    checks = [
        ("GET /models（默认 User-Agent）", lambda: raw_probe(provider, key, "/models")),
        (f"GET /models（User-Agent={CUSTOM_UA}）", lambda: raw_probe(provider, key, "/models", ua=CUSTOM_UA)),
        (
            f"POST /chat/completions（模型 {model}，max_tokens=8）",
            lambda: raw_probe(
                provider,
                key,
                "/chat/completions",
                method="POST",
                payload={"model": model, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 8},
            ),
        ),
    ]
    for name, fn in checks:
        status, body = fn()
        print(f"{name}\n  HTTP {status}  {_redact(body, key)[:300]!r}")


def list_models(provider, key):
    preset = providers.PROVIDER_PRESETS[provider]
    req = urllib.request.Request(
        f"{preset['base_url']}/models",
        headers={"Authorization": f"Bearer {key}"},
        method="GET",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return sorted(m.get("id") for m in data.get("data", []) if isinstance(m, dict) and m.get("id"))


def tokens_of(res):
    if isinstance(res, dict) and isinstance(res.get("_usage"), dict):
        return res["_usage"].get("total_tokens", 0)
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", default=[], help="provider=model-id (repeatable)")
    ap.add_argument("--list-models", action="store_true", help="print model ids for xai/deepseek")
    ap.add_argument("--diagnose", action="store_true", help="always print raw HTTP diagnostics for xai/deepseek")
    args = ap.parse_args()

    models = {p: providers.PROVIDER_PRESETS[p]["default_model"] for p in providers.SUPPORTED_PROVIDERS}
    for item in args.model:
        if "=" in item:
            p, m = item.split("=", 1)
            if p.strip() in models:
                models[p.strip()] = m.strip()

    cap = _Capture()
    logging.getLogger().addHandler(cap)
    logging.getLogger().setLevel(logging.WARNING)

    registry = llm.load_fields_registry()
    rows = []
    to_diagnose = []

    for prov in providers.SUPPORTED_PROVIDERS:
        key = os.environ.get(KEY_ENV[prov], "").strip()
        if not key:
            print(f"[skip] {prov}: {KEY_ENV[prov]} 未设置")
            continue
        model = models[prov]

        if args.list_models and prov in ("xai", "deepseek"):
            ok, ids, _, msg = _step(lambda: list_models(prov, key), key)
            print(f"\n[{prov}] 可用模型：" + (", ".join(ids[:80]) if ok else f"获取失败 {msg}"))

        # 1. models endpoint (xai/deepseek only)
        if prov in ("xai", "deepseek"):
            ok_m, _, _, msg_m = _step(lambda: providers.verify_openai_models(prov, key, model), key)
            models_cell = "通过" if ok_m else f"失败：{msg_m}"
        else:
            ok_m = True
            models_cell = "—"

        # 2. extract
        before = len(cap.messages)
        ok_e, res_e, ms_e, msg_e = _step(
            lambda: providers.call_model(prov, key, model, "extract", SAMPLE, timeout_sec=60), key
        )
        price_ok = False
        if ok_e and isinstance(res_e, dict) and isinstance(res_e.get("extracted"), list):
            for it in res_e["extracted"]:
                if isinstance(it, dict) and it.get("id") == "unit_price":
                    try:
                        price_ok = float(it.get("value")) == 800
                    except Exception:  # noqa: BLE001
                        pass
        extract_cell = "通过" if ok_e else f"失败：{msg_e}"

        # 3. analysis (built from the extract result when available)
        extracted = res_e.get("extracted", []) if (ok_e and isinstance(res_e, dict)) else []
        decision = res_e.get("decision", "") if (ok_e and isinstance(res_e, dict)) else ""
        fields_state, _ = verify.verify_extracted(SAMPLE, extracted, registry)
        result = server._build_result_object("verify", 1, decision, fields_state, registry)
        ctx = {
            "raw_text": SAMPLE,
            "fields_state": fields_state,
            "factors": result.get("factors", []),
            "flags": result.get("flags", []),
            "synthesis": result.get("synthesis"),
        }
        ok_a, res_a, ms_a, msg_a = _step(
            lambda: providers.call_model(prov, key, model, "analysis", "请根据以上信息进行详细会诊分析。", analysis_ctx=ctx, timeout_sec=120),
            key,
        )
        if ok_a and not (isinstance(res_a, dict) and all(k in res_a for k in ANALYSIS_KEYS)):
            ok_a, msg_a = False, "返回缺少必要字段：" + ", ".join(k for k in ANALYSIS_KEYS if k not in (res_a or {}))
        analysis_cell = "通过" if ok_a else f"失败：{msg_a}"

        notes = [m for m in cap.messages[before:] if prov in m or "thinking" in m.lower()]
        rows.append(
            {
                "provider": prov,
                "model": model,
                "models": models_cell,
                "extract": extract_cell,
                "price": "是" if price_ok else "否",
                "analysis": analysis_cell,
                "tokens": f"{tokens_of(res_e)} / {tokens_of(res_a)}",
                "ms": f"{ms_e} / {ms_a}",
                "notes": "; ".join(notes) if notes else "",
            }
        )
        if prov in ("xai", "deepseek") and (args.diagnose or not (ok_m and ok_e and ok_a)):
            to_diagnose.append((prov, key, model))

    print("\n| 厂商 | 模型 | 模型列表 | 抽取 | 抽到单价800 | 详细分析 | token（抽取/分析） | 耗时 ms（抽取/分析） | 日志备注 |")
    print("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        print(
            f"| {r['provider']} | {r['model']} | {r['models']} | {r['extract']} | {r['price']} | "
            f"{r['analysis']} | {r['tokens']} | {r['ms']} | {r['notes']} |"
        )
    print(f"\nDeepSeek 思考参数被拒后已回退：{providers._DEEPSEEK_THINKING_UNSUPPORTED}")
    print("提示：只有'抽取''详细分析'都显示通过，且日志备注里没有 rejected thinking，才算该厂商核实完成。")

    for prov, key, model in to_diagnose:
        diagnose(prov, key, model)


if __name__ == "__main__":
    main()
