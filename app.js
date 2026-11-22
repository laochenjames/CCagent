const $ = (id) => document.getElementById(id);
let currentSessionId = null;
let currentResult = null;
let advisorsList = [];
let advisorsDisclaimer = "";
const PROVIDER_NAMES = { gemini: "Google Gemini", xai: "Grok（xAI）", deepseek: "DeepSeek" };

const CANONICAL_GROUPS = ["基本情况", "变现与需求", "能力与渠道", "时间与执行", "划算程度", "财务安全垫", "止损设置"];
const GROUP_EXCLUDE_KEY = { "变现与需求": "excl_MONETIZATION", "划算程度": "excl_OPPORTUNITY" };
const groupRefs = new Map();
const rowRefs = new Map();

const pending = {
  fields: new Map(),
  skip: new Set(),
  unskip: new Set(),
  ticks: new Set(),
};
let inFlight = false;
let hostedMode = false;
const BYOK_DEFAULTS = {
  gemini: "gemini-3.5-flash",
  xai: "grok-3-mini-fast", // 待核实
  deepseek: "deepseek-flash",
};
let byokState = { provider: "gemini", key: "", model: "", remember: false };
try {
  const saved = JSON.parse(localStorage.getItem("cc_byok") || "null");
  if (saved && saved.key) {
    byokState = {
      provider: saved.provider || "gemini",
      key: saved.key || "",
      model: saved.model || "",
      remember: true,
    };
  }
} catch (_) { }

function updateQuotaBadge(q) {
  const el = $("quota-badge");
  if (!el) return;
  if (byokState.key) {
    el.textContent = "使用你自己的 Key，不占免费额度";
    el.classList.remove("hidden", "exhausted");
    return;
  }
  if (!hostedMode || !q) {
    el.classList.add("hidden");
    return;
  }
  el.textContent = `今日免费额度 ${q.remaining}/${q.limit}`;
  el.classList.remove("hidden");
  if (q.remaining <= 0) el.classList.add("exhausted");
  else el.classList.remove("exhausted");
}

(async function initMode() {
  try {
    const r = await api("/api/mode");
    const m = await r.json();
    hostedMode = Boolean(m.hosted);
    if (m.default_models) Object.assign(BYOK_DEFAULTS, m.default_models);
    const retEl = $("retention-days-text");
    if (retEl && m.retention_days) retEl.textContent = String(m.retention_days);
    if (hostedMode) {
      $("server-cfg-wrap")?.classList.add("hidden");
      const qr = await api("/api/quota");
      updateQuotaBadge(await qr.json());
    } else if (byokState.key) {
      updateQuotaBadge(null);
    }
    updatePrivacyNotice();
  } catch (err) {
    console.error("initMode failed:", err);
  }
})();
let flushTimer = null;

const dash = document.querySelector(".dashboard-card");
const dashSentinel = document.getElementById("dash-sentinel");

function updatePrivacyNotice() {
  const provEl = $("privacy-provider");
  if (!provEl) return;
  const provName = byokState.key ? (PROVIDER_NAMES[byokState.provider] || byokState.provider) : "Google Gemini";
  provEl.textContent = provName;
}

function api(path, opts = {}) {
  return fetch(path, opts);
}

async function postJson(path, body = {}, { llm = false } = {}) {
  const headers = { "Content-Type": "application/json" };
  if (llm && byokState.key) {
    headers["X-LLM-Provider"] = byokState.provider || "gemini";
    headers["X-LLM-Key"] = byokState.key;
    if (byokState.model) headers["X-LLM-Model"] = byokState.model;
  }
  const res = await fetch(path, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  const raw = await res.text();
  let data;
  try {
    data = raw ? JSON.parse(raw) : {};
  } catch {
    data = { error: `服务器返回非 JSON 响应（HTTP ${res.status}）`, category: "服务异常" };
  }
  if (data && data.quota) updateQuotaBadge(data.quota);
  if (res.status === 429 && data && data.category === "额度用完") {
    showError(data.error || "今日免费额度已用完，可在设置中使用你自己的 Key。");
    $("settings-modal")?.classList.remove("hidden");
  }
  return { res, data };
}

if (dash && dashSentinel && "IntersectionObserver" in window) {
  const dashObs = new IntersectionObserver(
    (entries) => {
      const entry = entries[0];
      if (!entry || $("result-section").classList.contains("hidden")) return;
      const stuck = !entry.isIntersecting && entry.boundingClientRect.top < 0;
      dash.classList.toggle("stuck", stuck);
      dash.classList.toggle("compact", stuck);
    },
    { threshold: 0 }
  );
  dashObs.observe(dashSentinel);
}

function recalcDashTop() {
  if (!dash) return;
  dash.classList.remove("compact", "stuck");
}

document.querySelectorAll(".chip").forEach((btn) => {
  btn.addEventListener("click", () => {
    $("raw-input").value = btn.dataset.example || "";
  });
});

$("btn-edit-desc").addEventListener("click", () => {
  $("input-collapsed").classList.add("hidden");
  $("input-expanded").classList.remove("hidden");
});

$("btn-evaluate").addEventListener("click", async () => {
  const text = $("raw-input").value.trim();
  if (!text) {
    showError("请输入你想做的事。");
    return;
  }
  hideError();
  setEvalLoading(true);
  try {
    const { res, data } = await postJson("/api/evaluate", { text }, { llm: true });
    if (!res.ok) {
      showError(`[${data.category || "错误"}] ${data.error || "体检失败"}`);
      return;
    }
    currentSessionId = data.session_id;
    currentResult = data;
    $("desc-preview").textContent = `你的描述：${text.slice(0, 36)}${text.length > 36 ? "…" : ""}`;
    $("input-expanded").classList.add("hidden");
    $("input-collapsed").classList.remove("hidden");
    renderResult(data);
  } catch (err) {
    showError(err.message);
  } finally {
    setEvalLoading(false);
  }
});

$("btn-append").addEventListener("click", async () => {
  const text = $("append-input").value.trim();
  if (!text || !currentSessionId) return;
  hideError();
  setEvalLoading(true);
  try {
    const { res, data } = await postJson(`/api/sessions/${currentSessionId}/append-text`, { text }, { llm: true });
    if (!res.ok) {
      showError(`[${data.category || "错误"}] ${data.error || "补充抽取失败"}`);
      return;
    }
    $("append-input").value = "";
    currentResult = data;
    renderResult(data);
  } catch (err) {
    showError(err.message);
  } finally {
    setEvalLoading(false);
  }
});

$("btn-analysis").addEventListener("click", () => runAnalysis());
$("btn-refresh-analysis").addEventListener("click", () => runAnalysis());
$("btn-dl-html").addEventListener("click", () => {
  if (currentSessionId) window.location.href = `/api/sessions/${currentSessionId}/report?format=html`;
});
$("btn-dl-md").addEventListener("click", () => {
  if (currentSessionId) window.location.href = `/api/sessions/${currentSessionId}/report?format=md`;
});

async function runAnalysis() {
  if (!currentSessionId) return;
  $("analysis-skeleton").classList.remove("hidden");
  $("btn-analysis").disabled = true;
  if ($("btn-refresh-analysis")) $("btn-refresh-analysis").disabled = true;
  try {
    const { res, data } = await postJson(`/api/sessions/${currentSessionId}/analysis`, {}, { llm: true });
    if (!res.ok) {
      showError(`[${data.category || "错误"}] ${data.error || "详细分析失败"}`);
      return;
    }
    if (currentResult) {
      if (!data || !data.analysis || !Array.isArray(data.analysis.advisors)) {
        showError("详细分析返回格式异常");
        return;
      }
      currentResult.analysis = data.analysis;
      currentResult.analysis_stale = Boolean(data.stale);
    }
    await loadAnalysisFragment(data.stale);
  } catch (err) {
    showError(err.message);
  } finally {
    $("analysis-skeleton").classList.add("hidden");
    $("btn-analysis").disabled = false;
    if ($("btn-refresh-analysis")) $("btn-refresh-analysis").disabled = false;
  }
}

async function loadAnalysisFragment(stale) {
  if (!currentSessionId) return;
  const res = await fetch(`/api/sessions/${currentSessionId}/report?format=fragment`);
  const data = await safeJson(res);
  if (!res.ok) return;
  $("analysis-body").classList.remove("hidden");
  $("analysis-html").innerHTML = data.html;
  setDownloadState(true, stale);
}

function setDownloadState(hasAnalysis, stale) {
  $("btn-dl-html").disabled = !hasAnalysis;
  $("btn-dl-md").disabled = !hasAnalysis;
  $("analysis-stale-banner").classList.toggle("hidden", !hasAnalysis || !stale);
  if (!hasAnalysis) {
    $("dl-hint").textContent = "生成详细分析后可下载";
  } else if (stale) {
    $("dl-hint").textContent = "下载内容会标注分析已过期";
  } else {
    $("dl-hint").textContent = "";
  }
}

async function safeJson(res) {
  const raw = await res.text();
  try {
    return JSON.parse(raw);
  } catch {
    throw new Error(`服务器返回非 JSON 响应（HTTP ${res.status}）`);
  }
}

function renderResult(data) {
  $("result-section").classList.remove("hidden");
  renderDashboard(data);
  renderFlags(data.flags || []);
  renderGroupsFull(data.groups || []);
  if (data.analysis) {
    loadAnalysisFragment(data.analysis_stale);
  } else {
    $("analysis-body").classList.add("hidden");
    setDownloadState(false, false);
  }
  $("disclaimer-text").textContent = data.disclaimer || "";
  requestAnimationFrame(recalcDashTop);
}

function applyFieldsResult(data) {
  renderDashboard(data);
  renderFlags(data.flags || []);
  reconcileGroups(data.groups || []);
  if (data.analysis) {
    setDownloadState(true, data.analysis_stale);
  }
}

function renderDashboard(data) {
  const sc = data.score;
  $("score-label").textContent = sc.label;
  $("score-action").textContent = sc.action || "";
  $("score-range").textContent = `可能范围 ${sc.low}–${sc.high}`;
  if (sc.red_line) {
    $("conf-row")?.classList.add("hidden");
    $("conf-note")?.classList.add("hidden");
    $("conf-redline")?.classList.remove("hidden");
  } else {
    $("conf-row")?.classList.remove("hidden");
    $("conf-note")?.classList.remove("hidden");
    $("conf-redline")?.classList.add("hidden");
    $("conf-pct").textContent = `${sc.confidence_pct}%`;
    $("conf-bar").style.width = `${sc.confidence_pct}%`;
  }

  const intervalEl = $("gauge-interval");
  intervalEl.style.left = `${sc.low}%`;
  intervalEl.style.width = `${Math.max(2, sc.high - sc.low)}%`;

  const markerEl = $("gauge-marker");
  if (sc.label === "还看不出来") {
    markerEl.classList.add("hidden");
    $("marker-hint").classList.add("hidden");
  } else {
    markerEl.classList.remove("hidden");
    markerEl.style.left = `${sc.point}%`;
    $("marker-hint").classList.toggle("hidden", sc.confidence >= 0.4);
  }

  $("headline-text").textContent = (data.headline || "").replace(/\*\*/g, "");

  const syn = data.synthesis || {};
  const synEl = $("synthesis-line");
  if (syn.sentence) {
    const advMap = new Map(advisorsList.map((a) => [a.id, a]));
    const wk = syn.weakest;
    const st = syn.strongest;
    if (wk && wk.id && advMap.has(wk.id)) {
      const wkCode = advMap.get(wk.id).code || wk.name;
      const gainTxt = wk.delta != null ? `，把它提升一档，评分约 +${wk.delta}` : "";
      const stTxt = st && st.id && advMap.has(st.id) ? `。最强项：${advMap.get(st.id).code}。` : (st && st.name ? `。最强项：${st.name}。` : "。");
      synEl.textContent = `最大短板：${wkCode} · ${wk.name}（${wk.rating || "未知"}）${gainTxt}${stTxt}`;
    } else {
      synEl.textContent = syn.sentence;
    }
    synEl.classList.remove("hidden");
    synEl.onclick = () => {
      if (!syn.group) return;
      const gref = groupRefs.get(syn.group);
      if (gref && gref.block) {
        gref.block.scrollIntoView({ behavior: "smooth", block: "center" });
        gref.block.classList.add("highlight");
        setTimeout(() => gref.block.classList.remove("highlight"), 1000);
      }
    };
  } else {
    synEl.classList.add("hidden");
  }

  const excl = sc.excluded || [];
  const exclEl = $("excluded-line");
  if (excl.length) {
    const parts = excl.map((e) => e.rating_if_included === "低" ? `${e.name}（若计入将评为低）` : e.name);
    exclEl.textContent = `评分未包含：${parts.join("、")}`;
    exclEl.classList.remove("hidden");
  } else {
    exclEl.classList.add("hidden");
  }
}

function renderFlags(flags) {
  const sum = $("risk-summary");
  const ul = $("flags-list");
  ul.innerHTML = "";
  if (!flags.length) {
    sum.textContent = "未发现明确风险（不代表没有风险）";
    return;
  }
  sum.textContent = `发现 ${flags.length} 个风险（点击展开）`;
  flags.forEach((f) => {
    const li = document.createElement("li");
    li.className = f.level === "红" ? "flag-red" : "flag-yellow";
    li.textContent = `[${f.level}] ${f.text}`;
    ul.appendChild(li);
  });
}

function renderGroupsFull(groups) {
  const container = $("groups-container");
  container.innerHTML = "";
  groupRefs.clear();
  rowRefs.clear();
  groups.forEach((g) => {
    const block = createGroupBlock(g);
    container.appendChild(block);
  });
}

function createGroupBlock(g) {
  const block = document.createElement("div");
  block.className = "group-block";
  block.dataset.groupId = g.id;
  const titleRow = document.createElement("div");
  titleRow.className = "group-title-row";
  const nameSpan = document.createElement("span");
  nameSpan.className = "group-name";
  const rightWrap = document.createElement("span");
  const gainSpan = document.createElement("span");
  gainSpan.className = "group-gain";
  rightWrap.appendChild(gainSpan);

  let exclBtn = null;
  if (g.excludable) {
    exclBtn = document.createElement("button");
    exclBtn.type = "button";
    exclBtn.className = "link-btn";
    exclBtn.style.marginLeft = "10px";
    exclBtn.addEventListener("click", () => {
      const key = GROUP_EXCLUDE_KEY[g.id];
      if (!key) return;
      const currentlyExcluded = block.dataset.excluded === "true";
      queueUpdate({ field: { id: key, value: !currentlyExcluded, unsure: false } }, 0);
    });
    rightWrap.appendChild(exclBtn);
  }

  titleRow.appendChild(nameSpan);
  titleRow.appendChild(rightWrap);
  block.appendChild(titleRow);

  const exclRow = document.createElement("div");
  exclRow.className = "group-excluded hidden";
  block.appendChild(exclRow);

  const ref = { block, nameSpan, gainSpan, exclBtn, exclRow };
  groupRefs.set(g.id, ref);
  _syncGroupContent(ref, g);
  return block;
}

function _syncGroupContent(ref, g) {
  ref.block.dataset.excluded = g.excluded ? "true" : "false";
  ref.nameSpan.innerHTML = `${g.name} <span class="muted">(${g.state})</span>`;
  ref.gainSpan.textContent = g.gain > 0 ? `补全可提升置信度约 +${g.gain}%` : "";
  if (ref.exclBtn) {
    ref.exclBtn.textContent = g.excluded ? "撤销" : "这组不适用于我";
  }
  if (g.excluded) {
    ref.exclRow.textContent = "已标记不适用，评分不含此项";
    ref.exclRow.classList.remove("hidden");
  } else {
    ref.exclRow.classList.add("hidden");
  }

  const incomingFids = new Set(g.fields.map((f) => f.id));
  for (const child of Array.from(ref.block.querySelectorAll(".field-row"))) {
    const fid = child.dataset.fieldId;
    if (!incomingFids.has(fid)) {
      child.remove();
      rowRefs.delete(fid);
    }
  }
  g.fields.forEach((f) => {
    const rref = rowRefs.get(f.id);
    if (!rref) {
      ref.block.appendChild(createFieldRow(f));
    } else {
      updateFieldRow(rref, f);
    }
  });
}

function reconcileGroups(groups) {
  const container = $("groups-container");
  const incomingIds = new Set(groups.map((g) => g.id));

  for (const [gid, ref] of Array.from(groupRefs.entries())) {
    if (!incomingIds.has(gid)) {
      ref.block.remove();
      groupRefs.delete(gid);
    }
  }

  groups.forEach((g) => {
    let ref = groupRefs.get(g.id);
    if (!ref) {
      const block = createGroupBlock(g);
      const targetIdx = CANONICAL_GROUPS.indexOf(g.id);
      let inserted = false;
      for (const child of container.children) {
        const cid = child.dataset.groupId;
        if (CANONICAL_GROUPS.indexOf(cid) > targetIdx) {
          container.insertBefore(block, child);
          inserted = true;
          break;
        }
      }
      if (!inserted) container.appendChild(block);
      return;
    }
    _syncGroupContent(ref, g);
  });
}

function createFieldRow(f) {
  const row = document.createElement("div");
  row.className = `field-row ${f.status === "skipped" ? "skipped" : ""}`;
  row.dataset.fieldId = f.id;

  const labelDiv = document.createElement("div");
  labelDiv.className = "field-label";
  labelDiv.innerHTML = `${f.ui_label}${f.sensitive ? ' <span class="muted">（涉及隐私，可不填）</span>' : ""}`;

  const ctrlDiv = document.createElement("div");
  ctrlDiv.className = "field-control";

  const actDiv = document.createElement("div");
  actDiv.className = "field-actions";
  const unsureLabel = document.createElement("label");
  unsureLabel.innerHTML = `<input type="checkbox" ${f.unsure ? "checked" : ""} /> 不太确定`;
  const unsureChk = unsureLabel.querySelector("input");

  const skipBtn = document.createElement("button");
  skipBtn.type = "button";
  skipBtn.className = "link-btn";
  skipBtn.textContent = f.status === "skipped" ? "撤销跳过" : "没概念";

  const tick = document.createElement("span");
  tick.className = "save-tick hidden";
  tick.textContent = "✓";

  const errDiv = document.createElement("div");
  errDiv.className = "row-error hidden";

  let inputEl = null;
  const chipBtns = [];

  if (f.type === "bool") {
    [
      { v: true, l: "是" },
      { v: false, l: "否" },
    ].forEach((opt) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.val = String(opt.v);
      b.className = `chip-opt ${f.status === "given" && f.value === opt.v ? "active" : ""}`;
      b.textContent = opt.l;
      b.addEventListener("click", () => {
        chipBtns.forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        queueUpdate({ field: { id: f.id, value: opt.v, unsure: unsureChk.checked } }, 0);
      });
      chipBtns.push(b);
      ctrlDiv.appendChild(b);
    });
  } else if (f.type === "enum") {
    (f.choices || []).forEach((c) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.val = c.value;
      b.className = `chip-opt ${f.status === "given" && f.value === c.value ? "active" : ""}`;
      b.textContent = c.label;
      b.addEventListener("click", () => {
        chipBtns.forEach((x) => x.classList.remove("active"));
        b.classList.add("active");
        queueUpdate({ field: { id: f.id, value: c.value, unsure: unsureChk.checked } }, 0);
      });
      chipBtns.push(b);
      ctrlDiv.appendChild(b);
    });
  } else if (f.type === "number") {
    const inp = document.createElement("input");
    inp.type = "number";
    inp.inputMode = "decimal";
    if (f.id === "take_home_ratio") {
      inp.min = "0";
      inp.max = "100";
    }
    if (f.status === "given" && f.value !== null && f.value !== undefined) {
      inp.value = f.id === "take_home_ratio" ? Math.round(f.value * 100) : f.value;
    }
    const readNum = () => {
      if (inp.value.trim() === "") return null;
      let num = Number(inp.value);
      if (Number.isNaN(num)) return null;
      if (f.id === "take_home_ratio") num = num / 100;
      return num;
    };
    inp.addEventListener("input", () => {
      const v = readNum();
      if (v !== null) queueUpdate({ field: { id: f.id, value: v, unsure: unsureChk.checked } }, 600);
    });
    inp.addEventListener("change", () => {
      if (inp.value.trim() === "") {
        queueUpdate({ field: { id: f.id, clear: true } }, 0);
      } else {
        const v = readNum();
        if (v !== null) queueUpdate({ field: { id: f.id, value: v, unsure: unsureChk.checked } }, 0);
      }
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if (inp.value.trim() === "") {
          queueUpdate({ field: { id: f.id, clear: true } }, 0);
        } else {
          const v = readNum();
          if (v !== null) queueUpdate({ field: { id: f.id, value: v, unsure: unsureChk.checked } }, 0);
        }
      }
    });
    inputEl = inp;
    ctrlDiv.appendChild(inp);
  } else {
    const inp = document.createElement("input");
    inp.type = "text";
    inp.placeholder = "简要填写";
    if (f.status === "given" && f.value) inp.value = typeof f.value === "string" ? f.value : JSON.stringify(f.value);
    inp.addEventListener("input", () => {
      if (inp.value.trim()) queueUpdate({ field: { id: f.id, value: inp.value.trim(), unsure: unsureChk.checked } }, 600);
    });
    inp.addEventListener("change", () => {
      if (inp.value.trim()) queueUpdate({ field: { id: f.id, value: inp.value.trim(), unsure: unsureChk.checked } }, 0);
      else queueUpdate({ field: { id: f.id, clear: true } }, 0);
    });
    inp.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        if (inp.value.trim()) queueUpdate({ field: { id: f.id, value: inp.value.trim(), unsure: unsureChk.checked } }, 0);
        else queueUpdate({ field: { id: f.id, clear: true } }, 0);
      }
    });
    inputEl = inp;
    ctrlDiv.appendChild(inp);
  }

  unsureChk.addEventListener("change", () => {
    let curVal = null;
    if (inputEl) {
      curVal = f.type === "number"
        ? (inputEl.value.trim() === "" ? null : (f.id === "take_home_ratio" ? Number(inputEl.value) / 100 : Number(inputEl.value)))
        : inputEl.value.trim();
    } else if (chipBtns.length > 0) {
      const activeChip = chipBtns.find((b) => b.classList.contains("active"));
      if (activeChip) {
        const raw = activeChip.dataset.val;
        curVal = raw === "true" ? true : (raw === "false" ? false : raw);
      }
    } else {
      curVal = f.value;
    }
    if (curVal !== null && curVal !== "" && !Number.isNaN(curVal)) {
      queueUpdate({ field: { id: f.id, value: curVal, unsure: unsureChk.checked } }, 0);
    }
  });

  skipBtn.addEventListener("click", () => {
    const isSkipped = row.classList.contains("skipped");
    if (isSkipped) {
      row.classList.remove("skipped");
      skipBtn.textContent = "没概念";
      queueUpdate({ unskip: f.id }, 0);
    } else {
      row.classList.add("skipped");
      skipBtn.textContent = "撤销跳过";
      queueUpdate({ skip: f.id }, 0);
    }
  });

  actDiv.appendChild(unsureLabel);
  actDiv.appendChild(skipBtn);
  actDiv.appendChild(tick);

  row.appendChild(labelDiv);
  row.appendChild(ctrlDiv);
  row.appendChild(actDiv);
  row.appendChild(errDiv);

  if (f.clarify) {
    const cb = document.createElement("div");
    cb.className = "clarify-banner";
    cb.textContent = `需要确认：${f.clarify.question}`;
    row.appendChild(cb);
  }

  rowRefs.set(f.id, { row, inputEl, chipBtns, unsureChk, skipBtn, tick, errDiv, field: f });
  return row;
}

function updateFieldRow(rref, f) {
  rref.field = f;
  if (pending.fields.has(f.id) || pending.skip.has(f.id) || pending.unskip.has(f.id)) return;
  if (rref.inputEl && document.activeElement === rref.inputEl) return;

  rref.row.classList.toggle("skipped", f.status === "skipped");
  rref.skipBtn.textContent = f.status === "skipped" ? "撤销跳过" : "没概念";
  rref.unsureChk.checked = Boolean(f.unsure);

  if (rref.chipBtns.length) {
    rref.chipBtns.forEach((b) => {
      const active = f.status === "given" && String(f.value) === b.dataset.val;
      b.classList.toggle("active", active);
    });
  } else if (rref.inputEl) {
    if (f.status === "given" && f.value !== null && f.value !== undefined) {
      rref.inputEl.value = f.id === "take_home_ratio" ? Math.round(f.value * 100) : (typeof f.value === "string" ? f.value : JSON.stringify(f.value));
    }
  }
}

function queueUpdate(op, delayMs) {
  if (!currentSessionId) return;
  if (op.field) {
    const fid = op.field.id;
    pending.fields.set(fid, op.field);
    pending.skip.delete(fid);
    pending.unskip.delete(fid);
    pending.ticks.add(fid);
  } else if (op.skip) {
    pending.skip.add(op.skip);
    pending.unskip.delete(op.skip);
    pending.fields.delete(op.skip);
    pending.ticks.add(op.skip);
  } else if (op.unskip) {
    pending.unskip.add(op.unskip);
    pending.skip.delete(op.unskip);
    pending.fields.delete(op.unskip);
    pending.ticks.add(op.unskip);
  }

  clearTimeout(flushTimer);
  if (delayMs <= 0) {
    flush();
  } else {
    flushTimer = setTimeout(flush, delayMs);
  }
}

function nothingPending() {
  return pending.fields.size === 0 && pending.skip.size === 0 && pending.unskip.size === 0;
}

function takePending() {
  const payload = {
    fields: Array.from(pending.fields.values()),
    skip: Array.from(pending.skip),
    unskip: Array.from(pending.unskip),
  };
  const ticks = Array.from(pending.ticks);
  pending.fields.clear();
  pending.skip.clear();
  pending.unskip.clear();
  pending.ticks.clear();
  return { payload, ticks };
}

async function flush() {
  if (inFlight || nothingPending() || !currentSessionId) return;
  const { payload, ticks } = takePending();
  inFlight = true;
  $("sync-hint").classList.remove("hidden");
  const t0 = performance.now();
  try {
    const res = await fetch(`/api/sessions/${currentSessionId}/fields`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await safeJson(res);
    const rtt = Math.round(performance.now() - t0);
    if (!res.ok) {
      showRowErrors(ticks, data.error || "保存失败");
    } else {
      console.debug(`[fields] server_ms=${data.server_ms}ms, rtt=${rtt}ms`);
      currentResult = data;
      applyFieldsResult(data);
      showTicks(ticks);
    }
  } catch (err) {
    showRowErrors(ticks, err.message);
  } finally {
    inFlight = false;
    $("sync-hint").classList.add("hidden");
    if (!nothingPending()) flush();
  }
}

function showTicks(fids) {
  fids.forEach((fid) => {
    const rref = rowRefs.get(fid);
    if (!rref) return;
    rref.errDiv.classList.add("hidden");
    rref.tick.classList.remove("hidden");
    setTimeout(() => rref.tick.classList.add("hidden"), 1500);
  });
}

function showRowErrors(fids, msg) {
  fids.forEach((fid) => {
    const rref = rowRefs.get(fid);
    if (!rref) return;
    rref.errDiv.textContent = msg;
    rref.errDiv.classList.remove("hidden");
  });
}

function setEvalLoading(on) {
  $("skeleton-bar").classList.toggle("hidden", !on);
  $("btn-evaluate").disabled = on;
}

function showError(msg, { openSettings = false } = {}) {
  const box = $("error-box");
  box.textContent = msg;
  if (openSettings || String(msg).includes("服务暂不可用")) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "btn-ghost";
    btn.style.marginLeft = "8px";
    btn.textContent = "打开设置";
    btn.addEventListener("click", () => $("btn-settings")?.click());
    box.appendChild(btn);
  }
  box.classList.remove("hidden");
}

function hideError() {
  $("error-box").classList.add("hidden");
}

// 历史会话
$("btn-history").addEventListener("click", async () => {
  $("history-drawer").classList.remove("hidden");
  const res = await fetch("/api/sessions");
  const data = await safeJson(res);
  const list = $("history-list");
  list.innerHTML = "";
  (data.sessions || []).forEach((s) => {
    const div = document.createElement("div");
    div.className = "history-item";
    div.innerHTML = `
      <div class="history-title"></div>
      <div class="history-meta">
        <span></span>
        <button class="btn-ghost btn-del" type="button">删除</button>
      </div>
    `;
    div.querySelector(".history-title").textContent = s.title || "";
    div.querySelector(".history-meta span").textContent = s.red_line
      ? `${s.label} · 红线`
      : `${s.label} · 置信度 ${s.confidence_pct}%`;
    div.querySelector(".history-title").addEventListener("click", async () => {
      const r = await fetch(`/api/sessions/${s.id}`);
      const d = await safeJson(r);
      if (r.ok) {
        currentSessionId = s.id;
        currentResult = d;
        renderResult(d);
        $("history-drawer").classList.add("hidden");
      }
    });
    div.querySelector(".btn-del").addEventListener("click", async () => {
      if (!confirm("确定删除该会话吗？删除后无法恢复。")) return;
      await fetch(`/api/sessions/${s.id}`, { method: "DELETE" });
      div.remove();
    });
    list.appendChild(div);
  });
});

$("btn-close-history").addEventListener("click", () => $("history-drawer").classList.add("hidden"));

function maskByokKey(k) {
  if (!k) return "";
  if (k.length <= 8) return "****";
  return `${k.slice(0, 4)}****${k.slice(-4)}`;
}

function updateByokPolicyHint() {
  const prov = $("byok-provider").value;
  const name = PROVIDER_NAMES[prov] || prov;
  $("byok-policy-hint").textContent = `你的描述会发送给 ${name}，按其数据政策处理。`;
}

// 设置弹窗
$("btn-settings").addEventListener("click", async () => {
  $("settings-modal").classList.remove("hidden");
  $("server-cfg-wrap").classList.toggle("hidden", hostedMode);
  $("byok-provider").value = byokState.provider || "gemini";
  $("byok-model").value = byokState.model || BYOK_DEFAULTS[byokState.provider] || "";
  $("byok-key").value = "";
  $("byok-remember").checked = !!byokState.remember;
  $("byok-status").textContent = byokState.key ? `当前已配置 Key：${maskByokKey(byokState.key)}` : "未配置自带 Key";
  updateByokPolicyHint();
  if (!hostedMode) {
    const res = await fetch("/api/config");
    const cfg = await safeJson(res);
    $("cfg-model").value = cfg.model || "gemini-3.5-flash";
    $("cfg-fast-model").value = cfg.fast_model || "";
    $("cfg-url").value = cfg.base_url || "https://generativelanguage.googleapis.com";
    $("cfg-status").textContent = cfg.has_key ? `当前已配置 Key：${cfg.masked_key}` : "尚未配置 API Key";
  }
});

$("byok-provider").addEventListener("change", () => {
  const prov = $("byok-provider").value;
  $("byok-model").value = BYOK_DEFAULTS[prov] || "";
  updateByokPolicyHint();
});

$("btn-byok-test").addEventListener("click", async () => {
  const prov = $("byok-provider").value;
  const inputKey = $("byok-key").value.trim();
  const model = $("byok-model").value.trim() || BYOK_DEFAULTS[prov] || "";
  const useKey = inputKey || byokState.key;
  if (!useKey) {
    $("byok-status").textContent = "请先输入 API Key";
    return;
  }
  $("byok-status").textContent = "正在测试连接并自测…";
  const prev = { ...byokState };
  byokState = { ...byokState, provider: prov, key: useKey, model };
  try {
    const { res, data } = await postJson("/api/test-connection", {}, { llm: true });
    if (!res.ok || data.ok === false) {
      $("byok-status").textContent = `[${data.category || "错误"}] ${data.message || data.error || "连接失败"}`;
    } else if (data.extracted_ok === false) {
      $("byok-status").textContent = `该模型可用，但抽取质量不足（${data.provider || prov} / ${data.model || model}）`;
    } else {
      $("byok-status").textContent = data.message || `连接成功（${data.provider || prov} / ${data.model || model}）`;
    }
  } catch (err) {
    $("byok-status").textContent = err.message;
  } finally {
    byokState = prev;
  }
});

$("btn-byok-save").addEventListener("click", () => {
  const prov = $("byok-provider").value;
  const inputKey = $("byok-key").value.trim();
  const model = $("byok-model").value.trim() || BYOK_DEFAULTS[prov] || "";
  const remember = $("byok-remember").checked;
  const finalKey = inputKey || byokState.key;
  if (!finalKey) {
    $("byok-status").textContent = "请输入 API Key";
    return;
  }
  byokState = { provider: prov, key: finalKey, model, remember };
  if (remember) {
    localStorage.setItem("cc_byok", JSON.stringify({ provider: prov, key: finalKey, model }));
  } else {
    localStorage.removeItem("cc_byok");
  }
  $("byok-key").value = "";
  $("byok-status").textContent = `已保存（${maskByokKey(finalKey)}）`;
  updateQuotaBadge();
  updatePrivacyNotice();
});

$("btn-byok-clear").addEventListener("click", () => {
  byokState = { provider: "gemini", key: "", model: "", remember: false };
  localStorage.removeItem("cc_byok");
  $("byok-key").value = "";
  $("byok-remember").checked = false;
  $("byok-status").textContent = "已清除自带 Key";
  updateQuotaBadge();
  updatePrivacyNotice();
  if (hostedMode) {
    fetch("/api/quota").then((r) => safeJson(r)).then((q) => updateQuotaBadge(q)).catch(() => { });
  }
});

$("btn-close-cfg").addEventListener("click", () => $("settings-modal").classList.add("hidden"));

$("btn-save-cfg").addEventListener("click", async () => {
  const payload = {
    api_key: $("cfg-key").value.trim(),
    model: $("cfg-model").value.trim(),
    fast_model: $("cfg-fast-model").value.trim(),
    base_url: $("cfg-url").value.trim(),
  };
  const res = await fetch("/api/save-config", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await safeJson(res);
  $("cfg-status").textContent = res.ok ? "已保存配置" : `保存失败：${data.error}`;
});

$("btn-test-cfg").addEventListener("click", async () => {
  $("cfg-status").textContent = "正在测试连接…";
  const payload = {
    api_key: $("cfg-key").value.trim(),
    model: $("cfg-model").value.trim(),
    base_url: $("cfg-url").value.trim(),
  };
  const { res, data } = await postJson("/api/test-connection", payload);
  $("cfg-status").textContent = res.ok ? (data.message || "连接成功") : `[${data.category || "错误"}] ${data.message || data.error || "连接失败"}`;
});

loadAdvisors();


function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

async function loadAdvisors() {
  try {
    const resp = await fetch("/api/advisors");
    if (!resp.ok) return;
    const data = await resp.json();
    if (data && Array.isArray(data.advisors)) {
      advisorsList = data.advisors.slice().sort((a, b) => (a.order || 99) - (b.order || 99));
      advisorsDisclaimer = data.disclaimer || "智囊是分析视角，不是持证顾问。";
    }
  } catch (_e) {
    // 静默降级：不影响主流程
  }
}

function _buildAdvisorModalCard(a) {
  const item = el("div", "advisors-modal-item");
  const head = el("div", "advisors-modal-item-head");
  const titleWrap = el("div", "advisors-modal-item-title");
  titleWrap.appendChild(el("span", "advisor-seal", a.seal || ""));
  titleWrap.appendChild(el("span", "advisors-modal-code", `${a.code || a.name}${a.name && a.code ? ` · ${a.name}` : ""}`));
  head.appendChild(titleWrap);
  if (!a.rated) {
    head.appendChild(el("span", "advisors-modal-tag", "旁听，不评级"));
  } else if (a.group) {
    head.appendChild(el("span", "advisors-modal-group", `所属分组：${a.group}`));
  }
  item.appendChild(head);
  if (a.id === "AI_IMPACT") {
    item.appendChild(el("div", "advisors-modal-note", "判断，不是数据"));
  }
  if (a.ask) {
    item.appendChild(el("div", "advisors-modal-row", `我只问：${a.ask}`));
  }
  if (a.watch) {
    item.appendChild(el("div", "advisors-modal-row", `我最警惕：${a.watch}`));
  }
  if (a.rule_public) {
    item.appendChild(el("div", "advisors-modal-rule", `判断规则：${a.rule_public}`));
  }
  return item;
}

function renderAdvisorsModal() {
  const body = $("advisors-modal-body");
  if (!body) return;
  body.replaceChildren();
  if (!advisorsList.length) {
    body.appendChild(el("div", "advisors-modal-empty", "智囊名册暂时无法加载"));
    return;
  }
  const rated = advisorsList.filter((a) => a.rated);
  const observers = advisorsList.filter((a) => !a.rated);

  const ratedSec = el("div", "advisors-modal-sec");
  ratedSec.appendChild(el("div", "advisors-modal-sec-title", `评分智囊（${rated.length}）`));
  rated.forEach((a) => ratedSec.appendChild(_buildAdvisorModalCard(a)));
  body.appendChild(ratedSec);

  if (observers.length) {
    const obsSec = el("div", "advisors-modal-sec");
    obsSec.appendChild(el("div", "advisors-modal-sec-title", `旁听（${observers.length}）`));
    observers.forEach((a) => obsSec.appendChild(_buildAdvisorModalCard(a)));
    body.appendChild(obsSec);
  }
}

function openAdvisorsModal() {
  const modal = $("advisors-modal");
  if (!modal) return;
  renderAdvisorsModal();
  modal.classList.remove("hidden");
  const closeBtn = $("btn-advisors-close");
  if (closeBtn) closeBtn.focus();
}

function closeAdvisorsModal() {
  const modal = $("advisors-modal");
  if (!modal || modal.classList.contains("hidden")) return;
  modal.classList.add("hidden");
  const trigger = $("btn-advisors");
  if (trigger) trigger.focus();
}

(function initAdvisorsModal() {
  const btn = $("btn-advisors");
  const closeBtn = $("btn-advisors-close");
  const modal = $("advisors-modal");
  if (btn) btn.addEventListener("click", openAdvisorsModal);
  if (closeBtn) closeBtn.addEventListener("click", closeAdvisorsModal);
  if (modal) {
    modal.addEventListener("click", (e) => {
      if (e.target === modal) closeAdvisorsModal();
    });
  }
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && modal && !modal.classList.contains("hidden")) {
      closeAdvisorsModal();
    }
  });
})();
