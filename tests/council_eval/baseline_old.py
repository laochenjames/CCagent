"""F9: Run pre-v1 backup agent servers on cases.json to collect 'old' baseline outputs.

Usage:
  python tests/council_eval/baseline_old.py --dry-run
  python tests/council_eval/baseline_old.py            # requires real API key
"""

import argparse
import importlib.util
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import thinking_core as core

BACKUP_DIR = os.path.join(ROOT, "docs", "archive", "council_backup_20261127")


def load_backup_module(agent_id):
    path = os.path.join(BACKUP_DIR, f"{agent_id}_server.py")
    spec = importlib.util.spec_from_file_location(f"old_{agent_id}_server", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Stub LLM to verify backup import & output format")
    args = parser.parse_args()

    eval_dir = os.path.dirname(os.path.abspath(__file__))
    res_dir = os.path.join(eval_dir, "results")
    os.makedirs(res_dir, exist_ok=True)
    with open(os.path.join(eval_dir, "cases.json"), "r", encoding="utf-8") as f:
        cases = json.load(f)

    cfg = {"provider": "gemini", "api_key": "stub", "model": "stub", "base_url": "https://x", "timeout": 10} if args.dry_run else core.resolve_llm_config()
    if not args.dry_run and not cfg.get("api_key"):
        print("ERROR: 真实模式需要环境变量或 .env 中配置 API Key。")
        sys.exit(1)

    orig_call = core.call_llm_json
    if args.dry_run:
        def _fake_old_call(prompt, c, **kw):
            return {
                "title": "旧版模拟标题",
                "summary": "旧版模拟摘要",
                "pillars": [
                    {"label": "支柱1", "content": "旧版支柱内容1"},
                    {"label": "支柱2", "content": "旧版支柱内容2"},
                    {"label": "支柱3", "content": "旧版支柱内容3"},
                ],
                "sections": [
                    {"heading": "一、旧版分节", "items": [{"name": "旧要点", "tag": "旧标签", "detail": "旧版分析详情"}]}
                ],
                "council_synthesis": {"consensus": "旧版共识", "tension": "旧版分歧"},
                "council_notes": [
                    {"id": "a1", "name": "顾问1", "verdict": "旧版判断1", "action": "旧版动作1"},
                    {"id": "a2", "name": "顾问2", "verdict": "旧版判断2", "action": "旧版动作2"},
                    {"id": "a3", "name": "顾问3", "verdict": "旧版判断3", "action": "旧版动作3"},
                    {"id": "a4", "name": "顾问4", "verdict": "旧版判断4", "action": "旧版动作4"},
                ],
            }
        core.call_llm_json = _fake_old_call

    loaded = {}
    try:
        for c in cases:
            aid = c["agent"]
            if aid not in loaded:
                loaded[aid] = load_backup_module(aid)
            mod = loaded[aid]
            res = mod._generate_ai(c["raw_text"], c.get("fields", {}), cfg)
            out_path = os.path.join(res_dir, f"{c['id']}_old.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            print(f"  [OK] {c['id']} ({aid}) -> {os.path.basename(out_path)}")
    finally:
        core.call_llm_json = orig_call


if __name__ == "__main__":
    main()
