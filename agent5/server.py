"""Agent5: 辩证抽象（毛泽东方法：《矛盾论》《实践论》）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "dialectics.db")

ADVISORS = [
    {
        "id": "principal_hunter",
        "name": "主要矛盾猎手",
        "tag": "抓牛鼻子 · 分清主次",
        "principle": "复杂局势中必有一个起领导、决定作用的主要矛盾；捉住了主要矛盾，一切问题就迎刃而解。",
        "focus": "从一团乱麻中剥离次要矛盾，锁定当下决定成败的唯一主要矛盾与主要方面。",
    },
    {
        "id": "united_front",
        "name": "统战格局师",
        "tag": "敌我友划分 · 争取中间派",
        "principle": "把朋友搞得多多的，把敌人搞得少少的；一切策略都要建立在真实力量对比上。",
        "focus": "识别核心依托力量、可争取的中间力量与主要阻力，避免四面出击。",
    },
    {
        "id": "transformation_officer",
        "name": "转化时机官",
        "tag": "动态演变 · 临界条件",
        "principle": "矛盾双方不是静止的，在一定条件下必然向相反方向转化；看清转化条件才能后发制人。",
        "focus": "判断当前处于防御、相持还是反攻阶段，找准扭转局势的关键变量。",
    },
    {
        "id": "practice_commander",
        "name": "实践路线官",
        "tag": "集中兵力 · 以点带面",
        "principle": "从实践中来、到实践中去；伤其十指不如断其一指，先打赢一场小胜仗建立根据地。",
        "focus": "制定分阶段、可检验的实践纲领，明确“先打哪一仗、次要问题先放一放”。",
    },
]

FIELDS_SCHEMA = [
    {"key": "situation", "group": "现状与矛盾", "label": "面临的局势/核心事件", "placeholder": "例如：同时做多个项目精力分散、团队内耗、副业卡在瓶颈"},
    {"key": "parties_involved", "group": "现状与矛盾", "label": "涉及的关键各方与诉求", "placeholder": "例如：自己、老板/客户、合作伙伴、目标用户各自想要什么"},
    {"key": "surface_conflicts", "group": "现状与矛盾", "label": "表面看到的冲突/卡点", "placeholder": "例如：时间不够、没人推广、产品和运营互相拖累"},
    {"key": "own_strengths", "group": "现状与矛盾", "label": "己方优势与短板", "placeholder": "例如：优势是产品开发快，短板是流量和持续运营"},
    {"key": "stage_goal", "group": "阶段与转化", "label": "当前阶段最想达成的目标", "placeholder": "例如：3 个月内跑通一个稳定现金流或核心抓手"},
    {"key": "time_pressure", "group": "阶段与转化", "label": "时间窗口与外部趋势", "placeholder": "例如：AI 工具红利期、年底前必须见到结果"},
    {"key": "key_allies", "group": "阶段与转化", "label": "可争取的中间力量/同盟", "placeholder": "例如：已有老用户、垂直社群、可复用的内容渠道"},
    {"key": "past_attempts", "group": "阶段与转化", "label": "之前试过什么、为何未打通", "placeholder": "例如：同时铺开 5 条线，每条都浅尝辄止"},
]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "当前局势"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields["situation"] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已提取核心局势，建议补充“表面冲突”和“己方优势与短板”，便于锁定主要矛盾。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是辩证抽象分析（矛盾论/实践论方法）的结构化抽取助手。请从用户输入中提取关键信息，未提及的字段留空 ""，不要编造。

用户输入：
{raw_text}

只返回 JSON：
{{
  "fields": {{
{keys_desc}
  }},
  "summary_note": "一句话提示用户最值得补充哪 1~2 项信息（35字以内）"
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900, tag="Agent5")
    rf = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(rf.get(f["key"]) or "").strip() for f in FIELDS_SCHEMA}
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": str(parsed.get("summary_note") or "").strip() or "局势信息已初步提取，补充空白项后矛盾定位更精准。",
    }


def _fallback_generate(raw_text, fields):
    sit = (fields.get("situation") or raw_text or "当前局势").strip()[:16]
    return {
        "title": f"辩证抽象：{sit}",
        "summary": "分清主次矛盾，先集中优势资源打通决定全局的唯一突破口，其余问题暂作战略搁置。",
        "pillars": [
            {"label": "唯一主要矛盾", "value": "有限资源全面铺开 vs 单点打透建立正反馈之间的矛盾。"},
            {"label": "矛盾转化临界条件", "value": "出现第一个可复制的小闭环样本，使信心与资源开始自我造血。"},
            {"label": "第一仗打哪里", "value": f"围绕「{sit}」选定阻力最小、反馈最快的一个切入点集中打穿。"},
        ],
        "sections": [
            {
                "heading": "一、主要矛盾与次要矛盾划分",
                "items": [
                    {"name": "主要矛盾（必须优先解决）", "tag": "牛鼻子", "detail": "决定全局走向的核心瓶颈，不解决它，其余努力都会被稀释。"},
                    {"name": "次要矛盾（暂时战略搁置）", "tag": "先放一放", "detail": "非决定性细节与外围杂务，等主要矛盾突破后往往会自然缓解。"},
                ],
            },
            {
                "heading": "二、力量对比与转化条件",
                "items": [
                    {"name": "可依托的核心优势", "tag": "根据地", "detail": fields.get("own_strengths") or "以己之长攻彼之短，绝不在短板领域打消耗战。"},
                    {"name": "矛盾向有利方向转化的条件", "tag": "临界点", "detail": "用一次确定的小胜利替代长期空转，带动外部同盟与资源聚拢。"},
                ],
            },
            {
                "heading": "三、分阶段实践路线（以点带面）",
                "items": [
                    {"name": "阶段 1：收缩战线、保住根据地", "tag": "防御/蓄力", "detail": "砍掉消耗精力但无产出的次要事项，集中 80% 精力到主战场。"},
                    {"name": "阶段 2：集中优势兵力打歼灭战", "tag": "突破", "detail": "只攻克 1 个最关键节点，拿到可验证的阶段战果。"},
                    {"name": "阶段 3：总结规律、以点带面", "tag": "扩张", "detail": "把打通的局部经验抽象成方法，再逐步复制到相邻战场。"},
                ],
            },
        ],
        "council_synthesis": {
            "consensus": "四位智囊一致认为：当前核心病根是战线过长，必须立刻收缩精力、单点打穿唯一主要矛盾。",
            "tension": "主要矛盾猎手主张彻底搁置次要事项，统战格局师提醒保留关键同盟的最低限度维护。",
        },
        "council_notes": [
            {"id": "principal_hunter", "name": "主要矛盾猎手", "role": "抓牛鼻子 · 分清主次", "stance": "核心警告", "verdict": "不要同时解五道题，只解决定全局生死的那一道。", "action": "写下未来 30 天唯一主战场，其余次要事项正式列入“暂缓清单”。"},
            {"id": "united_front", "name": "统战格局师", "role": "敌我友划分 · 争取中间派", "stance": "借力破局", "verdict": "先团结最容易认可你价值的种子同盟，别试图一开始就说服所有人。", "action": "锁定 2~3 位最易共鸣的中间力量，先为他们提供确定性小价值。"},
            {"id": "transformation_officer", "name": "转化时机官", "role": "动态演变 · 临界条件", "stance": "耐心蓄势", "verdict": "弱势时拼的是局部优势与节奏，创造转化条件比硬碰硬更有效。", "action": "明确触发局势反转的 1 个关键里程碑，围绕它积累量变。"},
            {"id": "practice_commander", "name": "实践路线官", "role": "集中兵力 · 以点带面", "stance": "单点突破", "verdict": "伤其十指不如断其一指，先打赢一场小胜仗建立根据地。", "action": "集中 80% 精力在本周打通第一个最小闭环，打完立刻复盘抽象。"},
        ],
    }


def _generate_ai(raw_text, fields, cfg):
    flines = "\n".join(f"- {f['label']}：{(fields.get(f['key']) or '').strip() or '（未填写）'}" for f in FIELDS_SCHEMA)
    prompt = f"""你是 CCagent 的「辩证抽象智囊团（毛泽东《矛盾论》《实践论》方法）」，由 4 位顾问组成：
1. 主要矛盾猎手（揪出唯一主要矛盾与矛盾的主要方面）
2. 统战格局师（划分核心依托力量、可争取中间派与主要阻力）
3. 转化时机官（看清动态演变与矛盾向有利方向转化的临界条件）
4. 实践路线官（集中优势兵力、先打哪一仗、以点带面的分阶段实践纲领）

用户原始输入：
{raw_text}

用户完善的局势信息表：
{flines}

请用冷静、务实、直击本质的中文输出，不要喊口号，严格返回以下 JSON：
{{
  "title": "辩证分析标题，16字以内",
  "summary": "一句话抓住本质规律与破局总方针，35字以内",
  "pillars": [
    {{ "label": "唯一主要矛盾", "value": "A 与 B 之间的核心矛盾，及矛盾的主要方面（35字以内）" }},
    {{ "label": "矛盾转化临界条件", "value": "达成什么条件后局势会由被动转为主动（35字以内）" }},
    {{ "label": "第一仗打哪里", "value": "集中优势兵力先攻克的唯一突破口（35字以内）" }}
  ],
  "sections": [
    {{
      "heading": "一、主要矛盾 vs 次要矛盾（主次分明）",
      "items": [
        {{ "name": "矛盾名称（12字内）", "tag": "主要矛盾", "detail": "为什么它决定全局、不解决它会怎样（35~60字）" }},
        {{ "name": "次要矛盾1（12字内）", "tag": "暂缓处理", "detail": "为什么现在不该在它身上消耗精力（35~60字）" }},
        {{ "name": "次要矛盾2（12字内）", "tag": "暂缓处理", "detail": "等主要矛盾解决后它会如何自然化解（35~60字）" }}
      ]
    }},
    {{
      "heading": "二、力量格局与转化条件（敌我友分析）",
      "items": [
        {{ "name": "核心根据地/优势", "tag": "依托", "detail": "己方真正站得住脚的筹码（35~60字）" }},
        {{ "name": "可争取的中间力量", "tag": "统战", "detail": "如何把中立/观望方转化为助力（35~60字）" }},
        {{ "name": "矛盾转化的关键变量", "tag": "转化条件", "detail": "需要积累什么量变才能引发质变（35~60字）" }}
      ]
    }},
    {{
      "heading": "三、分阶段实践路线（以点带面）",
      "items": [
        {{ "name": "阶段 1（12字内）", "tag": "收缩蓄力", "detail": "具体做什么、放弃什么（35~60字）" }},
        {{ "name": "阶段 2（12字内）", "tag": "单点突破", "detail": "集中兵力打赢哪一场小胜仗（35~60字）" }},
        {{ "name": "阶段 3（12字内）", "tag": "抽象扩张", "detail": "如何总结规律并以点带面放大战果（35~60字）" }}
      ]
    }}
  ],
  "council_synthesis": {{
    "consensus": "四位智囊达成的最大共识（35~55字）",
    "tension": "智囊之间最有价值的分歧或需要用户权衡的张力点（35~55字）"
  }},
  "council_notes": [
    {{ "id": "principal_hunter", "name": "主要矛盾猎手", "role": "抓牛鼻子 · 分清主次", "stance": "核心警告", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "united_front", "name": "统战格局师", "role": "敌我友划分 · 争取中间派", "stance": "借力破局", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "transformation_officer", "name": "转化时机官", "role": "动态演变 · 临界条件", "stance": "耐心蓄势", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "practice_commander", "name": "实践路线官", "role": "集中兵力 · 以点带面", "stance": "单点突破", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }}
  ]
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent5")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list):
        raise ValueError("辩证抽象输出结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent5",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
