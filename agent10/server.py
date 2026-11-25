"""Agent10: Lollapalooza 共振雷达"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "lollapalooza.db")

ADVISORS = [{'id': 'force_scanner', 'name': '共振因子扫描仪', 'tag': '多力叠加 · 同向共振', 'principle': 'Lollapalooza 效应不是 1+1=2，而是三四种心理倾向或商业力量朝同一方向叠加时产生的核爆级质变。', 'focus': '拆解出正在同时发力的 3~5 个具体心理倾向与商业飞轮，标出它们如何互相放大。'}, {'id': 'bubble_detector', 'name': '泡沫与反噬侦探', 'tag': '狂热甄别 · 退潮预判', 'principle': '负向 Lollapalooza 往往由社会认同+稀缺+嫉妒+权威背书驱动，一旦某个因子断裂就会雪崩。', 'focus': '区分“真实价值复利”与“纯情绪传销泡沫”，找出共振链条中最先可能断裂的那一环。'}, {'id': 'flywheel_builder', 'name': '正向飞轮架构师', 'tag': '临界质量 · 品牌复利', 'principle': '像可口可乐一样，把产品体验、渠道规模、条件反射与社会认同同向叠加，跨过临界质量后形成护城河。', 'focus': '提炼可复用的正向共振组合，指导用户如何在自己的业务/产品中合法合规地构建正反馈。'}, {'id': 'sober_anchor', 'name': '冷静隔离官', 'tag': '抽离群体 · 行动策略', 'principle': '身处 Lollapalooza 漩涡中心时，极少有人能靠意志力保持清醒，必须建立物理与规则隔离。', 'focus': '给出用户在面对这一现象时的明智姿态：借势、旁观、做空情绪还是立刻撤离。'}]

FIELDS_SCHEMA = [{'key': 'phenomenon_name', 'group': '现象与信号', 'label': '要拆解的爆火/狂热现象', 'placeholder': '例如：盲盒疯抢 / 某币暴涨 / 某网红品牌排队 3 小时 / 自己的产品飞轮'}, {'key': 'observed_signals', 'group': '现象与信号', 'label': '观察到的极端表现', 'placeholder': '例如：溢价 5 倍、全网刷屏、平时理性的人也跟着冲'}, {'key': 'crowd_emotion', 'group': '现象与信号', 'label': '群体情绪与传播方式', 'placeholder': '例如：晒单炫耀、害怕踏空、KOL 集体背书、限时限量'}, {'key': 'value_core', 'group': '现象与信号', 'label': '底层真实价值/产品力', 'placeholder': '例如：剥掉热度后，产品本身值不值这个价？有没有真实刚需？'}, {'key': 'user_role', 'group': '立场与目的', 'label': '你在这个局里的角色', 'placeholder': '例如：想跟风买的消费者 / 想投资的旁观者 / 想借鉴玩法的创业者'}, {'key': 'suspected_forces', 'group': '立场与目的', 'label': '你隐约感觉到的驱动力', 'placeholder': '例如：从众心理 + 赌博随机奖励 + 社交货币'}, {'key': 'risk_worry', 'group': '立场与目的', 'label': '最担心踩什么坑', 'placeholder': '例如：接最后一棒 / 盲目模仿却没有底层支撑'}, {'key': 'action_goal', 'group': '立场与目的', 'label': '希望得出的行动结论', 'placeholder': '例如：该不该买/投？或者怎么把其中健康的机制用到自己产品上？'}]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "Lollapalooza 共振雷达"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields[FIELDS_SCHEMA[0]["key"]] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已初步提取核心主题，补充更多具体背景与约束条件后，智囊团分析会更犀利。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是「Lollapalooza 共振雷达」结构化抽取助手。请从用户输入中提取关键信息，未提及的字段务必留空 ""，不要编造。

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
    topic = (fields.get(FIELDS_SCHEMA[0]["key"]) or raw_text or "Lollapalooza 共振雷达").strip()[:28]
    return {
        "title": f"{topic} · Lollapalooza 共振效应拆解",
        "summary": "看清是哪几种心理与商业力量正在同向叠加共振，判断这是可持续的品牌复利，还是即将退潮的情绪核爆。",
        "pillars": [
            {"label": "同向共振的 3~5 种力量", "content": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
            {"label": "核爆机制（为何非线性质变）", "content": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
            {"label": "本质定性：真复利 vs 情绪泡沫", "content": "给出冷静、可验证、带安全边际的最终判断与防错边界。"},
        ],
        "sections": [
            {
                "heading": "一、核心拆解与关键发现",
                "items": [
                    {"name": "同向共振的 3~5 种力量", "tag": "深度拆解", "detail": f"围绕「{topic}」，先剥离表面噪音，列出最核心的硬事实与底层结构。"},
                    {"name": "核爆机制（为何非线性质变）", "tag": "盲区预警", "detail": "重点排查最容易被忽视的隐性风险、扭曲点或心理盲区。"},
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
    prompt = f"""你是查理·芒格「Lollapalooza 效应（多力同向共振）」智囊团（源自《人类误判心理学》压轴第25条）。专门识别 3~5 种心理倾向（社会认同、权威、稀缺、承诺一致、剥夺超级反应、巴甫洛夫联想等）与商业力量（规模优势、临界质量）同向叠加产生的核爆效应，并精准甄别真复利与情绪泡沫。

智囊团成员：
{advisors_desc}

用户原始输入：
{raw_text}

完善后的分析信息表：
{field_lines}

核心要求（必须严格遵守）：
- 紧扣用户的具体案例，拒绝空泛鸡汤与教科书式套话，直指要害
- pillars 固定 3 项，标题分别为：同向共振的 3~5 种力量、核爆机制（为何非线性质变）、本质定性：真复利 vs 情绪泡沫
- steps 为 4~5 步应对或借势行动清单（如果是泡沫给出撤离/隔离步骤，如果是真复利给出借势/复用步骤）
- council_synthesis 提炼 4 位智囊的「合议共识」与「关键张力」
- 4 位智囊各自独立发声，给出立场标签、犀利判断与具体落地动作

只返回 JSON，不要多余文字：
{{
  "title": "报告标题，18字以内",
  "summary": "一句话核心结论，45字以内",
  "pillars": [
    {{ "label": "同向共振的 3~5 种力量", "content": "45~90字深度拆解" }},
    {{ "label": "核爆机制（为何非线性质变）", "content": "45~90字深度拆解" }},
    {{ "label": "本质定性：真复利 vs 情绪泡沫", "content": "45~90字深度拆解" }}
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
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent10")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list) or not parsed["sections"]:
        raise ValueError("模型返回结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent10",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
