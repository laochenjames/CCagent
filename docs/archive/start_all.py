"""One-command launcher for both CCagent (port 8100) and agent2 (port 8099)."""
import os
import signal
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.abspath(__file__))


def main():
    procs = [
        subprocess.Popen([sys.executable, "server.py"], cwd=ROOT),
        subprocess.Popen([sys.executable, "server.py"], cwd=os.path.join(ROOT, "agent2")),
    ]
    print("CCagent started -> http://127.0.0.1:8100")
    print("agent2  started -> http://127.0.0.1:8099")
    print("Press Ctrl+C to stop both.")

    def _shutdown(*_args):
        for p in procs:
            if p.poll() is None:
                p.terminate()
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
        sys.exit(0)

    signal.signal(signal.SIGINT, _shutdown)
    signal.signal(signal.SIGTERM, _shutdown)

    while True:
        for p in procs:
            if p.poll() is not None:
                _shutdown()
        time.sleep(0.5)


if __name__ == "__main__":
    main()
