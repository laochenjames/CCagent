"""
tools/export_cases.py
从 SQLite 数据库提取分诊历史（triage_runs 与关联 tasks），导出为测试草稿集 tests/golden/draft_cases_v2.json。
A7 规范要求：
1. 跳过 engine=fallback 的 run；
2. 同一 raw_input 只保留最近一次 AI run；
3. 预填 expected 的规则：若任务 correction_ignored=1，取 ai_quadrant/ai_domain，否则取当前值（quadrant/domain）；
4. 所有用例标记 confirmed: false；
5. 新增 needs_review_reason 字段，标明可疑点（例如：输入含“已完成”行、任务曾被用户拖拽修改过、包含模糊表述等）。
严格保护隐私与数据：严禁向评估集编造已确认用例，亦不泄露任何 Key 或敏感数据。
"""

import os
import sys
import json
import sqlite3
import re

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, 'data', 'ccagent.db')
OUTPUT_PATH = os.path.join(ROOT_DIR, 'tests', 'golden', 'draft_cases_v2.json')


def export_draft_cases_v2():
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 1. 仅获取 engine != 'fallback' 的 AI run，按时间从新到旧
    runs = c.execute("""
        SELECT id, input_text, context_snapshot, model, engine, created_at 
        FROM triage_runs 
        WHERE engine != 'fallback'
        ORDER BY created_at DESC
    """).fetchall()

    # 2. 同一 raw_input 只保留最近一次 AI run
    seen_inputs = set()
    deduped_runs = []
    for r in runs:
        inp = (r['input_text'] or '').strip()
        if not inp or inp in seen_inputs:
            continue
        seen_inputs.add(inp)
        deduped_runs.append(r)

    # 恢复正序以便给 case_id 编号
    deduped_runs.reverse()

    draft_cases = []

    for idx, run in enumerate(deduped_runs, 1):
        run_id = run['id']
        input_text = run['input_text']
        context_snap = run['context_snapshot']

        # 获取该 run 拆出的所有任务（非 removed 状态）
        tasks = c.execute("""
            SELECT id, title, domain, quadrant, ai_domain, ai_quadrant, 
                   reason, advice, factors, assumptions, confidence, expert_id, 
                   user_moved, correction_ignored
            FROM tasks
            WHERE run_id = ? AND status != 'removed'
            ORDER BY id ASC
        """, (run_id,)).fetchall()

        if not tasks:
            continue

        review_reasons = []
        if re.search(r'已完成[：:]|做完[：:]|完成[：:]', input_text):
            review_reasons.append("输入文本包含「已完成」前缀事项，需核对是否不应产出任务")

        expected_tasks = []
        has_user_moved = False
        for t in tasks:
            is_ignored = bool(t['correction_ignored'])
            is_moved = bool(t['user_moved'])
            if is_moved:
                has_user_moved = True

            # 3. 预填规则：若 correction_ignored=1 取 ai 值，否则取当前值
            if is_ignored:
                exp_dom = t['ai_domain'] or t['domain']
                exp_quad = t['ai_quadrant'] or t['quadrant']
            else:
                exp_dom = t['domain']
                exp_quad = t['quadrant']

            expected_tasks.append({
                "task_id": t['id'],
                "title": t['title'],
                "expected_domain": exp_dom,
                "expected_quadrant": exp_quad,
                "user_moved": is_moved,
                "correction_ignored": is_ignored,
                "ai_domain": t['ai_domain'],
                "ai_quadrant": t['ai_quadrant'],
                "archetype": t['expert_id'],
                "reason_hint": t['reason'],
                "advice_hint": t['advice'],
                "confidence": t['confidence']
            })

        if has_user_moved:
            review_reasons.append("包含用户手动拖拽或修改过的任务，需确认是否为真实偏好而非临时测试")

        draft_cases.append({
            "case_id": f"draft_v2_{idx:03d}",
            "source_run_id": run_id,
            "raw_input": input_text,
            "context": context_snap or "",
            "confirmed": False,  # 必须为 false，留待用户人工审查
            "needs_review_reason": "；".join(review_reasons) if review_reasons else "常规 AI 分诊批次",
            "notes": f"来源于 AI 运行 {run_id} ({run['model']})，共拆分 {len(expected_tasks)} 条任务",
            "expected_tasks": expected_tasks
        })

    conn.close()

    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    with open(OUTPUT_PATH, 'w', encoding='utf-8') as f:
        json.dump(draft_cases, f, ensure_ascii=False, indent=2)

    print(f"成功导出 {len(draft_cases)} 个运行批次至: {OUTPUT_PATH}")
    print(f"所有用例 confirmed 均标记为 false，严格遵守 A7 规范。")


if __name__ == '__main__':
    export_draft_cases_v2()
