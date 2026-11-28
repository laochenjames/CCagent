"""H6: Local Gemini responseSchema compliance checker for agent4-agent10 + built-in negative cases.

NOTE: This is a local static check against documented Gemini Schema fields,
NOT a substitute for real Gemini API verification.

Usage:
  python tools/check_schema.py
"""

import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

import thinking_core as core

KNOWN_SUPPORTED_KEYS = {"type", "properties", "items", "required", "enum", "description", "nullable", "format"}
PENDING_VERIFY_KEYS = {"minItems", "maxItems", "propertyOrdering"}
ALLOWED_TYPES = {"OBJECT", "ARRAY", "STRING", "NUMBER", "INTEGER", "BOOLEAN"}


def check_node(node, path="root"):
    """Return (errors, warnings)."""
    errors = []
    warnings = []
    if not isinstance(node, dict):
        return [f"{path}: node is not a dict"], warnings
    for k in node:
        if k in KNOWN_SUPPORTED_KEYS:
            continue
        if k in PENDING_VERIFY_KEYS:
            warnings.append(f"{path}: pending-verify key '{k}'")
        else:
            errors.append(f"{path}: disallowed key '{k}'")
    t = node.get("type")
    if t not in ALLOWED_TYPES:
        errors.append(f"{path}: invalid or missing uppercase type '{t}'")
    if "enum" in node and t != "STRING":
        errors.append(f"{path}: 'enum' only allowed on STRING nodes, got type='{t}'")
    if "properties" in node:
        if not isinstance(node["properties"], dict):
            errors.append(f"{path}.properties: must be dict")
        else:
            for pk, pv in node["properties"].items():
                e2, w2 = check_node(pv, f"{path}.properties.{pk}")
                errors.extend(e2)
                warnings.extend(w2)
    if "items" in node:
        e2, w2 = check_node(node["items"], f"{path}.items")
        errors.extend(e2)
        warnings.extend(w2)
    return errors, warnings


NEGATIVE_CASES = [
    ("neg_lowercase_type", {"type": "object", "properties": {"a": {"type": "STRING"}}}),
    ("neg_additionalProperties", {"type": "OBJECT", "additionalProperties": False}),
    ("neg_enum_on_non_string", {"type": "INTEGER", "enum": ["1", "2"]}),
]


def run_negative_cases():
    results = []
    for name, schema in NEGATIVE_CASES:
        errs, _ = check_node(schema, name)
        results.append((name, errs))
    return results


def main():
    print(f"Ruleset: known_supported={sorted(KNOWN_SUPPORTED_KEYS)}")
    print(f"Ruleset: pending_verify (WARN only)={sorted(PENDING_VERIFY_KEYS)}")
    print(f"Ruleset: allowed_types={sorted(ALLOWED_TYPES)}")
    failed = 0
    for n in range(4, 11):
        aid = f"agent{n}"
        cfg_path = os.path.join(ROOT, aid, "config.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            cfg = json.load(f)
        schema = core.build_generate_schema(cfg)
        errs, warns = check_node(schema, aid)
        if errs:
            failed += 1
            print(f"FAIL {aid}:")
            for e in errs:
                print(f"  - {e}")
        else:
            print(f"PASS {aid}" + (f" (WARN: {len(warns)})" if warns else ""))
            for w in warns:
                print(f"  WARN: {w}")

    print("--- Built-in negative cases (expected FAIL) ---")
    for name, errs in run_negative_cases():
        if errs:
            print(f"FAIL (expected) {name}: {errs[0]}")
        else:
            failed += 1
            print(f"UNEXPECTED PASS {name}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
