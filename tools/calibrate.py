"""Score calibration runner (no LLM calls)."""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import engine
import llm


def main():
    personas_path = os.path.join(ROOT, "tests", "calibration", "personas.json")
    with open(personas_path, "r", encoding="utf-8") as f:
        personas = json.load(f)
    registry = llm.load_fields_registry()

    mismatch = 0
    print("| 用例名 | 评估词 | 评分区间 | 置信度 | 最大短板 | 红线原因 | 符合预期 |")
    print("|---|---|---|---|---|---|---|")
    for p in personas:
        res = engine.evaluate_fields(p["fields"], registry)
        sc = res["score"]
        syn = res["synthesis"]
        weakest = syn["weakest"]["name"] if syn.get("weakest") else "—"
        red = engine.red_line_reasons(p["fields"])
        has_red = len(red) > 0
        exp = p.get("expected", {})
        red_ok = has_red == bool(exp.get("red_line", False))
        lbl_ok = sc["label"] in exp.get("labels", [sc["label"]])
        if not red_ok:
            mismatch += 1
        ok_str = "是" if (red_ok and lbl_ok) else ("红线不符" if not red_ok else "标签提示")
        red_str = "；".join(red) if red else "无"
        print(f"| {p['name']} | {sc['label']} | {sc['low']}–{sc['high']} | {sc['confidence_pct']}% | {weakest} | {red_str} | {ok_str} |")

    sys.exit(1 if mismatch > 0 else 0)


if __name__ == "__main__":
    main()

