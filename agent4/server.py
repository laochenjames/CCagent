"""Agent4: 第一性原理（马斯克）"""

import os
import sys

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

DB_PATH = os.path.join(BASE_DIR, "data", "first_principles.db")

ADVISORS = [
    {
        "id": "assumption_breaker",
        "name": "假设爆破手",
        "tag": "破除类比 · 质疑惯例",
        "principle": "大家一直这么做，不代表它符合底层规律；先把所有隐含假设摆上台面逐个证伪。",
        "focus": "识别行业惯例、经验主义与伪约束，区分“习惯如此”和“不得不如此”。",
    },
    {
        "id": "physics_floor",
        "name": "物理底线官",
        "tag": "不可再分 · 底层铁律",
        "principle": "剥离一切包装，只保留物理定律、数学约束、人性底线和真实资源边界。",
        "focus": "找到这件事真正不可动摇的 3~4 条基本事实。",
    },
    {
        "id": "cost_rebuilder",
        "name": "成本重构师",
        "tag": "从零重构 · 10x 路径",
        "principle": "站在基本事实之上重新组装方案，往往能发现比常规做法低一个数量级的路径。",
        "focus": "绕开中间环节，直接从原材料/核心要素重算最优路径。",
    },
    {
        "id": "min_experiment",
        "name": "极简执行官",
        "tag": "快速证伪 · 最小闭环",
        "principle": "再漂亮的底层推演也要接受现实检验；用 7 天内可跑通的最小实验验证核心假设。",
        "focus": "把重构方案压成第一步可落地、低成本的验证动作。",
    },
]

FIELDS_SCHEMA = [
    {"key": "target_issue", "group": "问题与惯例", "label": "核心问题/目标", "placeholder": "例如：我想低成本获客、做一款独立产品、转行进 AI 行业"},
    {"key": "conventional_way", "group": "问题与惯例", "label": "大家通常的做法（类比）", "placeholder": "例如：投信息流广告、先招团队开发半年、报万元培训班"},
    {"key": "current_cost", "group": "问题与惯例", "label": "当前成本/耗时/瓶颈", "placeholder": "例如：获客成本太高、开发周期长、没人付费"},
    {"key": "hard_constraints", "group": "问题与惯例", "label": "真正的物理/资源硬约束", "placeholder": "例如：只有下班 2 小时、预算不超过 5000 元、一个人干"},
    {"key": "core_assumptions", "group": "底层事实与重构", "label": "被默认的隐含假设", "placeholder": "例如：必须有完美 UI 才能卖、必须先做流量再变现"},
    {"key": "desired_outcome", "group": "底层事实与重构", "label": "最本质想要的结果", "placeholder": "例如：让 10 个真实用户愿意为一个明确痛点付钱"},
    {"key": "available_assets", "group": "底层事实与重构", "label": "手头可动用的要素/筹码", "placeholder": "例如：会写代码、有行业人脉、已有 3 个现成工具"},
    {"key": "risk_tolerance", "group": "底层事实与重构", "label": "可接受的试错代价", "placeholder": "例如：最多投入 2 周时间 + 1000 元试错"},
]


def init_db():
    core.init_sqlite(DB_PATH)


def _completeness(fields):
    filled = sum(1 for f in FIELDS_SCHEMA if (fields.get(f["key"]) or "").strip())
    return round(filled * 100 / len(FIELDS_SCHEMA))


def _fallback_extract(raw_text):
    first_line = (raw_text or "").strip().splitlines()[0][:28] if raw_text.strip() else "核心问题"
    fields = {f["key"]: "" for f in FIELDS_SCHEMA}
    fields["target_issue"] = first_line
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": "已提取核心问题，建议补充“大家通常的做法”和“真正的硬约束”，便于爆破伪假设。",
    }


def _extract_ai(raw_text, cfg):
    keys_desc = "\n".join(f'    "{f["key"]}": "{f["label"]}（未提及则留空）"' for f in FIELDS_SCHEMA)
    prompt = f"""你是第一性原理分析的结构化抽取助手。请从用户输入中提取关键信息，未提及的字段留空 ""，不要编造。

用户输入：
{raw_text}

只返回 JSON：
{{
  "fields": {{
{keys_desc}
  }},
  "summary_note": "一句话提示用户最值得补充哪 1~2 项信息（35字以内）"
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.2, max_tokens=900, tag="Agent4")
    rf = parsed.get("fields") if isinstance(parsed.get("fields"), dict) else {}
    fields = {f["key"]: str(rf.get(f["key"]) or "").strip() for f in FIELDS_SCHEMA}
    return {
        "fields": fields,
        "completeness": _completeness(fields),
        "summary_note": str(parsed.get("summary_note") or "").strip() or "信息已初步提取，补充空白项后拆解会更犀利。",
    }


def _fallback_generate(raw_text, fields):
    issue = (fields.get("target_issue") or raw_text or "当前问题").strip()[:16]
    return {
        "title": f"第一性原理拆解：{issue}",
        "summary": "剥离行业惯例，回到最底层的供需、成本与时间约束，重新组装最短路径。",
        "pillars": [
            {"label": "被打破的核心伪常识", "value": "把“别人成功的完整形态”误当成“起步必须具备的条件”。"},
            {"label": "最硬的底层约束", "value": fields.get("hard_constraints") or "时间与注意力有限，必须用最小成本验证真实价值。"},
            {"label": "7 天最小验证实验", "value": f"围绕「{issue}」做 1 个最小可用版本，直接找 3 个目标对象验证反馈。"},
        ],
        "sections": [
            {
                "heading": "被爆破的 3 个隐含假设",
                "items": [
                    {"name": "假设 1：必须按行业标准流程来", "tag": "伪约束", "detail": "标准流程服务于大团队风控，对个人或早期验证反而是最大阻力。"},
                    {"name": "假设 2：必须先做完再推向市场", "tag": "伪约束", "detail": "价值交换的最小单位往往是“解决一个具体痛点”，而不是完整系统。"},
                ],
            },
            {
                "heading": "不可再分的底层事实（第一性原理）",
                "items": [
                    {"name": "事实 1：价值 = 解决真实痛点", "tag": "底层事实", "detail": "任何形式包装都不改变最终是否有人愿意为此付出时间或金钱。"},
                    {"name": "事实 2：反馈速度决定迭代效率", "tag": "底层事实", "detail": "越早接触真实世界反馈，沉没成本越低。"},
                ],
            },
            {
                "heading": "从底层重构的新方案",
                "items": [
                    {"name": "第 1 步：砍掉所有非必要环节", "tag": "重构", "detail": f"只保留直接交付「{issue}」核心价值的唯一动作。"},
                    {"name": "第 2 步：用现有筹码直接拼出最小原型", "tag": "重构", "detail": "不新增重资产投入，在 48 小时内做出可展示/可测试的雏形。"},
                    {"name": "第 3 步：拿真实反馈校准方向", "tag": "验证", "detail": "根据前 3~5 个真实反馈决定加码还是转向。"},
                ],
            },
        ],
        "council_synthesis": {
            "consensus": "四位智囊一致认为：当前最大成本来自照搬行业惯例，而非真正的物理或资源硬约束。",
            "tension": "成本重构师主张彻底砍掉外围功能，极简执行官提醒保留最小可交付体验以确保验证有效。",
        },
        "council_notes": [
            {"id": "assumption_breaker", "name": "假设爆破手", "role": "破除类比 · 质疑惯例", "stance": "建议重构", "verdict": "把“大家都是这么做的”全部划掉，重新问一遍为什么必须这样。", "action": "列出当前计划中 3 个最耗时环节，逐一追问“不做它真的会死吗”。"},
            {"id": "physics_floor", "name": "物理底线官", "role": "不可再分 · 底层铁律", "stance": "明确边界", "verdict": "真正限制你的只有时间、精力与物理规律，其余大多是心理预设。", "action": "写下本题唯一不可违背的 2 条硬约束，其余全部视为可变量。"},
            {"id": "cost_rebuilder", "name": "成本重构师", "role": "从零重构 · 10x 路径", "stance": "强烈建议", "verdict": "把成本压到原来的 1/10，往往只需砍掉 80% 没人关心的装饰环节。", "action": "用现有免费工具或手工流程替代重开发，先跑通核心价值交付。"},
            {"id": "min_experiment", "name": "极简执行官", "role": "快速证伪 · 最小闭环", "stance": "立即验证", "verdict": "不要停留在纸面推演，7 天内必须拿到真实世界的第一手反馈。", "action": "48 小时内做出最小原型，直接找 3 个目标用户测试付费或使用意愿。"},
        ],
    }


def _generate_ai(raw_text, fields, cfg):
    flines = "\n".join(f"- {f['label']}：{(fields.get(f['key']) or '').strip() or '（未填写）'}" for f in FIELDS_SCHEMA)
    prompt = f"""你是 CCagent 的「第一性原理智囊团（马斯克方法）」，由 4 位顾问组成：
1. 假设爆破手（破除类比与伪常识）
2. 物理底线官（提炼不可再分的物理/经济/人性底层事实）
3. 成本重构师（从底层重新组装 10x 路径）
4. 极简执行官（设计 7 天内可验证的最小实验）

用户原始输入：
{raw_text}

用户完善的信息表：
{flines}

请严格按以下 JSON 结构输出，语言犀利、具体、去空话：
{{
  "title": "分析标题，16字以内",
  "summary": "一句话核心破局结论，35字以内",
  "pillars": [
    {{ "label": "被打破的核心伪常识", "value": "一句话点破最致命的错误假设（35字以内）" }},
    {{ "label": "最硬的底层事实", "value": "一句话总结不可动摇的底层规律（35字以内）" }},
    {{ "label": "7 天最小验证实验", "value": "本周就能做的低成本验证动作（35字以内）" }}
  ],
  "sections": [
    {{
      "heading": "一、被爆破的隐含假设（3 项）",
      "items": [
        {{ "name": "假设名称（12字内）", "tag": "伪常识", "detail": "为什么它不成立、背后隐藏了什么浪费（35~60字）" }}
      ]
    }},
    {{
      "heading": "二、不可再分的底层事实（3 项）",
      "items": [
        {{ "name": "底层事实（12字内）", "tag": "第一性原理", "detail": "客观不可违背的规律或核心约束说明（35~60字）" }}
      ]
    }},
    {{
      "heading": "三、从底层重构的新方案（3~4 步）",
      "items": [
        {{ "name": "重构步骤（12字内）", "tag": "第1步", "detail": "具体怎么做、相比常规做法省掉什么成本（35~60字）" }}
      ]
    }}
  ],
  "council_synthesis": {{
    "consensus": "四位智囊达成的最大共识（35~55字）",
    "tension": "智囊之间最有价值的分歧或需要用户权衡的张力点（35~55字）"
  }},
  "council_notes": [
    {{ "id": "assumption_breaker", "name": "假设爆破手", "role": "破除类比 · 质疑惯例", "stance": "建议重构", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "physics_floor", "name": "物理底线官", "role": "不可再分 · 底层铁律", "stance": "明确边界", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "cost_rebuilder", "name": "成本重构师", "role": "从零重构 · 10x 路径", "stance": "强烈建议", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }},
    {{ "id": "min_experiment", "name": "极简执行官", "role": "快速证伪 · 最小闭环", "stance": "立即验证", "verdict": "一句话核心判断（25字内）", "action": "1条具体落地动作（35字内）" }}
  ]
}}"""
    parsed = core.call_llm_json(prompt, cfg, temperature=0.35, max_tokens=2400, tag="Agent4")
    if not parsed.get("title") or not isinstance(parsed.get("sections"), list):
        raise ValueError("第一性原理输出结构不完整")
    return parsed


RequestHandler = core.make_handler(
    base_dir=BASE_DIR,
    db_path=DB_PATH,
    tag="Agent4",
    advisors=ADVISORS,
    fields_schema=FIELDS_SCHEMA,
    extract_fn=_extract_ai,
    fallback_extract_fn=_fallback_extract,
    generate_fn=_generate_ai,
    fallback_generate_fn=_fallback_generate,
)
