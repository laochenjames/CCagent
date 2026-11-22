(function () {
  const STORAGE_BYOK = "ccagent_agent3_byok";

  const state = {
    hosted: false,
    serverConfig: {},
    advisors: [],
    schema: [],
    rawText: "",
    fields: {},
    currentPlan: null,
  };

  const $ = (id) => document.getElementById(id);

  function escapeHtml(str) {
    return String(str == null ? "" : str)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function loadByok() {
    try {
      return JSON.parse(localStorage.getItem(STORAGE_BYOK) || "{}");
    } catch {
      return {};
    }
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
    if (!msg) {
      box.classList.add("hidden");
      box.textContent = "";
      return;
    }
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
    if (!res.ok) {
      throw new Error(data.error || `请求失败 (HTTP ${res.status})`);
    }
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
        badge.id = `badge-${f.key}`;
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

  function renderResult(data) {
    const plan = data.plan || data;
    state.currentPlan = plan;

    $("res-engine-tag").textContent = data.engine === "fallback" ? "规则保底" : `AI 智囊团 · ${data.model || ""}`;
    const fbTag = $("res-fallback-tag");
    if (data.fallback_reason) {
      fbTag.textContent = data.fallback_reason;
      fbTag.classList.remove("hidden");
    } else {
      fbTag.classList.add("hidden");
    }

    $("res-name").textContent = plan.name || "原子习惯方案";
    $("res-desc").textContent = plan.description || "";
    $("res-trigger").textContent = plan.trigger_formula || "当固定日常锚点发生时，立刻执行第 1 步两分钟微动作。";
    $("res-identity").textContent = plan.identity_statement || "每一次微小完成，都是对理想身份的一次投票。";
    $("res-fallback-plan").textContent = plan.fallback_plan || "状态最差时，只完成第 1 步启动动作即算打卡成功。";

    const nodes = Array.isArray(plan.subNodes) ? plan.subNodes : [];
    $("nodes-count-badge").textContent = `共 ${nodes.length} 个递进节点`;
    const list = $("nodes-list");
    list.innerHTML = "";
    nodes.forEach((node, idx) => {
      const card = document.createElement("div");
      card.className = "node-card";

      const num = document.createElement("div");
      num.className = "node-step-num";
      num.textContent = String(idx + 1);

      const body = document.createElement("div");
      body.className = "node-body";

      const head = document.createElement("div");
      head.className = "node-head";

      const nameEl = document.createElement("div");
      nameEl.className = "node-name";
      nameEl.contentEditable = "true";
      nameEl.textContent = node.name || `节点 ${idx + 1}`;
      nameEl.addEventListener("input", () => {
        node.name = nameEl.textContent.trim();
      });

      const levelEl = document.createElement("span");
      levelEl.className = "node-level";
      levelEl.textContent = node.level || (idx === 0 ? "启动层 · 两分钟" : `第 ${idx + 1} 阶`);

      head.appendChild(nameEl);
      head.appendChild(levelEl);

      const descEl = document.createElement("p");
      descEl.className = "node-desc";
      descEl.contentEditable = "true";
      descEl.textContent = node.description || "";
      descEl.addEventListener("input", () => {
        node.description = descEl.textContent.trim();
      });

      body.appendChild(head);
      body.appendChild(descEl);
      card.appendChild(num);
      card.appendChild(body);
      list.appendChild(card);
    });

    const notesGrid = $("council-notes-grid");
    notesGrid.innerHTML = "";
    const synth = plan.council_synthesis;
    if (synth && (synth.consensus || synth.tension)) {
      const banner = document.createElement("div");
      banner.className = "council-synthesis";
      banner.innerHTML =
        (synth.consensus ? `<div class="synth-row"><span class="synth-tag consensus">合议共识</span><span>${escapeHtml(synth.consensus)}</span></div>` : "") +
        (synth.tension ? `<div class="synth-row"><span class="synth-tag tension">关键张力</span><span>${escapeHtml(synth.tension)}</span></div>` : "");
      notesGrid.appendChild(banner);
    }
    const notes = Array.isArray(plan.council_notes) ? plan.council_notes : [];
    notes.forEach((item) => {
      const card = document.createElement("div");
      card.className = "council-card";
      const verdict = item.verdict || item.note || "";
      const roleHtml = item.role ? `<span class="council-role">${escapeHtml(item.role)}</span>` : "";
      const stanceHtml = item.stance ? `<span class="council-stance">${escapeHtml(item.stance)}</span>` : "";
      const actionHtml = item.action ? `<div class="council-action"><strong>落地动作：</strong>${escapeHtml(item.action)}</div>` : "";
      card.innerHTML =
        `<div class="council-head"><div class="council-title-wrap"><span class="council-name">${escapeHtml(item.name || "智囊顾问")}</span>${roleHtml}</div>${stanceHtml}</div>` +
        `<p class="council-note">${escapeHtml(verdict)}</p>${actionHtml}`;
      notesGrid.appendChild(card);
    });

    $("result-section").classList.remove("hidden");
    $("result-section").scrollIntoView({ behavior: "smooth", block: "start" });
  }

  function buildMarkdown(plan) {
    const lines = [
      `# ${plan.name || "原子习惯方案"}`,
      "",
      `> ${plan.description || ""}`,
      "",
      `- **触发公式**：${plan.trigger_formula || ""}`,
      `- **身份投票**：${plan.identity_statement || ""}`,
      `- **低电量防崩盘保底**：${plan.fallback_plan || ""}`,
      "",
      "## 原子习惯递进节点",
    ];
    (plan.subNodes || []).forEach((n, i) => {
      lines.push(`${i + 1}. **${n.name}**（${n.level || `第${i + 1}阶`}）：${n.description}`);
    });
    if (plan.council_synthesis && (plan.council_synthesis.consensus || plan.council_synthesis.tension)) {
      lines.push("", "## 智囊团合议纪要");
      if (plan.council_synthesis.consensus) lines.push(`- **合议共识**：${plan.council_synthesis.consensus}`);
      if (plan.council_synthesis.tension) lines.push(`- **关键张力**：${plan.council_synthesis.tension}`);
    }
    if (Array.isArray(plan.council_notes) && plan.council_notes.length) {
      lines.push("", "## 智囊团点评");
      plan.council_notes.forEach((c) => {
        const v = c.verdict || c.note || "";
        const act = c.action ? `（落地动作：${c.action}）` : "";
        lines.push(`- **${c.name}**${c.stance ? `[${c.stance}]` : ""}：${v}${act}`);
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
    if (!raw) {
      showError("请先输入你想养成的习惯或目标。");
      return;
    }
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
    $("btn-generate").textContent = "智囊团分解中…";
    try {
      const data = await apiFetch("api/generate", {
        method: "POST",
        body: JSON.stringify({
          raw_text: state.rawText,
          fields: state.fields,
          ...getRequestAuthPayload(),
        }),
      });
      renderResult(data);
    } catch (e) {
      showError(e.message);
    } finally {
      setLoading(false);
      $("btn-generate").textContent = "由智囊团分解为原子习惯";
    }
  }

  async function openHistory() {
    $("modal-history").classList.remove("hidden");
    const list = $("history-list");
    list.innerHTML = `<p class="muted">加载中…</p>`;
    try {
      const data = await apiFetch("api/history");
      const items = data.items || [];
      if (!items.length) {
        list.innerHTML = `<p class="muted">暂无历史方案，生成后会自动保存在这里。</p>`;
        return;
      }
      list.innerHTML = "";
      items.forEach((item) => {
        const row = document.createElement("div");
        row.className = "history-item";
        const main = document.createElement("div");
        main.className = "history-item-main";
        main.innerHTML = `<div><strong>${item.name}</strong> <span class="muted">${(item.created_at || "").slice(0, 10)}</span></div><div class="muted">${item.description || ""}</div>`;
        main.addEventListener("click", () => {
          state.rawText = item.raw_text || "";
          state.fields = item.fields || {};
          $("raw-input").value = state.rawText;
          $("desc-preview").textContent = state.rawText.slice(0, 60);
          $("input-expanded").classList.add("hidden");
          $("input-collapsed").classList.remove("hidden");
          renderForm();
          $("refine-section").classList.remove("hidden");
          renderResult({ plan: item.plan, engine: item.engine, model: item.model });
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
      const [cfg, council] = await Promise.all([
        apiFetch("api/config"),
        apiFetch("api/council"),
      ]);
      state.hosted = !!cfg.hosted;
      state.serverConfig = cfg;
      state.advisors = council.advisors || [];
      state.schema = council.fields_schema || [];

      $("engine-badge").textContent = cfg.has_key ? `引擎：${cfg.model}` : "未配置 API";
      if (state.hosted) $("hosted-notice").classList.remove("hidden");

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
      if (!state.currentPlan) return;
      await navigator.clipboard.writeText(buildMarkdown(state.currentPlan));
      $("btn-copy-md").textContent = "已复制";
      setTimeout(() => ($("btn-copy-md").textContent = "复制 Markdown"), 1500);
    });
    $("btn-dl-md").addEventListener("click", () => {
      if (!state.currentPlan) return;
      downloadText(`${state.currentPlan.name || "atomic-habit"}.md`, buildMarkdown(state.currentPlan), "text/markdown;charset=utf-8");
    });
    $("btn-dl-json").addEventListener("click", () => {
      if (!state.currentPlan) return;
      const exportObj = {
        name: state.currentPlan.name,
        description: state.currentPlan.description,
        subNodes: (state.currentPlan.subNodes || []).map((n) => ({ name: n.name, description: n.description })),
      };
      downloadText(`${state.currentPlan.name || "atomic-habit"}.json`, JSON.stringify(exportObj, null, 2), "application/json;charset=utf-8");
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
      bg.addEventListener("click", (e) => {
        if (e.target === bg) bg.classList.add("hidden");
      });
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
