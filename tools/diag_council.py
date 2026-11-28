"""Diagnostic script (A6 + H6 + H7): run 10 council eval cases against real LLM
and print finishReason, token usage, and optional --probe-schema probes.

Usage (requires GEMINI_API_KEY / XAI_API_KEY / DEEPSEEK_API_KEY in env or .env):
  python tools/diag_council.py
  python tools/diag_council.py --probe-schema
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import thinking_core as core


def _mask_key_only(text, api_key=""):
    """Mask API key without truncating response body (for --probe-schema raw capture)."""
    s = str(text or "")
    if api_key:
        s = s.replace(api_key, "***")
    return s


def run_probe_schema(cfg):
    """H6.3: Send 4 Gemini schema probes, print full key-masked body, and save to tests/fixtures/_probe_<name>.txt."""
    if cfg["provider"] != "gemini":
        print(f"NOTE: --probe-schema is designed for Gemini; current provider={cfg['provider']}")
    with open(os.path.join(ROOT, "agent7", "config.json"), "r", encoding="utf-8") as f:
        full_schema = core.build_generate_schema(json.load(f))

    probes = [
        ("1_full_schema", full_schema),
        ("2_min_enum", {"type": "OBJECT", "properties": {"stance": {"type": "STRING", "enum": ["support", "hold"]}}, "required": ["stance"]}),
        ("3_min_nested_array", {
            "type": "OBJECT",
            "properties": {
                "sections": {
                    "type": "ARRAY",
                    "items": {
                        "type": "OBJECT",
                        "properties": {"items": {"type": "ARRAY", "items": {"type": "STRING"}}},
                        "required": ["items"],
                    },
                }
            },
            "required": ["sections"],
        }),
        ("4_min_max_items", {
            "type": "OBJECT",
            "properties": {"arr": {"type": "ARRAY", "items": {"type": "STRING"}, "minItems": 2, "maxItems": 3}},
            "required": ["arr"],
        }),
    ]
    url = f"{cfg['base_url']}/v1beta/models/{cfg['model']}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": cfg["api_key"],
        "User-Agent": "CCagent/1.0",
    }
    fixtures_dir = os.path.join(ROOT, "tests", "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    for name, schema in probes:
        payload = {
            "contents": [{"role": "user", "parts": [{"text": "请按 JSON schema 返回一个最小合法示例。"}]}],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 512,
                "responseMimeType": "application/json",
                "responseSchema": schema,
            },
        }
        req = urllib.request.Request(url, data=json.dumps(payload, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
        out_file = os.path.join(fixtures_dir, f"_probe_{name}.txt")
        print(f"\n=== Probe {name} ===")
        try:
            with urllib.request.urlopen(req, timeout=cfg["timeout"]) as resp:
                body = _mask_key_only(resp.read().decode("utf-8", errors="replace"), cfg["api_key"])
            with open(out_file, "w", encoding="utf-8") as wf:
                wf.write(body)
            print(f"  ACCEPTED (HTTP 200) | saved={out_file}\n  {body}")
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = _mask_key_only(e.read().decode("utf-8", errors="replace"), cfg["api_key"])
            except Exception:
                pass
            with open(out_file, "w", encoding="utf-8") as wf:
                wf.write(body)
            print(f"  REJECTED (HTTP {e.code}) | saved={out_file}\n  {body}")
        except Exception as e:
            msg = _mask_key_only(str(e), cfg["api_key"])
            print(f"  ERROR | {msg}")


def _format_token_obs(usage):
    if not usage:
        return ""
    c_tok = usage.get("candidates_tokens", 0)
    t_tok = usage.get("thoughts_tokens", 0)
    tot = usage.get("total_tokens", 0)
    max_t = usage.get("max_tokens", 4096) or 4096
    out_used = c_tok + t_tok
    pct = (out_used * 100.0) / max_t
    flag = " [>70%]" if pct > 70.0 else ""
    return f"candidates={c_tok} thoughts={t_tok} total={tot} out/max={pct:.1f}%{flag}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--probe-schema", action="store_true", help="Run 4 Gemini schema probes")
    args = parser.parse_args()

    cfg = core.resolve_llm_config()
    if not cfg.get("api_key"):
        print("ERROR: 未检测到 API Key，请在环境变量或 .env 中配置后运行。")
        sys.exit(1)

    if args.probe_schema:
        run_probe_schema(cfg)
        return

    cases_path = os.path.join(ROOT, "tests", "council_eval", "cases.json")
    with open(cases_path, "r", encoding="utf-8") as f:
        cases = json.load(f)

    print(f"Diag provider={cfg['provider']} model={cfg['model']} cases={len(cases)}")
    for c in cases:
        agent_id = c["agent"]
        cfg_path = os.path.join(ROOT, agent_id, "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            agent_cfg = json.load(f)
        print(f"\n--- Case {c['id']} ({agent_id}): {c['title']} ---")
        try:
            res = core.run_generate(agent_cfg, c["raw_text"], c.get("fields", {}), cfg)
            stances = [n["stance"] for n in res.get("council_notes", [])]
            grounded = sum(1 for n in res.get("council_notes", []) if n.get("grounded"))
            tok_obs = _format_token_obs(core.get_last_llm_usage())
            print(f"  OK | stances={stances} | grounded={grounded}/4 | {tok_obs}")
        except Exception as e:
            msg = core._sanitize_error(e, cfg.get("api_key", ""))
            print(f"  FAIL | {msg}")


if __name__ == "__main__":
    main()
