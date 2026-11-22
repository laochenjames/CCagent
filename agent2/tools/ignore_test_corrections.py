"""
tools/ignore_test_corrections.py
列出并标记测试性的用户纠偏记录（将 correction_ignored 设为 1）。
默认模式：仅列出所有 user_moved=1 的任务及当前状态，不修改数据库。
--apply 模式：对已知测试项或指定项进行确认并写入 correction_ignored=1。
保留全部原始数据，不删除，不改变任务当前象限。
"""

import os
import sys
import sqlite3
import argparse

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.path.join(ROOT_DIR, 'data', 'ccagent.db')


def list_and_ignore_corrections(apply=False, target_keyword="阅读圣经与李敖著作"):
    if not os.path.exists(DB_PATH):
        print(f"数据库不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

    # 确保字段存在
    cols = [col[1] for col in c.execute('PRAGMA table_info(tasks)').fetchall()]
    if 'correction_ignored' not in cols:
        c.execute('ALTER TABLE tasks ADD COLUMN correction_ignored INTEGER DEFAULT 0')
        conn.commit()

    rows = c.execute("""
        SELECT id, title, domain, quadrant, ai_domain, ai_quadrant, user_moved, correction_ignored, updated_at
        FROM tasks
        WHERE user_moved = 1
        ORDER BY updated_at DESC
    """).fetchall()

    print(f"\n=======================================================")
    print(f"CCagent 用户纠偏记录管理器 (user_moved = 1)")
    print(f"当前共找到 {len(rows)} 条被手动调整过的任务记录:")
    print(f"=======================================================\n")

    matched_for_ignore = []

    for idx, r in enumerate(rows, 1):
        status_tag = "【已忽略】" if r['correction_ignored'] else "【生效中】"
        is_target = target_keyword in (r['title'] or '')
        marker = "👉 [待处理目标]" if is_target else "  "
        print(f"{marker} [{idx:02d}] {status_tag} {r['id']} | 「{r['title']}」")
        print(f"     领域: AI={r['ai_domain']} -> 当前={r['domain']} | 象限: AI={r['ai_quadrant']} -> 当前={r['quadrant']}")
        print(f"     更新时间: {r['updated_at']}")

        if is_target:
            matched_for_ignore.append(r)

    print("\n-------------------------------------------------------")

    if not apply:
        print(f"提示：当前为只读展示模式。若要对测试项写入忽略，请运行：")
        print(f"python tools/ignore_test_corrections.py --apply")
        conn.close()
        return

    if not matched_for_ignore:
        print(f"未匹配到包含「{target_keyword}」的待忽略记录。")
        conn.close()
        return

    print(f"准备对以下 {len(matched_for_ignore)} 条测试记录执行 correction_ignored = 1：")
    for item in matched_for_ignore:
        print(f" - {item['id']}: 「{item['title']}」 (保留数据与象限，仅将其移出提示词纠偏候选)")

    confirm = input("\n请确认是否应用修改？(y/N): ").strip().lower()
    if confirm in ['y', 'yes']:
        for item in matched_for_ignore:
            c.execute("UPDATE tasks SET correction_ignored = 1 WHERE id = ?", (item['id'],))
        conn.commit()
        print(f"✅ 成功将 {len(matched_for_ignore)} 条测试纠偏标记为 correction_ignored = 1！")
    else:
        print("操作已取消，未做任何修改。")

    conn.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="CCagent 测试纠偏清理与管理工具")
    parser.add_argument('--apply', action='store_true', help="应用修改并将测试项标记为忽略")
    parser.add_argument('--keyword', type=str, default="阅读圣经与李敖著作", help="要忽略的目标标题关键词")
    args = parser.parse_args()

    list_and_ignore_corrections(apply=args.apply, target_keyword=args.keyword)
