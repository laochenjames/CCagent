"""Agent9: 激励机制诊断"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "incentives.db")

ADVISORS = [{'id': 'incentive_mapper', 'name': '激励测绘师', 'tag': '超级反应 · 利益真相', 'principle': '给我看激励机制，我就能告诉你结果；永远不要听人们嘴上说什么，只看什么行为真正得到奖赏和惩罚。', 'focus': '画出局中各方的真实奖惩地图，揭露口号与真实激励之间的巨大裂缝。'}, {'id': 'bureaucracy_auditor', 'name': '官僚陷阱审计师', 'tag': '地盘意识 · 甩锅机制', 'principle': '组织变大后最致命的病是官僚主义与地盘意识：员工觉得把文件扔出自己的筐就算干完活了。', 'focus': '识别局部最优损害全局最优的KPI漏洞、形式主义与责任真空。'}, {'id': 'fedex_designer', 'name': '机制重构师', 'tag': '联邦快递法 · 顺人性设计', 'principle': '道德说教几乎永远无效；像联邦快递把按小时计薪改成按班次计薪一样，改规则就能一夜解决顽疾。', 'focus': '设计简单、直接、让参与者为了自身利益自动做出正确行为的新奖惩规则。'}, {'id': 'gaming_redteam', 'name': '钻空子红队', 'tag': '防作弊 · 二阶后果', 'principle': '任何新激励机制上线后，聪明人都会立刻寻找套利与刷数据的漏洞。', 'focus': '提前模拟新机制上线后的作弊手段与副作用，补上防刷与制衡条款。'}]

FIELDS_SCHEMA = [{'key': 'phenomenon', 'group': '现状与各方', 'label': '要诊断的现象/难题', 'placeholder': '例如：夜班分拣总延误 / 团队互相甩锅 / 用户不愿留存'}, {'key': 'desired_outcome', 'group': '现状与各方', 'label': '真正想要的结果', 'placeholder': '例如：包裹准时上飞机 / 交付质量提升 / 用户持续产出好内容'}, {'key': 'key_players', 'group': '现状与各方', 'label': '局中关键角色', 'placeholder': '例如：一线员工、中层主管、客户、平台算法'}, {'key': 'current_rewards', 'group': '现状与各方', 'label': '当前的奖惩/KPI规则', 'placeholder': '例如：按小时发薪 / 按工单数量考核 / 按短期销售额提成'}, {'key': 'distorted_behavior', 'group': '扭曲与重构', 'label': '实际出现的跑偏行为', 'placeholder': '例如：故意磨洋工赚加班费 / 只挑简单单子做 / 短期刷量'}, {'key': 'failed_attempts', 'group': '扭曲与重构', 'label': '试过但没用的办法', 'placeholder': '例如：开会强调价值观、发警告信、加更多审批流程'}, {'key': 'changeable_lever', 'group': '扭曲与重构', 'label': '你手头能改动的筹码', 'placeholder': '例如：奖金结构、流量分发权、下班时间、晋升标准'}, {'key': 'constraint', 'group': '扭曲与重构', 'label': '硬约束（预算/公平性等）', 'placeholder': '例如：总预算不能超标 / 不能引发老员工大规模抵触'}]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "激励机制诊断"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields[FIELDS_SCHEMA[0]["key"]] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已初步提取核心主题，补充更多具体背景与约束条件后，智囊团分析会更犀利。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是「激励机制诊断」结构化抽取助手。请从用户输入中提取关键信息，未提及的字段务必留空 ""，不要编造。

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
    topic = (fields.get(FIELDS_SCHEMA[0]["key"]) or raw_text or "激励机制诊断").strip()[:28]
    return {
        "title": f"{topic} · 激励机制诊断与重构方案",
        "summary": "停止道德说教，先看清当前规则到底在奖励什么跑偏行为，再用联邦快递式规则重构让利益与目标对齐。",
        "pillars": [
            {"label": "真实激励地图（明面 vs 暗面）", "content": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
            {"label": "核心激励扭曲点", "content": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
            {"label": "联邦快递式重构杠杆", "content": "给出冷静、可验证、带安全边际的最终判断与防错边界。"},
        ],
        "sections": [
            {
                "heading": "一、核心拆解与关键发现",
                "items": [
                    {"name": "真实激励地图（明面 vs 暗面）", "tag": "深度拆解", "detail": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
                    {"name": "核心激励扭曲点", "tag": "盲区预警", "detail": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
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
    prompt = f"""你是查理·芒格「激励机制超级反应倾向 + 官僚主义诊断」智囊团（源自《人类误判心理学》第1条）。铁律是“给我看激励机制，我就能告诉你结果”。禁止空洞的道德说教，必须直指真实奖惩结构，并给出联邦快递式的机制重构方案。

智囊团成员：
{advisors_desc}

用户原始输入：
{raw_text}

完善后的分析信息表：
{field_lines}

核心要求（必须严格遵守）：
- 紧扣用户的具体案例，拒绝空泛鸡汤与教科书式套话，直指要害
- pillars 固定 3 项，标题分别为：真实激励地图（明面 vs 暗面）、核心激励扭曲点、联邦快递式重构杠杆
- steps 为 4~5 步激励机制重构与防作弊落地步骤（把口号变成顺人性的硬规则）
- council_synthesis 提炼 4 位智囊的「合议共识」与「关键张力」
- 4 位智囊各自独立发声，给出立场标签、犀利判断与具体落地动作

只返回 JSON，不要多余文字：
{{
  "title": "报告标题，18字以内",
  "summary": "一句话核心结论，45字以内",
  "pillars": [
    {{ "label": "真实激励地图（明面 vs 暗面）", "content": "45~90字深度拆解" }},
    {{ "label": "核心激励扭曲点", "content": "45~90字深度拆解" }},
    {{ "label": "联邦快递式重构杠杆", "content": "45~90字深度拆解" }}
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
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent9")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        raise ValueError("模型返回结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent9",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
