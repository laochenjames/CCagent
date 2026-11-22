"""
CCagent - 自由职业者任务分诊本地服务 (v2 精准智囊 + 观感版)
零第三方依赖，纯 Python 原生库实现 (ThreadingHTTPServer + sqlite3 + Gemini 结构化输出)
"""

import os
import sys
import json
import sqlite3
import datetime
import urllib.request
import urllib.error
from urllib.parse import urlparse, parse_qs
import re
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(ROOT_DIR, 'data')
DB_PATH = os.path.join(DATA_DIR, 'ccagent.db')
_PARENT_ENV = os.path.join(os.path.dirname(ROOT_DIR), '.env')
ENV_FILE = _PARENT_ENV if os.path.exists(_PARENT_ENV) else os.path.join(ROOT_DIR, '.env')
PROMPT_FILE = os.path.join(ROOT_DIR, 'prompts', 'triage_prompt.md')
ADVISORY_LIB_FILE = os.path.join(ROOT_DIR, 'prompts', 'advisory_library.json')

PROVIDER_PRESETS = {
    'gemini': {
        'prefix': 'GEMINI',
        'label': 'Google Gemini',
        'default_model': 'gemini-3.5-flash-lite',
        'base_url': 'https://generativelanguage.googleapis.com',
    },
    'xai': {
        'prefix': 'XAI',
        'label': 'Grok (xAI)',
        'default_model': 'grok-3-mini-fast',
        'base_url': 'https://api.x.ai/v1',
    },
    'deepseek': {
        'prefix': 'DEEPSEEK',
        'label': 'DeepSeek',
        'default_model': 'deepseek-flash',
        'base_url': 'https://api.deepseek.com',
    },
}


def _resolve_provider_config(env, body=None):
    body = body or {}
    provider = (body.get('provider') or env.get('LLM_PROVIDER') or 'gemini').strip().lower()
    if provider not in PROVIDER_PRESETS:
        provider = 'gemini'
    preset = PROVIDER_PRESETS[provider]
    prefix = preset['prefix']
    req_key = (body.get('api_key') or '').strip()
    if not req_key or req_key == 'server-configured' or '...' in req_key:
        api_key = env.get(f'{prefix}_API_KEY', '')
    else:
        api_key = req_key
    raw_model = (body.get('model') or env.get(f'{prefix}_MODEL') or preset['default_model']).strip()
    model = sanitize_model(raw_model) if provider == 'gemini' else raw_model
    base_url = (body.get('base_url') or env.get(f'{prefix}_BASE_URL') or preset['base_url']).strip()
    return provider, api_key, model, base_url

# 静态文件访问白名单
ALLOWED_STATIC_FILES = {'index.html', 'style.css', 'app.js'}

DOMAINS = {'work', 'life', 'study', 'play'}
QUADRANTS = {'q1', 'q2', 'q3', 'q4', 'candidate'}
STATUSES = {'open', 'done', 'removed'}
CONFIDENCES = {'high', 'medium', 'low'}


def utcnow_iso():
    """统一输出规范的 UTC ISO 时间戳，带微秒与 Z 后缀"""
    now = datetime.datetime.now(datetime.timezone.utc)
    return now.strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def get_db():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db()
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS tasks (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL,
        domain TEXT NOT NULL,
        quadrant TEXT NOT NULL,
        action TEXT NOT NULL DEFAULT '',
        status TEXT NOT NULL DEFAULT 'open',
        timeframe TEXT DEFAULT 'tomorrow',
        due_date TEXT,
        est_minutes INTEGER DEFAULT 30,
        fixed_time TEXT,
        reason TEXT,
        advice TEXT,
        factors TEXT,
        assumptions TEXT,
        confidence TEXT DEFAULT 'medium',
        probe TEXT,
        expert_id TEXT,
        ai_quadrant TEXT,
        ai_domain TEXT,
        user_moved INTEGER DEFAULT 0,
        engine TEXT DEFAULT 'ai',
        run_id TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        done_at TEXT
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS triage_runs (
        id TEXT PRIMARY KEY,
        input_text TEXT NOT NULL,
        context_snapshot TEXT,
        model TEXT,
        engine TEXT,
        created_at TEXT NOT NULL
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS feedback_events (
        id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        run_id TEXT,
        type TEXT NOT NULL,
        from_value TEXT,
        to_value TEXT,
        created_at TEXT NOT NULL
    )
    ''')

    c.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        key TEXT PRIMARY KEY,
        value TEXT,
        updated_at TEXT NOT NULL
    )
    ''')

    # 检查并自动升级表结构：补全 advice / correction_ignored 列
    c.execute('PRAGMA table_info(tasks)')
    cols = [r[1] for r in c.fetchall()]
    if 'advice' not in cols:
        c.execute('ALTER TABLE tasks ADD COLUMN advice TEXT')
    if 'correction_ignored' not in cols:
        c.execute('ALTER TABLE tasks ADD COLUMN correction_ignored INTEGER DEFAULT 0')

    # 一次性将库中历史带 +00:00 的时间戳替换为标准的 Z 后缀
    for tbl in ['tasks', 'triage_runs', 'feedback_events', 'settings']:
        c.execute(f"PRAGMA table_info({tbl})")
        t_cols = [x[1] for x in c.fetchall()]
        for col in ['created_at', 'updated_at', 'done_at']:
            if col in t_cols:
                c.execute(f"UPDATE {tbl} SET {col} = REPLACE({col}, '+00:00', 'Z') WHERE {col} LIKE '%+00:00%'")

    conn.commit()
    conn.close()


_ENV_KEYS = (
    'LLM_PROVIDER',
    'GEMINI_API_KEY', 'GEMINI_MODEL', 'GEMINI_FAST_MODEL', 'GEMINI_BASE_URL', 'GEMINI_TIMEOUT',
    'XAI_API_KEY', 'XAI_MODEL', 'XAI_BASE_URL',
    'DEEPSEEK_API_KEY', 'DEEPSEEK_MODEL', 'DEEPSEEK_BASE_URL',
    'HOSTED', 'ALLOWED_ORIGINS',
)


def _read_env_file():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    return env


def load_env():
    env = _read_env_file()
    for k in _ENV_KEYS:
        val = os.environ.get(k)
        if val:
            env[k] = val
    return env


def save_env(updates):
    current = _read_env_file()
    current.update(updates)
    lines = ["# CCagent 配置文件"]
    for k, v in current.items():
        lines.append(f"{k}={v}")
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def get_advisory_library():
    try:
        with open(ADVISORY_LIB_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data if isinstance(data, list) else []
    except Exception:
        return []


def build_advisory_index():
    items = get_advisory_library()
    if not items:
        return "（智囊库暂不可用，所有任务 expert_id 一律填 null）"
    lines = []
    for item in items:
        signals = '、'.join(item.get('typical_signals', []))
        lines.append(f"- {item.get('id')}｜[{item.get('domain')}] {item.get('name')}｜典型信号: {signals}｜准则: {item.get('judgment_criteria')}｜建议导向: {item.get('advice_style', '')}")
    return '\n'.join(lines)


def get_current_context():
    conn = get_db()
    c = conn.cursor()
    c.execute('SELECT value FROM settings WHERE key=?', ('context',))
    row = c.fetchone()
    conn.close()
    return row['value'] if row and row['value'] else ""


def is_corrections_enabled():
    """检查是否启用用户历史纠偏 (settings: corrections_enabled, 默认 1)"""
    try:
        conn = get_db()
        c = conn.cursor()
        c.execute("SELECT value FROM settings WHERE key = 'corrections_enabled'")
        row = c.fetchone()
        conn.close()
        if row and row['value'] is not None:
            return str(row['value']).strip().lower() in ['1', 'true', 'yes', 'on']
        return True
    except Exception:
        return True


def get_recent_user_corrections(limit=8):
    """
    取最近最多 limit 条生效的纠偏记录：
    - 条件: correction_ignored = 0 且 status != 'removed' 且 (quadrant != ai_quadrant 或 domain != ai_domain)
    - 格式：
      * 象限纠正: 「标题」AI 判为 Q1 → 用户改为 Q2
      * 领域纠正: 「标题」AI 判为领域 工作 → 用户改为 生活
      * 两者兼改: 「标题」AI 判为 工作·Q1 → 用户改为 生活·Q2
    - 同标题只保留最新，标题截断40字。
    - 失败时不吞异常，打印一行日志。
    """
    if not is_corrections_enabled():
        return ""

    domain_names = {'work': '工作', 'life': '生活', 'study': '学习', 'play': '娱乐'}

    try:
        conn = get_db()
        c = conn.cursor()
        c.execute('''
            SELECT title, ai_domain, domain, ai_quadrant, quadrant, updated_at
            FROM tasks
            WHERE correction_ignored = 0 
              AND status != 'removed'
              AND (quadrant != ai_quadrant OR domain != ai_domain)
            ORDER BY updated_at DESC
        ''')
        rows = c.fetchall()
        conn.close()

        seen_titles = set()
        corrections = []
        for r in rows:
            clean_title = (r['title'] or '').strip()
            if not clean_title or clean_title in seen_titles:
                continue
            seen_titles.add(clean_title)
            short_title = clean_title[:40] + ('...' if len(clean_title) > 40 else '')

            quad_diff = (r['quadrant'] != r['ai_quadrant'])
            dom_diff = (r['domain'] != r['ai_domain'])

            if quad_diff and dom_diff:
                old_dom = domain_names.get(r['ai_domain'], r['ai_domain'])
                new_dom = domain_names.get(r['domain'], r['domain'])
                corrections.append(f"「{short_title}」AI 判为 {old_dom}·{r['ai_quadrant'].upper()} → 用户改为 {new_dom}·{r['quadrant'].upper()}")
            elif dom_diff:
                old_dom = domain_names.get(r['ai_domain'], r['ai_domain'])
                new_dom = domain_names.get(r['domain'], r['domain'])
                corrections.append(f"「{short_title}」AI 判为领域 {old_dom} → 用户改为 {new_dom}")
            elif quad_diff:
                corrections.append(f"「{short_title}」AI 判为 {r['ai_quadrant'].upper()} → 用户改为 {r['quadrant'].upper()}")

            if len(corrections) >= limit:
                break

        if corrections:
            lines = ["【该用户的历史纠正与偏好（参考用户个性偏好，类似任务应当参考，不要机械照搬）】"]
            for corr in corrections:
                lines.append(f"- {corr}")
            return '\n'.join(lines)
    except Exception as e:
        print(f"[{utcnow_iso()}] [WARNING] 获取用户历史纠正记录失败: {e}")
    return ""


def build_system_prompt(custom_context=None, corrections_text=None, prompt_path=None):
    target_prompt = prompt_path if prompt_path and os.path.exists(prompt_path) else PROMPT_FILE
    with open(target_prompt, 'r', encoding='utf-8') as f:
        template = f.read()

    ctx = custom_context if custom_context is not None else get_current_context()
    ctx_clean = ctx.strip() if isinstance(ctx, str) else ""
    context_text = ctx_clean if ctx_clean else "（用户当前未设置本周重点与硬约束）"

    corr_text = corrections_text if corrections_text is not None else get_recent_user_corrections(8)

    prompt = template.replace('{{ADVISORY_INDEX}}', build_advisory_index())
    prompt = prompt.replace('{{USER_CONTEXT}}', context_text)
    prompt = prompt.replace('{{USER_CORRECTIONS}}', corr_text)
    return prompt


def sanitize_model(model):
    if not model or model in ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-flash']:
        return 'gemini-3.5-flash-lite'
    return model


def validate_base_url(url):
    if not url:
        return False
    u = url.strip()
    return u.startswith('https://') or u.startswith('http://127.0.0.1') or u.startswith('http://localhost')


# ============================================================================
# 任务校验与归一化 (阶段 B 精简版：剔除已删字段)
# ============================================================================
def normalize_task_item(t, engine='ai', run_id=None):
    now_iso = utcnow_iso()
    domain = t.get('domain', 'work')
    if domain not in DOMAINS:
        domain = 'work'

    quadrant = t.get('quadrant', 'q2')
    if quadrant not in QUADRANTS:
        quadrant = 'q2'

    title = str(t.get('title', '')).strip() or '（未命名事项）'
    reason = str(t.get('reason', '')).strip()[:100]
    advice = str(t.get('advice', '')).strip()[:100]

    expert_id = t.get('expert_id')
    valid_ids = {e['id'] for e in get_advisory_library()}
    if expert_id not in valid_ids:
        expert_id = None

    confidence = t.get('confidence', 'medium')
    if confidence not in CONFIDENCES:
        confidence = 'medium'

    factors = t.get('factors')
    if not isinstance(factors, dict):
        factors = {
            'deadline': '无/模糊',
            'consequence': '无明显不可逆损失',
            'reversible': True,
            'waiting_party': '无',
            'money_related': False
        }
    else:
        # 只保留 5 大核心因子
        factors = {
            'deadline': str(factors.get('deadline', '无/模糊')),
            'consequence': str(factors.get('consequence', '无明显不可逆损失')),
            'reversible': bool(factors.get('reversible', True)),
            'waiting_party': str(factors.get('waiting_party', '无')),
            'money_related': bool(factors.get('money_related', False))
        }

    assumptions = t.get('assumptions')
    if not isinstance(assumptions, list):
        assumptions = []

    probe = str(t.get('probe', '')).strip() if quadrant == 'candidate' or confidence == 'low' else ''

    task_id = t.get('id') or f"t_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"

    return {
        'id': task_id,
        'title': title,
        'domain': domain,
        'quadrant': quadrant,
        'action': '',  # 保留列兼容，用空字符串占位
        'status': 'open',
        'timeframe': 'tomorrow',
        'due_date': None,
        'est_minutes': 0,
        'fixed_time': None,
        'reason': reason,
        'advice': advice,
        'factors': json.dumps(factors, ensure_ascii=False),
        'assumptions': json.dumps(assumptions, ensure_ascii=False),
        'confidence': confidence,
        'probe': probe,
        'expert_id': expert_id,
        'ai_quadrant': quadrant,
        'ai_domain': domain,
        'user_moved': 0,
        'engine': engine,
        'run_id': run_id,
        'created_at': t.get('created_at') or now_iso,
        'updated_at': t.get('updated_at') or now_iso,
        'done_at': None
    }


# ============================================================================
# 规则兜底引擎 (A9 优化：短字符 candidate 移至关键词之后)
# ============================================================================
def fallback_triage(text, run_id=None):
    lines = [l.strip() for l in text.split('\n') if l.strip()]
    tasks = []
    for line in lines:
        # 提示词与原则：用户明确说已完成的事项不要输出
        if re.match(r'^(已完成|完成|做完|Done)[:：]', line, re.I):
            continue

        clean = re.sub(r'^(今日顺延|顺延|未完成|明日计划|明天|计划|待办)[:：]', '', line, flags=re.I)
        clean = re.sub(r'^[-*•\d+.\s]+', '', clean).strip()
        if not clean:
            continue

        domain = 'work'
        quadrant = 'q2'
        expert_id = None
        consequence = '常规事项推进'
        advice = '结合当前重点，合理排入日程推进。'
        money_rel = False
        reversible = True
        waiting = '无'

        # 优先比对关键词
        # 1. 娱乐与身心 -> play
        if re.search(r'健身|运动|跑步|午休|早睡|散步|散步放空|做操', clean):
            domain = 'play'
            quadrant = 'q2'
            expert_id = 'PLAY_RIGID_RECOVERY'
            consequence = '机体疲劳积累影响状态'
            advice = f'安排固定作息时段进行{clean}，安心恢复精力。'
        elif re.search(r'游戏|刷剧|看电影|逛街|刷视频|聚餐|休闲', clean):
            domain = 'play'
            quadrant = 'q4'
            expert_id = 'PLAY_LEISURE_RELAX'
            consequence = '适度消遣，无刚性损失'
            advice = f'在完成今日重点交付后，为{clean}设定时间盒安心享受。'
        # 2. 学习 -> study
        elif re.search(r'课程|考证|精读|论文|技能练习|技术文档|攻关', clean):
            domain = 'study'
            quadrant = 'q2'
            expert_id = 'STUDY_TARGETED_SKILL'
            consequence = '延缓长期技能复利增长'
            advice = f'设定专注时间盒推进{clean}，以实操产出检验效果。'
        elif re.search(r'通识|阅读|听播客|科普|泛读', clean):
            domain = 'study'
            quadrant = 'q4'
            expert_id = 'STUDY_BROAD_HORIZON'
            consequence = '通识拓展，可按需排期'
            advice = f'将{clean}安排在低脑力碎片时段阅读，不占用核心工作时段。'
        # 3. 生活 -> life
        elif re.search(r'水电费|房租|报税|看病|买药|断网|服务器续费|证件', clean):
            domain = 'life'
            quadrant = 'q1'
            expert_id = 'LIFE_HARD_DEADLINE'
            consequence = '逾期面临停摆、断网或滞纳金'
            reversible = False
            advice = f'今日优先处理{clean}，并建议设置自动扣款或周期提醒。'
        elif re.search(r'快递|买日用品|买猫粮|洗衣服|晾衣服|倒垃圾|洗碗|买菜', clean):
            domain = 'life'
            quadrant = 'q3'
            expert_id = 'LIFE_INTRUSIVE_CHORES'
            consequence = '日常杂务积压'
            advice = f'在长时间用脑后顺便起身处理{clean}，当做肢体换脑休息。'
        # 4. 工作 -> work
        elif re.search(r'交付|定稿|变现|主线|核心代码|核心脚本|分镜攻坚|尾款|上线|签约', clean):
            domain = 'work'
            quadrant = 'q1'
            money_rel = True
            reversible = False
            waiting = '客户/需求方'
            expert_id = 'WORK_CORE_DELIVERY'
            consequence = '延误交付直接影响款项与合作进度'
            advice = f'锁定整块黄金专注时段全力攻坚{clean}，拆出前10分钟启动动作。'
        elif re.search(r'回消息|回复|小修改|导出|发票|对账|群聊', clean):
            domain = 'work'
            quadrant = 'q3'
            waiting = '对接人'
            expert_id = 'WORK_SHALLOW_NOISE'
            consequence = '外部沟通延迟'
            advice = f'集中归拢至下午低脑力时段批处理{clean}，用模板快速响应。'
        elif re.search(r'SOP|工作流|提示词库|自动化|素材库|长线IP', clean):
            domain = 'work'
            quadrant = 'q2'
            expert_id = 'WORK_LEVERAGE_SOP'
            consequence = '长期生产效率缺乏复利积累'
            advice = f'控制在60至90分钟时间盒内推进{clean}，以最小可用MVP为准。'
        # 5. A9 优化：短字符或模糊事项移到最后判断
        elif re.search(r'^(看下|想想|研究|试试|了解|随便|等|纠结|待定)', clean) or re.search(r'还没定|不确定|拿不准', clean) or len(clean) <= 4:
            quadrant = 'candidate'
            consequence = '信息不充分，后果未知'
            advice = f'先厘清{clean}的具体操作与截止约束，再做决定。'
        else:
            advice = f'按计划推进{clean}，关注是否符合本周重点。'

        raw_item = {
            'title': clean,
            'domain': domain,
            'quadrant': quadrant,
            'reason': f"因为属于{domain}领域常规事项，所以置于{quadrant.upper()}；若有紧急外部约束则应调整。",
            'advice': advice,
            'confidence': 'low',
            'probe': '❓ 请确认此事项是否存在外部催促或截止硬约束？' if quadrant == 'candidate' else '',
            'factors': {
                'deadline': '无/模糊',
                'consequence': consequence,
                'reversible': reversible,
                'waiting_party': waiting,
                'money_related': money_rel
            },
            'assumptions': ['规则兜底保底推断', '未接入大模型实时推理'],
            'expert_id': expert_id
        }
        tasks.append(normalize_task_item(raw_item, engine='fallback', run_id=run_id))
    return tasks


# ============================================================================
# Gemini 结构化输出 Schema (阶段 C1 精准定义)
# ============================================================================
STRUCTURED_RESPONSE_SCHEMA = {
    'type': 'OBJECT',
    'properties': {
        'tasks': {
            'type': 'ARRAY',
            'items': {
                'type': 'OBJECT',
                'properties': {
                    'title': {'type': 'STRING'},
                    'domain': {'type': 'STRING', 'enum': ['work', 'life', 'study', 'play']},
                    'quadrant': {'type': 'STRING', 'enum': ['q1', 'q2', 'q3', 'q4', 'candidate']},
                    'reason': {'type': 'STRING'},
                    'advice': {'type': 'STRING'},
                    'confidence': {'type': 'STRING', 'enum': ['high', 'medium', 'low']},
                    'probe': {'type': 'STRING'},
                    'expert_id': {'type': 'STRING'},
                    'factors': {
                        'type': 'OBJECT',
                        'properties': {
                            'deadline': {'type': 'STRING'},
                            'consequence': {'type': 'STRING'},
                            'reversible': {'type': 'BOOLEAN'},
                            'waiting_party': {'type': 'STRING'},
                            'money_related': {'type': 'BOOLEAN'}
                        },
                        'required': ['deadline', 'consequence', 'reversible', 'waiting_party', 'money_related']
                    },
                    'assumptions': {
                        'type': 'ARRAY',
                        'items': {'type': 'STRING'}
                    }
                },
                'required': ['title', 'domain', 'quadrant', 'reason', 'advice', 'confidence', 'probe', 'factors', 'assumptions']
            }
        }
    },
    'required': ['tasks']
}


class GeminiAPIError(Exception):
    def __init__(self, category, message, status_code=None, raw_summary=None):
        super().__init__(message)
        self.category = category
        self.message = message
        self.status_code = status_code
        self.raw_summary = raw_summary


def call_gemini_api(api_key, model, base_url, user_text, custom_prompt=None, provider='gemini'):
    if not api_key:
        raise GeminiAPIError("Key 无效或未授权", f"尚未配置 {PROVIDER_PRESETS.get(provider, {}).get('label', provider)} API Key！")
    if not validate_base_url(base_url):
        raise GeminiAPIError("网络异常", "不合法的 Base URL！仅允许 https:// 或本地 http://127.0.0.1 / localhost。")

    system_inst = custom_prompt if custom_prompt is not None else build_system_prompt()

    # B8: 超时默认 120 秒 (环境变量 GEMINI_TIMEOUT 可覆盖)
    env = load_env()
    timeout_sec = 120
    try:
        env_timeout = os.environ.get('GEMINI_TIMEOUT') or env.get('GEMINI_TIMEOUT')
        if env_timeout:
            timeout_sec = int(env_timeout)
    except Exception:
        timeout_sec = 120

    if provider in ('xai', 'deepseek'):
        endpoint = f"{base_url.rstrip('/')}/chat/completions"
        if not base_url.rstrip('/').endswith('/v1') and provider == 'deepseek':
            endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
        payload = {
            "model": model,
            "temperature": 0.2,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_inst + "\n\n请务必仅输出合法的 JSON 对象，包含 tasks 数组。"},
                {"role": "user", "content": f"请对以下任务流水账进行分诊解析：\n\n{user_text}"},
            ],
        }
        req = urllib.request.Request(
            endpoint,
            data=json.dumps(payload).encode('utf-8'),
            headers={
                'Content-Type': 'application/json',
                'Authorization': f'Bearer {api_key}',
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                data = json.loads(resp.read().decode('utf-8'))
            raw_text = data.get('choices', [{}])[0].get('message', {}).get('content', '{}')
            clean_json_str = raw_text.strip()
            if clean_json_str.startswith('```json'):
                clean_json_str = clean_json_str[7:]
            if clean_json_str.startswith('```'):
                clean_json_str = clean_json_str[3:]
            if clean_json_str.endswith('```'):
                clean_json_str = clean_json_str[:-3]
            parsed = json.loads(clean_json_str.strip())
            return parsed.get('tasks', [])
        except urllib.error.HTTPError as he:
            detail = he.read().decode('utf-8', errors='ignore')[:200]
            raise GeminiAPIError("API错误", f"HTTP {he.code}: {detail}")
        except TimeoutError:
            raise GeminiAPIError("请求超时", "请求超时，请检查网络或增大 GEMINI_TIMEOUT。")
        except Exception as exc:
            raise GeminiAPIError("模型输出格式异常", f"调用或解析失败: {exc}")

    model = sanitize_model(model)
    endpoint = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"

    payload = {
        "system_instruction": {
            "parts": [{"text": system_inst}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"请对以下任务流水账进行分诊解析：\n\n{user_text}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json",
            "response_schema": STRUCTURED_RESPONSE_SCHEMA
        }
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={
            'Content-Type': 'application/json',
            'x-goog-api-key': api_key
        }
    )

    # B8: 只对 429、5xx 与网络错误重试一次（退避 2 秒），对 4xx 与超时不重试
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            with urllib.request.urlopen(req, timeout=timeout_sec) as resp:
                resp_bytes = resp.read()
                data = json.loads(resp_bytes.decode('utf-8'))
                candidates = data.get('candidates', [])
                if not candidates:
                    raise GeminiAPIError("模型输出格式异常", "Gemini 未返回候选内容")
                raw_text = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
                clean_json_str = raw_text.strip()
                if clean_json_str.startswith('```json'):
                    clean_json_str = clean_json_str[7:]
                if clean_json_str.startswith('```'):
                    clean_json_str = clean_json_str[3:]
                if clean_json_str.endswith('```'):
                    clean_json_str = clean_json_str[:-3]
                try:
                    parsed = json.loads(clean_json_str.strip())
                    return parsed.get('tasks', [])
                except Exception as json_err:
                    raise GeminiAPIError("模型输出格式异常", f"JSON 解析失败: {json_err}", raw_summary=clean_json_str[:150])
        except urllib.error.HTTPError as he:
            code = he.code
            body_snippet = ""
            try:
                body_snippet = he.read().decode('utf-8', errors='ignore')[:150]
            except Exception:
                pass

            if code in [401, 403]:
                cat = "Key 无效或无权限"
            elif code == 400:
                cat = "请求被拒绝（可能是结构化输出参数）"
            elif code == 404:
                cat = "模型名或 Base URL 不存在"
            elif code == 429:
                cat = "限流"
            elif code >= 500:
                cat = "服务繁忙"
            else:
                cat = f"HTTP {code} 异常"

            # 打印安全日志（不含 key）
            print(f"[{utcnow_iso()}] [GeminiError] HTTPError: code={code}, category={cat}, summary={body_snippet}", flush=True)

            # 仅限 429 或 5xx 进行第 2 次重试
            if attempt < max_attempts - 1 and (code == 429 or code >= 500):
                print(f"[{utcnow_iso()}] [GeminiRetry] 遭遇 {code}，等待 2 秒退避后进行重试...", flush=True)
                import time
                time.sleep(2)
                continue

            raise GeminiAPIError(cat, f"HTTP Error {code}: {cat}", status_code=code, raw_summary=body_snippet)

        except urllib.error.URLError as ue:
            reason_str = str(ue.reason)
            is_timeout = 'timed out' in reason_str.lower() or isinstance(ue.reason, TimeoutError)
            cat = "请求超时" if is_timeout else "网络异常"
            print(f"[{utcnow_iso()}] [GeminiError] URLError: category={cat}, summary={reason_str[:150]}", flush=True)

            # 超时不重试；其他网络错误若第一次则重试
            if not is_timeout and attempt < max_attempts - 1:
                print(f"[{utcnow_iso()}] [GeminiRetry] 遭遇网络异常，等待 2 秒退避重试...", flush=True)
                import time
                time.sleep(2)
                continue

            raise GeminiAPIError(cat, f"{cat}: {reason_str}", raw_summary=reason_str[:150])

        except GeminiAPIError as ge:
            print(f"[{utcnow_iso()}] [GeminiError] {ge.category}: summary={str(ge.raw_summary or ge.message)[:150]}", flush=True)
            raise ge

        except Exception as oe:
            oe_str = str(oe)
            is_timeout = 'timed out' in oe_str.lower()
            cat = "请求超时" if is_timeout else "模型输出格式异常"
            print(f"[{utcnow_iso()}] [GeminiError] Unexpected: category={cat}, summary={oe_str[:150]}")
            raise GeminiAPIError(cat, f"{cat}: {oe_str}", raw_summary=oe_str[:150])


# ============================================================================
# HTTP 服务处理器 (阶段 A1/A6: Threading + 安全强化)
# ============================================================================
class TriageRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def get_server_port(self):
        return self.server.server_port

    def get_allowed_hosts(self):
        port = self.get_server_port()
        return {
            f'127.0.0.1:{port}',
            f'localhost:{port}',
            '127.0.0.1',
            'localhost'
        }

    def get_allowed_origins(self):
        port = self.get_server_port()
        origins = {
            f'http://127.0.0.1:{port}',
            f'http://localhost:{port}'
        }
        extra = os.environ.get('ALLOWED_ORIGINS', '') or load_env().get('ALLOWED_ORIGINS', '')
        if extra:
            for item in extra.split(','):
                item = item.strip()
                if item:
                    origins.add(item)
        return origins

    def check_origin_header(self):
        origin = self.headers.get('Origin')
        if not origin:
            return True, None
        origin = origin.strip().rstrip('/')
        allowed = self.get_allowed_origins()
        if origin in allowed:
            return True, origin
        return False, None

    def check_security(self):
        host = self.headers.get('Host', '').strip()
        if host not in self.get_allowed_hosts():
            return False, "Invalid Host header"
        valid_origin, _ = self.check_origin_header()
        if not valid_origin:
            return False, "Forbidden Origin"
        return True, None

    def send_json(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        _, origin = self.check_origin_header()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        valid, _ = self.check_security()
        if not valid:
            self.send_error(403, "Forbidden")
            return
        self.send_response(200)
        _, origin = self.check_origin_header()
        if origin:
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PATCH, PUT, DELETE, OPTIONS, HEAD')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, x-goog-api-key')
        self.end_headers()

    # A6 覆写 do_HEAD，复用静态文件白名单
    def do_HEAD(self):
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]
        filename = clean_path.lstrip('/')
        if filename == '':
            filename = 'index.html'
        if filename not in ALLOWED_STATIC_FILES:
            self.send_error(403, "Forbidden")
            return
        super().do_HEAD()

    def do_GET(self):
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]

        # A6: 对 /api/* 也做 Host 校验
        if clean_path.startswith('/api/'):
            valid, err_msg = self.check_security()
            if not valid:
                self.send_error(403, f"Forbidden: {err_msg}")
                return

        # 静态资源白名单
        if not clean_path.startswith('/api/'):
            filename = clean_path.lstrip('/')
            if filename == '':
                filename = 'index.html'
            if filename not in ALLOWED_STATIC_FILES:
                self.send_error(403, "Forbidden")
                return
            super().do_GET()
            return

        # API 1: /api/config
        if clean_path == '/api/config':
            env = load_env()
            provider, key, model, base_url = _resolve_provider_config(env)
            masked = (key[:6] + '...' + key[-4:]) if len(key) > 10 else ('已配置' if key else '')
            resp = {
                "provider": provider,
                "has_key": bool(key),
                "masked_key": masked,
                "model": model,
                "base_url": base_url
            }
            self.send_json(200, resp)
            return

        # API 2: /api/context
        if clean_path == '/api/context':
            self.send_json(200, {"context": get_current_context()})
            return

        # API: /api/advisory (智囊策略库)
        if clean_path == '/api/advisory':
            items = get_advisory_library()
            self.send_json(200, {"advisory": items})
            return

        # API 3: /api/tasks (A2: parse_qs + A5 SQL 参数化)
        if clean_path == '/api/tasks':
            parsed_q = parse_qs(urlparse(self.path).query)
            status_filter = parsed_q.get('status', [None])[0]
            updated_after = parsed_q.get('updated_after', [None])[0]

            sql = 'SELECT * FROM tasks WHERE 1=1'
            args = []
            if status_filter:
                sql += ' AND status = ?'
                args.append(status_filter)
            else:
                sql += ' AND status != ?'
                args.append('removed')
            if updated_after:
                sql += ' AND updated_at > ?'
                args.append(updated_after)
            sql += ' ORDER BY created_at DESC'

            conn = get_db()
            c = conn.cursor()
            c.execute(sql, args)
            rows = c.fetchall()
            tasks = []
            for r in rows:
                t = dict(r)
                try:
                    t['factors'] = json.loads(t['factors']) if t['factors'] else {}
                except Exception:
                    pass
                try:
                    t['assumptions'] = json.loads(t['assumptions']) if t['assumptions'] else []
                except Exception:
                    pass
                tasks.append(t)
            conn.close()
            self.send_json(200, {"tasks": tasks})
            return

        # API: /api/settings (获取全局设置，含 corrections_enabled)
        if clean_path == '/api/settings':
            conn = get_db()
            c = conn.cursor()
            c.execute("SELECT key, value FROM settings")
            rows = c.fetchall()
            conn.close()
            settings_dict = {r['key']: r['value'] for r in rows}
            corrections_enabled = str(settings_dict.get('corrections_enabled', '1')).lower() in ['1', 'true', 'yes', 'on']
            self.send_json(200, {
                "corrections_enabled": corrections_enabled,
                "context": settings_dict.get('context', '')
            })
            return

        # API: /api/corrections (获取生效中和已忽略的纠正列表供设置抽屉查看)
        if clean_path == '/api/corrections':
            conn = get_db()
            c = conn.cursor()
            c.execute('''
                SELECT id, title, ai_domain, domain, ai_quadrant, quadrant, user_moved, correction_ignored, updated_at
                FROM tasks
                WHERE user_moved = 1 AND status != 'removed'
                ORDER BY updated_at DESC
            ''')
            rows = [dict(r) for r in c.fetchall()]
            conn.close()
            self.send_json(200, {"corrections": rows})
            return

        # API 4: /api/export (阶段 B/B9 Markdown 格式升级，去掉 emoji，status 支持 open, done, all)
        if clean_path == '/api/export':
            parsed_q = parse_qs(urlparse(self.path).query)
            fmt = parsed_q.get('format', ['md'])[0]
            status_filter = parsed_q.get('status', ['open'])[0]

            conn = get_db()
            c = conn.cursor()
            sql = 'SELECT * FROM tasks WHERE status != ?'
            args = ['removed']
            if status_filter and status_filter != 'all':
                sql += ' AND status = ?'
                args.append(status_filter)
            sql += ' ORDER BY created_at ASC'
            c.execute(sql, args)
            rows = [dict(r) for r in c.fetchall()]
            conn.close()

            if fmt == 'json':
                for t in rows:
                    try:
                        t['factors'] = json.loads(t['factors'])
                    except Exception:
                        pass
                    try:
                        t['assumptions'] = json.loads(t['assumptions'])
                    except Exception:
                        pass
                self.send_json(200, {"tasks": rows})
                return
            else:
                now_str = datetime.datetime.now().strftime('%Y-%m-%d')
                md_lines = [f"# 任务分流清单 ({now_str})\n"]
                quad_headers = {
                    'q1': '## Q1 重要且紧急',
                    'q2': '## Q2 重要不紧急',
                    'q3': '## Q3 紧急不重要',
                    'q4': '## Q4 不重要不紧急',
                    'candidate': '## 待确认事项'
                }
                for q_key in ['q1', 'q2', 'q3', 'q4', 'candidate']:
                    q_tasks = [t for t in rows if t['quadrant'] == q_key]
                    if not q_tasks:
                        continue
                    md_lines.append(f"\n{quad_headers[q_key]}")
                    for t in q_tasks:
                        check = "x" if t['status'] == 'done' else " "
                        md_lines.append(f"- [{check}] {t['title']} #{t['domain']}")
                        if t.get('reason'):
                            md_lines.append(f"  > 判断：{t['reason']}")
                        if t.get('advice'):
                            md_lines.append(f"  > 建议：{t['advice']}")
                        if t.get('probe'):
                            md_lines.append(f"  > 澄清：{t['probe']}")
                md_text = '\n'.join(md_lines)
                body = md_text.encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'text/markdown; charset=utf-8')
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return

        self.send_error(404, "Not Found")

    def do_POST(self):
        valid, err_msg = self.check_security()
        if not valid:
            self.send_error(403, f"Forbidden: {err_msg}")
            return

        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]

        # API: /api/save-config
        if clean_path == '/api/save-config':
            body = self.read_json_body()
            provider = (body.get('provider') or 'gemini').strip().lower()
            if provider not in PROVIDER_PRESETS:
                provider = 'gemini'
            prefix = PROVIDER_PRESETS[provider]['prefix']
            updates = {'LLM_PROVIDER': provider}
            raw_key = body.get('api_key', '')
            if isinstance(raw_key, str):
                raw_key = raw_key.strip()
            if raw_key and raw_key != 'server-configured' and '...' not in raw_key:
                updates[f'{prefix}_API_KEY'] = raw_key
            if 'model' in body and body['model']:
                m = body['model'].strip()
                updates[f'{prefix}_MODEL'] = sanitize_model(m) if provider == 'gemini' else m
            if 'base_url' in body and body['base_url']:
                cand_url = body['base_url'].strip()
                if not validate_base_url(cand_url):
                    self.send_json(400, {"error": "Base URL 仅允许 https:// 或本地 http://127.0.0.1 / localhost。"})
                    return
                updates[f'{prefix}_BASE_URL'] = cand_url
            save_env(updates)
            self.send_json(200, {"status": "ok", "message": "配置已保存"})
            return

        # API: /api/test-connection
        if clean_path == '/api/test-connection':
            body = self.read_json_body()
            env = load_env()
            provider, api_key, model, base_url = _resolve_provider_config(env, body)
            label = PROVIDER_PRESETS[provider]['label']

            if not validate_base_url(base_url):
                self.send_json(400, {"error": "Base URL 仅允许 https:// 或本地 http://127.0.0.1 / localhost。"})
                return

            try:
                if provider in ('xai', 'deepseek'):
                    endpoint = f"{base_url.rstrip('/')}/chat/completions"
                    if not base_url.rstrip('/').endswith('/v1') and provider == 'deepseek':
                        endpoint = f"{base_url.rstrip('/')}/v1/chat/completions"
                    test_payload = {
                        "model": model,
                        "max_tokens": 16,
                        "messages": [{"role": "user", "content": "Pong"}],
                    }
                    req = urllib.request.Request(
                        endpoint,
                        data=json.dumps(test_payload).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'},
                    )
                else:
                    endpoint = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent"
                    test_payload = {"contents": [{"parts": [{"text": "Pong"}]}]}
                    req = urllib.request.Request(
                        endpoint,
                        data=json.dumps(test_payload).encode('utf-8'),
                        headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key},
                    )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    json.loads(resp.read().decode('utf-8'))
                    self.send_json(200, {"status": "ok", "message": f"连通成功！{label} ({model}) 响应正常。"})
            except Exception as e:
                err_detail = str(e)
                if hasattr(e, 'read'):
                    err_detail += " - " + e.read().decode('utf-8', errors='ignore')
                self.send_json(500, {"status": "error", "message": err_detail})
            return

        # API: /api/tasks (手动新增任务)
        if clean_path == '/api/tasks':
            body = self.read_json_body()
            norm = normalize_task_item(body, engine='manual')
            conn = get_db()
            c = conn.cursor()
            c.execute('''
            INSERT INTO tasks (
                id, title, domain, quadrant, action, status, timeframe, due_date, est_minutes, fixed_time,
                reason, advice, factors, assumptions, confidence, probe, expert_id, ai_quadrant, ai_domain,
                user_moved, engine, run_id, created_at, updated_at, done_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                norm['id'], norm['title'], norm['domain'], norm['quadrant'], norm['action'], norm['status'],
                norm['timeframe'], norm['due_date'], norm['est_minutes'], norm['fixed_time'],
                norm['reason'], norm['advice'], norm['factors'], norm['assumptions'], norm['confidence'], norm['probe'],
                norm['expert_id'], norm['ai_quadrant'], norm['ai_domain'], norm['user_moved'],
                norm['engine'], norm['run_id'], norm['created_at'], norm['updated_at'], norm['done_at']
            ))
            conn.commit()
            conn.close()
            self.send_json(201, {"task": norm})
            return

        # API: /api/triage (A4 保底原因增加 + A8 去重提示)
        if clean_path == '/api/triage':
            body = self.read_json_body()
            user_text = body.get('text', '').strip()
            allow_fallback = bool(body.get('fallback', True))
            if not user_text:
                self.send_json(400, {"error": "请输入需要分诊的任务文本"})
                return

            env = load_env()
            provider, api_key, model, base_url = _resolve_provider_config(env, body)

            run_id = f"run_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
            context_snap = get_current_context()
            now_iso = utcnow_iso()

            raw_tasks = []
            engine_used = 'ai'
            fallback_reason = None

            if api_key:
                try:
                    raw_tasks = call_gemini_api(api_key, model, base_url, user_text, provider=provider)
                    engine_used = 'ai'
                except GeminiAPIError as ge:
                    fallback_reason = ge.category
                    print(f"[{utcnow_iso()}] [TriageFallback] category={ge.category}, msg={str(ge.message)[:150]}", flush=True)
                    if allow_fallback:
                        raw_tasks = fallback_triage(user_text, run_id=run_id)
                        engine_used = 'fallback'
                    else:
                        self.send_json(500, {"error": f"大模型分诊失败: {fallback_reason}"})
                        return
                except Exception as e:
                    fallback_reason = '网络或模型异常'
                    print(f"[{utcnow_iso()}] [TriageFallback] exc={type(e).__name__}: {str(e)[:150]}", flush=True)
                    if allow_fallback:
                        raw_tasks = fallback_triage(user_text, run_id=run_id)
                        engine_used = 'fallback'
                    else:
                        self.send_json(500, {"error": f"大模型分诊失败: {fallback_reason}"})
                        return
            else:
                fallback_reason = '未配置 API Key'
                if allow_fallback:
                    raw_tasks = fallback_triage(user_text, run_id=run_id)
                    engine_used = 'fallback'
                else:
                    self.send_json(400, {"error": "未配置 API Key，且未开启规则保底。"})
                    return

            # 入库 triage_runs
            conn = get_db()
            c = conn.cursor()
            c.execute('''
            INSERT INTO triage_runs (id, input_text, context_snapshot, model, engine, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (run_id, user_text, context_snap, model, engine_used, now_iso))

            # 入库 tasks（A8: 跳过标题相同的未完成任务并统计数量）
            created_tasks = []
            skipped_duplicates = 0
            for r in raw_tasks:
                norm = normalize_task_item(r, engine=engine_used, run_id=run_id)
                c.execute('SELECT id FROM tasks WHERE title = ? AND status = ?', (norm['title'], 'open'))
                dup = c.fetchone()
                if dup:
                    skipped_duplicates += 1
                    continue

                c.execute('''
                INSERT INTO tasks (
                    id, title, domain, quadrant, action, status, timeframe, due_date, est_minutes, fixed_time,
                    reason, advice, factors, assumptions, confidence, probe, expert_id, ai_quadrant, ai_domain,
                    user_moved, engine, run_id, created_at, updated_at, done_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    norm['id'], norm['title'], norm['domain'], norm['quadrant'], norm['action'], norm['status'],
                    norm['timeframe'], norm['due_date'], norm['est_minutes'], norm['fixed_time'],
                    norm['reason'], norm['advice'], norm['factors'], norm['assumptions'], norm['confidence'], norm['probe'],
                    norm['expert_id'], norm['ai_quadrant'], norm['ai_domain'], norm['user_moved'],
                    norm['engine'], norm['run_id'], norm['created_at'], norm['updated_at'], norm['done_at']
                ))
                created_tasks.append(norm)

            conn.commit()
            conn.close()

            resp_payload = {
                "run_id": run_id,
                "engine": engine_used,
                "model": model,
                "tasks": created_tasks,
                "skipped_duplicates": skipped_duplicates
            }
            if fallback_reason:
                resp_payload["fallback_reason"] = fallback_reason

            self.send_json(200, resp_payload)
            return

        self.send_error(404, "Not Found")

    def do_PUT(self):
        valid, err_msg = self.check_security()
        if not valid:
            self.send_error(403, f"Forbidden: {err_msg}")
            return
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]

        if clean_path == '/api/context':
            body = self.read_json_body()
            ctx_val = str(body.get('context', '')).strip()
            now_iso = utcnow_iso()
            conn = get_db()
            c = conn.cursor()
            c.execute('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)',
                      ('context', ctx_val, now_iso))
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "ok", "context": ctx_val})
            return

        if clean_path == '/api/settings':
            body = self.read_json_body()
            now_iso = utcnow_iso()
            conn = get_db()
            c = conn.cursor()
            if 'corrections_enabled' in body:
                val = '1' if body['corrections_enabled'] else '0'
                c.execute('INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES (?, ?, ?)',
                          ('corrections_enabled', val, now_iso))
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "ok", "message": "设置已保存"})
            return

        self.send_error(404, "Not Found")

    def do_PATCH(self):
        valid, err_msg = self.check_security()
        if not valid:
            self.send_error(403, f"Forbidden: {err_msg}")
            return
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]

        m = re.match(r'^/api/tasks/([^/]+)$', clean_path)
        if m:
            task_id = m.group(1)
            body = self.read_json_body()

            # A3: PATCH 取值强校验
            if 'quadrant' in body and body['quadrant'] not in QUADRANTS:
                self.send_json(400, {"error": f"非法的象限取值: {body['quadrant']}"})
                return
            if 'domain' in body and body['domain'] not in DOMAINS:
                self.send_json(400, {"error": f"非法的领域取值: {body['domain']}"})
                return
            if 'status' in body and body['status'] not in STATUSES:
                self.send_json(400, {"error": f"非法的生活状态取值: {body['status']}"})
                return

            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            old = c.fetchone()
            if not old:
                conn.close()
                self.send_json(404, {"error": "Task not found"})
                return

            now_iso = utcnow_iso()
            updates = []
            args = []
            events = []

            track_fields = ['quadrant', 'domain', 'title', 'status', 'correction_ignored']
            for f in track_fields:
                if f in body:
                    new_val = body[f]
                    old_val = old[f] if f in old.keys() else None
                    if new_val != old_val:
                        updates.append(f"{f} = ?")
                        args.append(new_val)
                        event_id = f"fb_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
                        events.append((event_id, task_id, old['run_id'], f, str(old_val), str(new_val), now_iso))

            # B3: user_moved 按“当前值是否不同于 ai_quadrant/ai_domain”重新计算（拖回原位则恢复为 0）
            target_quad = body['quadrant'] if 'quadrant' in body else old['quadrant']
            target_dom = body['domain'] if 'domain' in body else old['domain']
            ai_quad = old['ai_quadrant']
            ai_dom = old['ai_domain']

            new_user_moved = 1 if (target_quad != ai_quad or target_dom != ai_dom) else 0
            if new_user_moved != old['user_moved']:
                updates.append("user_moved = ?")
                args.append(new_user_moved)

            for direct_f in ['reason', 'advice']:
                if direct_f in body:
                    updates.append(f"{direct_f} = ?")
                    args.append(body[direct_f])

            if 'status' in body:
                if body['status'] == 'done' and not old['done_at']:
                    updates.append("done_at = ?")
                    args.append(now_iso)
                elif body['status'] == 'open':
                    updates.append("done_at = NULL")

            if updates:
                updates.append("updated_at = ?")
                args.append(now_iso)
                args.append(task_id)
                c.execute(f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?", args)

            for ev in events:
                c.execute('''
                INSERT INTO feedback_events (id, task_id, run_id, type, from_value, to_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', ev)

            conn.commit()
            c.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            updated_task = dict(c.fetchone())
            conn.close()
            self.send_json(200, {"task": updated_task})
            return

        self.send_error(404, "Not Found")

    def do_DELETE(self):
        valid, err_msg = self.check_security()
        if not valid:
            self.send_error(403, f"Forbidden: {err_msg}")
            return
        clean_path = self.path.split('?', 1)[0].split('#', 1)[0]

        # 清空所有当前任务 (软删除，将 open/done 变为 removed)
        if clean_path == '/api/tasks':
            now_iso = utcnow_iso()
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT id, run_id, status FROM tasks WHERE status != ?', ('removed',))
            active_tasks = c.fetchall()
            for t in active_tasks:
                ev_id = f"fb_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
                c.execute('''
                INSERT INTO feedback_events (id, task_id, run_id, type, from_value, to_value, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ''', (ev_id, t['id'], t['run_id'], 'status', t['status'], 'removed', now_iso))
            c.execute('UPDATE tasks SET status = ?, updated_at = ? WHERE status != ?', ('removed', now_iso, 'removed'))
            affected = c.rowcount
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "ok", "message": f"已清空看板，共归档移除 {affected} 项任务", "cleared_count": affected})
            return

        m = re.match(r'^/api/tasks/([^/]+)$', clean_path)
        if m:
            task_id = m.group(1)
            conn = get_db()
            c = conn.cursor()
            c.execute('SELECT * FROM tasks WHERE id = ?', (task_id,))
            old = c.fetchone()
            if not old:
                conn.close()
                self.send_json(404, {"error": "Task not found"})
                return

            now_iso = utcnow_iso()
            c.execute('UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?', ('removed', now_iso, task_id))
            ev_id = f"fb_{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}_{os.urandom(3).hex()}"
            c.execute('''
            INSERT INTO feedback_events (id, task_id, run_id, type, from_value, to_value, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (ev_id, task_id, old['run_id'], 'status', old['status'], 'removed', now_iso))
            conn.commit()
            conn.close()
            self.send_json(200, {"status": "ok", "message": "Task soft-deleted"})
            return

        self.send_error(404, "Not Found")

    def read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 0:
            raw = self.rfile.read(length).decode('utf-8')
            return json.loads(raw)
        return {}


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    init_db()
    env = load_env()
    host = os.environ.get('HOST', '') or env.get('HOST', '127.0.0.1')
    port = int(os.environ.get('PORT', '') or env.get('PORT', 8099))

    # A1: ThreadingHTTPServer 避免多请求串行阻塞
    server = ThreadingHTTPServer((host, port), TriageRequestHandler)
    print("=====================================================")
    print("CCagent 任务分诊服务 (v2 多线程精准智囊版) 已启动！")
    print(f"监听地址: http://{host}:{port}")
    print(f"数据库位置: {DB_PATH}")
    print(f"Gemini API Key: {'[已在 .env 配置]' if env.get('GEMINI_API_KEY') else '[未配置]'}")
    print("=====================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已关闭。")


if __name__ == '__main__':
    main()
