"""One-click deploy script for CCagent -> production VPS."""

import os
import sys
import urllib.request
import paramiko

ROOT = os.path.dirname(os.path.abspath(__file__))
ENV_PATH = r"E:\Doc\Python_daye\cchabit\.deploy.env"
REMOTE_BASE = "/opt/ccagent1/current"

FILES_TO_SYNC = [
    "server.py",
    "thinking_core.py",
    "index.html",
    "favicon.ico",
    "favicon.png",
    "shared/nav.js",
    "shared/thinking.css",
    "shared/thinking.js",
    "agent2/index.html",
    "agent2/app.js",
    "agent3/server.py",
    "agent3/index.html",
    "agent3/style.css",
    "agent3/app.js",
    "agent4/server.py",
    "agent4/index.html",
    "agent5/server.py",
    "agent5/index.html",
    "agent6/server.py",
    "agent6/index.html",
    "agent7/server.py",
    "agent7/index.html",
    "agent8/server.py",
    "agent8/index.html",
    "agent9/server.py",
    "agent9/index.html",
    "agent10/server.py",
    "agent10/index.html",
]

HEALTH_URLS = [
    "https://ccagent.mycici.top/",
    "https://ccagent.mycici.top/favicon.ico",
    "https://ccagent.mycici.top/favicon.png",
    "https://ccagent.mycici.top/shared/nav.js",
    "https://ccagent.mycici.top/shared/thinking.css",
    "https://ccagent.mycici.top/shared/thinking.js",
    "https://ccagent.mycici.top/agent2/",
    "https://ccagent.mycici.top/agent3/",
    "https://ccagent.mycici.top/agent4/",
    "https://ccagent.mycici.top/agent5/",
    "https://ccagent.mycici.top/agent6/",
    "https://ccagent.mycici.top/agent7/",
    "https://ccagent.mycici.top/agent8/",
    "https://ccagent.mycici.top/agent9/",
    "https://ccagent.mycici.top/agent10/",
]


def load_deploy_env(path):
    env = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def ensure_remote_dir(sftp, remote_dir):
    parts = remote_dir.strip("/").split("/")
    cur = ""
    for p in parts:
        cur += "/" + p
        try:
            sftp.stat(cur)
        except FileNotFoundError:
            sftp.mkdir(cur)


def main():
    env = load_deploy_env(ENV_PATH)
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        env["DEPLOY_HOST"],
        port=int(env.get("DEPLOY_PORT", 22)),
        username=env["DEPLOY_USER"],
        password=env["DEPLOY_PASSWORD"],
        timeout=30,
        banner_timeout=45,
        auth_timeout=30,
    )
    sftp = ssh.open_sftp()

    for rel in FILES_TO_SYNC:
        local_f = os.path.join(ROOT, rel)
        if not os.path.isfile(local_f):
            print(f"[SKIP] missing local file: {rel}")
            continue
        remote_f = f"{REMOTE_BASE}/{rel}"
        ensure_remote_dir(sftp, os.path.dirname(remote_f))
        sftp.put(local_f, remote_f)
        print(f"[OK] uploaded {rel}")

    sftp.close()

    _, out, err = ssh.exec_command(
        "systemctl restart ccagent1.service && sleep 1 && systemctl is-active ccagent1.service"
    )
    status = out.read().decode().strip()
    err_txt = err.read().decode().strip()
    ssh.close()
    print(f"[SERVICE] ccagent1.service -> {status}" + (f" ({err_txt})" if err_txt else ""))
    if status != "active":
        sys.exit(1)

    failed = 0
    for url in HEALTH_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read()
                print(f"[{resp.status}] {resp.headers.get('Content-Type')} ({len(body)}B) {url}")
        except Exception as exc:
            print(f"[FAIL] {url} -> {exc}")
            failed += 1
    if failed:
        sys.exit(1)
    print("Deploy & health check passed!")


if __name__ == "__main__":
    main()
