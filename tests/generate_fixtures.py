import json
import os
import sys
import tempfile
import threading
import urllib.request
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import llm
import report
import score
import server
import store


def build_fixtures():
    registry = llm.load_fields_registry()

    # 1. 非红线主评估 fixture（purpose="money"，3+ 个不同评级，synthesis.weakest 非空且带 delta）
    fields_main = {
        "decision": {"value": "自媒体副业", "status": "given"},
        "purpose": {"value": "money", "status": "given"},
        "paid_evidence": {"value": "asked", "status": "given"},
        "skill_evidence": {"value": "direct", "status": "given"},
        "channel_access": {"value": "has", "status": "given"},
        "borrowing_or_essential_funds": {"value": False, "status": "given"},
        "needs_cash": {"value": True, "status": "given"},
        "cash_outlay": {"value": 5, "status": "given"},
        "cash_free": {"value": 100, "status": "given"},
        "monthly_expense": {"value": 100, "status": "given"},
        "income_after_monthly": {"value": 100, "status": "given"},
        "weekly_hours_actual_recent": {"value": 2, "status": "given"},
    }
    res_main = server._build_result_object(
        "s_fixture_main", 1, "自媒体副业", fields_main, registry
    )

    # 2. 学习型（purpose="learn"）
    fields_learn = {
        "decision": {"value": "学做播客", "status": "given"},
        "purpose": {"value": "learn", "status": "given"},
        "weekly_hours_planned": {"value": 6, "status": "given"},
    }
    res_learn = server._build_result_object(
        "s_fixture_learn", 1, "学做播客", fields_learn, registry
    )

    # 3. 用户标记不适用（excluded=["MONETIZATION"]）+ 智守整项不适用（needs_cash=False, affects_main_job=False）
    fields_excl = {
        "decision": {"value": "开源工具", "status": "given"},
        "purpose": {"value": "money", "status": "given"},
        "excl_MONETIZATION": {"value": True, "status": "given"},
        "needs_cash": {"value": False, "status": "given"},
        "affects_main_job": {"value": False, "status": "given"},
        "borrowing_or_essential_funds": {"value": False, "status": "given"},
        "weekly_hours_actual_recent": {"value": 8, "status": "given"},
    }
    res_excl = server._build_result_object(
        "s_fixture_excl", 1, "开源工具", fields_excl, registry
    )

    # 4. 真实 /analysis 响应结构（严格对照 ANALYSIS_SCHEMA）
    analysis_resp = {
        "analysis": {
            "critique": [
                {
                    "target": "MONETIZATION",
                    "text": "当前仅有口头询问，尚未验证陌生人真实付费意愿。",
                },
                {
                    "target": "weekly_hours_actual_recent",
                    "text": "每周实际投入 2 小时偏少，可能拉长验证周期。",
                },
            ],
            "two_week_checks": [
                {"side": "需求侧", "text": "找 3 位陌生目标用户完成预售或付费访谈"},
                {"side": "执行侧", "text": "记录连续两周实际可投入小时数是否稳定超过 4 小时"},
            ],
            "validation_design": {
                "action": "发布 1 个最小可交付服务页并向目标人群推送",
                "pass_line": "两周内收到至少 1 笔真实预付款",
                "fail_line": "两周内 0 笔付费且无人愿意预约试用",
                "cost": "每周 4 小时，现金支出 0 元",
            },
            "advisors": [
                {
                    "id": "MONETIZATION",
                    "insight": "当前尚无陌生人付费验证，建议先用最小样本测试付费意愿。",
                    "next_step": "找 3 位目标用户做预售或付费访谈。",
                },
                {
                    "id": "AI_IMPACT",
                    "insight": "AI 工具可显著降低内容生产成本，但也加剧同质化竞争。",
                    "next_step": "明确自身不可替代的真实经历或数据视角。",
                },
            ],
            "summary": "整体可行，优先补齐付费验证与时间投入。",
        },
        "stale": False,
    }

    return {
        "advisors_eval.json": res_main,
        "advisors_eval_learn.json": res_learn,
        "advisors_eval_excluded.json": res_excl,
        "advisors_analysis.json": analysis_resp,
    }


def main():
    fixtures_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
    os.makedirs(fixtures_dir, exist_ok=True)
    for filename, payload in build_fixtures().items():
        path = os.path.join(fixtures_dir, filename)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        print(f"Wrote {path}")

    advisors = llm.load_advisors_library()
    eval_data = json.load(open(os.path.join(fixtures_dir, "advisors_eval.json"), encoding="utf-8"))
    analysis_data = json.load(open(os.path.join(fixtures_dir, "advisors_analysis.json"), encoding="utf-8"))
    frag_html = report.build_fragment(eval_data, analysis_data["analysis"], registry=llm.load_fields_registry(), advisors=advisors)
    frag_path = os.path.join(fixtures_dir, "advisors_fragment.html")
    with open(frag_path, "w", encoding="utf-8") as f:
        f.write(frag_html)
    print(f"Wrote {frag_path}")


if __name__ == "__main__":
    main()
