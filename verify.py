"""Extraction verification and output linting."""

import json
import re
from engine import FUTURE_FIELDS, NUMBER_WHITELIST

VALID_CATEGORIES = {"事实", "自报", "估计", "猜测"}

BANNED_PHRASES = [
    "停。",
    "重复同一模式",
    "又是试试看",
    "你反复",
    "别再用",
    "废话",
]
BANNED_REGEX = re.compile(r"你(这个人|总是|一直|习惯|性格)")

_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}
_CN_NUM_RE = re.compile(r"([零〇一二两三四五六七八九十百千万]+)(?=[个年月周天小时块元倍成万千%])")
_ARABIC_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


def normalize_text(text):
    """Normalize whitespace and full-width/half-width punctuation for substring matching."""
    if not text:
        return ""
    trans = str.maketrans({
        "，": ",", "。": ".", "！": "!", "？": "?", "：": ":", "；": ";",
        "（": "(", "）": ")", "【": "[", "】": "]", "“": '"', "”": '"',
        "‘": "'", "’": "'", "、": ",", "　": " ",
    })
    s = text.translate(trans)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def parse_chinese_numeral(token):
    """Convert a simple Chinese numeral string (up to 万) into a float/int, or None."""
    if not token:
        return None
    if all(ch in _CN_DIGITS for ch in token):
        val = 0
        for ch in token:
            val = val * 10 + _CN_DIGITS[ch]
        return float(val)

    total = 0
    section = 0
    num = 0
    has_any = False
    for ch in token:
        if ch in _CN_DIGITS:
            num = _CN_DIGITS[ch]
            has_any = True
        elif ch in _CN_UNITS:
            unit = _CN_UNITS[ch]
            has_any = True
            if unit == 10000:
                section = (section + num) * unit if (section + num) > 0 else unit
                total += section
                section = 0
                num = 0
            else:
                if num == 0 and unit == 10 and section == 0:
                    num = 1
                section += num * unit
                num = 0
        else:
            return None
    if not has_any:
        return None
    return float(total + section + num)


def extract_numbers(text):
    """Extract all Arabic and Chinese numbers from text as a set of floats."""
    nums = set()
    if not text:
        return nums
    for m in _ARABIC_NUM_RE.findall(text):
        try:
            nums.add(float(m))
        except ValueError:
            pass
    for m in _CN_NUM_RE.findall(text):
        val = parse_chinese_numeral(m)
        if val is not None:
            nums.add(val)
    return nums


def _number_in_quote(target_val, quote):
    """Check if target_val (float) appears in quote via Arabic or Chinese numerals."""
    q_nums = extract_numbers(quote)
    for n in q_nums:
        if abs(n - target_val) < 1e-6:
            return True
    return False


def verify_extracted(raw_text, extracted_list, registry, existing_fields=None):
    """Verify LLM-extracted items against registry, quotes, and locked fields."""
    reg_map = {f["id"]: f for f in registry}
    norm_raw = normalize_text(raw_text)
    existing = existing_fields or {}
    verified = {}
    dropped = []

    for item in (extracted_list or []):
        if not isinstance(item, dict):
            continue
        fid = item.get("id", "")
        if fid not in reg_map:
            dropped.append({"id": fid, "reason": "unknown_field"})
            continue

        if fid in existing and existing[fid].get("source") == "form":
            continue

        fdef = reg_map[fid]
        ftype = fdef.get("type", "text")
        raw_val = item.get("value")
        status = item.get("status", "given")
        if status not in ("given", "ambiguous"):
            status = "given"

        quote = item.get("quote", "")
        if not quote or normalize_text(quote) not in norm_raw:
            dropped.append({"id": fid, "reason": "quote_not_in_text"})
            continue

        parsed_val = raw_val
        if status == "given":
            if ftype == "enum":
                valid_choices = {c["value"] for c in fdef.get("choices", [])}
                if str(raw_val) not in valid_choices:
                    dropped.append({"id": fid, "reason": "invalid_enum"})
                    continue
                parsed_val = str(raw_val)
            elif ftype == "bool":
                low = str(raw_val).strip().lower()
                if low == "true":
                    parsed_val = True
                elif low == "false":
                    parsed_val = False
                else:
                    dropped.append({"id": fid, "reason": "invalid_bool"})
                    continue
            elif ftype == "number":
                try:
                    num_val = float(raw_val)
                except (TypeError, ValueError):
                    dropped.append({"id": fid, "reason": "invalid_number"})
                    continue
                if not _number_in_quote(num_val, quote):
                    dropped.append({"id": fid, "reason": "number_not_in_quote"})
                    continue
                parsed_val = int(num_val) if num_val.is_integer() else num_val
            elif ftype == "list":
                if isinstance(raw_val, str):
                    try:
                        parsed_val = json.loads(raw_val)
                    except Exception:
                        dropped.append({"id": fid, "reason": "invalid_list"})
                        continue
                if not isinstance(parsed_val, list):
                    dropped.append({"id": fid, "reason": "invalid_list"})
                    continue

        cat = item.get("category", "自报")
        if cat not in VALID_CATEGORIES:
            cat = "自报"
        if fid in FUTURE_FIELDS and cat == "事实":
            cat = "估计"

        readings = item.get("readings", [])
        if not isinstance(readings, list):
            readings = []

        verified[fid] = {
            "id": fid,
            "value": parsed_val,
            "unit": item.get("unit") or fdef.get("unit", ""),
            "category": cat,
            "quote": quote,
            "status": status,
            "readings": readings if status == "ambiguous" else [],
            "source": "text",
            "ask_count": existing.get(fid, {}).get("ask_count", 0),
        }

    return verified, dropped


def _has_banned_phrase(text):
    if not text:
        return False
    for p in BANNED_PHRASES:
        if p in text:
            return True
    return bool(BANNED_REGEX.search(text))


def _has_unverified_number(text, allowed_nums):
    if not text:
        return False
    nums = extract_numbers(text)
    for n in nums:
        if not any(abs(n - a) < 1e-6 for a in allowed_nums):
            return True
    return False


def lint_output(raw_text, confirmed_numbers, llm_output, allow_hide=True):
    """Lint LLM output for unverified numbers, banned phrases, threshold tags, and AI_IMPACT."""
    allowed_nums = set(extract_numbers(raw_text))
    for n in (confirmed_numbers or []):
        try:
            allowed_nums.add(float(n))
        except (TypeError, ValueError):
            pass
    for n in NUMBER_WHITELIST:
        allowed_nums.add(float(n))

    norm_raw = normalize_text(raw_text)
    hidden_count = 0
    number_violations = 0

    def _clean_text(t):
        nonlocal hidden_count, number_violations
        if not t or not isinstance(t, str):
            return t
        if _has_banned_phrase(t):
            hidden_count += 1
            return "（该条含不当措辞，已隐藏）"
        if _has_unverified_number(t, allowed_nums):
            number_violations += 1
            if allow_hide:
                hidden_count += 1
                return "（该条含未核实数字，已隐藏）"
        return t

    out = json.loads(json.dumps(llm_output, ensure_ascii=False))

    for adv in out.get("advisors", []):
        if not isinstance(adv, dict):
            continue
        for k in ("basis", "note", "insight", "next_step"):
            if k in adv:
                adv[k] = _clean_text(adv.get(k, ""))
        if adv.get("id") == "AI_IMPACT":
            for k in ("basis", "note", "insight"):
                val = adv.get(k, "")
                if val and "隐藏" not in val and "判断，不是数据" not in val:
                    adv[k] = val + "（判断，不是数据）"

    for c in out.get("critique", []):
        if isinstance(c, dict):
            c["text"] = _clean_text(c.get("text", ""))

    for tw in out.get("two_week_checks", []):
        if isinstance(tw, dict):
            tw["text"] = _clean_text(tw.get("text", ""))

    vd = out.get("validation_design", {})
    if isinstance(vd, dict):
        for k in ("supply", "demand"):
            if isinstance(vd.get(k), list):
                vd[k] = [_clean_text(x) for x in vd[k]]
        if isinstance(vd.get("threshold"), list):
            new_th = []
            for th in vd["threshold"]:
                cleaned = _clean_text(th)
                if "隐藏" not in cleaned:
                    if cleaned.endswith("【用户确认】"):
                        body = cleaned[:-6].strip()
                        if normalize_text(body) not in norm_raw:
                            cleaned = body + "【AI建议值】"
                    elif not cleaned.endswith("【AI建议值】"):
                        cleaned = cleaned + "【AI建议值】"
                new_th.append(cleaned)
            vd["threshold"] = new_th

    for cl in out.get("clarify", []):
        if isinstance(cl, dict):
            cl["question"] = _clean_text(cl.get("question", ""))
            cl["why"] = _clean_text(cl.get("why", ""))

    return out, number_violations, hidden_count

