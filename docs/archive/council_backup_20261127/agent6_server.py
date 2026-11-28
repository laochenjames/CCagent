"""Agent6: 一法多解（芒格 · 多元模型与高杠杆机制）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "munger_lever.db")

ADVISORS = [
    {
        "id": "root_detective",
        "name": "共性根因侦探",
        "tag": "穿透表象 · 合并同类项",
        "principle": "表面上互不相干的 5 个问题，底层往往共享同 1 个系统缺陷或激励错位。",
        "focus": "把多个分散痛点归因到 1~2 个共同根源，避免头痛医头、脚痛医脚。",
    },
    {
        "id": "mental_models",
        "name": "多元模型参谋",
        "tag": "跨学科模型 · Lollapalooza",
        "principle": "手里只有一把锤子，看什么都像钉子；叠加 2~3 个跨学科模型才能产生组合拳效应。",
        "focus": "调用激励机制、复利、冗余、反馈闭环、规模效应等模型寻找高杠杆解。",
    },
    {
        "id": "lever_designer",
        "name": "杠杆设计师",
        "tag": "一石多鸟 · 机制化落地",
        "principle": "最好的解法不是更努力，而是设计一个结构或机制，做一件事同时产出多份收益。",
        "focus": "设计 1 个具体的“统一方法/核心机制”，逐一映射它如何同时解决每个输入问题。",
    },
    {
        "id": "inversion_guard",
        "name": "逆向避坑官",
        "tag": "反过来想 · 避开愚蠢",
        "principle": "如果我知道我会死在哪里，我就永远不去那里；先想清楚这套方案怎么会失败。",
        "focus": "用芒格式逆向思考，提前列出 2~3 个最可能让“一法多解”失效的陷阱。",
    },
]

FIELDS_SCHEMA = [
    {"key": "problems_list", "group": "多问题清单", "label": "同时面临的多个问题", "placeholder": "例如：1. 产品没流量 2. 自己缺乏输入 3. 没时间写文档 4. 难以建立信任"},
    {"key": "common_context", "group": "多问题清单", "label": "共同发生的场景/系统", "placeholder": "例如：都是我作为独立开发者日常工作流里的环节"},
    {"key": "bottleneck_resource", "group": "多问题清单", "label": "最稀缺的瓶颈资源", "placeholder": "例如：每天只有 3 小时高精力时间 / 注意力极易被切碎"},
    {"key": "interconnections", "group": "多问题清单", "label": "问题间的连锁拖累", "placeholder": "例如：没流量导致焦虑，焦虑又影响开发和内容输出"},
    {"key": "ideal_state", "group": "杠杆与约束", "label": "一举解决后的理想状态", "placeholder": "例如：每天只做 1 个核心动作，同时带动曝光、沉淀与成交"},
    {"key": "existing_leverage", "group": "杠杆与约束", "label": "已有的工具/资产/习惯", "placeholder": "例如：已有推特账号、现成小游戏/工具、每天都会写笔记"},
    {"key": "non_negotiables", "group": "杠杆与约束", "label": "不能牺牲的底线", "placeholder": "例如：不能靠熬夜硬扛、不能做违背长期口碑的短视营销"},
    {"key": "time_horizon", "group": "杠杆与约束", "label": "期望见效周期", "placeholder": "例如：2 周内跑顺机制，3 个月看到复利效果"},
]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    clean = (raw_text or "").strip()
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields["problems_list"] = clean[:120]
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已汇总你的多问题清单，建议补充“最稀缺资源”和“已有筹码”，便于设计一石多鸟的统一机制。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是芒格“一法多解”思维模型的结构化抽取助手。用户会输入多个同时面临的问题，请提取关键字段，未提及的留空 ""，不要编造。

用户输入：
{raw_text}

只返回 JSON：
{{
  "fields": {{
{keys_desc}
  }},
  "summary_note": "一句话提示用户最值得补充哪 1~2 项信息（35字以内）"
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900, tag="Agent6")
    rf = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(rf.get(f["key"]) or "").strip() for f in FIELDS_SCHEMA}
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": str(parsed.get("summary_note") or "").strip() or "多问题清单已提取，补充瓶颈资源与现有筹码后杠杆方案更精准。",
    }


def _fallback_generate(raw_text, fields):
    return {
        "title": "一法多解：统一高杠杆机制",
        "summary": "用“公开建造 + 标准化沉淀”这一条主线动作，同时解决曝光、信任、复盘与资产积累。",
        "pillars": [
            {"label": "共同根因", "value": "把多个本可复用的环节拆成了互不联通的孤岛任务，导致精力被反复消耗。"},
            {"label": "核心“一法”", "value": "建立 1 个可复用的核心母动作，让每次投入同时产生多份副产品收益。"},
            {"label": "逆向避坑（芒格）", "value": "如果这个统一机制本身太复杂、需要额外意志力维护，它一定会先崩盘。"},
        ],
        "sections": [
            {
                "heading": "一、一法如何同时击中每个问题（逐项映射）",
                "items": [
                    {"name": "击中问题 1：消除重复劳动", "tag": "杠杆映射", "detail": "把单次产出标准化，一份投入同时服务于内部沉淀与外部展示。"},
                    {"name": "击中问题 2：建立复利飞轮", "tag": "杠杆映射", "detail": "每次执行都在增强同一项核心资产，而不是每次从零开始。"},
                ],
            },
            {
                "heading": "二、调用的多元思维模型",
                "items": [
                    {"name": "激励相容 + 副产品复利", "tag": "多元模型", "detail": "让日常必做动作自然产生对外价值，无需额外耗费意志力。"},
                ],
            },
            {
                "heading": "三、3 步落地这个统一机制",
                "items": [
                    {"name": "第 1 步：选定唯一母动作", "tag": "落地", "detail": "明确每天/每周只围绕这 1 个动作转，其余顺带产出。"},
                    {"name": "第 2 步：固化模板与流水线", "tag": "落地", "detail": "把动作做成 15 分钟内可完成的固定模板，降低启动摩擦。"},
                    {"name": "第 3 步：2 周后检验多目标收益", "tag": "复盘", "detail": "检查输入清单里的每个问题是否都同步得到了缓解。"},
                ],
            },
        ],
        "council_synthesis": {
            "consensus": "四位智囊一致认为：这几个问题共享同一个注意力碎片化根因，必须用单一母动作取代多线救火。",
            "tension": "杠杆设计师追求一石多鸟的极致复用，逆向避坑官警告机制一旦超过 3 步就会因太重而废弃。",
        },
        "council_notes": [
            {"id": "root_detective", "name": "共性根因侦探", "role": "穿透表象 · 合并同类项", "stance": "归因锁定", "verdict": "这几件事表面分开，本质都在抢同一份稀缺注意力。", "action": "把所有痛点画在同一张工作流里，标出唯一共同上游瓶颈。"},
            {"id": "mental_models", "name": "多元模型参谋", "role": "跨学科模型 · Lollapalooza", "stance": "模型叠加", "verdict": "把“单次动作”改造成“复利管道”，才能产生叠加杠杆效应。", "action": "让每次必做动作自动留下可复用副产品，消除重复劳动。"},
            {"id": "lever_designer", "name": "杠杆设计师", "role": "一石多鸟 · 机制化落地", "stance": "强烈建议", "verdict": "好机制的标准是：只增加 1 份动作，却同时消掉 3 份焦虑。", "action": "把核心母动作固化成 15 分钟固定模板，每天只推这一张多米诺骨牌。"},
            {"id": "inversion_guard", "name": "逆向避坑官", "role": "反过来想 · 避开愚蠢", "stance": "核心警告", "verdict": "最容易失败的是把统一方法设计得过于宏大，反而成为新负担。", "action": "砍掉机制里所有超过 3 步的复杂环节，确保低电量时也能跑通。"},
        ],
    }


def _generate_ai(raw_text, fields, cfg):
    flines = "\n".join(f"- {f['label']}：{(fields.get(f['key']) or '').strip() or '（未填写）'}" for f in FIELDS_SCHEMA)
    prompt = f"""你是 CCagent 的「一法多解智囊团（查理·芒格多元思维模型方法）」，由 4 位顾问组成：
1. 共性根因侦探（找出多个问题背后的共同根因）
2. 多元模型参谋（调用激励机制、复利、逆向思考、规模效应等跨学科模型）
3. 杠杆设计师（设计 1 个核心“统一方法/机制”，同时解决用户输入的多个问题）
4. 逆向避坑官（反过来想：这套方案最可能在哪翻车）

用户输入的多个问题：
{raw_text}

用户完善的信息表：
{flines}

核心要求：
- 必须真正提出 **1 个具体、可落地的统一方法/核心机制**（而不是给每个问题分别写一个独立建议！）
- 在 sections 第一部分中，逐一映射这个“统一方法”如何同时解决用户提到的每一个具体问题
- 严格返回以下 JSON，语言犀利务实：
{{
  "title": "核心一法名称，16字以内",
  "summary": "一句话说清用哪一个方法同时解决哪几个问题，35字以内",
  "pillars": [
    {{ "label": "多个问题的共同根因", "value": "一句话穿透表象指出共同根因（35字以内）" }},
    {{ "label": "核心“一法”（统一杠杆）", "value": "一句话定义这个一石多鸟的核心机制（35字以内）" }},
    {{ "label": "逆向避坑（芒格）", "value": "避免什么愚蠢错误就能防止这套机制失效（35字以内）" }}
  ],
  "sections": [
    {{
      "heading": "一、一法如何同时解决每个问题（逐项映射）",
      "items": [
        {{ "name": "对应问题名称（12字内）", "tag": "同步解决", "detail": "核心一法具体如何顺带把这个问题一并解决（35~60字）" }}
      ]
    }},
    {{
      "heading": "二、背后的多元思维模型（2~3 个）",
      "items": [
        {{ "name": "思维模型名称（12字内）", "tag": "跨学科模型", "detail": "这个模型在此处如何产生叠加杠杆效应（35~60字）" }}
      ]
    }},
    {{
      "heading": "三、落地这个“一法”的执行步骤（3 步）",
      "items": [
        {{ "name": "执行步骤（12字内）", "tag": "第1步", "detail": "具体操作动作与检验标准（35~60字）" }}
      ]
    }}
  ],
  "council_synthesis": {{
    "consensus": "四位智囊达成的最大共识（35~55字）",
    "tension": "智囊之间最有价值的分歧或需要用户权衡的张力点（35~55字）"
  }},
  "council_notes": [
    {{ "id": "root_detective", "name": "共性根因侦探", "role": "穿透表象 · 合并同类项", "stance": "归因锁定", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "mental_models", "name": "多元模型参谋", "role": "跨学科模型 · Lollapalooza", "stance": "模型叠加", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "lever_designer", "name": "杠杆设计师", "role": "一石多鸟 · 机制化落地", "stance": "强烈建议", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "inversion_guard", "name": "逆向避坑官", "role": "反过来想 · 避开愚蠢", "stance": "核心警告", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }}
  ]
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent6")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list):
        raise ValueError("一法多解输出结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent6",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
