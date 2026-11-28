"""Agent7: 双轨分析（芒格）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "dual_track.db")

ADVISORS = [{'id': 'rational_bridge', 'name': '桥牌理性官', 'tag': '第一轨 · 客观利益 · 真实概率', 'principle': '像打桥牌一样，剥离情绪与故事，只看真正支配局面的客观利益、真实概率与商业规律。', 'focus': '拆解这件事背后的硬事实、真实赔率、各方利益诉求与长期基本面。'}, {'id': 'bias_hunter', 'name': '误判猎手', 'tag': '第二轨 · 潜意识心理排查', 'principle': '人类大脑的心理捷径平时很有用，但在关键决策时刻往往自动触发，让人得出荒谬结论。', 'focus': '逐项扫描社会认同、权威误导、承诺一致、稀缺焦虑、损失厌恶、锚定效应等潜意识陷阱。'}, {'id': 'incentive_check', 'name': '激励审计师', 'tag': '利益一致性 · 防忽悠', 'principle': '在双轨交叉处，最容易让人上当的是把对方的利益诉求误当成客观建议。', 'focus': '检查信息来源与推动者的真实激励，识别谁在从你的冲动中获利。'}, {'id': 'calibrator', 'name': '双轨校准官', 'tag': '冷静纠偏 · 可执行边界', 'principle': '双轨分析的终点不是否定行动，而是在剔除心理干扰后，做出配得上真实赔率的理性决策。', 'focus': '综合两条轨道的结论，给出冷静后的行动决策、观察窗口与反悔/止损边界。'}]

FIELDS_SCHEMA = [{'key': 'decision_topic', 'group': '第一轨：客观事实', 'label': '面临的核心决策/判断', 'placeholder': '例如：是否重仓某标的 / 是否加入朋友创业 / 是否签下某合作'}, {'key': 'objective_upside', 'group': '第一轨：客观事实', 'label': '明面上的收益与硬逻辑', 'placeholder': '例如：潜在回报、商业逻辑、可验证的数据或事实'}, {'key': 'real_odds', 'group': '第一轨：客观事实', 'label': '真实概率与下行风险', 'placeholder': '例如：最坏会亏多少、胜率大概几成、输了能否承受'}, {'key': 'other_incentives', 'group': '第一轨：客观事实', 'label': '相关方/推荐者的利益', 'placeholder': '例如：谁在极力推这件事？他们是拿佣金、找接盘还是共担风险？'}, {'key': 'emotional_trigger', 'group': '第二轨：心理状态', 'label': '当下最强烈的情绪/冲动', 'placeholder': '例如：怕错过(FOMO)、想翻本、碍于面子、被大V背书吸引'}, {'key': 'social_pressure', 'group': '第二轨：心理状态', 'label': '周围人的态度与氛围', 'placeholder': '例如：群里都在喊冲、权威大佬背书、朋友已经投了'}, {'key': 'sunk_cost', 'group': '第二轨：心理状态', 'label': '已投入的沉没成本/承诺', 'placeholder': '例如：已经研究了一个月 / 已经口头答应 / 之前亏过钱想回本'}, {'key': 'cooling_condition', 'group': '第二轨：心理状态', 'label': '如果延迟 7 天再决定会怎样', 'placeholder': '例如：机会真的会消失，还是只是人为制造的紧迫感？'}]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "双轨分析（芒格）"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields[FIELDS_SCHEMA[0]["key"]] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已初步提取核心主题，补充更多具体背景与约束条件后，智囊团分析会更犀利。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是「双轨分析（芒格）」结构化抽取助手。请从用户输入中提取关键信息，未提及的字段务必留空 ""，不要编造。

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
    topic = (fields.get(FIELDS_SCHEMA[0]["key"]) or raw_text or "双轨分析（芒格）").strip()[:28]
    return {
        "title": f"{topic} · 芒格双轨分析报告",
        "summary": "先用第一轨算清客观利益与真实赔率，再用第二轨剥离潜意识心理干扰，避免在关键时刻做出荒谬决策。",
        "pillars": [
            {"label": "第一轨：客观利益与概率", "content": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
            {"label": "第二轨：潜意识误判排查", "content": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
            {"label": "双轨校准后的最终判断", "content": "给出冷静、可验证、带安全边际的最终判断与防错边界。"},
        ],
        "sections": [
            {
                "heading": "一、核心拆解与关键发现",
                "items": [
                    {"name": "第一轨：客观利益与概率", "tag": "深度拆解", "detail": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
                    {"name": "第二轨：潜意识误判排查", "tag": "盲区预警", "detail": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
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
    prompt = f"""你是查理·芒格「双轨分析（Two-Track Analysis）」智囊团（源自1994年《普世智慧的探讨》）。遇到复杂决策时，必须同时运行两条轨道：第一轨冷静计算客观利益、真实概率与商业规律；第二轨专门排查潜意识误判倾向（社会认同、权威误导、承诺一致、稀缺、损失厌恶、沉没成本等）。

智囊团成员：
{advisors_desc}

用户原始输入：
{raw_text}

完善后的分析信息表：
{field_lines}

核心要求（必须严格遵守）：
- 紧扣用户的具体案例，拒绝空泛鸡汤与教科书式套话，直指要害
- pillars 固定 3 项，标题分别为：第一轨：客观利益与概率、第二轨：潜意识误判排查、双轨校准后的最终判断
- steps 为 4~5 步双轨决策执行清单（先做客观事实核验，再做心理误判隔离，最后给出冷静决策与边界）
- council_synthesis 提炼 4 位智囊的「合议共识」与「关键张力」
- 4 位智囊各自独立发声，给出立场标签、犀利判断与具体落地动作

只返回 JSON，不要多余文字：
{{
  "title": "报告标题，18字以内",
  "summary": "一句话核心结论，45字以内",
  "pillars": [
    {{ "label": "第一轨：客观利益与概率", "content": "45~90字深度拆解" }},
    {{ "label": "第二轨：潜意识误判排查", "content": "45~90字深度拆解" }},
    {{ "label": "双轨校准后的最终判断", "content": "45~90字深度拆解" }}
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
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent7")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        raise ValueError("模型返回结构不完整")
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
