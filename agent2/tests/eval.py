"""
CCagent 离线评估脚本 (tests/eval.py - v3 隔离与严谨版)
严格遵循规范：
A1 隔离生产数据：
   - 显式传入 context（取自用例的 context 字段，缺省为空串）；
   - 纠正默认传“（未启用纠偏）”，仅当给出 --corrections-file <path> 时才读取该文件；
   - 评估及其导入链路绝不调用 get_db()、init_db()，不读写 data/ccagent.db；
   - 旧参数 --with-corrections 报错并提示改用 --corrections-file。
A2 异常单列：
   - API 调用失败（含超时、4xx/5xx、解析失败）不回退到 fallback；
   - 该用例标记 status: error 并记录简短原因；
   - 准确率/召回率分母只含成功运行的用例，报告里单列 error 数；
   - 允许 --retries N（默认 0，只对 429/5xx 重试）；
   - --dry-run 仍可单独评估 fallback，但结果标记 engine: fallback，不与 AI 混排。
A3 保存完整输出：
   - 每个任务保存 title, domain, quadrant, confidence, expert_id, reason, advice, factors, assumptions；
   - 顶层保存 label, model, prompt, corrections_file, 耗时（平均/最大/最小）。
A4 可读报告：
   - 输出 tests/results/eval_<时间>_<label>.md；
   - 先列所有判错或 error 用例，再列判对用例；
   - 每个任务并排显示“输入片段｜期望｜实际｜reason｜advice”；
   - 文末附留空的人工评分表（具体性、依据可查性、有无套话 各打 1-3 分）。
A6 指标：
   - 领域准确率、象限准确率；
   - 拆分召回（被匹配上的期望任务占比）；
   - 多拆率（未匹配的实际任务占实际任务数的比例）；
   - 低置信度占比。
"""

import os
import sys
import json
import time
import argparse
import datetime
from collections import defaultdict

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(ROOT_DIR)

# 确保完全不调用生产 DB
import server

DEFAULT_CASES_FILE = os.path.join(ROOT_DIR, 'tests', 'golden', 'cases.json')
RESULTS_DIR = os.path.join(ROOT_DIR, 'tests', 'results')


def match_tasks(expected_tasks, actual_tasks):
    """
    匹配预期任务与模型实际输出任务。
    返回: (matched_pairs, unmatched_actuals)
    matched_pairs: [(expected_item, matched_actual_or_None), ...]
    unmatched_actuals: [actual_item, ...]
    """
    matches = []
    unmatched_actuals = list(actual_tasks)

    # 快捷通道：单任务对单任务
    if len(expected_tasks) == 1 and len(actual_tasks) == 1:
        return [(expected_tasks[0], actual_tasks[0])], []

    for exp in expected_tasks:
        exp_title = exp.get('title', exp.get('input', '')).strip().lower()
        clean_exp = "".join(ch for ch in exp_title if ch.isalnum() or '\u4e00' <= ch <= '\u9fff')
        
        best_match = None
        best_score = 0.0
        best_idx = -1

        for idx, act in enumerate(unmatched_actuals):
            act_title = act.get('title', '').strip().lower()
            clean_act = "".join(ch for ch in act_title if ch.isalnum() or '\u4e00' <= ch <= '\u9fff')
            if not clean_act or not clean_exp:
                continue

            if clean_exp in clean_act or clean_act in clean_exp:
                score = 1.0
            else:
                set_exp = set(clean_exp)
                set_act = set(clean_act)
                intersection = set_exp.intersection(set_act)
                union = set_exp.union(set_act)
                score = len(intersection) / len(union) if union else 0.0

            if score > best_score:
                best_score = score
                best_match = act
                best_idx = idx

        if best_match is not None and best_score >= 0.25:
            matches.append((exp, best_match))
            unmatched_actuals.pop(best_idx)
        else:
            matches.append((exp, None))

    return matches, unmatched_actuals


def run_evaluation(args):
    # 参数校验
    if getattr(args, 'with_corrections', False):
        print("\n❌ 错误：参数 --with-corrections 已废弃以防隐式依赖生产数据！")
        print("请改用 --corrections-file <path> 显式指定测试纠偏文件。\n")
        sys.exit(1)

    os.makedirs(RESULTS_DIR, exist_ok=True)
    cases_file = args.cases or DEFAULT_CASES_FILE

    if not os.path.exists(cases_file):
        print(f"❌ 错误：用例集文件不存在：{cases_file}")
        sys.exit(1)

    with open(cases_file, 'r', encoding='utf-8') as f:
        raw_data = json.load(f)

    test_runs = []
    for item in raw_data:
        if 'confirmed' in item and not item['confirmed'] and not args.include_unconfirmed:
            continue

        if 'expected_tasks' in item:
            test_runs.append({
                'case_id': item.get('case_id', item.get('id', 'case')),
                'input': item.get('raw_input', item.get('input', '')),
                'context': item.get('context', ''),
                'expected_tasks': item['expected_tasks'],
                'notes': item.get('notes', '')
            })
        elif 'expected_domain' in item:
            test_runs.append({
                'case_id': item.get('id', 'case'),
                'input': item.get('input', ''),
                'context': item.get('context', ''),
                'expected_tasks': [{
                    'title': item.get('input', ''),
                    'expected_domain': item.get('expected_domain'),
                    'expected_quadrant': item.get('expected_quadrant')
                }],
                'notes': item.get('notes', '')
            })

    total_runs = len(test_runs)
    if total_runs == 0:
        print(f"提示：在 {cases_file} 中没有找到可执行的测试用例（如需测试草稿请加 --include-unconfirmed）。")
        return None

    # 读取纠正文件 (完全隔离)
    corrections_content = "（未启用纠偏）"
    corrections_source = "none"
    if args.corrections_file:
        if not os.path.exists(args.corrections_file):
            print(f"❌ 错误：指定的纠偏文件不存在：{args.corrections_file}")
            sys.exit(1)
        with open(args.corrections_file, 'r', encoding='utf-8') as cf:
            corrections_content = cf.read()
        corrections_source = args.corrections_file

    env = server.load_env()
    api_key = env.get('GEMINI_API_KEY', '') if not args.dry_run else ''
    model = args.model if args.model else server.sanitize_model(env.get('GEMINI_MODEL', 'gemini-3.5-flash-lite'))
    base_url = env.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com')
    prompt_path = args.prompt if args.prompt else None
    label = args.label if args.label else 'eval'
    retries = args.retries

    print(f"\n=======================================================")
    print(f"CCagent 离线分诊评估 (Eval Suite v3 - 隔离版)")
    print(f"实验标签 (Label):       {label}")
    print(f"用例文件:              {cases_file} (共 {total_runs} 批次)")
    print(f"分诊模型:              {model if not args.dry_run else 'fallback 规则引擎'}")
    print(f"Prompt 模板:           {prompt_path or '默认 (prompts/triage_prompt.md)'}")
    print(f"纠偏文件 (Corrections): {corrections_source}")
    print(f"运行模式:              {'Dry-Run 保底规则' if args.dry_run else 'Gemini 智能分诊'}")
    print(f"=======================================================\n")

    cases_results = []
    error_count = 0
    success_latencies = []

    # 统计指标计数器（仅针对成功 run）
    total_expected_count = 0
    matched_expected_count = 0
    total_actual_count = 0
    unmatched_actual_count = 0

    domain_correct = 0
    quadrant_correct = 0
    low_confidence_count = 0

    confusion_domain = defaultdict(lambda: defaultdict(int))
    confusion_quadrant = defaultdict(lambda: defaultdict(int))

    for r_idx, run in enumerate(test_runs, 1):
        input_text = run['input']
        expected_tasks = run['expected_tasks']
        case_context = run['context']

        t0 = time.time()
        engine = 'fallback' if args.dry_run else 'ai'
        raw_tasks = []
        is_error = False
        error_msg = None

        if args.dry_run:
            raw_tasks = server.fallback_triage(input_text)
            duration = time.time() - t0
            success_latencies.append(duration)
        else:
            # AI 调用，支持 --retries N（仅对 429/5xx 重试）
            sys_prompt = server.build_system_prompt(
                custom_context=case_context,
                corrections_text=corrections_content,
                prompt_path=prompt_path
            )
            attempt = 0
            while attempt <= retries:
                try:
                    raw_tasks = server.call_gemini_api(
                        api_key=api_key,
                        model=model,
                        base_url=base_url,
                        user_text=input_text,
                        custom_prompt=sys_prompt
                    )
                    is_error = False
                    error_msg = None
                    break
                except Exception as e:
                    err_str = str(e)
                    is_retryable = ('429' in err_str or '500' in err_str or '503' in err_str or '504' in err_str)
                    if attempt < retries and is_retryable:
                        attempt += 1
                        print(f"   ⚠️ Run {r_idx:02d} 遭遇可重试错误 ({err_str[:40]}...)，等待 2 秒进行第 {attempt} 次重试...")
                        time.sleep(2)
                        continue
                    else:
                        is_error = True
                        error_msg = err_str
                        break

            duration = time.time() - t0
            if not is_error:
                success_latencies.append(duration)

        if is_error:
            error_count += 1
            print(f"Run {r_idx:02d} [{run['case_id']}] ❌ 执行异常 (耗时 {duration:.2f}s): {error_msg[:60]}")
            cases_results.append({
                'case_id': run['case_id'],
                'input': input_text,
                'context': case_context,
                'status': 'error',
                'error_message': error_msg,
                'engine': engine,
                'latency_sec': round(duration, 3),
                'expected_tasks': expected_tasks,
                'actual_tasks': [],
                'matched_pairs': [],
                'unmatched_actuals': []
            })
            continue

        # 规范化任务列表
        norm_actuals = []
        for t in raw_tasks:
            norm_item = server.normalize_task_item(t, engine=engine)
            norm_actuals.append(norm_item)

        total_expected_count += len(expected_tasks)
        total_actual_count += len(norm_actuals)

        # 匹配任务
        matched_pairs, unmatched_actuals = match_tasks(expected_tasks, norm_actuals)
        unmatched_actual_count += len(unmatched_actuals)

        matched_count_this_run = sum(1 for exp, act in matched_pairs if act is not None)
        matched_expected_count += matched_count_this_run

        print(f"Run {r_idx:02d} [{run['case_id']}] 耗时 {duration:.2f}s | 预期 {len(expected_tasks)} 条 | 实际 {len(norm_actuals)} 条 | 匹配 {matched_count_this_run} 条")

        task_matches_detail = []
        case_all_correct = True

        for exp, act in matched_pairs:
            exp_dom = exp.get('expected_domain', '')
            exp_quad = exp.get('expected_quadrant', '')

            if act:
                act_dom = act.get('domain', 'unknown')
                act_quad = act.get('quadrant', 'unknown')
                conf = act.get('confidence', 'medium')
                act_title = act.get('title', '')
                if conf == 'low':
                    low_confidence_count += 1
            else:
                act_dom = 'missing'
                act_quad = 'missing'
                conf = 'none'
                act_title = '(未拆出此任务)'

            is_dom_match = (act_dom == exp_dom)
            is_quad_match = (act_quad == exp_quad)
            if not (is_dom_match and is_quad_match):
                case_all_correct = False

            if is_dom_match:
                domain_correct += 1
            if is_quad_match:
                quadrant_correct += 1

            confusion_domain[exp_dom][act_dom] += 1
            confusion_quadrant[exp_quad][act_quad] += 1

            status_icon = '✅' if (is_dom_match and is_quad_match) else '⚠️'
            exp_title = exp.get('title', exp.get('input', ''))
            print(f"   {status_icon} 任务: '{exp_title[:15]}' -> 预期 [{exp_dom}|{exp_quad}] 实际 [{act_dom}|{act_quad}] (置信度: {conf})")

            task_matches_detail.append({
                'expected_title': exp_title,
                'actual_title': act_title,
                'expected_domain': exp_dom,
                'actual_domain': act_dom,
                'expected_quadrant': exp_quad,
                'actual_quadrant': act_quad,
                'confidence': conf,
                'domain_match': is_dom_match,
                'quadrant_match': is_quad_match,
                'reason': act.get('reason', '') if act else '',
                'advice': act.get('advice', '') if act else '',
                'factors': act.get('factors', {}) if act else {},
                'assumptions': act.get('assumptions', []) if act else [],
                'expert_id': act.get('expert_id', '') if act else ''
            })

        cases_results.append({
            'case_id': run['case_id'],
            'input': input_text,
            'context': case_context,
            'status': 'success',
            'all_correct': case_all_correct,
            'engine': engine,
            'latency_sec': round(duration, 3),
            'expected_tasks': expected_tasks,
            'actual_tasks': norm_actuals,
            'matched_pairs': task_matches_detail,
            'unmatched_actuals': unmatched_actuals
        })

    # 计算指标
    successful_runs = total_runs - error_count
    dom_acc = domain_correct / total_expected_count if total_expected_count else 0.0
    quad_acc = quadrant_correct / total_expected_count if total_expected_count else 0.0
    split_recall = matched_expected_count / total_expected_count if total_expected_count else 0.0
    over_split_ratio = unmatched_actual_count / total_actual_count if total_actual_count else 0.0
    low_conf_ratio = low_confidence_count / total_actual_count if total_actual_count else 0.0

    avg_latency = sum(success_latencies) / len(success_latencies) if success_latencies else 0.0
    max_latency = max(success_latencies) if success_latencies else 0.0
    min_latency = min(success_latencies) if success_latencies else 0.0

    print(f"\n=======================================================")
    print(f"评估完成总结 ({label})")
    print(f"总批次数:                     {total_runs} (成功 {successful_runs}, 失败/Error {error_count})")
    print(f"评估总期望任务数:             {total_expected_count}")
    print(f"领域准确率 (Domain Accuracy):     {dom_acc:.1%} ({domain_correct}/{total_expected_count})")
    print(f"象限准确率 (Quadrant Accuracy):   {quad_acc:.1%} ({quadrant_correct}/{total_expected_count})")
    print(f"拆分召回率 (Split Recall):        {split_recall:.1%} ({matched_expected_count}/{total_expected_count})")
    print(f"多拆率 (Over-split Ratio):        {over_split_ratio:.1%} ({unmatched_actual_count}/{total_actual_count})")
    print(f"低置信度占比 (Low Conf Ratio):    {low_conf_ratio:.1%} ({low_confidence_count}/{total_actual_count})")
    print(f"单次耗时 (平均 / 最大 / 最小):    {avg_latency:.2f}s / {max_latency:.2f}s / {min_latency:.2f}s")
    print(f"=======================================================\n")

    timestamp_str = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
    result_data = {
        'label': label,
        'timestamp': datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'model': model if not args.dry_run else 'fallback',
        'prompt_file': prompt_path or 'default (prompts/triage_prompt.md)',
        'corrections_file': corrections_source,
        'engine': 'fallback' if args.dry_run else 'ai',
        'total_runs': total_runs,
        'successful_runs': successful_runs,
        'error_runs': error_count,
        'total_expected_tasks': total_expected_count,
        'total_actual_tasks': total_actual_count,
        'domain_accuracy': round(dom_acc, 4),
        'quadrant_accuracy': round(quad_acc, 4),
        'split_recall': round(split_recall, 4),
        'over_split_ratio': round(over_split_ratio, 4),
        'low_confidence_ratio': round(low_conf_ratio, 4),
        'latency': {
            'avg_sec': round(avg_latency, 3),
            'max_sec': round(max_latency, 3),
            'min_sec': round(min_latency, 3)
        },
        'confusion_domain': {k: dict(v) for k, v in confusion_domain.items()},
        'confusion_quadrant': {k: dict(v) for k, v in confusion_quadrant.items()},
        'cases': cases_results
    }

    # 1. 写入 json 文件
    out_json = os.path.join(RESULTS_DIR, f"eval_{timestamp_str}_{label}.json")
    with open(out_json, 'w', encoding='utf-8') as f:
        json.dump(result_data, f, ensure_ascii=False, indent=2)

    # 2. 写入可读 markdown 报告 (A4 要求)
    out_md = os.path.join(RESULTS_DIR, f"eval_{timestamp_str}_{label}.md")
    write_markdown_report(out_md, result_data)

    print(f"JSON 报告已保存至: {out_json}")
    print(f"Markdown 报告已保存至: {out_md}\n")
    return result_data


def write_markdown_report(md_path, res):
    """生成结构化、易读且带人工评分表的 Markdown 评测报告"""
    lines = []
    lines.append(f"# 🧪 CCagent 分诊评估报告 · {res['label']}")
    lines.append(f"- **评估时间**: {res['timestamp']}")
    lines.append(f"- **模型**: `{res['model']}` | **Prompt**: `{res['prompt_file']}`")
    lines.append(f"- **纠偏来源**: `{res['corrections_file']}` | **引擎**: `{res['engine']}`")
    lines.append(f"- **总批次数**: {res['total_runs']} (成功 {res['successful_runs']}, 错误 {res['error_runs']})")
    lines.append(f"- **指标总结**:")
    lines.append(f"  - **象限准确率**: **{res['quadrant_accuracy']:.1%}**")
    lines.append(f"  - **领域准确率**: **{res['domain_accuracy']:.1%}**")
    lines.append(f"  - **拆分召回率**: {res['split_recall']:.1%} ｜ **多拆率**: {res['over_split_ratio']:.1%}")
    lines.append(f"  - **耗时**: 平均 {res['latency']['avg_sec']}s / 最大 {res['latency']['max_sec']}s / 最小 {res['latency']['min_sec']}s")
    lines.append("\n---\n")

    cases = res.get('cases', [])
    err_or_wrong = [c for c in cases if c['status'] == 'error' or not c.get('all_correct', False)]
    correct_cases = [c for c in cases if c['status'] == 'success' and c.get('all_correct', False)]

    # 1. 判错或 Error 的用例
    lines.append("## ❌ 待核查用例（判错或执行异常）\n")
    if not err_or_wrong:
        lines.append("（本轮无判错或异常用例，全部匹配通过！）\n")
    else:
        for c in err_or_wrong:
            lines.append(f"### 用例 `{c['case_id']}` ({'异常' if c['status'] == 'error' else '部分判错'})")
            lines.append(f"- **原始输入**: `{c['input']}`")
            if c.get('context'):
                lines.append(f"- **上下文 (Context)**: `{c['context']}`")
            if c['status'] == 'error':
                lines.append(f"- **错误信息**: `{c.get('error_message')}`")
            else:
                lines.append("| 任务标题片段 | 期望 [领域|象限] | 实际 [领域|象限] | 💡 判断 (Reason) | 🎯 建议 (Advice) |")
                lines.append("| :--- | :--- | :--- | :--- | :--- |")
                for p in c.get('matched_pairs', []):
                    icon = "✅" if (p['domain_match'] and p['quadrant_match']) else "⚠️"
                    lines.append(f"| {icon} {p['expected_title'][:20]} | `[{p['expected_domain']}|{p['expected_quadrant']}]` | `[{p['actual_domain']}|{p['actual_quadrant']}]` | {p['reason']} | {p['advice']} |")
            lines.append("")

    # 2. 判对的用例
    lines.append("## ✅ 判定正确的用例\n")
    if not correct_cases:
        lines.append("（无全对用例）\n")
    else:
        for c in correct_cases:
            lines.append(f"### 用例 `{c['case_id']}` (全部正确)")
            lines.append(f"- **原始输入**: `{c['input']}`")
            lines.append("| 任务标题片段 | 期望 [领域|象限] | 实际 [领域|象限] | 💡 判断 (Reason) | 🎯 建议 (Advice) |")
            lines.append("| :--- | :--- | :--- | :--- | :--- |")
            for p in c.get('matched_pairs', []):
                lines.append(f"| ✅ {p['expected_title'][:20]} | `[{p['expected_domain']}|{p['expected_quadrant']}]` | `[{p['actual_domain']}|{p['actual_quadrant']}]` | {p['reason']} | {p['advice']} |")
            lines.append("")

    # 3. 留空的人工评分表 (A4 明确要求)
    lines.append("## 📝 人工评分表（留空供填）\n")
    lines.append("请对以下用例的 Reason（判断）与 Advice（破局建议）进行人工质检打分（每项打 1–3 分）：")
    lines.append("- **具体性** (1: 抽象套话 ➜ 3: 具体结合任务事实)")
    lines.append("- **依据可查性** (1: 凭空捏造 ➜ 3: 依据清晰因果合乎逻辑)")
    lines.append("- **有无套话** (1: 充斥AI说教/废话 ➜ 3: 纯粹精准中立行动指令)\n")

    lines.append("| 用例 ID | 任务标题 | 💡 具体性 (1-3) | 🔍 依据可查 (1-3) | 🚫 无套话 (1-3) | 评语与修改备注 |")
    lines.append("| :--- | :--- | :---: | :---: | :---: | :--- |")
    for c in cases:
        if c['status'] == 'success':
            for p in c.get('matched_pairs', []):
                title = p.get('actual_title') or p.get('expected_title')
                lines.append(f"| `{c['case_id']}` | {title[:25]} | | | | |")

    lines.append("\n")

    with open(md_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="CCagent 离线评估工具 v3")
    parser.add_argument('--cases', type=str, help="用例集路径")
    parser.add_argument('--prompt', type=str, help="指定系统分诊 prompt 模板文件")
    parser.add_argument('--model', type=str, help="指定评测模型")
    parser.add_argument('--corrections-file', type=str, help="指定纠偏记录文本文件路径")
    parser.add_argument('--with-corrections', action='store_true', help="(已废弃，将提示报错)")
    parser.add_argument('--label', type=str, default="eval", help="实验标签标识符")
    parser.add_argument('--retries', type=int, default=0, help="429/5xx 错误重试次数 (默认 0)")
    parser.add_argument('--include-unconfirmed', action='store_true', help="包含未人工确认的草稿用例")
    parser.add_argument('--dry-run', action='store_true', help="纯保底规则运行，不调用 API")
    args = parser.parse_args()

    run_evaluation(args)
