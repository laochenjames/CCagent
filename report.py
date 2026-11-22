"""Pure report renderer (HTML fragment, standalone HTML, Markdown) with strict escaping."""

import html
import re
from urllib.parse import quote

CATEGORY_LABELS = {
    "事实": "有记录可查",
    "自报": "自己报的",
    "估计": "有依据的估计",
    "猜测": "不太确定",
}

_THRESHOLD_SUFFIX_RE = re.compile(r"(【用户确认】|【AI建议值】)\s*$")
_MD_ESCAPE_RE = re.compile(r"([\\`*_\#|<>[\]])")


def _esc(text):
    """HTML-escape any dynamic text."""
    return html.escape("" if text is None else str(text), quote=True)


def _plain(text):
    """Strip literal markdown bold markers for display."""
    return ("" if text is None else str(text)).replace("**", "")


def _assign_critiques(critiques, result, advisors, adv_meta):
    """Assign critiques to rated advisors by target (advisor id -> field group -> other)."""
    by_adv = {a["id"]: [] for a in advisors if a.get("rated")}
    other = []
    field_to_adv = {}
    group_to_adv = {a.get("group"): a["id"] for a in advisors if a.get("rated") and a.get("group")}
    for g in (result.get("groups") or []):
        aid = group_to_adv.get(g.get("id")) or group_to_adv.get(g.get("name"))
        if aid:
            for f in (g.get("fields") or []):
                if f.get("id"):
                    field_to_adv[f["id"]] = aid

    for raw_c in (critiques or []):
        c = raw_c if isinstance(raw_c, dict) else {"text": str(raw_c)}
        if not str(c.get("text") or "").strip():
            continue
        tgt = c.get("target")
        if tgt and tgt in by_adv:
            by_adv[tgt].append(c)
        elif tgt and tgt in field_to_adv:
            by_adv[field_to_adv[tgt]].append(c)
        else:
            other.append(c)
    return by_adv, other


def _md_esc(text):
    """Escape Markdown special characters."""
    s = "" if text is None else str(text)
    return _MD_ESCAPE_RE.sub(r"\\\1", s)


def _md_cell(text):
    """Escape Markdown table cell and replace newlines with spaces."""
    return _md_esc(text).replace("\r\n", " ").replace("\n", " ").replace("\r", " ")


def safe_filename(title, dt_str, ext):
    """Build sanitized filename and RFC 5987 Content-Disposition header."""
    clean = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "_", (title or "").strip())
    clean = clean[:20].strip("_") or "未命名"
    fname = f"职业投入体检报告_{clean}_{dt_str}.{ext}"
    ascii_fallback = f"report.{ext}"
    encoded = quote(fname, safe="")
    return f'attachment; filename="{ascii_fallback}"; filename*=UTF-8\'\'{encoded}'


def format_value(field_def, value):
    """Format a field value for human-readable display."""
    if value is None or value == "":
        return "未提供"
    fid = field_def.get("id", "")
    ftype = field_def.get("type", "text")
    unit = field_def.get("unit", "")

    if ftype == "bool":
        if value is True or str(value).lower() == "true":
            return "是"
        if value is False or str(value).lower() == "false":
            return "否"
        return str(value)

    if ftype == "enum":
        for c in field_def.get("choices", []):
            if c.get("value") == str(value):
                return c.get("label", str(value))
        return str(value)

    if ftype == "number":
        if fid == "take_home_ratio":
            try:
                return f"{round(float(value) * 100)}%"
            except (TypeError, ValueError):
                return str(value)
        return f"{value} {unit}".strip() if unit else str(value)

    if ftype == "list" and isinstance(value, list):
        if not value:
            return "未提供"
        parts = []
        for item in value:
            if not isinstance(item, dict):
                continue
            pm = item.get("planned_months", "?")
            am = item.get("actual_months", "?")
            sr = "仍在做" if item.get("still_running") else "已结束"
            parts.append(f"计划 {pm} 月，实际 {am} 月，{sr}")
        return "；".join(parts) if parts else "未提供"

    return str(value)


def label_for_target(target, registry, advisors):
    """Map field/advisor/factor ID to Chinese label, or None if unknown."""
    if not target:
        return None
    for f in registry:
        if f.get("id") == target:
            return f.get("ui_label") or f.get("label") or target
    for a in advisors:
        if a.get("id") == target:
            return a.get("code") or a.get("name") or target
    return None


def _rating_badge_html(rating):
    cls = "rp-badge-unknown"
    if rating == "高":
        cls = "rp-badge-high"
    elif rating == "中":
        cls = "rp-badge-mid"
    elif rating == "低":
        cls = "rp-badge-low"
    if rating == "不参与":
        text = "不评级"
    elif rating in ("高", "中", "低", "无法判断", "不适用"):
        text = rating
    else:
        text = "不评级"
    return f'<span class="rp-badge {cls}">{_esc(text)}</span>'


def _split_threshold_tag(text):
    """Strip trailing 【用户确认】/【AI建议值】 and return (body, tag_or_none)."""
    s = "" if text is None else str(text)
    m = _THRESHOLD_SUFFIX_RE.search(s)
    if not m:
        return s, None
    tag = "用户确认" if "用户确认" in m.group(1) else "AI 建议值"
    return s[:m.start()].strip(), tag


def _render_sections_4_to_8_html(result, analysis, registry, advisors):
    """Render sections for fragment and full HTML (分项会诊 + 其他假设批判 + 两周内可验证 + 验证设计)."""
    analysis = analysis or {}
    adv_meta = {a["id"]: a for a in advisors}
    factors_by_id = {f.get("id"): f for f in (result.get("factors") or []) if f.get("id")}
    excl_by_id = {e.get("id"): e for e in ((result.get("score") or {}).get("excluded") or []) if e.get("id")}
    ai_by_id = {a.get("id"): a for a in (analysis.get("advisors") or []) if isinstance(a, dict) and a.get("id")}
    weakest = (result.get("synthesis") or {}).get("weakest")
    weakest_id = weakest.get("id") if isinstance(weakest, dict) else None
    crit_by_adv, other_crit = _assign_critiques(analysis.get("critique") or [], result, advisors, adv_meta)
    yellow_flags = [f.get("text", "") for f in (result.get("flags") or []) if f.get("level") == "黄"]

    parts = []
    rated_cards = []
    observer_cards = []

    for meta in advisors:
        aid = meta.get("id", "")
        is_rated = meta.get("rated", aid not in ("AI_IMPACT", "CONSISTENCY"))
        adv_name = meta.get("name", "")
        adv_code = meta.get("code", "")
        adv_seal = meta.get("seal", "")
        card_title = f"{adv_code} · {adv_name}" if adv_code else adv_name
        adv_ask = meta.get("ask") or ""
        ai = ai_by_id.get(aid, {})

        if is_rated:
            fac = factors_by_id.get(aid)
            ex = excl_by_id.get(aid)
            is_muted = False
            iv_html = ""
            weak_html = ""

            if fac:
                rating = fac.get("rating", "无法判断")
                badge_html = _rating_badge_html(rating)
                iv = fac.get("interval")
                if iv and len(iv) >= 2:
                    iv_html = f'<span class="rp-dim">可能范围：{_esc(iv[0])}–{_esc(iv[1])}</span>'
                if weakest_id and aid == weakest_id:
                    weak_html = '<span class="rp-badge rp-badge-tag">最大短板</span>'

                rule_txt = fac.get("rule_note", "")
                if rating == "无法判断":
                    rule_txt = f"信息不足，按未知处理。{rule_txt}" if rule_txt else "信息不足，按未知处理。"
                raw_missing = fac.get("missing") or ai.get("missing") or []
            elif ex:
                is_muted = True
                reason = ex.get("reason") or "已排除"
                badge_txt = "学习型不适用" if reason == "学习型不适用" else "未计入"
                badge_html = f'<span class="rp-badge rp-badge-unknown">{_esc(badge_txt)}</span>'
                r_inc = ex.get("rating_if_included")
                rule_txt = f"{reason}（若计入将评为{r_inc}）" if r_inc and r_inc != "无法判断" else reason
                raw_missing = []
            else:
                is_muted = True
                badge_html = '<span class="rp-badge rp-badge-unknown">不适用</span>'
                rule_txt = "当前情形不适用该项"
                raw_missing = []

            missing_labels = []
            for m in raw_missing:
                lbl = label_for_target(m, registry, advisors)
                missing_labels.append(lbl if lbl else m)

            rule_block = (
                f'<div class="rp-block-rule">'
                f'<span class="rp-block-label">程序规则判定</span> '
                f'<span>{_esc(rule_txt)}</span>'
                + (f'<div class="rp-dim">缺少的信息：{_esc("、".join(missing_labels))}</div>' if missing_labels else "")
                + '</div>'
            )

            insight = ai.get("insight", "")
            next_step = ai.get("next_step", "")
            basis = ai.get("basis", "")
            note = ai.get("note", "")
            ai_lines = []
            if insight or next_step:
                if insight:
                    ai_lines.append(f'<p><strong>提醒：</strong>{_esc(insight)}</p>')
                if next_step:
                    ai_lines.append(f'<p><strong>下一步：</strong>{_esc(next_step)}</p>')
            elif basis or note:
                if basis:
                    ai_lines.append(f'<p><strong>依据：</strong>{_esc(basis)}</p>')
                if note:
                    ai_lines.append(f'<p><strong>提示：</strong>{_esc(note)}</p>')
            else:
                ai_lines.append('<p class="rp-dim">本次分析未包含该智囊的解读</p>')

            ai_block = (
                f'<div class="rp-block-ai">'
                f'<span class="rp-block-label">AI 解读</span>'
                f'{"".join(ai_lines)}'
                f'</div>'
            )

            adv_crits = crit_by_adv.get(aid, [])
            crit_html = ""
            if adv_crits:
                c_li = []
                for c in adv_crits:
                    lbl = label_for_target(c.get("target"), registry, advisors)
                    tag = f'<span class="rp-badge rp-badge-tag">针对：{_esc(lbl)}</span> ' if lbl else ""
                    c_li.append(f"<li>{tag}{_esc(c.get('text', ''))}</li>")
                crit_html = f'<div class="rp-adv-crit"><strong>针对本智囊的假设批判</strong><ul class="rp-list">{"".join(c_li)}</ul></div>'

            seal_html = f'<span class="rp-seal">{_esc(adv_seal)}</span>' if adv_seal else ""
            ask_html = f'<div class="rp-dim">我只问：{_esc(adv_ask)}</div>' if adv_ask else ""
            muted_cls = " rp-card-muted" if is_muted else ""
            rated_cards.append(
                f'<div class="rp-card rp-advisor{muted_cls}">'
                f'<div class="rp-card-head"><span class="rp-card-title">{seal_html}{_esc(card_title)}</span>'
                f'<span class="rp-card-badges">{badge_html}{weak_html}{iv_html}</span></div>'
                f'{ask_html}{rule_block}{ai_block}{crit_html}</div>'
            )
        else:
            insight = ai.get("insight", "")
            next_step = ai.get("next_step", "")
            basis = ai.get("basis", "")
            note = ai.get("note", "")
            has_flags = (aid == "CONSISTENCY" and bool(yellow_flags))
            if not insight and not next_step and not basis and not note and not has_flags:
                continue
            body_parts = []
            if aid == "AI_IMPACT":
                body_parts.append('<div class="rp-dim">判断，不是数据</div>')
            if insight:
                body_parts.append(f'<p><strong>提醒：</strong>{_esc(insight)}</p>')
            if next_step:
                body_parts.append(f'<p><strong>下一步：</strong>{_esc(next_step)}</p>')
            if not insight and not next_step:
                if basis:
                    body_parts.append(f'<p><strong>依据：</strong>{_esc(basis)}</p>')
                if note:
                    body_parts.append(f'<p><strong>提示：</strong>{_esc(note)}</p>')
            if has_flags:
                yf_li = "".join(f"<li>{_esc(y)}</li>" for y in yellow_flags)
                body_parts.append(f'<ul class="rp-list">{yf_li}</ul>')
            seal_html = f'<span class="rp-seal">{_esc(adv_seal)}</span>' if adv_seal else ""
            ask_html = f'<div class="rp-dim">我只问：{_esc(adv_ask)}</div>' if adv_ask else ""
            observer_cards.append(
                f'<div class="rp-card rp-advisor">'
                f'<div class="rp-card-head"><span class="rp-card-title">{seal_html}{_esc(card_title)}</span>'
                f'<span class="rp-badge rp-badge-unknown">旁听，不评级</span></div>'
                f'{ask_html}{"".join(body_parts)}</div>'
            )

    obs_block = (
        f'<div class="rp-subhead">旁听提示</div><div class="rp-advisor-list">{"".join(observer_cards)}</div>'
        if observer_cards else ""
    )
    parts.append(
        '<section class="rp-section"><h2>分项会诊</h2>'
        f'<div class="rp-advisor-list">{"".join(rated_cards)}</div>{obs_block}</section>'
    )

    if other_crit:
        crit_items = []
        for c in other_crit:
            lbl = label_for_target(c.get("target"), registry, advisors)
            tag = f'<span class="rp-badge rp-badge-tag">针对：{_esc(lbl)}</span> ' if lbl else ""
            crit_items.append(f"<li>{tag}{_esc(c.get('text', ''))}</li>")
        parts.append(f'<section class="rp-section"><h2>其他假设批判</h2><ul class="rp-list">{"".join(crit_items)}</ul></section>')

    # 两周内可验证的 3 件事
    chk_items = []
    for t in (analysis.get("two_week_checks") or []):
        if not isinstance(t, dict):
            continue
        is_dem = t.get("side") == "demand"
        cls = "rp-check-demand" if is_dem else "rp-check-supply"
        side_txt = "需求侧" if is_dem else "供给侧"
        chk_items.append(f'<li class="{cls}"><span class="rp-badge rp-badge-tag">{side_txt}</span> {_esc(t.get("text", ""))}</li>')
    parts.append(f'<section class="rp-section"><h2>两周内可验证的 3 件事</h2><ol class="rp-list">{"".join(chk_items)}</ol></section>')

    # 验证设计
    vd = analysis.get("validation_design") or {}
    sup_li = "".join(f"<li>{_esc(x)}</li>" for x in (vd.get("supply") or []))
    dem_li = "".join(f"<li>{_esc(x)}</li>" for x in (vd.get("demand") or []))
    th_li_parts = []
    for x in (vd.get("threshold") or []):
        body, tag = _split_threshold_tag(x)
        badge = f' <span class="rp-badge rp-badge-tag">{_esc(tag)}</span>' if tag else ""
        th_li_parts.append(f"<li>{_esc(body)}{badge}</li>")
    parts.append(
        '<section class="rp-section"><h2>验证设计</h2><div class="rp-vd-grid">'
        f'<div class="rp-card"><strong>供给侧（你能控制的行为）</strong><ul class="rp-list">{sup_li}</ul></div>'
        f'<div class="rp-card"><strong>需求侧（陌生人的真实反应）</strong><ul class="rp-list">{dem_li}</ul></div>'
        f'<div class="rp-card"><strong>止损与继续条件</strong><ul class="rp-list">{"".join(th_li_parts)}</ul></div>'
        "</div></section>"
    )

    return "".join(parts)


def missing_html_needed(labels):
    return len(labels) > 0


def build_fragment(result, analysis, registry, advisors):
    """Build HTML fragment for 分项会诊 and subsequent sections."""
    inner = _render_sections_4_to_8_html(result, analysis, registry, advisors)
    return f'<div class="rp rp-fragment">{inner}</div>'


def build_full_html(result, analysis, registry, advisors, meta, css_text):
    """Build standalone, self-contained HTML report."""
    title = meta.get("title") or result.get("decision") or "未命名"
    gen_at = meta.get("generated_at", "—")
    ana_at = analysis.get("generated_at") or "—"
    model = analysis.get("model") or "—"
    stale = bool(meta.get("stale", False))
    raw_text = meta.get("raw_text", "")
    fields_state = meta.get("fields_state", {})

    stale_html = '<div class="rp-stale">详细分析基于较早的信息，你之后修改过部分项目</div>' if stale else ""

    # 1. 评估摘要
    sc = result.get("score", {})
    low, high, point = sc.get("low", 15), sc.get("high", 95), sc.get("point", 55)
    marker_html = "" if sc.get("label") == "还看不出来" else f'<div class="rp-gauge-marker" style="left:{point}%"></div>'
    syn_sent = _plain((result.get("synthesis") or {}).get("sentence", ""))
    syn_html = f"<p><strong>{_esc(syn_sent)}</strong></p>" if syn_sent else ""
    excl = sc.get("excluded", [])
    excl_parts_s = [f"{e['name']}（若计入将评为低）" if e.get("rating_if_included") == "低" else e["name"] for e in excl]
    excl_html = f'<p class="rp-dim">评分未包含：{_esc("、".join(excl_parts_s))}</p>' if excl else ""
    conf_html = (
        f'<div>由规则直接判定（红线） · 可能范围 {_esc(low)}–{_esc(high)}</div></div>'
        if sc.get("red_line")
        else f'<div>置信度 <strong>{_esc(sc.get("confidence_pct", 0))}%</strong> · 可能范围 {_esc(low)}–{_esc(high)}</div></div>'
    )
    sec1 = (
        '<section class="rp-section"><h2>评估摘要</h2>'
        f'<div class="rp-summary-top"><div><span class="rp-label-big">{_esc(sc.get("label", ""))}</span> '
        f'<strong>{_esc(sc.get("action", ""))}</strong></div>'
        f'{conf_html}'
        f'<div class="rp-gauge"><div class="rp-gauge-track">'
        f'<div class="rp-gauge-interval" style="left:{low}%;width:{max(2, high - low)}%"></div>{marker_html}</div>'
        '<div class="rp-gauge-zones"><span>偏低 (0–35)</span><span>一般 (35–65)</span><span>偏高 (65–100)</span></div></div>'
        f'<p>{_esc(_plain(result.get("headline", "")))}</p>{syn_html}{excl_html}</section>'
    )

    # 2. 风险提示
    flags = result.get("flags", [])
    if flags:
        fl_li = "".join(
            f'<li><span class="rp-badge {"rp-badge-low" if f.get("level") == "红" else "rp-badge-mid"}">{_esc(f.get("level", ""))}</span> {_esc(f.get("text", ""))}</li>'
            for f in flags
        )
        sec2 = f'<section class="rp-section"><h2>风险提示</h2><ul class="rp-list">{fl_li}</ul></section>'
    else:
        sec2 = '<section class="rp-section"><h2>风险提示</h2><p>未发现明确风险（不代表没有风险）</p></section>'

    # 3. 你提供的信息
    reg_map = {f["id"]: f for f in registry}
    info_rows = []
    missing_labels = []
    for g in (result.get("groups") or []):
        for fld in g.get("fields", []):
            fid = fld["id"]
            fdef = reg_map.get(fid, fld)
            st = fields_state.get(fid, {})
            if st.get("status") == "given":
                cat = CATEGORY_LABELS.get(st.get("category", "自报"), "自己报的")
                val_str = format_value(fdef, st.get("value"))
                info_rows.append(f"<tr><td>{_esc(fdef.get('ui_label', fid))}</td><td>{_esc(val_str)}</td><td>{_esc(cat)}</td></tr>")
            else:
                missing_labels.append(fdef.get("ui_label", fid))
    if missing_labels:
        info_rows.append(f'<tr><td>未提供</td><td colspan="2">{_esc("、".join(missing_labels))}</td></tr>')
    sec3 = (
        '<section class="rp-section"><h2>你提供的信息</h2>'
        '<div class="rp-table-wrap"><table class="rp-table">'
        "<thead><tr><th>项目</th><th>你的回答</th><th>可信度</th></tr></thead>"
        f"<tbody>{''.join(info_rows)}</tbody></table></div></section>"
    )

    sec4_8 = _render_sections_4_to_8_html(result, analysis, registry, advisors)

    # 9. 如何让评估更准
    gain_groups = [g for g in (result.get("groups") or []) if g.get("gain", 0) > 0][:3]
    sec9 = ""
    if gain_groups:
        g_li = []
        for g in gain_groups:
            unfilled = [fld.get("ui_label", fld["id"]) for fld in g.get("fields", []) if fld.get("status") != "given"]
            if unfilled:
                g_li.append(f"<li><strong>{_esc(g['name'])}</strong>（补全可提升置信度约 +{_esc(g['gain'])}%）：{_esc('、'.join(unfilled))}</li>")
        if g_li:
            sec9 = f'<section class="rp-section"><h2>如何让评估更准</h2><ul class="rp-list">{"".join(g_li)}</ul></section>'

    # 10. 说明
    hidden_cnt = analysis.get("hidden_count", 0)
    hidden_note = f" 另有 {hidden_cnt} 条 AI 文字因含未核实数字被隐藏。" if hidden_cnt > 0 else ""
    disclaimer = result.get("disclaimer", "")
    sec10 = (
        '<section class="rp-section"><h2>说明</h2>'
        f"<p>评分、评级和风险提示由程序按固定规则计算；依据、批判和验证建议由 AI 根据你提供的信息生成，仅供参考。{_esc(disclaimer)}{_esc(hidden_note)}</p>"
        "</section>"
    )

    raw_block = (
        '<details class="rp-raw-details"><summary>你的原始描述</summary>'
        f'<pre class="rp-raw-pre">{_esc(raw_text)}</pre></details>'
    )

    return (
        "<!DOCTYPE html><html lang=\"zh-CN\"><head><meta charset=\"UTF-8\" />"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1.0\" />"
        f"<title>职业投入体检报告 - {_esc(title)}</title>"
        f"<style>{css_text}</style></head><body>"
        '<div class="rp rp-full">'
        '<header class="rp-header"><div><h1>职业投入体检报告</h1>'
        '<div class="rp-dim">本报告由智市、智配、智续、智衡、智守、智断六位智囊会诊（智望、智核旁听）。智囊是分析视角，不是持证顾问。</div>'
        f'<div class="rp-meta">决策：{_esc(title)}<br/>报告生成：{_esc(gen_at)} · 分析生成：{_esc(ana_at)} · 模型：{_esc(model)}</div></div>'
        '<button type="button" class="rp-print-btn no-print" onclick="window.print()">打印 / 另存为 PDF</button></header>'
        f"{stale_html}{sec1}{sec2}{sec3}{sec4_8}{sec9}{sec10}{raw_block}"
        "</div></body></html>"
    )


def build_markdown(result, analysis, registry, advisors, meta):
    """Build Markdown report in the same section order."""
    title = meta.get("title") or result.get("decision") or "未命名"
    gen_at = meta.get("generated_at", "—")
    ana_at = analysis.get("generated_at") or "—"
    model = analysis.get("model") or "—"
    stale = bool(meta.get("stale", False))
    fields_state = meta.get("fields_state", {})

    adv_meta = {a["id"]: a for a in advisors if "id" in a}
    lines = [
        "# 职业投入体检报告",
        "",
        "本报告由智市、智配、智续、智衡、智守、智断六位智囊会诊（智望、智核旁听）。智囊是分析视角，不是持证顾问。",
        f"- 决策：{_md_esc(title)}",
        f"- 报告生成：{gen_at} · 分析生成：{ana_at} · 模型：{_md_esc(model)}",
    ]
    if stale:
        lines.append("\n> **注意：详细分析基于较早的信息，你之后修改过部分项目。**")

    sc = result.get("score", {})
    syn_sent = _plain((result.get("synthesis") or {}).get("sentence", ""))
    excl = sc.get("excluded", [])
    excl_parts_s = [f"{e['name']}（若计入将评为低）" if e.get("rating_if_included") == "低" else e["name"] for e in excl]
    excl_md_line = f"- 评分未包含：{_md_esc('、'.join(excl_parts_s))}" if excl else ""
    conf_md_line = (
        f"- 由规则直接判定（红线） · 可能范围：{sc.get('low', 15)}–{sc.get('high', 95)}"
        if sc.get("red_line")
        else f"- 置信度：{sc.get('confidence_pct', 0)}% · 可能范围：{sc.get('low', 15)}–{sc.get('high', 95)}"
    )
    lines += [
        "\n## 1. 评估摘要",
        f"- **{_md_esc(sc.get('label', ''))}** {_md_esc(sc.get('action', ''))}",
        conf_md_line,
        f"\n{_md_esc(_plain(result.get('headline', '')))}",
    ]
    if syn_sent:
        lines.append(f"\n**{_md_esc(syn_sent)}**")
    if excl_md_line:
        lines.append(f"\n{excl_md_line}")

    lines.append("\n## 2. 风险提示")
    flags = list(result.get("flags", []))
    for cf in (analysis.get("consistency_flags") or []):
        if isinstance(cf, dict):
            flags.append({"level": cf.get("level", "黄"), "text": cf.get("text", "")})
        elif isinstance(cf, str) and cf.strip():
            flags.append({"level": "黄", "text": cf.strip()})
    if flags:
        for f in flags:
            lines.append(f"- [{_md_esc(f.get('level', ''))}] {_md_esc(f.get('text', ''))}")
    else:
        lines.append("未发现明确风险（不代表没有风险）")

    lines += ["\n## 3. 你提供的信息", "| 项目 | 你的回答 | 可信度 |", "|---|---|---|"]
    reg_map = {f["id"]: f for f in registry}
    missing_labels = []
    for g in (result.get("groups") or []):
        for fld in g.get("fields", []):
            fid = fld["id"]
            fdef = reg_map.get(fid, fld)
            st = fields_state.get(fid, {})
            if st.get("status") == "given":
                cat = CATEGORY_LABELS.get(st.get("category", "自报"), "自己报的")
                lines.append(f"| {_md_cell(fdef.get('ui_label', fid))} | {_md_cell(format_value(fdef, st.get('value')))} | {_md_cell(cat)} |")
            else:
                missing_labels.append(fdef.get("ui_label", fid))
    if missing_labels:
        lines.append(f"| 未提供 | {_md_cell('、'.join(missing_labels))} | — |")

    sec_no = 4
    lines.append(f"\n## {sec_no}. 分项会诊")
    sec_no += 1
    factors_by_id = {f.get("id"): f for f in (result.get("factors") or []) if f.get("id")}
    excl_by_id = {e.get("id"): e for e in ((result.get("score") or {}).get("excluded") or []) if e.get("id")}
    ai_by_id = {a.get("id"): a for a in ((analysis or {}).get("advisors") or []) if isinstance(a, dict) and a.get("id")}
    weakest = (result.get("synthesis") or {}).get("weakest")
    weakest_id = weakest.get("id") if isinstance(weakest, dict) else None
    crit_by_adv, other_crit = _assign_critiques((analysis or {}).get("critique") or [], result, advisors, adv_meta)
    yellow_flags = [f.get("text", "") for f in (result.get("flags") or []) if f.get("level") == "黄"]

    for meta in advisors:
        aid = meta.get("id", "")
        is_rated = meta.get("rated", aid not in ("AI_IMPACT", "CONSISTENCY"))
        a_name = meta.get("name", "")
        a_code = meta.get("code", "")
        a_title = f"{a_code} · {a_name}" if a_code else a_name
        ai = ai_by_id.get(aid, {})

        if is_rated:
            fac = factors_by_id.get(aid)
            ex = excl_by_id.get(aid)
            if fac:
                r = fac.get("rating", "无法判断")
                r_txt = f"【{r}】"
                weak_txt = " 【最大短板】" if (weakest_id and aid == weakest_id) else ""
                iv = fac.get("interval")
                iv_txt = f"（可能范围：{iv[0]}–{iv[1]}）" if iv and len(iv) >= 2 else ""
                rule_txt = fac.get("rule_note", "")
                if r == "无法判断":
                    rule_txt = f"信息不足，按未知处理。{rule_txt}" if rule_txt else "信息不足，按未知处理。"
                raw_missing = fac.get("missing") or ai.get("missing") or []
            elif ex:
                reason = ex.get("reason") or "已排除"
                r_txt = "【学习型不适用】" if reason == "学习型不适用" else "【未计入】"
                weak_txt = ""
                iv_txt = ""
                r_inc = ex.get("rating_if_included")
                rule_txt = f"{reason}（若计入将评为{r_inc}）" if r_inc and r_inc != "无法判断" else reason
                raw_missing = []
            else:
                r_txt = "【不适用】"
                weak_txt = ""
                iv_txt = ""
                rule_txt = "当前情形不适用该项"
                raw_missing = []

            lines.append(f"### {_md_esc(a_title)} {r_txt}{weak_txt}{iv_txt}")
            if meta.get("ask"):
                lines.append(f"- 我只问：{_md_esc(meta['ask'])}")
            lines.append(f"- 【程序规则判定】{_md_esc(rule_txt)}")
            m_lbls = [label_for_target(mid, registry, advisors) or mid for mid in raw_missing]
            if m_lbls:
                lines.append(f"- 缺少的信息：{_md_esc('、'.join(m_lbls))}")
            insight = ai.get("insight", "")
            next_step = ai.get("next_step", "")
            basis = ai.get("basis", "")
            note = ai.get("note", "")
            if insight or next_step:
                if insight:
                    lines.append(f"- 【AI 解读】提醒：{_md_esc(insight)}")
                if next_step:
                    lines.append(f"- 【AI 解读】下一步：{_md_esc(next_step)}")
            elif basis or note:
                if basis:
                    lines.append(f"- 【AI 解读】依据：{_md_esc(basis)}")
                if note:
                    lines.append(f"- 【AI 解读】提示：{_md_esc(note)}")
            else:
                lines.append("- 【AI 解读】本次分析未包含该智囊的解读")
            for c in crit_by_adv.get(aid, []):
                lbl = label_for_target(c.get("target"), registry, advisors)
                prefix = f"针对【{_md_esc(lbl)}】：" if lbl else ""
                lines.append(f"- 假设批判：{prefix}{_md_esc(c.get('text', ''))}")
        else:
            insight = ai.get("insight", "")
            next_step = ai.get("next_step", "")
            basis = ai.get("basis", "")
            note = ai.get("note", "")
            has_flags = (aid == "CONSISTENCY" and bool(yellow_flags))
            if not insight and not next_step and not basis and not note and not has_flags:
                continue
            lines.append(f"### {_md_esc(a_title)} 【旁听，不评级】")
            if aid == "AI_IMPACT":
                lines.append("- 判断，不是数据")
            if meta.get("ask"):
                lines.append(f"- 我只问：{_md_esc(meta['ask'])}")
            if insight:
                lines.append(f"- 【AI 解读】提醒：{_md_esc(insight)}")
            if next_step:
                lines.append(f"- 【AI 解读】下一步：{_md_esc(next_step)}")
            if not insight and not next_step:
                if basis:
                    lines.append(f"- 【AI 解读】依据：{_md_esc(basis)}")
                if note:
                    lines.append(f"- 【AI 解读】提示：{_md_esc(note)}")
            if has_flags:
                for y in yellow_flags:
                    lines.append(f"- 黄色提示：{_md_esc(y)}")

    if other_crit:
        lines.append(f"\n## {sec_no}. 其他假设批判")
        sec_no += 1
        for c in other_crit:
            lbl = label_for_target(c.get("target"), registry, advisors)
            prefix = f"针对【{_md_esc(lbl)}】：" if lbl else ""
            lines.append(f"- {prefix}{_md_esc(c.get('text', ''))}")

    lines.append(f"\n## {sec_no}. 两周内可验证的 3 件事")
    sec_no += 1
    for idx, t in enumerate((analysis or {}).get("two_week_checks") or [], 1):
        if not isinstance(t, dict):
            continue
        side = "需求侧｜" if t.get("side") == "demand" else "供给侧｜"
        lines.append(f"{idx}. {side}{_md_esc(t.get('text', ''))}")

    vd = (analysis or {}).get("validation_design") or {}
    lines.append(f"\n## {sec_no}. 验证设计")
    sec_no += 1
    lines.append("**供给侧（你能控制的行为）**")
    for x in (vd.get("supply") or []):
        lines.append(f"- {_md_esc(x)}")
    lines.append("\n**需求侧（陌生人的真实反应）**")
    for x in (vd.get("demand") or []):
        lines.append(f"- {_md_esc(x)}")
    lines.append("\n**止损与继续条件**")
    for x in (vd.get("threshold") or []):
        body, tag = _split_threshold_tag(x)
        suffix = f" 【{tag}】" if tag else ""
        lines.append(f"- {_md_esc(body)}{suffix}")

    gain_groups = [g for g in (result.get("groups") or []) if g.get("gain", 0) > 0][:3]
    if gain_groups:
        lines.append(f"\n## {sec_no}. 如何让评估更准")
        sec_no += 1
        for g in gain_groups:
            unfilled = [fld.get("ui_label", fld["id"]) for fld in g.get("fields", []) if fld.get("status") != "given"]
            if unfilled:
                lines.append(f"- **{_md_esc(g['name'])}**（补全可提升置信度约 +{g['gain']}%）：{_md_esc('、'.join(unfilled))}")

    hidden_cnt = analysis.get("hidden_count", 0)
    hidden_note = f" 另有 {hidden_cnt} 条 AI 文字因含未核实数字被隐藏。" if hidden_cnt > 0 else ""
    lines += [
        f"\n## {sec_no}. 说明",
        f"评分、评级和风险提示由程序按固定规则计算；依据、批判和验证建议由 AI 根据你提供的信息生成，仅供参考。{_md_esc(result.get('disclaimer', ''))}{hidden_note}",
    ]
    return "\n".join(lines)
