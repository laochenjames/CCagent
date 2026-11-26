(function () {
  const STORAGE_BYOK = "ccagent_shared_byok";

  const state = {
    hosted: false,
    serverConfig: {},
    advisors: [],
    schema: [],
    rawText: "",
    fields: {},
    currentResult: null,
  };

  const $ = (id) => document.getElementById(id);

  function loadByok() {
    if (window.__CCAGENT_BYOK__ && window.__CCAGENT_BYOK__.api_key) {
      return window.__CCAGENT_BYOK__;
    }
    try { return JSON.parse(localStorage.getItem(STORAGE_BYOK) || "{}"); } catch { return {}; }
  }
  function saveByok(obj) {
    localStorage.setItem(STORAGE_BYOK, JSON.stringify(obj || {}));
  }
  function getRequestAuthPayload() {
    const byok = loadByok();
    const out = {};
    if (byok.provider) out.provider = byok.provider;
    if (byok.model) out.model = byok.model;
    if (byok.api_key) out.api_key = byok.api_key;
    if (byok.base_url) out.base_url = byok.base_url;
    return out;
  }

  function showError(msg) {
    const box = $("error-box");
    if (!msg) { box.classList.add("hidden"); box.textContent = ""; return; }
    box.textContent = msg;
    box.classList.remove("hidden");
  }

  function setLoading(on) {
    $("skeleton-bar").classList.toggle("hidden", !on);
    $("btn-extract").disabled = on;
    $("btn-generate").disabled = on;
  }

  async function apiFetch(path, options = {}) {
    const res = await fetch(path, {
      headers: { "Content-Type": "application/json", ...(options.headers || {}) },
      ...options,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.error || `请求失败 (HTTP ${res.status})`);
    return data;
  }

  function updateCompleteness() {
    const total = state.schema.length || 8;
    const filled = state.schema.filter((f) => (state.fields[f.key] || "").trim().length > 0).length;
    const pct = Math.round((filled * 100) / total);
    $("completeness-pct").textContent = `${pct}%`;
    $("completeness-bar").style.width = `${pct}%`;
  }

  function renderForm() {
    const container = $("form-groups-container");
    container.innerHTML = "";
    const groups = {};
    state.schema.forEach((f) => {
      if (!groups[f.group]) groups[f.group] = [];
      groups[f.group].push(f);
    });
    Object.entries(groups).forEach(([groupName, items]) => {
      const card = document.createElement("div");
      card.className = "form-group-card";
      const title = document.createElement("div");
      title.className = "form-group-title";
      title.textContent = groupName;
      card.appendChild(title);

      items.forEach((f) => {
        const wrap = document.createElement("div");
        wrap.className = "form-item";
        const val = state.fields[f.key] || "";

        const label = document.createElement("label");
        label.setAttribute("for", `field-${f.key}`);
        const badge = document.createElement("span");
        badge.className = val.trim() ? "field-badge-filled" : "field-badge-empty";
        badge.textContent = val.trim() ? "已填写" : "待补充";
        label.innerHTML = `<span>${f.label}</span>`;
        label.appendChild(badge);

        const input = document.createElement("input");
        input.type = "text";
        input.id = `field-${f.key}`;
        input.value = val;
        input.placeholder = f.placeholder || "";
        input.addEventListener("input", (e) => {
          const v = e.target.value;
          state.fields[f.key] = v;
          badge.className = v.trim() ? "field-badge-filled" : "field-badge-empty";
          badge.textContent = v.trim() ? "已填写" : "待补充";
          updateCompleteness();
        });

        wrap.appendChild(label);
        wrap.appendChild(input);
        card.appendChild(wrap);
      });
      container.appendChild(card);
    });
    updateCompleteness();
  }

  function stanceClass(stance) {
    const s = stance || "";
    if (s.includes("警告") || s.includes("止损") || s.includes("底线") || s.includes("风险")) return "stance-badge stance-warn";
    if (s.includes("建议") || s.includes("验证") || s.includes("突破") || s.includes("押注")) return "stance-badge stance-go";
    return "stance-badge";
  }

  function renderResult(data) {
    const res = data.result || data;
    state.currentResult = res;

    $("res-engine-tag").textContent = data.engine === "fallback" ? "规则保底" : `AI 智囊团 · ${data.model || ""}`;
    const fbTag = $("res-fallback-tag");
    if (data.fallback_reason) {
      fbTag.textContent = data.fallback_reason;
      fbTag.classList.remove("hidden");
    } else {
      fbTag.classList.add("hidden");
    }

    $("res-title").textContent = res.title || "思维模型分析";
    $("res-summary").textContent = res.summary || "";

    const pillarsEl = $("res-pillars");
    pillarsEl.innerHTML = "";
    (res.pillars || []).forEach((p, idx) => {
      const box = document.createElement("div");
      box.className = idx === 2 ? "pillar-box pillar-fallback" : "pillar-box";
      box.innerHTML = `<div class="pillar-label">${p.label || ""}</div><div class="pillar-val">${p.value || ""}</div>`;
      pillarsEl.appendChild(box);
    });

    const secWrap = $("res-sections");
    secWrap.innerHTML = "";
    (res.sections || []).forEach((sec) => {
      const card = document.createElement("div");
      card.className = "card section-block";
      const h2 = document.createElement("h2");
      h2.style.marginBottom = "12px";
      h2.textContent = sec.heading || "";
      card.appendChild(h2);

      const list = document.createElement("div");
      list.className = "result-items";
      (sec.items || []).forEach((item, idx) => {
        const row = document.createElement("div");
        row.className = "result-item-card";
        row.innerHTML = `
          <div class="result-item-num">${idx + 1}</div>
          <div class="result-item-body">
            <div class="result-item-head">
              <span class="result-item-name">${item.name || ""}</span>
              ${item.tag ? `<span class="result-item-tag">${item.tag}</span>` : ""}
            </div>
            <p class="result-item-detail">${item.detail || ""}</p>
          </div>
        `;
        list.appendChild(row);
      });
      card.appendChild(list);
      secWrap.appendChild(card);
    });

    const synthWrap = $("council-synthesis-wrap");
    if (res.council_synthesis && (res.council_synthesis.consensus || res.council_synthesis.tension)) {
      synthWrap.innerHTML = `
        <div class="synth-box synth-consensus">
          <div class="synth-label">智囊团最大共识</div>
          <p class="synth-text">${res.council_synthesis.consensus || ""}</p>
        </div>
        <div class="synth-box synth-tension">
          <div class="synth-label">核心分歧 / 权衡张力</div>
          <p class="synth-text">${res.council_synthesis.tension || ""}</p>
        </div>
      `;
      synthWrap.classList.remove("hidden");
    } else {
      synthWrap.innerHTML = "";
      synthWrap.classList.add("hidden");
    }

    const notesGrid = $("council-notes-grid");
    notesGrid.innerHTML = "";
    (res.council_notes || []).forEach((item) => {
      const card = document.createElement("div");
      card.className = "council-card";
      const verdict = item.verdict || item.note || "";
      const role = item.role || "";
      const stance = item.stance || "";
      const action = item.action || "";
      card.innerHTML = `
        <div class="council-card-head">
          <div>
            <div class="council-name">${item.name || "智囊顾问"}</div>
            ${role ? `<div class="council-role">${role}</div>` : ""}
          </div>
          ${stance ? `<span class="${stanceClass(stance)}">${stance}</span>` : ""}
        </div>
        <p class="council-verdict">${verdict}</p>
        ${action ? `<p class="council-action"><strong>建议动作：</strong>${action}</p>` : ""}
      `;
      notesGrid.appendChild(card);
    });

    $("result-section").classList.remove("hidden");
    $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function buildMarkdown(res) {
    const lines = [`# ${res.title || "思维模型分析"}`, "", `> ${res.summary || ""}`, ""];
    (res.pillars || []).forEach((p) => lines.push(`- **${p.label}**：${p.value}`));
    (res.sections || []).forEach((sec) => {
      lines.push("", `## ${sec.heading}`);
      (sec.items || []).forEach((item, i) => {
        lines.push(`${i + 1}. **${item.name}**（${item.tag || ""}）：${item.detail}`);
      });
    });
    if (res.council_synthesis) {
      lines.push("", "## 智囊团合议");
      if (res.council_synthesis.consensus) lines.push(`- **最大共识**：${res.council_synthesis.consensus}`);
      if (res.council_synthesis.tension) lines.push(`- **核心分歧**：${res.council_synthesis.tension}`);
    }
    if (Array.isArray(res.council_notes) && res.council_notes.length) {
      lines.push("", "## 智囊团意见备忘录");
      res.council_notes.forEach((c) => {
        const v = c.verdict || c.note || "";
        const act = c.action ? `｜建议动作：${c.action}` : "";
        lines.push(`- **${c.name}**${c.stance ? ` [${c.stance}]` : ""}：${v}${act}`);
      });
    }
    return lines.join("\n");
  }

  function downloadText(filename, text, mime) {
    const blob = new Blob([text], { type: mime });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
  }

  async function handleExtract() {
    const raw = $("raw-input").value.trim();
    if (!raw) { showError("请先输入要分析的内容。"); return; }
    showError("");
    state.rawText = raw;
    setLoading(true);
    try {
      const data = await apiFetch("api/extract", {
        method: "POST",
        body: JSON.stringify({ raw_text: raw, ...getRequestAuthPayload() }),
      });
      state.fields = data.fields || {};
      $("desc-preview").textContent = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
      $("input-expanded").classList.add("hidden");
      $("input-collapsed").classList.remove("hidden");
      $("extract-summary-note").textContent = data.summary_note || "";
      renderForm();
      $("refine-section").classList.remove("hidden");
      $("result-section").classList.add("hidden");
    } catch (e) {
      showError(e.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleGenerate() {
    showError("");
    setLoading(true);
    const origLabel = $("btn-generate").dataset.label || $("btn-generate").textContent;
    $("btn-generate").dataset.label = origLabel;
    $("btn-generate").textContent = "智囊团合议推演中…";
    try {
      const data = await apiFetch("api/generate", {
        method: "POST",
        body: JSON.stringify({ raw_text: state.rawText, fields: state.fields, ...getRequestAuthPayload() }),
      });
      renderResult(data);
    } catch (e) {
      showError(e.message);
    } finally {
      setLoading(false);
      $("btn-generate").textContent = origLabel;
    }
  }

  async function openHistory() {
    $("modal-history").classList.remove("hidden");
    const list = $("history-list");
    list.innerHTML = `<p class="muted">加载中…</p>`;
    try {
      const data = await apiFetch("api/history");
      const items = data.items || [];
      if (!items.length) { list.innerHTML = `<p class="muted">暂无历史分析记录。</p>`; return; }
      list.innerHTML = "";
      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "history-item";
        const main = document.createElement("div");
        main.className = "history-item-main";
        main.innerHTML = `<div><strong>${item.title}</strong> <span class="muted">${(item.created_at || "").slice(0, 10)}</span></div><div class="muted">${item.summary || ""}</div>`;
        main.addEventListener("click", () => {
          state.rawText = item.raw_text || "";
          state.fields = item.fields || {};
          $("raw-input").value = state.rawText;
          $("desc-preview").textContent = state.rawText.slice(0, 60);
          $("input-expanded").classList.add("hidden");
          $("input-collapsed").classList.remove("hidden");
          renderForm();
          $("refine-section").classList.remove("hidden");
          renderResult({ result: item.result, engine: item.engine, model: item.model });
          $("modal-history").classList.add("hidden");
        });
        const del = document.createElement("button");
        del.className = "btn-ghost";
        del.textContent = "删除";
        del.addEventListener("click", async () => {
          await apiFetch(`api/history/${item.id}`, { method: "DELETE" });
          openHistory();
        });
        row.appendChild(main);
        row.appendChild(del);
        list.appendChild(row);
      });
    } catch (e) {
      list.innerHTML = `<p class="muted">加载失败：${e.message}</p>`;
    }
  }

  async function init() {
    try {
      const [cfg, council] = await Promise.all([apiFetch("api/config"), apiFetch("api/council")]);
      state.hosted = !!cfg.hosted;
      state.serverConfig = cfg;
      state.advisors = council.advisors || [];
      state.schema = council.fields_schema || [];

      $("engine-badge").textContent = cfg.has_key ? `引擎：${cfg.model}` : "未配置 API";
      const hostedNotice = $("hosted-notice");
      if (state.hosted && hostedNotice) hostedNotice.classList.remove("hidden");

      const byok = loadByok();
      $("cfg-provider").value = byok.provider || cfg.provider || "gemini";
      $("cfg-model").value = byok.model || cfg.model || "gemini-3.5-flash-lite";
      $("cfg-key").value = byok.api_key || "";
      $("cfg-base-url").value = byok.base_url || cfg.base_url || "";

      const roster = $("council-roster-list");
      roster.innerHTML = "";
      state.advisors.forEach((a) => {
        const div = document.createElement("div");
        div.className = "roster-item";
        div.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><strong>${a.name}</strong><span class="muted">${a.tag}</span></div><div style="font-size:13px;margin-bottom:4px;">${a.principle}</div><div class="muted">关注点：${a.focus}</div>`;
        roster.appendChild(div);
      });
    } catch (e) {
      showError(`初始化失败：${e.message}`);
    }

    document.querySelectorAll(".chip").forEach((btn) => {
      btn.addEventListener("click", () => {
        $("raw-input").value = btn.getAttribute("data-example") || "";
        $("raw-input").focus();
      });
    });

    $("btn-extract").addEventListener("click", handleExtract);
    $("btn-generate").addEventListener("click", handleGenerate);

    window.addEventListener("ccagent:direct-generate", (e) => {
      const raw = ((e.detail && e.detail.text) || $("raw-input").value || "").trim();
      if (!raw) return;
      state.rawText = raw;
      state.fields = {};
      $("raw-input").value = raw;
      $("desc-preview").textContent = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
      $("input-expanded").classList.add("hidden");
      $("input-collapsed").classList.remove("hidden");
      $("refine-section").classList.add("hidden");
      handleGenerate();
    });
    $("btn-edit-desc").addEventListener("click", () => {
      $("input-collapsed").classList.add("hidden");
      $("input-expanded").classList.remove("hidden");
    });
    $("btn-reset-all").addEventListener("click", () => {
      $("input-collapsed").classList.add("hidden");
      $("input-expanded").classList.remove("hidden");
      $("refine-section").classList.add("hidden");
      $("result-section").classList.add("hidden");
      $("raw-input").focus();
    });

    $("btn-copy-md").addEventListener("click", async () => {
      if (!state.currentResult) return;
      await navigator.clipboard.writeText(buildMarkdown(state.currentResult));
      $("btn-copy-md").textContent = "已复制";
      setTimeout(() => ($("btn-copy-md").textContent = "复制 Markdown"), 1500);
    });
    $("btn-dl-md").addEventListener("click", () => {
      if (!state.currentResult) return;
      downloadText(`${state.currentResult.title || "analysis"}.md`, buildMarkdown(state.currentResult), "text/markdown;charset=utf-8");
    });
    $("btn-dl-json").addEventListener("click", () => {
      if (!state.currentResult) return;
      downloadText(`${state.currentResult.title || "analysis"}.json`, JSON.stringify(state.currentResult, null, 2), "application/json;charset=utf-8");
    });

    $("btn-council").addEventListener("click", () => $("modal-council").classList.remove("hidden"));
    $("btn-history").addEventListener("click", openHistory);
    $("btn-settings").addEventListener("click", () => {
      $("settings-status").textContent = "";
      $("modal-settings").classList.remove("hidden");
    });

    document.querySelectorAll(".btn-close-modal").forEach((btn) => {
      btn.addEventListener("click", () => $(btn.getAttribute("data-close")).classList.add("hidden"));
    });
    document.querySelectorAll(".modal-backdrop").forEach((bg) => {
      bg.addEventListener("click", (e) => { if (e.target === bg) bg.classList.add("hidden"); });
    });

    $("btn-test-conn").addEventListener("click", async () => {
      $("settings-status").textContent = "正在测试连接…";
      try {
        const res = await apiFetch("api/test-connection", {
          method: "POST",
          body: JSON.stringify({
            provider: $("cfg-provider").value,
            model: $("cfg-model").value.trim(),
            api_key: $("cfg-key").value.trim(),
            base_url: $("cfg-base-url").value.trim(),
          }),
        });
        $("settings-status").textContent = res.ok ? `连接成功（${res.provider} / ${res.model}）` : `连接失败：${res.error}`;
      } catch (e) {
        $("settings-status").textContent = `测试失败：${e.message}`;
      }
    });

    $("btn-save-cfg").addEventListener("click", async () => {
      const payload = {
        provider: $("cfg-provider").value,
        model: $("cfg-model").value.trim(),
        api_key: $("cfg-key").value.trim(),
        base_url: $("cfg-base-url").value.trim(),
      };
      if (state.hosted) {
        saveByok(payload);
        $("settings-status").textContent = "已保存到当前浏览器（托管模式）。";
        return;
      }
      try {
        await apiFetch("api/save-config", { method: "POST", body: JSON.stringify(payload) });
        saveByok(payload);
        $("settings-status").textContent = "已保存到服务端配置。";
        $("engine-badge").textContent = `引擎：${payload.model || state.serverConfig.model}`;
      } catch (e) {
        $("settings-status").textContent = `保存失败：${e.message}`;
      }
    });
  }

  init();
})();
