"""
tests/compare.py (A5 对比脚本)
读取 tests/results/ 下指定的多份 json 评测结果，输出横向指标对比表。
指标包含：label, 有效用例数, error 数, 领域准确率, 象限准确率, 拆分召回, 多拆率, 低置信占比, 平均耗时, 最大耗时。
支持命令行传入多个 json 文件路径，若未提供参数则默认对比 results 目录下最新的 2-5 份结果。
"""

import os
import sys
import json
import glob
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS_DIR = os.path.join(ROOT_DIR, 'tests', 'results')


def compare_results(file_paths):
    if not file_paths:
        # 自动获取最近的 json 文件
        json_files = sorted(glob.glob(os.path.join(RESULTS_DIR, 'eval_*.json')), key=os.path.getmtime)
        if not json_files:
            print(f"❌ 未在 {RESULTS_DIR} 找到任何评测 json 文件。")
            return
        file_paths = json_files[-4:]  # 最多取最近 4 份

    reports = []
    for fp in file_paths:
        if not os.path.exists(fp):
            print(f"⚠️ 文件不存在跳过: {fp}")
            continue
        try:
            with open(fp, 'r', encoding='utf-8') as f:
                data = json.load(f)
                reports.append((os.path.basename(fp), data))
        except Exception as e:
            print(f"⚠️ 解析失败跳过 {fp}: {e}")

    if not reports:
        print("未加载到有效的评测报告数据。")
        return

    print(f"\n==========================================================================================================")
    print(f"CCagent 分诊评估横向对比 (Eval Comparison)")
    print(f"==========================================================================================================")

    headers = [
        ("实验标签 (Label)", 18),
        ("模型", 20),
        ("成功/总数", 10),
        ("Error", 6),
        ("象限准确率", 11),
        ("领域准确率", 11),
        ("拆分召回", 9),
        ("多拆率", 8),
        ("低置信比", 9),
        ("平均耗时", 9),
        ("最大耗时", 9),
    ]

    header_str = " | ".join(h[0].ljust(h[1]) for h in headers)
    separator_str = "-+-".join("-" * h[1] for h in headers)

    print(header_str)
    print(separator_str)

    for fname, d in reports:
        label = str(d.get('label', 'unknown'))[:18].ljust(18)
        model = str(d.get('model', 'unknown'))[:20].ljust(20)
        
        succ = d.get('successful_runs', d.get('total_runs', 0))
        tot = d.get('total_runs', 0)
        runs_str = f"{succ}/{tot}".ljust(10)

        err_str = str(d.get('error_runs', 0)).ljust(6)

        quad_acc = d.get('quadrant_accuracy', 0.0)
        quad_str = f"{quad_acc:.1%}".ljust(11)

        dom_acc = d.get('domain_accuracy', 0.0)
        dom_str = f"{dom_acc:.1%}".ljust(11)

        split_rec = d.get('split_recall', 1.0)
        split_str = f"{split_rec:.1%}".ljust(9)

        over_split = d.get('over_split_ratio', 0.0)
        over_str = f"{over_split:.1%}".ljust(8)

        low_conf = d.get('low_confidence_ratio', 0.0)
        low_str = f"{low_conf:.1%}".ljust(9)

        lat = d.get('latency', {})
        if isinstance(lat, dict):
            avg_lat = f"{lat.get('avg_sec', 0.0):.2f}s".ljust(9)
            max_lat = f"{lat.get('max_sec', 0.0):.2f}s".ljust(9)
        else:
            avg_lat = f"{d.get('avg_latency_sec', 0.0):.2f}s".ljust(9)
            max_lat = "-".ljust(9)

        row_str = f"{label} | {model} | {runs_str} | {err_str} | {quad_str} | {dom_str} | {split_rec:.1%}".ljust(len(header_str))
        print(f"{label} | {model} | {runs_str} | {err_str} | {quad_str} | {dom_str} | {split_str} | {over_str} | {low_str} | {avg_lat} | {max_lat}")

    print(f"==========================================================================================================\n")


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="对比 CCagent 评测报告")
    parser.add_argument('files', nargs='*', help="指定要对比的 json 文件列表")
    args = parser.parse_args()

    compare_results(args.files)
