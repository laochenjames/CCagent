"""
CCagent - 管理者任务分诊台 本地服务端与 Gemini API 转发中继
零第三方依赖，纯 Python 原生库实现
"""

import os
import sys
import json
import urllib.request
import urllib.error
from http.server import HTTPServer, SimpleHTTPRequestHandler

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ENV_FILE = os.path.join(ROOT_DIR, '.env')
PROMPT_FILE = os.path.join(ROOT_DIR, 'prompts', 'triage_prompt.md')
EVENT_LIB_FILE = os.path.join(ROOT_DIR, 'prompts', 'event_library_v2.json')

# 禁止通过静态服务直接下载的文件
BLOCKED_NAMES = {'.env', 'server.py'}


def load_env():
    env = {}
    if os.path.exists(ENV_FILE):
        with open(ENV_FILE, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, v = line.split('=', 1)
                    env[k.strip()] = v.strip()
    return env


def save_env(updates):
    current = load_env()
    current.update(updates)
    lines = []
    lines.append("# CCagent 配置文件")
    for k, v in current.items():
        lines.append(f"{k}={v}")
    with open(ENV_FILE, 'w', encoding='utf-8') as f:
        f.write('\n'.join(lines) + '\n')


def build_event_index():
    """只把事件库的精简索引（id、名称、识别特征）交给模型，完整内容留在本地，不外发。"""
    try:
        with open(EVENT_LIB_FILE, 'r', encoding='utf-8') as f:
            events = json.load(f)
    except Exception:
        return "（事件库不可用，所有任务的 eventId 一律填 null）"
    lines = []
    for item in events:
        lines.append(f"- {item.get('id')}｜{item.get('name')}｜{item.get('feature')}")
    return '\n'.join(lines) if lines else "（事件库为空，所有任务的 eventId 一律填 null）"


def build_system_prompt():
    """提示词的唯一来源是 prompts/triage_prompt.md，每次请求重新读取，改完无需重启。"""
    with open(PROMPT_FILE, 'r', encoding='utf-8') as f:
        template = f.read()
    return template.replace('{{EVENT_INDEX}}', build_event_index())


def sanitize_model(model):
    # 自动将已废弃的模型映射到最新可用的稳定版
    if not model or model in ['gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-2.5-flash']:
        return 'gemini-3.5-flash'
    return model


def call_gemini(api_key, model, base_url, user_text):
    if not api_key:
        raise ValueError("尚未配置谷歌 Gemini API Key！请在界面右上角 [API 配置] 中输入。")

    model = sanitize_model(model)
    endpoint = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {
            "parts": [{"text": build_system_prompt()}]
        },
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"请对以下管理者的任务进行分诊：\n\n{user_text}"}]
            }
        ],
        "generationConfig": {
            "temperature": 0.2,
            "response_mime_type": "application/json"
        }
    }

    req = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode('utf-8'),
        headers={'Content-Type': 'application/json'}
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            candidates = data.get('candidates', [])
            if not candidates:
                raise ValueError("Gemini 未返回有效候选内容")
            raw_content = candidates[0].get('content', {}).get('parts', [{}])[0].get('text', '{}')
            # 兼容可能的 markdown 标记包裹
            clean_json_str = raw_content.strip()
            if clean_json_str.startswith('```json'):
                clean_json_str = clean_json_str[7:]
            if clean_json_str.startswith('```'):
                clean_json_str = clean_json_str[3:]
            if clean_json_str.endswith('```'):
                clean_json_str = clean_json_str[:-3]

            return json.loads(clean_json_str.strip())
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8', errors='ignore')
        raise RuntimeError(f"Google Gemini API 报错 ({e.code}): {err_msg}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"网络连接失败: {e.reason}。请检查代理设置或在配置中填写中转反代 Base URL。")


class TriageRequestHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=ROOT_DIR, **kwargs)

    def is_blocked_path(self):
        clean = self.path.split('?', 1)[0].split('#', 1)[0]
        name = os.path.basename(clean).lower()
        return (
            name in BLOCKED_NAMES
            or name.endswith('.pyc')
            or '/__pycache__' in clean
        )

    def do_GET(self):
        if self.is_blocked_path():
            self.send_error(403, "Forbidden")
            return

        if self.path == '/api/config':
            env = load_env()
            key = env.get('GEMINI_API_KEY', '')
            masked = (key[:6] + '...' + key[-4:]) if len(key) > 10 else ('已配置' if key else '')
            raw_model = env.get('GEMINI_MODEL', 'gemini-3.5-flash')
            resp = {
                "has_key": bool(key),
                "masked_key": masked,
                "model": sanitize_model(raw_model),
                "base_url": env.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com')
            }
            self.send_json(200, resp)
            return

        super().do_GET()

    def do_POST(self):
        if self.path == '/api/save-config':
            body = self.read_json_body()
            updates = {}
            raw_key = body.get('api_key', '')
            if isinstance(raw_key, str):
                raw_key = raw_key.strip()
            else:
                raw_key = ''

            # 严防覆盖：只有当用户输入了真正的新 Key 时才写入 .env，避免占位符抹除已有 Key
            if raw_key and raw_key != 'server-configured' and '...' not in raw_key and '已在' not in raw_key:
                updates['GEMINI_API_KEY'] = raw_key
            if 'model' in body and body['model']:
                updates['GEMINI_MODEL'] = sanitize_model(body['model'].strip())
            if 'base_url' in body and body['base_url']:
                updates['GEMINI_BASE_URL'] = body['base_url'].strip()

            save_env(updates)
            self.send_json(200, {"status": "ok", "message": "配置已保存"})
            return

        elif self.path == '/api/test-connection':
            body = self.read_json_body()
            env = load_env()
            req_key = body.get('api_key', '').strip()
            if not req_key or req_key == 'server-configured' or '...' in req_key:
                api_key = env.get('GEMINI_API_KEY', '')
            else:
                api_key = req_key

            model = sanitize_model(body.get('model') or env.get('GEMINI_MODEL', 'gemini-3.5-flash'))
            base_url = body.get('base_url') or env.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com')

            try:
                endpoint = f"{base_url.rstrip('/')}/v1beta/models/{model}:generateContent?key={api_key}"
                test_payload = {
                    "contents": [{"parts": [{"text": "Hello, answer in 1 word: Pong"}]}]
                }
                req = urllib.request.Request(
                    endpoint,
                    data=json.dumps(test_payload).encode('utf-8'),
                    headers={'Content-Type': 'application/json'}
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    json.loads(resp.read().decode('utf-8'))
                    self.send_json(200, {"status": "ok", "message": f"连通成功！Google Gemini ({model}) 响应正常。"})
            except Exception as e:
                err_detail = str(e)
                if hasattr(e, 'read'):
                    err_detail += " - " + e.read().decode('utf-8', errors='ignore')
                self.send_json(500, {"status": "error", "message": err_detail})
            return

        elif self.path == '/api/triage':
            body = self.read_json_body()
            user_text = body.get('text', '').strip()
            if not user_text:
                self.send_json(400, {"error": "请输入需要分诊的任务文本"})
                return

            env = load_env()
            req_key = body.get('api_key', '').strip()
            if not req_key or req_key == 'server-configured' or '...' in req_key:
                api_key = env.get('GEMINI_API_KEY', '')
            else:
                api_key = req_key

            model = sanitize_model(body.get('model') or env.get('GEMINI_MODEL', 'gemini-3.5-flash'))
            base_url = body.get('base_url') or env.get('GEMINI_BASE_URL', 'https://generativelanguage.googleapis.com')

            try:
                result = call_gemini(api_key, model, base_url, user_text)
                if isinstance(result, dict):
                    result['engine'] = 'gemini'
                    result['model'] = model
                self.send_json(200, result)
            except Exception as e:
                err_detail = str(e)
                if hasattr(e, 'read'):
                    err_detail += " - " + e.read().decode('utf-8', errors='ignore')
                self.send_json(500, {"error": err_detail})
            return

        self.send_error(404, "Not Found")

    def read_json_body(self):
        length = int(self.headers.get('Content-Length', 0))
        if length > 0:
            raw = self.rfile.read(length).decode('utf-8')
            return json.loads(raw)
        return {}

    def send_json(self, status_code, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()


def main():
    if sys.platform == "win32":
        try:
            sys.stdout.reconfigure(encoding='utf-8')
            sys.stderr.reconfigure(encoding='utf-8')
        except Exception:
            pass

    env = load_env()
    port = int(env.get('PORT', 8099))
    server = HTTPServer(('0.0.0.0', port), TriageRequestHandler)
    print("=====================================================")
    print(f"CCagent 管理者任务分诊服务已启动！")
    print(f"本地访问地址: http://127.0.0.1:{port}")
    print(f"Gemini API Key 状态: {'[已配置]' if env.get('GEMINI_API_KEY') else '[未配置，请在界面右上角点击 API 配置]'}")
    print("=====================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已关闭。")


if __name__ == '__main__':
    main()
