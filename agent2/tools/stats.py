"""
CCagent 用户改动率统计工具 (tools/stats.py)
读取 SQLite 数据库，统计最近 N 次分诊或近期任务中，各象限与领域被用户人工调整 (user_moved) 的比例。
"""

import os
import sys
import sqlite3

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, 'data', 'ccagent.db')


def show_stats(limit_runs=10):
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 获取最近 N 次运行的 ID
    c.execute('SELECT id, created_at, model, engine FROM triage_runs ORDER BY created_at DESC LIMIT ?', (limit_runs,))
    runs = c.fetchall()
    run_ids = [r['id'] for r in runs]

    print("\n=======================================================")
    print(f"CCagent 分诊人工改动率统计 (基于最近 {len(runs)} 次分诊)")
    print("=======================================================\n")

    if not run_ids:
        c.execute('SELECT COUNT(*) as cnt FROM tasks')
        total_tasks = c.fetchone()['cnt']
        c.execute('SELECT COUNT(*) as cnt FROM tasks WHERE user_moved = 1')
        moved_tasks = c.fetchone()['cnt']
        rate = (moved_tasks / total_tasks) if total_tasks else 0.0
        print(f"当前全部任务数: {total_tasks}，人工调整过象限/领域的任务数: {moved_tasks} (改动率: {rate:.1%})\n")
    else:
        placeholders = ','.join('?' * len(run_ids))
        c.execute(f'''
            SELECT COUNT(*) as total,
                   SUM(user_moved) as moved,
                   SUM(CASE WHEN status = "done" THEN 1 ELSE 0 END) as done_cnt,
                   SUM(CASE WHEN status = "removed" THEN 1 ELSE 0 END) as removed_cnt
            FROM tasks
            WHERE run_id IN ({placeholders})
        ''', run_ids)
        row = c.fetchone()
        tot = row['total'] or 0
        mov = row['moved'] or 0
        done_cnt = row['done_cnt'] or 0
        rem_cnt = row['removed_cnt'] or 0
        rate = (mov / tot) if tot else 0.0

        print(f"总计分流任务: {tot} 项")
        print(f"人工改动象限/领域: {mov} 项 (改动率: {rate:.1%})")
        print(f"已打勾完成: {done_cnt} 项")
        print(f"已删除归档: {rem_cnt} 项\n")

        # 统计象限流转详情
        c.execute(f'''
            SELECT from_value, to_value, COUNT(*) as cnt
            FROM feedback_events
            WHERE run_id IN ({placeholders}) AND type = 'quadrant'
            GROUP BY from_value, to_value
        ''', run_ids)
        moves = c.fetchall()
        if moves:
            print("象限调整流向 (From -> To):")
            for m in moves:
                print(f"  {m['from_value']} -> {m['to_value']}: {m['cnt']} 次")
            print()

        # 统计各象限稳定性
        c.execute(f'''
            SELECT ai_quadrant, COUNT(*) as total, SUM(user_moved) as moved
            FROM tasks
            WHERE run_id IN ({placeholders})
            GROUP BY ai_quadrant
        ''', run_ids)
        quad_stats = c.fetchall()
        if quad_stats:
            print("AI 初始象限稳定性 (未被改动比例):")
            for qs in quad_stats:
                t = qs['total']
                m = qs['moved']
                stable_rate = ((t - m) / t) if t else 0.0
                print(f"  {qs['ai_quadrant'].upper()}: 共 {t} 项，用户保留 {t - m} 项 (稳定性: {stable_rate:.1%})")
            print()

    conn.close()


if __name__ == '__main__':
    limit = 10
    if len(sys.argv) > 1 and sys.argv[1].isdigit():
        limit = int(sys.argv[1])
    show_stats(limit)

