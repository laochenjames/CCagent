"""一法多解（芒格多元模型） (agent6) — config-driven thinking agent."""

import json
import os
import sys
from http.server import ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

import thinking_core as core

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
with open(CONFIG_PATH, "r", encoding="utf-8") as _f:
    AGENT_CONFIG = json.load(_f)

core.validate_agent_config(AGENT_CONFIG)

DB_PATH = os.path.join(BASE_DIR, "data", "munger_lever.db")
DEFAULT_PORT = 8776


def init_db():
    core.init_sqlite(DB_PATH)


RequestHandler = core.make_handler(
    config=AGENT_CONFIG,
    base_dir=BASE_DIR,
    db_path=DB_PATH,
)


if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", DEFAULT_PORT))
    srv = ThreadingHTTPServer(("127.0.0.1", port), RequestHandler)
    print(f"[agent6] listening on http://127.0.0.1:{port}", flush=True)
    srv.serve_forever()
