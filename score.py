"""Pure scoring model for career investment checkup (v2.3, no I/O)."""

import copy
import engine

RULES_VERSION = "2.3"

# 经验权重（仅用于加权几何平均，非统计回归结果）
FACTOR_WEIGHTS = {
    "MONETIZATION": 3,
    "CAPABILITY": 2,
    "EXECUTION": 2,
    "OPPORTUNITY": 2,
    "SAFETY_NET": 2,
    "STOPLOSS": 1,
}

FACTOR_NAMES = {
    "MONETIZATION": "变现与需求",
    "CAPABILITY": "能力与渠道",
    "EXECUTION": "时间与执行",
    "OPPORTUNITY": "划算程度",
    "SAFETY_NET": "财务安全垫",
    "STOPLOSS": "止损设置",
}

FACTOR_GROUP = {
    "MONETIZATION": "变现与需求",
    "CAPABILITY": "能力与渠道",
    "EXECUTION": "时间与执行",
    "OPPORTUNITY": "划算程度",
    "SAFETY_NET": "财务安全垫",
    "STOPLOSS": "止损设置",
}

GROUP_EXCLUDE_KEY = {
    "变现与需求": "excl_MONETIZATION",
    "划算程度": "excl_OPPORTUNITY",
}

FACTOR_EXCLUDE_KEY = {
    "MONETIZATION": "excl_MONETIZATION",
    "OPPORTUNITY": "excl_OPPORTUNITY",
}

# 评级 -> 经验评分点
RATING_SCORE = {
    "高": 0.85,
    "中": 0.55,
    "低": 0.20,
}

# 证据类别 -> 半宽（经验值）
EVIDENCE_HALF_WIDTH = {
    "事实": 0.00,
    "自报": 0.05,
    "估计": 0.10,
    "猜测": 0.18,
}

UNKNOWN_INTERVAL = (0.15, 0.95)
UNKNOWN_POINT = 0.55

FACTOR_KEY_FIELDS = {
    "MONETIZATION": ["paid_evidence", "precedent"],
    "CAPABILITY": ["skill_evidence", "channel_access"],
    "EXECUTION": ["weekly_hours_actual_recent", "weekly_hours_planned", "continuity_weeks_12m"],
    "OPPORTUNITY": ["unit_price", "take_home_ratio", "floor_take_home_per_unit"],
    "SAFETY_NET": ["cash_free", "monthly_expense", "income_after_monthly", "cash_outlay", "borrowing_or_essential_funds"],
    "STOPLOSS": ["first_paid_month", "validation_months", "will_really_stop"],
}


def _applicable_key_fields(factor_id, fields_state, reg_map):
    """Return applicable key field IDs for a factor."""
    keys = list(FACTOR_KEY_FIELDS.get(factor_id, []))
    if factor_id == "OPPORTUNITY":
        f_th = fields_state.get("floor_take_home_per_unit", {})
        f_cl = fields_state.get("floor_price_client", {})
        if f_th.get("status") != "given" and f_cl.get("status") == "given":
            keys = ["unit_price", "take_home_ratio", "floor_price_client"]
    applicable = []
    for fid in keys:
        fdef = reg_map.get(fid)
        if fdef and engine.is_field_applicable(fdef, fields_state):
            applicable.append(fid)
    return applicable


def _factor_interval(factor_id, rating, fields_state, reg_map):
    """Compute (point, lo, hi, known) for a single factor."""
    if rating == "无法判断":
        return UNKNOWN_POINT, UNKNOWN_INTERVAL[0], UNKNOWN_INTERVAL[1], False

    p = RATING_SCORE[rating]
    app_keys = _applicable_key_fields(factor_id, fields_state, reg_map)
    provided = [
        fields_state[fid]
        for fid in app_keys
        if fields_state.get(fid, {}).get("status") == "given"
    ]

    if not provided:
        ev_hw = 0.18
    else:
        ev_hw = max(EVIDENCE_HALF_WIDTH.get(f.get("category", "自报"), 0.05) for f in provided)

    cov = (len(provided) / len(app_keys)) if app_keys else 1.0
    cov_hw = 0.15 * (1.0 - cov)
    hw = ev_hw + cov_hw

    lo = max(0.15, p - hw)
    hi = min(0.95, p + hw)
    return p, lo, hi, True


def _compute_synthesis(raw_factors, active_weights, total_w, point_f, red_line):
    """Compute weakest/strongest factor and synthesis sentence."""
    known_factors = [f for f in raw_factors if f["known"]]
    if not known_factors:
        return {"weakest": None, "strongest": None, "group": None, "sentence": ""}

    if red_line:
        return {
            "weakest": None,
            "strongest": None,
            "group": None,
            "sentence": "红线未解除前，改善其他项不会改变结论。",
        }

    # Strongest: highest point among known factors
    strongest_f = max(known_factors, key=lambda f: (f["point"], active_weights[f["id"]]))
    strongest = {"id": strongest_f["id"], "name": strongest_f["name"], "rating": strongest_f["rating"]}

    # Weakest: simulate +1 tier for 低/中
    next_tier = {"低": ("中", RATING_SCORE["中"]), "中": ("高", RATING_SCORE["高"])}
    candidates = []
    for f in known_factors:
        if f["rating"] not in next_tier:
            continue
        _, new_p = next_tier[f["rating"]]
        sim_prod = 1.0
        for f2 in raw_factors:
            w = active_weights[f2["id"]] / total_w
            p2 = new_p if f2["id"] == f["id"] else f2["point"]
            sim_prod *= p2 ** w
        delta_raw = 100.0 * sim_prod - point_f
        delta = max(1, round(delta_raw)) if delta_raw > 0 else 0
        candidates.append((delta, -engine.RATING_ORDER[f["rating"]], active_weights[f["id"]], f))

    if not candidates:
        return {
            "weakest": None,
            "strongest": strongest,
            "group": None,
            "sentence": "已评估的项目目前没有明显短板。",
        }

    candidates.sort(key=lambda x: (x[0], x[1], x[2]), reverse=True)
    best_delta, _, _, wf = candidates[0]
    weakest = {"id": wf["id"], "name": wf["name"], "rating": wf["rating"], "delta": best_delta}
    if strongest["id"] == weakest["id"]:
        strongest = None

    sentence = f"最大短板：{weakest['name']}（{weakest['rating']}），把它提升一档，评分约 +{best_delta}。"
    if strongest:
        sentence += f" 最强项：{strongest['name']}。"

    return {
        "weakest": weakest,
        "strongest": strongest,
        "group": FACTOR_GROUP.get(weakest["id"]),
        "sentence": sentence,
    }


def compute_score(fields_state, registry):
    """Compute overall score, confidence, intervals, factors, synthesis, and headline."""
    reg_map = {f["id"]: f for f in registry}
    rate_fns = {
        "MONETIZATION": engine.rate_monetization,
        "CAPABILITY": engine.rate_capability,
        "EXECUTION": engine.rate_execution,
        "OPPORTUNITY": engine.rate_opportunity,
        "SAFETY_NET": engine.rate_safety_net,
        "STOPLOSS": engine.rate_stoploss,
    }

    purpose = engine._get_given_val(fields_state, "purpose")
    is_learn = purpose == "learn"

    raw_factors = []
    active_weights = {}
    excluded = []

    for fid, fn in rate_fns.items():
        if is_learn and fid in ("MONETIZATION", "OPPORTUNITY", "CAPABILITY"):
            excluded.append({"id": fid, "name": FACTOR_NAMES[fid], "reason": "学习型不适用", "rating_if_included": None})
            continue
        excl_key = FACTOR_EXCLUDE_KEY.get(fid)
        if excl_key and engine._to_bool(engine._get_given_val(fields_state, excl_key)) is True:
            incl_rating, _ = fn(fields_state)
            excluded.append({"id": fid, "name": FACTOR_NAMES[fid], "reason": "你标记为不适用", "rating_if_included": incl_rating})
            continue

        rating, rule_note = fn(fields_state)
        if rating == "不适用":
            continue
        active_weights[fid] = FACTOR_WEIGHTS[fid]
        p, lo, hi, known = _factor_interval(fid, rating, fields_state, reg_map)
        raw_factors.append({
            "id": fid,
            "name": FACTOR_NAMES[fid],
            "rating": rating,
            "rule_note": rule_note,
            "known": known,
            "point": p,
            "interval": [round(lo * 100), round(hi * 100)],
            "_lo": lo,
            "_hi": hi,
        })

    total_w = sum(active_weights.values())
    if total_w <= 0:
        point_f = 55.0
        low_f = 15.0
        high_f = 95.0
    else:
        point_prod = 1.0
        low_prod = 1.0
        high_prod = 1.0
        for f in raw_factors:
            w = active_weights[f["id"]] / total_w
            point_prod *= f["point"] ** w
            low_prod *= f["_lo"] ** w
            high_prod *= f["_hi"] ** w
        point_f = 100.0 * point_prod
        low_f = 100.0 * low_prod
        high_f = 100.0 * high_prod

    conf = max(0.0, min(1.0, 1.0 - (high_f - low_f) / 80.0))
    display_conf = min(0.95, conf)

    red_reasons = engine.red_line_reasons(fields_state)
    red_line = len(red_reasons) > 0
    if red_line:
        high_f = min(high_f, 25.0)
        low_f = min(low_f, high_f)
        point_f = min(point_f, high_f)

    if red_line:
        label = "偏低"
        action = "不建议投入"
    elif display_conf < 0.25:
        label = "还看不出来"
        action = ""
    else:
        if point_f < 35.0:
            label = "偏低"
            action = "目前不太划算，除非能改善下面几项"
        elif point_f < 65.0:
            label = "一般"
            action = "适合先小额试验"
        else:
            label = "偏高"
            if display_conf >= 0.5 and low_f >= 50.0:
                action = "值得认真推进验证"
            else:
                action = "目前偏乐观，先补下面几项"

    if display_conf < 0.25 and not red_line:
        headline_body = "目前信息太少，还看不出来。把下面几项补一补，判断会更有依据。"
    elif red_line:
        headline_body = f"综合来看，现阶段**不建议**投入。原因：{'；'.join(red_reasons)}。"
    else:
        prefix = "初步看法：" if display_conf < 0.5 else ""
        if is_learn:
            headline_body = f"{prefix}学习型：按试错成本与坚持度评估——{label}——{action}。"
        else:
            headline_body = f"{prefix}{label}——{action}。"

    headline = f"{headline_body}\n这是基于你提供的信息的大致判断，不是精确数字。"
    synthesis = _compute_synthesis(raw_factors, active_weights, total_w, point_f, red_line)

    factors_out = [
        {
            "id": f["id"],
            "name": f["name"],
            "rating": f["rating"],
            "rule_note": f["rule_note"],
            "known": f["known"],
            "interval": f["interval"],
        }
        for f in raw_factors
    ]

    return {
        "score": {
            "point": round(point_f),
            "low": round(low_f),
            "high": round(high_f),
            "label": label,
            "action": action,
            "confidence": round(display_conf, 4),
            "confidence_pct": round(display_conf * 100),
            "confidence_note": "置信度表示信息够不够，不表示结论一定对。",
            "red_line": bool(red_line),
            "excluded": excluded,
        },
        "factors": factors_out,
        "synthesis": synthesis,
        "headline": headline,
        "_raw_confidence": display_conf,
    }


def build_groups(fields_state, registry, base_confidence):
    """Build grouped checklist with estimated confidence gain and exclusion flags."""
    group_order = ["基本情况", "变现与需求", "能力与渠道", "时间与执行", "划算程度", "财务安全垫", "止损设置"]
    groups_map = {g: [] for g in group_order}

    purpose = engine._get_given_val(fields_state, "purpose")
    is_learn = purpose == "learn"

    for fdef in registry:
        if not fdef.get("ui_show", False):
            continue
        gname = fdef.get("ui_group", "")
        if gname not in groups_map:
            continue
        if is_learn and gname in ("变现与需求", "划算程度", "能力与渠道"):
            continue
        if engine.is_field_applicable(fdef, fields_state):
            groups_map[gname].append(fdef)

    groups_out = []
    for gname in group_order:
        if is_learn and gname in ("变现与需求", "划算程度", "能力与渠道"):
            continue

        excl_key = GROUP_EXCLUDE_KEY.get(gname)
        excludable = excl_key is not None
        is_excluded = bool(excl_key and engine._to_bool(engine._get_given_val(fields_state, excl_key)) is True)

        if is_excluded:
            groups_out.append({
                "id": gname,
                "name": gname,
                "state": "不适用",
                "gain": 0,
                "excludable": True,
                "excluded": True,
                "auto_excluded": False,
                "fields": [],
            })
            continue

        fdefs = sorted(groups_map[gname], key=lambda x: x.get("ui_priority", 99))
        if not fdefs:
            continue

        given_cnt = 0
        fields_out = []
        missing_for_gain = []
        for fdef in fdefs:
            fid = fdef["id"]
            st = fields_state.get(fid, {})
            status = st.get("status", "missing")
            if status == "given":
                given_cnt += 1
            elif fdef.get("neutral_value") is not None and gname != "基本情况":
                missing_for_gain.append(fdef)

            fields_out.append({
                "id": fid,
                "ui_label": fdef.get("ui_label", fdef["label"]),
                "type": fdef.get("type", "text"),
                "unit": fdef.get("unit", ""),
                "choices": fdef.get("choices", []),
                "item_fields": fdef.get("item_fields", []),
                "value": st.get("value"),
                "status": status,
                "unsure": status == "given" and st.get("category") == "猜测",
                "sensitive": bool(fdef.get("sensitive", False)),
            })

        state = "未评" if given_cnt == 0 else ("部分" if given_cnt < len(fdefs) else "已评")
        gain = 0
        if gname != "基本情况" and missing_for_gain:
            sim_state = copy.deepcopy(fields_state)
            for fdef in missing_for_gain:
                sim_state[fdef["id"]] = {
                    "id": fdef["id"],
                    "value": fdef["neutral_value"],
                    "status": "given",
                    "category": "自报",
                    "source": "form",
                }
            sim_res = compute_score(sim_state, registry)
            diff = round((sim_res["_raw_confidence"] - base_confidence) * 100)
            if diff > 0:
                gain = max(1, diff)

        groups_out.append({
            "id": gname,
            "name": gname,
            "state": state,
            "gain": gain,
            "excludable": excludable,
            "excluded": False,
            "auto_excluded": False,
            "fields": fields_out,
        })

    head = [g for g in groups_out if g["name"] == "基本情况"]
    rest = [g for g in groups_out if g["name"] != "基本情况"]
    rest.sort(key=lambda g: (g["excluded"], -g["gain"], g["state"] == "已评"))
    return head + rest
