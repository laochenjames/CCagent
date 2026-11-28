"""F9: Generate blind evaluation sheet (blind_sheet.md) and answer key (blind_key.json).

Usage:
  python tests/council_eval/make_blind_sheet.py [--dry-run] [--seed 42]
"""

import argparse
import json
import os
import random


def format_readable(res):
    lines = []
    lines.append(f"**标题**：{res.get('title', '')}")
    lines.append(f"**摘要**：{res.get('summary', '')}")
    pillars = res.get("pillars") or []
    if pillars:
        lines.append("**三支柱**：")
        for p in pillars:
            val = p.get("value") or p.get("content") or ""
            lines.append(f"- {p.get('label', '')}：{val}")
    for sec in (res.get("sections") or []):
        lines.append(f"**{sec.get('heading', '')}**：")
        for it in (sec.get("items") or []):
            lines.append(f"- {it.get('name', '')}：{it.get('detail', '')}")
    notes = res.get("council_notes") or []
    if notes:
        lines.append("**4 条判断**：")
        for n in notes:
            v = n.get("verdict") or n.get("note") or ""
            act = n.get("action") or ""
            lines.append(f"- {n.get('name', '顾问')}：{v}" + (f"（动作：{act}）" if act else ""))
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Read Cxx_dry.json instead of Cxx_real.json")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    eval_dir = os.path.dirname(os.path.abspath(__file__))
    res_dir = os.path.join(eval_dir, "results")
    with open(os.path.join(eval_dir, "cases.json"), "r", encoding="utf-8") as f:
        cases = json.load(f)

    rng = random.Random(args.seed)
    new_suffix = "dry" if args.dry_run else "real"

    sheet_lines = [
        "# 智囊团人工盲评表",
        "",
        "说明：旧版输出使用旧 prompt 经新传输层（请求头 Key、新错误处理）生成，二者的差别仅来自 prompt 与输出契约。",
        "样本量小、单一评分者，结论仅作方向性参考。",
        "",
        "每条用例提供版本 A 与版本 B（已隐藏来源），请评价：**哪个更具体**、**哪个更像在编**。",
        "",
    ]
    key_map = {}

    for c in cases:
        cid = c["id"]
        old_path = os.path.join(res_dir, f"{cid}_old.json")
        new_path = os.path.join(res_dir, f"{cid}_{new_suffix}.json")
        if not (os.path.isfile(old_path) and os.path.isfile(new_path)):
            continue
        old_res = json.load(open(old_path, encoding="utf-8"))
        new_res = json.load(open(new_path, encoding="utf-8"))
        pair = [("old", old_res), ("new", new_res)]
        rng.shuffle(pair)
        key_map[cid] = {"A": pair[0][0], "B": pair[1][0]}

        sheet_lines.append(f"## {cid}：{c['title']}")
        sheet_lines.append("")
        sheet_lines.append("### 版本 A")
        sheet_lines.append(format_readable(pair[0][1]))
        sheet_lines.append("")
        sheet_lines.append("### 版本 B")
        sheet_lines.append(format_readable(pair[1][1]))
        sheet_lines.append("")
        sheet_lines.append("- 哪个更具体（A/B/平）：")
        sheet_lines.append("- 哪个更像在编（A/B/无）：")
        sheet_lines.append("")

    with open(os.path.join(eval_dir, "blind_sheet.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(sheet_lines))
    with open(os.path.join(eval_dir, "blind_key.json"), "w", encoding="utf-8") as f:
        json.dump(key_map, f, ensure_ascii=False, indent=2)
    print(f"Generated blind_sheet.md ({len(key_map)} cases) and blind_key.json")


if __name__ == "__main__":
    main()
