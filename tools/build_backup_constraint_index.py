"""H3: Mechanically extract constraint fragments from backup agent4-10 server.py using AST.

Requires docs/archive/council_backup_20261127/ to exist (manual run only).
Writes tests/fixtures/backup_constraint_index.json.

Usage:
  python tools/build_backup_constraint_index.py
"""

import ast
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BACKUP_DIR = os.path.join(ROOT, "docs", "archive", "council_backup_20261127")
OUT_PATH = os.path.join(ROOT, "tests", "fixtures", "backup_constraint_index.json")

RE_LEN = re.compile(r"\d+\s*[~～\-–]?\s*\d*\s*字(?:以内|以下|内)?")
RE_CNT = re.compile(r"\d+\s*[~～\-–]?\s*\d*\s*(?:项|步|条|个)")
RE_JSON_KV = re.compile(r'"(tag|heading|label)"\s*:\s*"([^"]+)"')


def _collect_string_constants(func_node):
    """Return all constant string chunks (including f-string literal parts) inside a function."""
    chunks = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            chunks.append(node.value)
    return chunks


def extract_for_agent(backup_path):
    src = open(backup_path, "r", encoding="utf-8").read()
    tree = ast.parse(src)
    found = []
    seen = set()

    def add(frag, where, kind):
        frag = frag.strip()
        if not frag:
            return
        key = (where, frag)
        if key not in seen:
            seen.add(key)
            found.append({"text": frag, "where": where, "kind": kind})

    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef) or node.name not in ("_generate_ai", "_extract_ai"):
            continue
        where = "extract" if node.name == "_extract_ai" else "generate"
        for chunk in _collect_string_constants(node):
            lines = chunk.splitlines()
            in_core_rules = False
            for raw_line in lines:
                line = raw_line.strip()
                if not line:
                    in_core_rules = False
                    continue
                # Extract prompt instruction sentence
                if where == "extract" and ("未提及" in line or "不要编造" in line or "留空" in line) and "{" not in line:
                    add(line, where, "wording")
                # Core rules block bullet lines
                if line.startswith("核心要求"):
                    in_core_rules = True
                    continue
                if in_core_rules and line.startswith("- "):
                    add(line[2:].strip(), where, "wording")
                    continue
                elif in_core_rules and not line.startswith("- "):
                    in_core_rules = False
                # Length fragments
                for m in RE_LEN.finditer(line):
                    add(m.group(0), where, "length")
                # Count fragments
                for m in RE_CNT.finditer(line):
                    add(m.group(0), where, "count")
                # JSON template tag / heading / label string values
                for m in RE_JSON_KV.finditer(line):
                    add(m.group(2), where, "structure")
    return found


def main():
    if not os.path.isdir(BACKUP_DIR):
        print(f"ERROR: Backup directory not found: {BACKUP_DIR}")
        sys.exit(1)
    index = {}
    total = 0
    for n in range(4, 11):
        aid = f"agent{n}"
        p = os.path.join(BACKUP_DIR, f"{aid}_server.py")
        items = extract_for_agent(p)
        index[aid] = items
        total += len(items)
        print(f"{aid}: {len(items)} fragments")
    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=2)
    print(f"Wrote {OUT_PATH} (total {total} fragments)")


if __name__ == "__main__":
    main()
