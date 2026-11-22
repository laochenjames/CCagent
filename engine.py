"""Pure rule engine for career investment checkup (v2.3, no I/O)."""

NUMBER_WHITELIST = {0, 1, 2, 3, 5, 6, 10, 25, 36}
FUTURE_FIELDS = {
    "first_paid_month",
    "validation_months",
    "weekly_hours_planned",
    "target_monthly_income",
}
RATING_ORDER = {"低": 1, "中": 2, "高": 3}


def _get_given_val(fields_state, field_id):
    """Return value if field status is 'given', else None."""
    f = fields_state.get(field_id)
    if not f or f.get("status") != "given":
        return None
    return f.get("value")


def _to_float(val):
    """Safely convert a value to float, returning None on failure."""
    if val is None or isinstance(val, bool):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return None


def _to_bool(val):
    """Safely convert a value to bool, returning None if not boolean-like."""
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        low = val.strip().lower()
        if low == "true":
            return True
        if low == "false":
            return False
    return None


def is_field_applicable(field_def, fields_state):
    """Evaluate three-valued applicability for a field definition."""
    purpose = _get_given_val(fields_state, "purpose")
    gname = field_def.get("ui_group", "")
    if purpose == "learn" and gname in ("变现与需求", "划算程度", "能力与渠道"):
        return False
    if gname == "变现与需求" and _to_bool(_get_given_val(fields_state, "excl_MONETIZATION")) is True:
        return False
    if gname == "划算程度" and _to_bool(_get_given_val(fields_state, "excl_OPPORTUNITY")) is True:
        return False

    tag = field_def.get("applicable_if", "always")
    if tag == "always":
        return True
    needs_cash = _to_bool(_get_given_val(fields_state, "needs_cash"))
    affects_main = _to_bool(_get_given_val(fields_state, "affects_main_job"))
    if tag == "cash_relevant":
        return (needs_cash is not False) or (affects_main is not False)
    if tag == "outlay_relevant":
        return needs_cash is not False
    if tag == "target_given":
        return _get_given_val(fields_state, "target_monthly_income") is not None
    return True


def rate_monetization(fields_state):
    """Rate MONETIZATION advisor (distinguishing stranger vs acquaintance)."""
    paid = _get_given_val(fields_state, "paid_evidence")
    prec = _get_given_val(fields_state, "precedent")
    if paid == "paid_stranger":
        return "高", "已有陌生人付过钱（paid_stranger），需求已初步验证。"
    if paid == "paid_acquaintance":
        return "中", "有熟人/朋友付过钱（paid_acquaintance），仍需陌生人付费验证。"
    if paid == "paid":
        return "中", "旧数据未区分付费者，按熟人付费处理（paid→中）。"
    if paid == "asked":
        return "中", "有人主动询价或表达意愿（asked），待验证真实付费。"
    if paid == "none":
        if prec == "yes":
            return "中", "尚无付费/询价（none），但有同类做成先例（precedent=yes）。"
        if prec == "no":
            return "低", "尚无付费/询价且未找到先例（none, precedent=no），视为需求未验证。"
        return "无法判断", "尚无付费/询价（none），且未提供先例情况（precedent 缺失）。"
    if prec == "no":
        return "低", "未提供付费证据，且未找到同类先例（precedent=no）。"
    if prec == "yes":
        return "中", "未提供付费证据，但有同类做成先例（precedent=yes）。"
    return "无法判断", "付费证据（paid_evidence）与先例（precedent）均未提供。"


def rate_capability(fields_state):
    """Rate CAPABILITY advisor from skill_evidence and channel_access."""
    skill_map = {"direct": ("高", "有直接相关经验/作品"), "adjacent": ("中", "有相近经验"), "none": ("低", "基本没有相关经验")}
    chan_map = {"has": ("高", "已有触达渠道"), "untested": ("中", "有渠道但没试过"), "none": ("低", "暂无渠道")}

    signals = []
    notes = []
    sk = _get_given_val(fields_state, "skill_evidence")
    if sk in skill_map:
        r, desc = skill_map[sk]
        signals.append(r)
        notes.append(f"技能：{desc} → {r}")

    ch = _get_given_val(fields_state, "channel_access")
    if ch in chan_map:
        r, desc = chan_map[ch]
        signals.append(r)
        notes.append(f"渠道：{desc} → {r}")

    if not signals:
        return "无法判断", "经验/作品（skill_evidence）与渠道（channel_access）均未提供。"

    lowest = min(signals, key=lambda s: RATING_ORDER[s])
    suffix = "。取较低一档。" if len(signals) > 1 else "。"
    return lowest, "；".join(notes) + suffix


def rate_execution(fields_state):
    """Rate EXECUTION advisor across 3 signals, taking the lowest."""
    signals = []
    notes = []

    actual = _to_float(_get_given_val(fields_state, "weekly_hours_actual_recent"))
    planned = _to_float(_get_given_val(fields_state, "weekly_hours_planned"))
    if actual is not None and planned is not None and planned > 0:
        ratio = actual / planned
        if ratio < 0.5:
            r = "低"
        elif ratio < 0.8:
            r = "中"
        else:
            r = "高"
        signals.append(r)
        notes.append(f"信号A（近期实际 {actual:g}h ÷ 计划 {planned:g}h = {ratio:.2f}）→ {r}")

    cont = _to_float(_get_given_val(fields_state, "continuity_weeks_12m"))
    if cont is not None:
        if cont < 16:
            r = "低"
        elif cont <= 30:
            r = "中"
        else:
            r = "高"
        signals.append(r)
        notes.append(f"信号B（过去12个月连续周数 {cont:g}）→ {r}")

    past = _get_given_val(fields_state, "past_projects")
    if isinstance(past, list) and len(past) > 0:
        has_actual = any(_to_float(p.get("actual_months")) is not None for p in past if isinstance(p, dict))
        if has_actual:
            score_sum = 0.0
            for p in past:
                if not isinstance(p, dict):
                    continue
                still = _to_bool(p.get("still_running"))
                had_inc = _to_bool(p.get("had_income"))
                act_m = _to_float(p.get("actual_months"))
                pln_m = _to_float(p.get("planned_months"))
                if act_m is not None and pln_m is not None and act_m >= pln_m:
                    score_sum += 1.0
                elif still is True:
                    score_sum += 0.5 if had_inc is False else 1.0
            rate = score_sum / len(past)
            if rate < 0.5:
                r = "低"
            elif rate < 0.67:
                r = "中"
            else:
                r = "高"
            signals.append(r)
            notes.append(f"信号C（过去项目持续率 {score_sum:g}/{len(past)} = {rate:.2f}）→ {r}")

    if not signals:
        return "无法判断", "执行力三个信号（实际/计划工时、连续周数、过去项目）均不足。（以上阈值为经验阈值，仅供参考）"

    lowest = min(signals, key=lambda s: RATING_ORDER[s])
    return lowest, "；".join(notes) + "。（以上阈值为经验阈值，仅供参考）"


def rate_opportunity(fields_state):
    """Rate OPPORTUNITY advisor without mixing take-home and client-price bases."""
    unit_price = _to_float(_get_given_val(fields_state, "unit_price"))
    ratio = _to_float(_get_given_val(fields_state, "take_home_ratio"))
    floor_take_home = _to_float(_get_given_val(fields_state, "floor_take_home_per_unit"))
    floor_client = _to_float(_get_given_val(fields_state, "floor_price_client"))

    if floor_take_home is not None and floor_take_home > 0 and unit_price is not None and ratio is not None:
        take_home = unit_price * ratio
        x = take_home / floor_take_home
        if x < 0.8:
            r = "低"
        elif x < 1.5:
            r = "中"
        else:
            r = "高"
        note = (
            f"单价 {unit_price:g} 元 × 到手比例 {ratio:g} = 每单到手 {take_home:g} 元；"
            f"你的到手底线 {floor_take_home:g} 元；比值 {x:.2f}，评为{r}（经验阈值）。"
        )
        return r, note

    if floor_take_home is None and floor_client is not None and floor_client > 0 and unit_price is not None:
        x = unit_price / floor_client
        if x < 0.8:
            r = "低"
        elif x < 1.5:
            r = "中"
        else:
            r = "高"
        note = (
            f"单价 {unit_price:g} 元 ÷ 客户价底线 {floor_client:g} 元 = 比值 {x:.2f}，评为{r}"
            "（这是客户付的价之间的比较，经验阈值）。"
        )
        return r, note

    return "无法判断", "缺少单价、到手比例或对应底线，无法判断机会成本。"


def rate_safety_net(fields_state):
    """Rate SAFETY_NET advisor using Signal S (survival) and Signal O (outlay)."""
    needs_cash = _to_bool(_get_given_val(fields_state, "needs_cash"))
    affects_main = _to_bool(_get_given_val(fields_state, "affects_main_job"))
    if needs_cash is False and affects_main is False:
        return "不适用", "不花钱且不影响主业（纯时间项目），财务安全垫不适用。"

    if _to_bool(_get_given_val(fields_state, "borrowing_or_essential_funds")) is True:
        return "低", "涉及借贷或动用生活必需资金（红线），评为低。"

    cash_free = _to_float(_get_given_val(fields_state, "cash_free"))
    monthly_exp = _to_float(_get_given_val(fields_state, "monthly_expense"))
    income_after = _to_float(_get_given_val(fields_state, "income_after_monthly"))
    cash_outlay = _to_float(_get_given_val(fields_state, "cash_outlay"))

    signals = []
    notes = []

    if cash_free is not None and monthly_exp is not None and monthly_exp > 0:
        if income_after is not None:
            net_burn = monthly_exp - income_after
            if net_burn <= 0:
                signals.append("高")
                notes.append(f"信号S：月支出 {monthly_exp:g} ≤ 仍有收入 {income_after:g}，无生存压力 → 高")
            else:
                months = cash_free / net_burn
                r = "低" if months < 3 else ("中" if months < 6 else "高")
                signals.append(r)
                notes.append(f"信号S：现金 {cash_free:g} ÷ 净消耗 {net_burn:g} = {months:.1f} 个月 → {r}")
        else:
            notes.append("未确认现有收入是否继续，生存月数未计入评级")

    if cash_outlay is not None and cash_free is not None and cash_free > 0 and needs_cash is not False:
        ratio = cash_outlay / cash_free
        r = "低" if ratio > 0.25 else ("中" if ratio >= 0.10 else "高")
        signals.append(r)
        notes.append(f"信号O：花费 {cash_outlay:g} ÷ 现金 {cash_free:g} = {ratio:.1%} → {r}")

    if not signals:
        msg = "；".join(notes) + "。" if notes else "无风险现金、月支出或预计花费信息不足，无法判断财务安全垫。"
        return "无法判断", msg

    lowest = min(signals, key=lambda s: RATING_ORDER[s])
    return lowest, "；".join(notes) + "。"


def rate_stoploss(fields_state):
    """Rate STOPLOSS advisor."""
    first_paid = _to_float(_get_given_val(fields_state, "first_paid_month"))
    val_months = _to_float(_get_given_val(fields_state, "validation_months"))
    if first_paid is None or val_months is None:
        return "无法判断", "缺少预计首个付费月或验证期，无法判断止损线。"

    will_stop = _to_bool(_get_given_val(fields_state, "will_really_stop"))
    time_ok = val_months >= first_paid + 2
    if not time_ok:
        return "低", f"验证期 {val_months:g} 个月早于首个付费月 {first_paid:g} + 2 个月，评为低。"
    if will_stop is False:
        return "低", "到期不会真的停止（will_really_stop=false），止损线无效，评为低。"
    if will_stop is True:
        return "高", f"验证期 {val_months:g} ≥ 首个付费月 {first_paid:g} + 2，且确认到期会停，评为高。"
    return "中", f"验证期 {val_months:g} ≥ 首个付费月 {first_paid:g} + 2，但到期是否真停未知，评为中。"


def red_line_reasons(fields_state):
    """Return list of red-line reasons (borrowing, net_burn survival < 3m, outlay > 25%)."""
    reasons = []
    if _to_bool(_get_given_val(fields_state, "borrowing_or_essential_funds")) is True:
        reasons.append("涉及借贷或动用生活必需资金")

    cash_free = _to_float(_get_given_val(fields_state, "cash_free"))
    monthly_exp = _to_float(_get_given_val(fields_state, "monthly_expense"))
    income_after = _to_float(_get_given_val(fields_state, "income_after_monthly"))
    cash_outlay = _to_float(_get_given_val(fields_state, "cash_outlay"))

    if income_after is not None and cash_free is not None and monthly_exp is not None:
        net_burn = monthly_exp - income_after
        if net_burn > 0:
            months = cash_free / net_burn
            if months < 3:
                reasons.append(f"现金 ÷ 每月净消耗 = {cash_free:g} ÷ {net_burn:g} = {months:.1f} 个月 < 3 个月")

    if cash_outlay is not None and cash_free is not None and cash_free > 0:
        ratio = cash_outlay / cash_free
        if ratio > 0.25:
            reasons.append(f"花费占比 = {cash_outlay:g} ÷ {cash_free:g} = {ratio:.2%} > 25%")

    return reasons


def compute_flags(fields_state):
    """Compute red and yellow warning flags."""
    flags = []

    for r in red_line_reasons(fields_state):
        flags.append({"level": "红", "text": r + "。"})

    cash_free = _to_float(_get_given_val(fields_state, "cash_free"))
    monthly_exp = _to_float(_get_given_val(fields_state, "monthly_expense"))
    income_after = _to_float(_get_given_val(fields_state, "income_after_monthly"))
    if income_after is None and cash_free is not None and monthly_exp is not None and monthly_exp > 0:
        months_gross = cash_free / monthly_exp
        if months_gross < 3:
            flags.append({"level": "黄", "text": f"如果这段时间没有稳定收入，现金大约只够 {months_gross:.1f} 个月（尚未确认你的现有收入是否继续）。"})

    first_paid = _to_float(_get_given_val(fields_state, "first_paid_month"))
    val_months = _to_float(_get_given_val(fields_state, "validation_months"))
    if first_paid is not None and val_months is not None and val_months < first_paid + 2:
        flags.append({
            "level": "红",
            "text": "止损月不要早于预计首个付费月加2个月。可以延后止损月，或改用领先指标（如主动询问量、首个付费）作为止损依据；请不要把首个付费月估计改早。",
        })

    if _get_given_val(fields_state, "target_scope") == "project":
        flags.append({"level": "黄", "text": "目标收入为整个店/团队/项目口径，个人到手金额尚未确认。"})

    actual = _to_float(_get_given_val(fields_state, "weekly_hours_actual_recent"))
    planned = _to_float(_get_given_val(fields_state, "weekly_hours_planned"))
    if actual is not None and planned is not None and planned > actual * 2:
        flags.append({"level": "黄", "text": f"计划每周投入（{planned:g}h）超过近期实际（{actual:g}h）的 2 倍，差距较大。"})

    if _get_given_val(fields_state, "unit_price") is not None and _get_given_val(fields_state, "take_home_ratio") is None:
        flags.append({"level": "黄", "text": "已提供单价但未提供到手比例，注意不要把客户付的价当成自己到手的钱。"})

    stop_rule = _get_given_val(fields_state, "stop_loss_rule")
    if isinstance(stop_rule, str) and any(kw in stop_rule for kw in ("反思", "调整", "再看看", "看情况")):
        flags.append({"level": "黄", "text": "止损条件偏模糊（含反思/调整/再看看），建议改为可检查的具体条件。"})

    return flags


def evaluate_fields(fields_state, registry):
    """Run score.py and compute_flags on fields_state."""
    import score

    sc = score.compute_score(fields_state, registry)
    groups = score.build_groups(fields_state, registry, sc["_raw_confidence"])
    flags = compute_flags(fields_state)
    return {
        "rules_version": score.RULES_VERSION,
        "score": sc["score"],
        "factors": sc["factors"],
        "synthesis": sc["synthesis"],
        "headline": sc["headline"],
        "groups": groups,
        "flags": flags,
    }
