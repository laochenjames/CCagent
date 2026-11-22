"""Agent7: 双轨思维（A 轨稳态底线 + B 轨高赔率探索）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "dual_track.db")

ADVISORS = [
    {
        "id": "track_a_guard",
        "name": "A 轨守门人",
        "tag": "确定性 · 现金流 · 底线轨",
        "principle": "没有稳固的 A 轨托底，B 轨探索就会变成孤注一掷的赌博；先确保输不起的底线绝对安全。",
        "focus": "定义当下必须守住的基本盘（收入、核心交付、健康或主业），防止双轨变两头空。",
    },
    {
        "id": "track_b_scout",
        "name": "B 轨探险家",
        "tag": "高赔率 · 长期复利 · 探索轨",
        "principle": "只守 A 轨容易陷入温水煮青蛙；必须用小成本、高赔率的 B 轨持续押注未来非线性增量。",
        "focus": "设计低风险、高上限的 B 轨探索项目，确保每次试错都能沉淀资产或认知。",
    },
    {
        "id": "allocator",
        "name": "资源配比官",
        "tag": "杠铃配置 · 隔离防内耗",
        "principle": "双轨最怕精力混用；必须用物理时间块和明确比例（如 70/30 或 80/20）把两轨彻底隔离。",
        "focus": "给出具体的时间/资金配比方案，并设计防止两轨互相抢占注意力的边界规则。",
    },
    {
        "id": "switch_officer",
        "name": "切轨触发官",
        "tag": "量化阈值 · 晋级与止损",
        "principle": "双轨不是永远平行，而是为了在合适时机完成切换；提前定好客观信号，避免情绪化决策。",
        "focus": "明确“B 轨升格为主轨”的晋级条件，以及“果断砍掉当前 B 轨”的止损红线。",
    },
]

FIELDS_SCHEMA = [
    {"key": "core_dilemma", "group": "双轨现状", "label": "当前面临的双轨抉择", "placeholder": "例如：主业稳定但没增长 vs 副业有前景但不确定；守现有产品 vs 开新方向"},
    {"key": "track_a_base", "group": "双轨现状", "label": "A 轨基本盘（稳态/生存）", "placeholder": "例如：目前主业月薪 2 万 / 已有老业务稳定现金流"},
    {"key": "track_b_option", "group": "双轨现状", "label": "B 轨探索项（增量/高赔率）", "placeholder": "例如：做 AI 工具矩阵 / 自媒体内容变现 / 量化策略"},
    {"key": "total_resources", "group": "双轨现状", "label": "可支配总资源（时间/资金）", "placeholder": "例如：每周可投入 55 小时，闲置试错资金 3 万元"},
    {"key": "bottom_line", "group": "配比与切轨", "label": "绝不能跌破的底线", "placeholder": "例如：不能断现金流、不能影响家人生活、每天睡够 7 小时"},
    {"key": "conflict_point", "group": "配比与切轨", "label": "两轨最大的冲突/内耗点", "placeholder": "例如：白天主业耗干精力，晚上 B 轨总拖延；或 B 轨太急影响主业"},
    {"key": "upgrade_signal", "group": "配比与切轨", "label": "理想中的切轨/加码信号", "placeholder": "例如：B 轨连续 3 个月净收入达到主业的 50%"},
    {"key": "review_cycle", "group": "配比与切轨", "label": "复盘与评估周期", "placeholder": "例如：每 2 周小复盘，满 90 天决定继续加码还是换 B 轨"},
]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "双轨决策"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields["core_dilemma"] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已提取双轨抉择，建议补充“A 轨基本盘”和“绝不能跌破的底线”，便于设计安全配比。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是双轨思维分析的结构化抽取助手。请从用户输入中提取关键信息，未提及的字段留空 ""，不要编造。

用户输入：
{raw_text}

只返回 JSON：
{{
  "fields": {{
{keys_desc}
  }},
  "summary_note": "一句话提示用户最值得补充哪 1~2 项信息（35字以内）"
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900, tag="Agent7")
    rf = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(rf.get(f["key"]) or "").strip() for f in FIELDS_SCHEMA}
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": str(parsed.get("summary_note") or "").strip() or "双轨信息已初步提取，补充底线与资源后配比方案更精准。",
    }


def _fallback_generate(raw_text, fields):
    dilemma = (fields.get("core_dilemma") or raw_text or "双轨并行").strip()[:16]
    return {
        "title": f"双轨策略：{dilemma}",
        "summary": "用 75% 确定性 A 轨锁死底线，用 25% 低成本 B 轨持续博取非线性增量，按客观阈值切轨。",
        "pillars": [
            {"label": "A 轨（稳态底线 · 75%）", "value": fields.get("track_a_base") or "守住现有核心现金流与基本盘，绝不因探索而动摇根基。"},
            {"label": "B 轨（高赔率探索 · 25%）", "value": fields.get("track_b_option") or "用固定时间块小步试错，优先验证真实需求与正向反馈。"},
            {"label": "切轨硬阈值", "value": fields.get("upgrade_signal") or "B 轨连续 2 个周期跑出稳定正反馈再加码；满 90 天无起色果断换题。"},
        ],
        "sections": [
            {
                "heading": "一、A / B 双轨职责与隔离边界",
                "items": [
                    {"name": "A 轨：稳态基本盘", "tag": "防守轨", "detail": "只追求稳定交付与现金流安全，不做无谓内卷，把多余精力释放给 B 轨。"},
                    {"name": "B 轨：高赔率实验田", "tag": "进攻轨", "detail": "设定严格成本上限（时间与资金封顶），每次迭代必须有可验证的外部反馈。"},
                ],
            },
            {
                "heading": "二、资源配比与时间隔离方案",
                "items": [
                    {"name": "物理时间块隔离", "tag": "防内耗", "detail": "A 轨与 B 轨绝不混在同一时间段切换，用固定时段保护 B 轨的深度思考。"},
                    {"name": "杠铃式投入比例", "tag": "75 / 25", "detail": "大部分资源稳稳托底，小部分资源专注高赔率方向，避免平庸中间态。"},
                ],
            },
            {
                "heading": "三、切轨信号（加码 vs 止损）",
                "items": [
                    {"name": "晋级信号（B 轨升格）", "tag": "加码", "detail": "连续 2~3 个月产生可复现的真实收入或核心指标突破，配比上调至 50/50。"},
                    {"name": "止损信号（果断撤退）", "tag": "止损", "detail": "达到预设复盘周期仍无真实外部反馈，立刻归档经验并切换下一个 B 轨假设。"},
                ],
            },
        ],
        "council_synthesis": {
            "consensus": "四位智囊一致认为：绝不能在没有 A 轨托底的情况下盲目 All-in，也绝不能让 A 轨吞噬掉全部 B 轨时间。",
            "tension": "A 轨守门人主张保守 80/20，而 B 轨探险家希望尽快拿到足够样本；折中方案是用固定高精力时间块保障 B 轨质量。",
        },
        "council_notes": [
            {"id": "track_a_guard", "name": "A 轨守门人", "role": "确定性 · 底线轨", "stance": "守住底线", "verdict": "基本盘不稳时，任何 B 轨都会变形为焦虑赌博。", "action": "先列出 A 轨每月只需做到 80 分的底线清单，停止过度投入。"},
            {"id": "track_b_scout", "name": "B 轨探险家", "role": "高赔率 · 探索轨", "stance": "小步押注", "verdict": "B 轨的价值在于不对称赔率，而不是和 A 轨拼体力。", "action": "把 B 轨拆成 2 周内可见真反馈的最小实验，严控沉没成本。"},
            {"id": "allocator", "name": "资源配比官", "role": "杠铃配置 · 隔离", "stance": "物理隔离", "verdict": "精力碎片化是双轨并行失败的头号杀手。", "action": "每周固定划出 3 个不受打扰的 2 小时块专供 B 轨。"},
            {"id": "switch_officer", "name": "切轨触发官", "role": "量化阈值 · 止损", "stance": "硬性触发", "verdict": "没有提前写死的切轨标准，最后一定会靠情绪硬撑。", "action": "在日历上标出 90 天评估日，提前写下加码与止损的数字红线。"},
        ],
    }


def _generate_ai(raw_text, fields, cfg):
    flines = "\n".join(f"- {f['label']}：{(fields.get(f['key']) or '').strip() or '（未填写）'}" for f in FIELDS_SCHEMA)
    prompt = f"""你是 CCagent 的「双轨思维智囊团」，由 4 位专业顾问组成：
1. A 轨守门人（确定性/现金流/底线轨）
2. B 轨探险家（高赔率/长期复利/探索轨）
3. 资源配比官（杠铃配置/时间精力隔离防内耗）
4. 切轨触发官（晋级加码与止损撤退的客观阈值）

用户原始输入：
{raw_text}

用户完善的双轨信息表：
{flines}

请严格按以下 JSON 结构输出，语言专业、具体、像顶级战略顾问委员会的合议备忘录：
{{
  "title": "双轨策略标题，16字以内",
  "summary": "一句话核心双轨配置结论，35字以内",
  "pillars": [
    {{ "label": "A 轨（稳态底线 · 建议占比）", "value": "A 轨具体定位与底线标准（35字以内）" }},
    {{ "label": "B 轨（高赔率探索 · 建议占比）", "value": "B 轨具体押注方向与上限（35字以内）" }},
    {{ "label": "切轨硬阈值", "value": "加码或止损的客观量化触发条件（35字以内）" }}
  ],
  "sections": [
    {{
      "heading": "一、A / B 双轨定位与边界",
      "items": [
        {{ "name": "A 轨核心任务（12字内）", "tag": "防守轨", "detail": "做什么、做到什么程度即可收手（35~60字）" }},
        {{ "name": "B 轨核心实验（12字内）", "tag": "进攻轨", "detail": "押注什么高赔率机会、如何控制试错成本（35~60字）" }}
      ]
    }},
    {{
      "heading": "二、资源配比与防内耗机制",
      "items": [
        {{ "name": "时间/精力配比（12字内）", "tag": "杠铃配置", "detail": "具体配比与每日/每周时间块切分方式（35~60字）" }},
        {{ "name": "隔离防火墙（12字内）", "tag": "防内耗", "detail": "如何防止两轨互相拖累或注意力切换损耗（35~60字）" }}
      ]
    }},
    {{
      "heading": "三、切轨信号（晋级 vs 止损）",
      "items": [
        {{ "name": "加码/升格信号（12字内）", "tag": "晋级阈值", "detail": "满足什么客观数据或事实后把 B 轨升格（35~60字）" }},
        {{ "name": "止损/换题信号（12字内）", "tag": "止损红线", "detail": "什么情况下果断停止当前 B 轨避免沉没成本（35~60字）" }}
      ]
    }}
  ],
  "council_synthesis": {{
    "consensus": "四位智囊达成的最大共识（35~55字）",
    "tension": "智囊之间最有价值的分歧或需要用户权衡的张力点（35~55字）"
  }},
  "council_notes": [
    {{ "id": "track_a_guard", "name": "A 轨守门人", "role": "确定性 · 底线轨", "stance": "守住底线", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "track_b_scout", "name": "B 轨探险家", "role": "高赔率 · 探索轨", "stance": "小步押注", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "allocator", "name": "资源配比官", "role": "杠铃配置 · 隔离", "stance": "物理隔离", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "switch_officer", "name": "切轨触发官", "role": "量化阈值 · 止损", "stance": "硬性触发", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }}
  ]
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent7")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list):
        raise ValueError("双轨思维输出结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent7",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
