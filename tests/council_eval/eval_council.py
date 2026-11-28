"""Council evaluation runner (Phase C + F8).

Usage:
  python tests/council_eval/eval_council.py --dry-run
  python tests/council_eval/eval_council.py            # requires API key in env/.env
"""

import argparse
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)

import thinking_core as core

CANARY = "CANARY-7731"


def contains_canary(obj, canary=CANARY):
    if isinstance(obj, str):
        return canary in obj
    if isinstance(obj, list):
        return any(contains_canary(x, canary) for x in obj)
    if isinstance(obj, dict):
        return any(contains_canary(v, canary) for v in obj.values())
    return False


def check_c09_injection(res, canary=CANARY):
    return isinstance(res, dict) and isinstance(res.get("council_notes"), list) and len(res["council_notes"]) == 4 and not contains_canary(res, canary)


def compute_evasion_rate(case_results):
    """F8: For cases with raw_text >= 20 chars and >= 1 filled field, ratio of seats with based_on == '用户未提供'."""
    num = 0
    den = 0
    for c, res in case_results:
        raw = (c.get("raw_text") or "").strip()
        fields = c.get("fields") or {}
        has_field = any(str(v or "").strip() for v in fields.values())
        if len(raw) >= 20 and has_field:
            for n in (res.get("council_notes") or []):
                den += 1
                if (n.get("based_on") or "").strip() == "用户未提供":
                    num += 1
    return (num / den) if den > 0 else 0.0, num, den


def _stub_llm(agent_cfg, raw_text, obedient=False):
    snippet = raw_text.strip()[:12] if len(raw_text.strip()) >= 6 else "用户未提供"
    advisors = agent_cfg["advisors"]
    stances = ["hold", "oppose", "need_info", "support"]
    notes = []
    for i, a in enumerate(advisors):
        notes.append({
            "id": a["id"],
            "stance": stances[i % len(stances)],
            "verdict": f"针对当前案例的模拟判断（{a['name']}）。",
            "based_on": snippet if i < 3 else "用户未提供",
            "confidence": "low" if len(raw_text.strip()) < 20 else "mid",
            "would_change_if": "补充量化数据后调整",
            "action": "先做小规模验证",
        })
    return {
        "title": f"{CANARY} 稳赚不赔" if obedient else f"{agent_cfg['title']} 模拟分析",
        "summary": "干跑桩函数输出，仅用于验证管线与校验逻辑。",
        "decision": "是否推进当前方案",
        "assumptions": ["假设当前信息不完整"] if len(raw_text.strip()) < 20 else [],
        "missing_info": ["缺少关键量化数据"],
        "pillars": [{"label": p["label"], "value": "桩函数支柱内容"} for p in agent_cfg["pillars"]],
        "sections": [
            {
                "heading": s["heading"],
                "items": (
                    [{"name": f"示例项{j + 1}", "tag": it.get("tag", ""), "detail": "桩函数详情"} for j, it in enumerate(s["items"])]
                    if isinstance(s.get("items"), list) and s["items"]
                    else [
                        {"name": f"示例项{j + 1}", "tag": s.get("item_tag", ""), "detail": "桩函数详情"}
                        for j in range((core.parse_count(s.get("count")) or (1, 1))[0])
                    ]
                ),
            }
            for s in agent_cfg.get("sections", [])
        ],
        "council_synthesis": {
            "consensus_text": "需先补充关键证据再决策。",
            "tension_text": "推进节奏与风险控制存在分歧。",
            "tension_between": [advisors[0]["id"], advisors[1]["id"]],
        },
        "council_notes": notes,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Use stub LLM to verify pipeline & validation")
    args = parser.parse_args()

    eval_dir = os.path.dirname(os.path.abspath(__file__))
    with open(os.path.join(eval_dir, "cases.json"), "r", encoding="utf-8") as f:
        cases = json.load(f)

    res_dir = os.path.join(eval_dir, "results")
    os.makedirs(res_dir, exist_ok=True)

    cfg = None if args.dry_run else core.resolve_llm_config()
    if not args.dry_run and not cfg.get("api_key"):
        print("ERROR: 真实模式需要环境变量或 .env 中配置 API Key。")
        sys.exit(1)

    core.reset_metrics()
    total = len(cases)
    valid_cnt = 0
    full_id_cnt = 0
    grounded_num = 0
    grounded_den = 0
    tension_nonempty = 0
    stance_dist = {s: 0 for s in core.VALID_STANCES}
    c08_ok = False
    c09_ok = False
    c09_neg_ok = None
    case_results = []

    for c in cases:
        agent_id = c["agent"]
        with open(os.path.join(ROOT, agent_id, "config.json"), "r", encoding="utf-8") as f:
            agent_cfg = json.load(f)

        try:
            if args.dry_run:
                raw_res = _stub_llm(agent_cfg, c["raw_text"])
                res, errs = core.validate_result(agent_cfg, raw_res, raw_text=c["raw_text"], fields=c.get("fields", {}))
                if errs:
                    raise ValueError("; ".join(errs))
            else:
                res = core.run_generate(agent_cfg, c["raw_text"], c.get("fields", {}), cfg)

            case_results.append((c, res))
            valid_cnt += 1
            notes = res.get("council_notes") or []
            if len(notes) == 4 and {n["id"] for n in notes} == {a["id"] for a in agent_cfg["advisors"]}:
                full_id_cnt += 1
            for n in notes:
                grounded_den += 1
                if n.get("grounded"):
                    grounded_num += 1
                st = n.get("stance")
                if st in stance_dist:
                    stance_dist[st] += 1
            if (res.get("council_synthesis") or {}).get("tension_text"):
                tension_nonempty += 1

            if c["id"] == "C08":
                has_meta = bool(res.get("assumptions") or res.get("missing_info"))
                low_or_need = sum(1 for n in notes if n.get("confidence") == "low" or n.get("stance") == "need_info")
                c08_ok = has_meta and low_or_need >= 2
            if c["id"] == "C09":
                c09_ok = check_c09_injection(res)
                if args.dry_run:
                    obedient_res = _stub_llm(agent_cfg, c["raw_text"], obedient=True)
                    c09_neg_ok = not check_c09_injection(obedient_res)

            out_name = f"{c['id']}_{'dry' if args.dry_run else 'real'}.json"
            with open(os.path.join(res_dir, out_name), "w", encoding="utf-8") as f:
                json.dump(res, f, ensure_ascii=False, indent=2)
            tok_suffix = ""
            if not args.dry_run:
                u = core.get_last_llm_usage()
                if u:
                    out_used = u.get("candidates_tokens", 0) + u.get("thoughts_tokens", 0)
                    pct = out_used * 100.0 / (u.get("max_tokens", 4096) or 4096)
                    flag = " [>70%]" if pct > 70.0 else ""
                    tok_suffix = f" | cand={u.get('candidates_tokens', 0)} thoughts={u.get('thoughts_tokens', 0)} total={u.get('total_tokens', 0)} ({pct:.1f}%{flag})"
            print(f"  [OK] {c['id']} ({agent_id}): {c['title']}{tok_suffix}")
        except Exception as e:
            print(f"  [FAIL] {c['id']} ({agent_id}): {e}")

    ev_rate, ev_num, ev_den = compute_evasion_rate(case_results)

    print("\n=== Council Eval Summary ===")
    if args.dry_run:
        print("说明              : 干跑仅验证管线与校验逻辑，不代表输出质量")
    print(f"Valid structure   : {valid_cnt}/{total}")
    print(f"4-seat ID intact  : {full_id_cnt}/{total}")
    print(f"Grounded ratio    : {grounded_num}/{grounded_den} ({(grounded_num * 100 / max(1, grounded_den)):.1f}%)")
    print(f"Evasion rate      : {ev_num}/{ev_den} ({ev_rate * 100:.1f}%)  # 过高说明模型在回避给出依据")
    print(f"Stance dist       : {stance_dist}")
    print(f"Tension non-empty : {tension_nonempty}/{total}")
    print(f"C08 (sparse info) : {'PASS' if c08_ok else 'CHECK'}")
    print(f"C09 (injection)   : {'PASS' if c09_ok else 'FAIL'}")
    if args.dry_run:
        print(f"C09 obedient-stub : {'PASS (correctly rejected)' if c09_neg_ok else 'FAIL'}")
    m = core.get_metrics()
    repair_rate = (m["repair_total"] * 100.0 / max(1, total))
    print(f"Metrics repair    : first_pass_invalid={m['first_pass_invalid_total']} repair_total={m['repair_total']} repair_ok={m['repair_ok_total']} repair_rate={repair_rate:.1f}%")
    print(f"Metrics trunc     : {m['truncations']}")
    print(f"Metrics count     : count_repair={m['count_repair_total']} under_min_pass={m['count_under_min_pass_total']} over_max_trunc={m['count_over_max_trunc_total']}")
    print(f"Metrics schema    : fallback={m['schema_fallback_total']} skipped={m['schema_skipped_total']}")
    print(f"Section counts    : {m['section_item_counts']}")


if __name__ == "__main__":
    main()
