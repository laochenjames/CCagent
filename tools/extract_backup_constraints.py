"""H3.5: Rebuild backup constraint index and verify fixture entries exist in backup.

Requires docs/archive/council_backup_20261127/ to exist (manual run).
Combines index generation (build_backup_constraint_index.py) with backup-existence verification.
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))

import build_backup_constraint_index as idx_builder

BACKUP_DIR = idx_builder.BACKUP_DIR
FIXTURE_PATH = os.path.join(ROOT, "tests", "fixtures", "council_constraints.json")


def main():
    idx_builder.main()
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        fixture = json.load(f)
    for n in range(4, 11):
        aid = f"agent{n}"
        p = os.path.join(BACKUP_DIR, f"{aid}_server.py")
        src = open(p, encoding="utf-8").read()
        entries = fixture.get(aid, [])
        missing_in_backup = []
        for e in entries:
            if e.get("status") == "required" and e.get("kind") in ("count",) and e.get("path", "").endswith(".count"):
                continue  # normalized count token like "3-4" / "4-5"
            if e.get("path") == "synthesis_hint":
                continue  # combined hint string
            check_txt = e.get("old") or e.get("text") or ""
            if check_txt and check_txt not in src:
                missing_in_backup.append(check_txt)
        print(f"{aid}: {len(entries)} fixture entries, not-in-backup={len(missing_in_backup)}")
        for m in missing_in_backup:
            print(f"  WARN not found verbatim in backup: {m}")


if __name__ == "__main__":
    main()
