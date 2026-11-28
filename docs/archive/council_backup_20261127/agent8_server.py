"""Agent8: 反向思考（事前验尸）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "inversion.db")

ADVISORS = [{'id': 'mortem_coroner', 'name': '事前验尸官', 'tag': '反过来想 · 死亡路径', 'principle': '反过来想，总是反过来想（Invert, always invert）；先假设项目已经彻底失败，倒推最可能的致命死因。', 'focus': '列出能把这件事直接搞死的 3 条最高概率路径，不留情面地戳破乐观假设。'}, {'id': 'breakpoint_eng', 'name': '断裂点工程师', 'tag': '工程学 · 阈值崩溃', 'principle': '系统承受压力不会线性缓慢下降，一旦越过某个断裂点（Breakpoint），会直接瞬间崩盘。', 'focus': '找出现金流、精力、口碑、技术或合作关系中最脆弱的单点故障与崩溃阈值。'}, {'id': 'backup_architect', 'name': '备份系统设计师', 'tag': '冗余设计 · 安全边际', 'principle': '最可靠的模型是工程学备份系统（Backup System）：关键环节必须有双保险，绝不把命押在单一假设上。', 'focus': '为每个高危死因设计冗余备份、降级预案和实打实的安全边际。'}, {'id': 'avoidance_guard', 'name': '负面清单守门人', 'tag': '绝不做什么 · 止损红线', 'principle': '只要知道自己会死在哪里，就永远不要去那个地方；避开愚蠢比追求聪明更容易赢。', 'focus': '提炼出 3 条绝对不可触碰的“绝不做”负面清单与强制退出红线。'}]

FIELDS_SCHEMA = [{'key': 'project_goal', 'group': '目标与假设', 'label': '准备推进的目标/项目', 'placeholder': '例如：辞职做 AI 产品 / 合伙开店 / 押注某个新业务'}, {'key': 'core_assumption', 'group': '目标与假设', 'label': '最依赖的核心假设', 'placeholder': '例如：假设用户愿意每月付费 99 元 / 假设流量能自然裂变'}, {'key': 'resource_bet', 'group': '目标与假设', 'label': '准备押上的筹码（钱/时间）', 'placeholder': '例如：投入 20 万存款 + 6 个月全职时间'}, {'key': 'worst_outcome', 'group': '目标与假设', 'label': '最惨会是什么结果', 'placeholder': '例如：钱亏光且空窗半年 / 欠债 / 团队反目'}, {'key': 'fragile_link', 'group': '断裂点与备份', 'label': '目前最脆弱的环节', 'placeholder': '例如：不懂获客、单人全栈精力有限、依赖单一平台封号风险'}, {'key': 'external_shock', 'group': '断裂点与备份', 'label': '可能遭遇的外部黑天鹅', 'placeholder': '例如：大厂免费入场、政策收紧、API 涨价、合伙人退出'}, {'key': 'current_backup', 'group': '断裂点与备份', 'label': '现有的后路/安全垫', 'placeholder': '例如：还留有 1 年生活费 / 保留兼职收入 / 可随时回职场'}, {'key': 'stop_loss', 'group': '断裂点与备份', 'label': '预设的止损/撤退线', 'placeholder': '例如：3 个月没跑出 50 个付费用户就立刻止损'}]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "反向思考（事前验尸）"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields[FIELDS_SCHEMA[0]["key"]] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已初步提取核心主题，补充更多具体背景与约束条件后，智囊团分析会更犀利。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是「反向思考（事前验尸）」结构化抽取助手。请从用户输入中提取关键信息，未提及的字段务必留空 ""，不要编造。

用户输入：
{raw_text}

只返回 JSON：
{{
  "fields": {{
{keys_desc}
  }},
  "summary_note": "一句话提示用户最值得补充哪 1~2 项关键信息（35字以内）"
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900)
    raw_fields = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(raw_fields.get(f["key"]) or "").strip() for f in FIELDS_SCHEMA}
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": str(parsed.get("summary_note") or "").strip() or "信息已提取，补充空白项可获得更精准的智囊团分析。",
    }


def _fallback_generate(raw_text, fields):
    topic = (fields.get(FIELDS_SCHEMA[0]["key"]) or raw_text or "反向思考（事前验尸）").strip()[:28]
    return {
        "title": f"{topic} · 反向思考 · 事前验尸报告",
        "summary": "先找出最容易把这件事彻底搞死的路径与系统断裂点，再逐一装上工程学备份与负面清单红线。",
        "pillars": [
            {"label": "Top 1 致命死因", "content": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
            {"label": "系统断裂点（Breakpoint）", "content": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
            {"label": "工程学备份与安全边际", "content": "给出冷静、可验证、带安全边际的最终判断与防错边界。"},
        ],
        "sections": [
            {
                "heading": "一、核心拆解与关键发现",
                "items": [
                    {"name": "Top 1 致命死因", "tag": "深度拆解", "detail": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
                    {"name": "系统断裂点（Breakpoint）", "tag": "盲区预警", "detail": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
                ],
            },
            {
                "heading": "二、可执行行动与安全边界",
                "items": [
                    {"name": "第 1 步：剥离情绪与噪音", "tag": "落地", "detail": "把听来的故事、口号和群体情绪先放一边，只保留可验证的硬事实。"},
                    {"name": "第 2 步：设计安全边际与红线", "tag": "防错", "detail": "在行动前写下明确的止损红线、备份预案或观察窗口，不靠临场意志力。"},
                    {"name": "第 3 步：小步验证并复盘", "tag": "复盘", "detail": "用低成本动作验证核心假设，定期对照初始判断做复盘校准。"},
                ],
            },
        ],
        "council_synthesis": {
            "consensus": f"围绕「{topic}」，4 位智囊一致认为必须先看清底层结构与人性盲区，再决定是否投入重注。",
            "tension": "进攻视角希望抓住机会窗口，风控视角则强调在排除致命盲区前绝不越过安全边际。",
        },
        "council_notes": [
            {
                "id": a["id"],
                "name": a["name"],
                "role": a["tag"],
                "stance": "核心视角",
                "verdict": a["principle"],
                "action": a["focus"],
            }
            for a in ADVISORS
        ],
    }


def _generate_ai(raw_text, fields, cfg):
    field_lines = "\n".join(
        f"- {f['label']}：{(fields.get(f['key']) or '').strip() or '（未填写，请结合上下文合理推演）'}"
        for f in FIELDS_SCHEMA
    )
    advisors_desc = "\n".join(
        f"{i+1}. {a['name']}（{a['tag']}）：{a['principle']}"
        for i, a in enumerate(ADVISORS)
    )
    advisors_json = ",\n    ".join(
        f'{{ "id": "{a["id"]}", "name": "{a["name"]}", "role": "{a["tag"]}", "stance": "4字以内立场标签", "verdict": "针对该案例的一针见血判断（30~55字）", "action": "今天即可执行的具体动作（20~40字）" }}'
        for a in ADVISORS
    )
    prompt = f"""你是查理·芒格「反向思考（Inversion）+ 工程学断裂点与备份系统」智囊团。核心信条是“反过来想，总是反过来想”——先假设这件事已经彻底失败，精准定位致命死因、系统断裂点，再设计工程学双保险备份与绝不触碰的负面清单。

智囊团成员：
{advisors_desc}

用户原始输入：
{raw_text}

完善后的分析信息表：
{field_lines}

核心要求（必须严格遵守）：
- 紧扣用户的具体案例，拒绝空泛鸡汤与教科书式套话，直指要害
- pillars 固定 3 项，标题分别为：Top 1 致命死因、系统断裂点（Breakpoint）、工程学备份与安全边际
- steps 为 4~5 步防死与安全边际构建行动（按致命优先级排序，每步必须可落地、可检查）
- council_synthesis 提炼 4 位智囊的「合议共识」与「关键张力」
- 4 位智囊各自独立发声，给出立场标签、犀利判断与具体落地动作

只返回 JSON，不要多余文字：
{{
  "title": "报告标题，18字以内",
  "summary": "一句话核心结论，45字以内",
  "pillars": [
    {{ "label": "Top 1 致命死因", "content": "45~90字深度拆解" }},
    {{ "label": "系统断裂点（Breakpoint）", "content": "45~90字深度拆解" }},
    {{ "label": "工程学备份与安全边际", "content": "45~90字深度拆解" }}
  ],
  "sections": [
    {{
      "heading": "一、核心拆解与关键发现",
      "items": [
        {{ "name": "要点名称，14字以内", "tag": "核心洞察", "detail": "结合案例的具体分析（40~75字）" }}
      ]
    }},
    {{
      "heading": "二、可执行行动与安全边界",
      "items": [
        {{ "name": "行动步骤，14字以内", "tag": "落地动作", "detail": "做什么、怎么验证、为什么（40~75字）" }}
      ]
    }}
  ],
  "council_synthesis": {{
    "consensus": "4位智囊达成的核心共识（35~60字）",
    "tension": "智囊之间最关键的分歧或风险提醒（35~60字）"
  }},
  "council_notes": [
    {advisors_json}
  ]
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent8")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        raise ValueError("模型返回结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent8",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
