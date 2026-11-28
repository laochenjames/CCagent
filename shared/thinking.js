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

  function esc(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  const STANCE_MAP = {
    support: { label: "支持", cls: "stance-badge stance-go" },
    hold: { label: "有保留", cls: "stance-badge stance-hold" },
    oppose: { label: "反对", cls: "stance-badge stance-warn" },
    need_info: { label: "需补信息", cls: "stance-badge stance-info" },
  };

  const CONF_MAP = {
    high: "高",
    mid: "中",
    low: "低",
  };

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
    if (!state.hosted && byok.base_url) out.base_url = byok.base_url;
    return out;
  }

  function showError(msg, retryFn) {
    const box = $("error-box");
    if (!box) return;
    if (!msg) { box.classList.add("hidden"); box.textContent = ""; return; }
    box.textContent = "";
    const span = document.createElement("span");
    span.textContent = msg;
    box.appendChild(span);
    if (typeof retryFn === "function") {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "btn-retry-inline";
      btn.textContent = "重试";
      btn.addEventListener("click", () => {
        showError("");
        retryFn();
      });
      box.appendChild(btn);
    }
    box.classList.remove("hidden");
  }

  function setLoading(on) {
    const bar = $("skeleton-bar");
    if (bar) bar.classList.toggle("hidden", !on);
    const btnEx = $("btn-extract");
    if (btnEx) btnEx.disabled = on;
    const btnGen = $("btn-generate");
    if (btnGen) btnGen.disabled = on;
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
    const pctEl = $("completeness-pct");
    const barEl = $("completeness-bar");
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (barEl) barEl.style.width = `${pct}%`;
  }

  function renderForm() {
    const container = $("form-groups-container");
    if (!container) return;
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
        const labelText = document.createElement("span");
        labelText.textContent = f.label || "";
        const badge = document.createElement("span");
        badge.className = val.trim() ? "field-badge-filled" : "field-badge-empty";
        badge.textContent = val.trim() ? "已填写" : "待补充";
        label.appendChild(labelText);
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

  function renderStanceBadge(stance) {
    if (!stance) return "";
    const mapped = STANCE_MAP[stance];
    if (mapped) {
      return `<span class="${mapped.cls}">${esc(mapped.label)}</span>`;
    }
    return `<span class="stance-badge">${esc(stance)}</span>`;
  }

  function renderResult(data) {
    const res = data.result || data;
    state.currentResult = res;

    const engTag = $("res-engine-tag");
    if (engTag) engTag.textContent = `AI 智囊团 · ${data.model || ""}`;
    const fbTag = $("res-fallback-tag");
    if (fbTag) {
      fbTag.textContent = "";
      fbTag.classList.add("hidden");
    }

    const titleEl = $("res-title");
    if (titleEl) titleEl.textContent = res.title || "思维模型分析";
    const sumEl = $("res-summary");
    if (sumEl) sumEl.textContent = res.summary || "";

    const pillarsEl = $("res-pillars");
    if (pillarsEl) {
      // B2: Assumptions & Missing Info blocks before pillars
      let metaWrap = $("res-meta-blocks");
      if (!metaWrap && pillarsEl.parentNode) {
        metaWrap = document.createElement("div");
        metaWrap.id = "res-meta-blocks";
        pillarsEl.parentNode.insertBefore(metaWrap, pillarsEl);
      }
      if (metaWrap) {
        const parts = [];
        if (res.decision) {
          parts.push(`<div class="meta-block meta-decision"><strong>待判断决策：</strong>${esc(res.decision)}</div>`);
        }
        if (Array.isArray(res.assumptions) && res.assumptions.length) {
          parts.push(
            `<div class="meta-block meta-assumptions"><div class="meta-block-title">AI 做了这些假设</div><ul>` +
            res.assumptions.map((a) => `<li>${esc(a)}</li>`).join("") +
            `</ul></div>`
          );
        }
        if (Array.isArray(res.missing_info) && res.missing_info.length) {
          parts.push(
            `<div class="meta-block meta-missing"><div class="meta-block-title">最需补充的信息</div><ul>` +
            res.missing_info.map((m) => `<li>${esc(m)}</li>`).join("") +
            `</ul></div>`
          );
        }
        metaWrap.innerHTML = parts.join("");
      }

      pillarsEl.innerHTML = "";
      (res.pillars || []).forEach((p, idx) => {
        const box = document.createElement("div");
        box.className = idx === 2 ? "pillar-box pillar-fallback" : "pillar-box";
        const val = p.value ?? p.content ?? "";
        box.innerHTML = `<div class="pillar-label">${esc(p.label || "")}</div><div class="pillar-val">${esc(val)}</div>`;
        pillarsEl.appendChild(box);
      });
    }

    const secWrap = $("res-sections");
    if (secWrap) {
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
                <span class="result-item-name">${esc(item.name || "")}</span>
                ${item.tag ? `<span class="result-item-tag">${esc(item.tag)}</span>` : ""}
              </div>
              <p class="result-item-detail">${esc(item.detail || "")}</p>
            </div>
          `;
          list.appendChild(row);
        });
        card.appendChild(list);
        secWrap.appendChild(card);
      });
    }

    const synthWrap = $("council-synthesis-wrap");
    if (synthWrap) {
      const syn = res.council_synthesis || {};
      const consensus = syn.consensus_text ?? syn.consensus ?? "";
      const tension = syn.tension_text ?? syn.tension ?? "";
      if (consensus || tension) {
        const boxes = [];
        if (consensus) {
          boxes.push(`
            <div class="synth-box synth-consensus">
              <div class="synth-label">智囊团最大共识</div>
              <p class="synth-text">${esc(consensus)}</p>
            </div>
          `);
        }
        if (tension) {
          boxes.push(`
            <div class="synth-box synth-tension">
              <div class="synth-label">核心分歧 / 权衡张力</div>
              <p class="synth-text">${esc(tension)}</p>
            </div>
          `);
        }
        synthWrap.innerHTML = boxes.join("");
        synthWrap.classList.remove("hidden");
      } else {
        synthWrap.innerHTML = "";
        synthWrap.classList.add("hidden");
      }
    }

    const notesGrid = $("council-notes-grid");
    if (notesGrid) {
      notesGrid.innerHTML = "";
      (res.council_notes || []).forEach((item) => {
        const card = document.createElement("div");
        card.className = "council-card";
        const verdict = item.verdict || item.note || "";
        const role = item.role || "";
        const stance = item.stance || "";
        const action = item.action || "";
        const basedOn = item.based_on || "";
        const conf = item.confidence ? (CONF_MAP[item.confidence] || item.confidence) : "";
        const changeIf = item.would_change_if || "";
        const ungroundedBadge = item.grounded === false
          ? `<span class="ungrounded-badge">依据未能在输入中找到</span>`
          : "";

        card.innerHTML = `
          <div class="council-card-head">
            <div>
              <div class="council-name">${esc(item.name || "智囊顾问")}</div>
              ${role ? `<div class="council-role">${esc(role)}</div>` : ""}
            </div>
            <div>
              ${renderStanceBadge(stance)}
              ${conf ? `<span class="conf-badge">置信度：${esc(conf)}</span>` : ""}
            </div>
          </div>
          <p class="council-verdict">${esc(verdict)}</p>
          ${basedOn ? `<p class="council-based-on"><strong>依据：</strong>${esc(basedOn)}${ungroundedBadge}</p>` : ""}
          ${changeIf ? `<p class="council-change-if"><strong>若出现则改变判断：</strong>${esc(changeIf)}</p>` : ""}
          ${action ? `<p class="council-action"><strong>建议动作：</strong>${esc(action)}</p>` : ""}
        `;
        notesGrid.appendChild(card);
      });
    }

    const resSec = $("result-section");
    if (resSec) {
      resSec.classList.remove("hidden");
      if (typeof resSec.scrollIntoView === "function") {
        resSec.scrollIntoView({ behavior: "smooth", block: "start" });
      }
    }
  }

  function buildMarkdown(res) {
    const lines = [`# ${res.title || "思维模型分析"}`, "", `> ${res.summary || ""}`, ""];
    if (res.decision) lines.push(`- **待判断决策**：${res.decision}`);
    if (Array.isArray(res.assumptions) && res.assumptions.length) {
      lines.push("", "## AI 做了这些假设");
      res.assumptions.forEach((a) => lines.push(`- ${a}`));
    }
    if (Array.isArray(res.missing_info) && res.missing_info.length) {
      lines.push("", "## 最需补充的信息");
      res.missing_info.forEach((m) => lines.push(`- ${m}`));
    }
    lines.push("");
    (res.pillars || []).forEach((p) => lines.push(`- **${p.label}**：${p.value ?? p.content ?? ""}`));
    (res.sections || []).forEach((sec) => {
      lines.push("", `## ${sec.heading}`);
      (sec.items || []).forEach((item, i) => {
        lines.push(`${i + 1}. **${item.name}**（${item.tag || ""}）：${item.detail}`);
      });
    });
    if (res.council_synthesis) {
      const consensus = res.council_synthesis.consensus_text ?? res.council_synthesis.consensus ?? "";
      const tension = res.council_synthesis.tension_text ?? res.council_synthesis.tension ?? "";
      if (consensus || tension) {
        lines.push("", "## 智囊团合议");
        if (consensus) lines.push(`- **最大共识**：${consensus}`);
        if (tension) lines.push(`- **核心分歧**：${tension}`);
      }
    }
    if (Array.isArray(res.council_notes) && res.council_notes.length) {
      lines.push("", "## 智囊团意见备忘录");
      res.council_notes.forEach((c) => {
        const v = c.verdict || c.note || "";
        const st = c.stance ? (STANCE_MAP[c.stance] ? STANCE_MAP[c.stance].label : c.stance) : "";
        const act = c.action ? `｜建议动作：${c.action}` : "";
        lines.push(`- **${c.name}**${st ? ` [${st}]` : ""}：${v}${act}`);
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
      showError(e.message, handleExtract);
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
      const imgs = Array.isArray(state.images) && state.images.length
        ? state.images
        : (Array.isArray(window.__CCAGENT_IMAGES__) ? window.__CCAGENT_IMAGES__ : []);
      const webSearchChk = $("chk-web-search");
      const webSearch = Boolean(webSearchChk && webSearchChk.checked);
      const data = await apiFetch("api/generate", {
        method: "POST",
        body: JSON.stringify({
          raw_text: state.rawText,
          fields: state.fields,
          images: imgs.slice(0, 2),
          web_search: webSearch,
          ...getRequestAuthPayload(),
        }),
      });
      renderResult(data);
    } catch (e) {
      showError(e.message, handleGenerate);
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
        main.innerHTML = `<div><strong>${esc(item.title)}</strong> <span class="muted">${esc((item.created_at || "").slice(0, 10))}</span></div><div class="muted">${esc(item.summary || "")}</div>`;
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
      list.innerHTML = `<p class="muted">加载失败：${esc(e.message)}</p>`;
    }
  }

  async function init() {
    if (!$("raw-input")) return;
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
      const baseUrlInput = $("cfg-base-url");
      if (baseUrlInput) {
        if (state.hosted) {
          baseUrlInput.value = "";
          if (baseUrlInput.parentElement) baseUrlInput.parentElement.style.display = "none";
        } else {
          baseUrlInput.value = byok.base_url || cfg.base_url || "";
        }
      }

      const roster = $("council-roster-list");
      if (roster) {
        roster.innerHTML = "";
        state.advisors.forEach((a) => {
          const div = document.createElement("div");
          div.className = "roster-item";
          div.innerHTML = `<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:4px;"><strong>${esc(a.name)}</strong><span class="muted">${esc(a.tag)}</span></div><div style="font-size:13px;margin-bottom:4px;">${esc(a.principle)}</div><div class="muted">关注点：${esc(a.focus)}</div>`;
          roster.appendChild(div);
        });
      }
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
    const genBtn = $("btn-generate");
    if (genBtn && !$("chk-web-search")) {
      const lbl = document.createElement("label");
      lbl.className = "web-search-toggle";
      lbl.title = "开启后使用 Gemini Google Search 联网查证最新事实与数据（托管模式仅 BYOK 可用）";
      lbl.innerHTML = `<input type="checkbox" id="chk-web-search"> <span>联网查证（Gemini）</span>`;
      genBtn.parentNode.insertBefore(lbl, genBtn);
    }
    $("btn-edit-desc").addEventListener("click", () => {
      $("input-collapsed").classList.add("hidden");
      $("input-expanded").classList.remove("hidden");
    });
    $("btn-reset-all").addEventListener("click", () => {
      state.images = [];
      window.__CCAGENT_IMAGES__ = [];
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
    initShareCard();

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
        const payload = {
          provider: $("cfg-provider").value,
          model: $("cfg-model").value.trim(),
          api_key: $("cfg-key").value.trim(),
        };
        if (!state.hosted && $("cfg-base-url")) {
          payload.base_url = $("cfg-base-url").value.trim();
        }
        const res = await apiFetch("api/test-connection", {
          method: "POST",
          body: JSON.stringify(payload),
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
      };
      if (!state.hosted && $("cfg-base-url")) {
        payload.base_url = $("cfg-base-url").value.trim();
      }
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

  function wrapCanvasText(ctx, text, maxWidth, maxLines) {
    const lines = [];
    const paras = String(text || "").split(/\r?\n/);
    paras.forEach((p) => {
      if (!p) { lines.push(""); return; }
      let cur = "";
      for (const ch of p) {
        if (ctx.measureText(cur + ch).width > maxWidth && cur) {
          lines.push(cur);
          cur = ch;
        } else {
          cur += ch;
        }
      }
      if (cur) lines.push(cur);
    });
    if (maxLines && lines.length > maxLines) {
      const sliced = lines.slice(0, maxLines);
      let last = sliced[maxLines - 1];
      while (last.length > 1 && ctx.measureText(last + "…").width > maxWidth) {
        last = last.slice(0, -1);
      }
      sliced[maxLines - 1] = last + "…";
      return sliced;
    }
    return lines;
  }

  function roundRectPath(ctx, x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r);
    ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r);
    ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }

  function renderShareCardCanvas(res, themeName, ratioName) {
    const isDark = themeName === "dark";
    const isVertical = ratioName === "4:5";
    const C = isDark ? {
      bg: "#0f1115",
      card: "#181b22",
      border: "#2a2f3a",
      text: "#f8fafc",
      muted: "#9ca3af",
      accent: "#fb923c",
      accentBg: "#271b13",
      summaryBg: "#1c2230",
      pillBg: "#23262f",
      stance: {
        support: { bg: "#143524", fg: "#4ade80", label: "支持" },
        hold: { bg: "#3a2e12", fg: "#fbbf24", label: "观望" },
        oppose: { bg: "#3d181a", fg: "#f87171", label: "反对" },
        need_info: { bg: "#172a45", fg: "#60a5fa", label: "缺信息" },
      },
    } : {
      bg: "#f6f3ec",
      card: "#ffffff",
      border: "#e2ddd2",
      text: "#111827",
      muted: "#57606a",
      accent: "#9a3412",
      accentBg: "#fff7ed",
      summaryBg: "#fdfaf4",
      pillBg: "#faf9f5",
      stance: {
        support: { bg: "#ecfdf3", fg: "#067647", label: "支持" },
        hold: { bg: "#fffaeb", fg: "#b54708", label: "观望" },
        oppose: { bg: "#fef3f2", fg: "#b42318", label: "反对" },
        need_info: { bg: "#eff8ff", fg: "#175cd3", label: "缺信息" },
      },
    };

    const FONT = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", sans-serif';
    const modelTitle = (document.querySelector("h1") && document.querySelector("h1").textContent.trim()) || "CCagent 智囊团";
    const dateStr = new Date().toISOString().slice(0, 10);
    const pillars = Array.isArray(res.pillars) ? res.pillars.slice(0, 3) : [];
    const notes = Array.isArray(res.council_notes) ? res.council_notes.slice(0, 4) : [];
    const syn = res.council_synthesis || {};
    const cons = syn.consensus_text || syn.consensus || "";
    const tens = syn.tension_text || syn.tension || "";

    // X-optimized 16:9 (1600x900) two-column landscape card
    if (!isVertical) {
      const W = 1600;
      const H = 900;
      const PAD = 54;
      const INNER = W - PAD * 2;
      const canvas = document.createElement("canvas");
      canvas.width = W;
      canvas.height = H;
      canvas.style.width = "100%";
      canvas.style.height = "auto";
      const ctx = canvas.getContext("2d");

      ctx.fillStyle = C.bg;
      ctx.fillRect(0, 0, W, H);

      // Top brand bar
      ctx.fillStyle = C.accent;
      ctx.font = `800 22px ${FONT}`;
      ctx.fillText("CCagent", PAD, PAD + 22);
      ctx.fillStyle = C.muted;
      ctx.font = `600 19px ${FONT}`;
      ctx.fillText(`·  ${modelTitle}`, PAD + 106, PAD + 22);
      const dw = ctx.measureText(dateStr).width;
      ctx.fillText(dateStr, W - PAD - dw, PAD + 22);

      // Big Title (1 line, high legibility on X)
      ctx.fillStyle = C.text;
      ctx.font = `800 42px ${FONT}`;
      const tLines = wrapCanvasText(ctx, res.title || "智囊团深度分析", INNER, 1);
      ctx.fillText(tLines[0] || "", PAD, PAD + 78);

      // Summary highlight bar
      const sumY = PAD + 98;
      const sumH = 74;
      roundRectPath(ctx, PAD, sumY, INNER, sumH, 12);
      ctx.fillStyle = C.summaryBg;
      ctx.fill();
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      roundRectPath(ctx, PAD, sumY, 6, sumH, 3);
      ctx.fillStyle = C.accent;
      ctx.fill();
      ctx.fillStyle = C.text;
      ctx.font = `600 22px ${FONT}`;
      const sumLines = wrapCanvasText(ctx, res.summary || "", INNER - 44, 2);
      const sumStartY = sumLines.length === 1 ? sumY + 45 : sumY + 32;
      sumLines.forEach((ln, idx) => ctx.fillText(ln, PAD + 24, sumStartY + idx * 29));

      // Two-column body
      const bodyY = sumY + sumH + 26;
      const bodyH = H - bodyY - 62;
      const GAP = 28;
      const leftW = Math.floor((INNER - GAP) * 0.48);
      const rightW = INNER - GAP - leftW;
      const rightX = PAD + leftW + GAP;

      // Left column: 3 Pillars + Consensus/Tension
      ctx.fillStyle = C.muted;
      ctx.font = `700 17px ${FONT}`;
      ctx.fillText("核心支柱", PAD, bodyY + 16);
      const pTop = bodyY + 28;
      const hasSyn = Boolean(cons || tens);
      const synH = hasSyn ? 124 : 0;
      const pAvailH = bodyH - 28 - (hasSyn ? synH + 14 : 0);
      const pGap = 12;
      const pCardH = pillars.length ? Math.floor((pAvailH - pGap * (pillars.length - 1)) / pillars.length) : 0;

      pillars.forEach((p, idx) => {
        const py = pTop + idx * (pCardH + pGap);
        roundRectPath(ctx, PAD, py, leftW, pCardH, 12);
        ctx.fillStyle = C.card;
        ctx.fill();
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = C.accent;
        ctx.font = `700 19px ${FONT}`;
        ctx.fillText(wrapCanvasText(ctx, p.label || "", leftW - 36, 1)[0] || "", PAD + 18, py + 32);
        ctx.fillStyle = C.text;
        ctx.font = `400 19px ${FONT}`;
        const vLines = wrapCanvasText(ctx, p.value || p.content || "", leftW - 36, 3);
        vLines.forEach((ln, li) => ctx.fillText(ln, PAD + 18, py + 62 + li * 26));
      });

      if (hasSyn) {
        const sy = bodyY + bodyH - synH;
        roundRectPath(ctx, PAD, sy, leftW, synH, 12);
        ctx.fillStyle = C.accentBg;
        ctx.fill();
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 1.5;
        ctx.stroke();
        ctx.fillStyle = C.accent;
        ctx.font = `700 18px ${FONT}`;
        const synLabel = tens ? "合议共识 & 关键张力" : "合议共识";
        ctx.fillText(synLabel, PAD + 18, sy + 30);
        ctx.fillStyle = C.text;
        ctx.font = `400 18px ${FONT}`;
        const synText = tens ? `${cons} ｜ 张力：${tens}` : cons;
        const sLines = wrapCanvasText(ctx, synText, leftW - 36, 3);
        sLines.forEach((ln, li) => ctx.fillText(ln, PAD + 18, sy + 58 + li * 25));
      }

      // Right column: 4 Council Notes
      ctx.fillStyle = C.muted;
      ctx.font = `700 17px ${FONT}`;
      ctx.fillText("智囊团 4 个分析视角", rightX, bodyY + 16);
      const nTop = bodyY + 28;
      const nGap = 12;
      const nAvailH = bodyH - 28;
      const nCardH = notes.length ? Math.floor((nAvailH - nGap * (notes.length - 1)) / notes.length) : 0;

      notes.forEach((n, idx) => {
        const ny = nTop + idx * (nCardH + nGap);
        const st = C.stance[n.stance] || { bg: C.pillBg, fg: C.muted, label: n.stance || "观点" };
        roundRectPath(ctx, rightX, ny, rightW, nCardH, 12);
        ctx.fillStyle = C.card;
        ctx.fill();
        ctx.strokeStyle = C.border;
        ctx.lineWidth = 1.5;
        ctx.stroke();

        ctx.fillStyle = C.text;
        ctx.font = `700 20px ${FONT}`;
        ctx.fillText(n.name || "视角", rightX + 18, ny + 32);

        ctx.font = `700 15px ${FONT}`;
        const bw = ctx.measureText(st.label).width + 22;
        roundRectPath(ctx, rightX + rightW - 18 - bw, ny + 12, bw, 28, 14);
        ctx.fillStyle = st.bg;
        ctx.fill();
        ctx.fillStyle = st.fg;
        ctx.fillText(st.label, rightX + rightW - 18 - bw + 11, ny + 31);

        ctx.fillStyle = C.text;
        ctx.font = `400 18.5px ${FONT}`;
        const vLines = wrapCanvasText(ctx, n.verdict || n.note || "", rightW - 36, 3);
        vLines.forEach((ln, li) => ctx.fillText(ln, rightX + 18, ny + 62 + li * 25));
      });

      // Footer
      ctx.fillStyle = C.muted;
      ctx.font = `600 16px ${FONT}`;
      ctx.fillText("Generated by CCagent · ccagent.mycici.top", PAD, H - 24);
      return canvas;
    }

    // 4:5 (1200x1500) X-safe vertical card
    const W = 1200;
    const H = 1500;
    const PAD = 56;
    const INNER = W - PAD * 2;
    const canvas = document.createElement("canvas");
    canvas.width = W;
    canvas.height = H;
    canvas.style.width = "100%";
    canvas.style.height = "auto";
    const ctx = canvas.getContext("2d");

    ctx.fillStyle = C.bg;
    ctx.fillRect(0, 0, W, H);

    let y = PAD;
    ctx.fillStyle = C.accent;
    ctx.font = `800 24px ${FONT}`;
    ctx.fillText("CCagent", PAD, y + 24);
    ctx.fillStyle = C.muted;
    ctx.font = `600 20px ${FONT}`;
    ctx.fillText(`·  ${modelTitle}`, PAD + 112, y + 24);
    const dw = ctx.measureText(dateStr).width;
    ctx.fillText(dateStr, W - PAD - dw, y + 24);
    y += 50;

    ctx.fillStyle = C.text;
    ctx.font = `800 44px ${FONT}`;
    const titleLines = wrapCanvasText(ctx, res.title || "智囊团深度分析", INNER, 2);
    titleLines.forEach((ln, idx) => ctx.fillText(ln, PAD, y + 42 + idx * 56));
    y += titleLines.length * 56 + 22;

    if (res.summary) {
      ctx.font = `600 24px ${FONT}`;
      const sumLines = wrapCanvasText(ctx, res.summary, INNER - 48, 3);
      const boxH = sumLines.length * 36 + 36;
      roundRectPath(ctx, PAD, y, INNER, boxH, 14);
      ctx.fillStyle = C.summaryBg;
      ctx.fill();
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      roundRectPath(ctx, PAD, y, 7, boxH, 3);
      ctx.fillStyle = C.accent;
      ctx.fill();
      ctx.fillStyle = C.text;
      sumLines.forEach((ln, idx) => ctx.fillText(ln, PAD + 26, y + 40 + idx * 36));
      y += boxH + 28;
    }

    ctx.fillStyle = C.muted;
    ctx.font = `700 18px ${FONT}`;
    ctx.fillText("核心支柱", PAD, y + 18);
    y += 32;
    pillars.forEach((p) => {
      const pH = 112;
      roundRectPath(ctx, PAD, y, INNER, pH, 12);
      ctx.fillStyle = C.card;
      ctx.fill();
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = C.accent;
      ctx.font = `700 21px ${FONT}`;
      ctx.fillText(wrapCanvasText(ctx, p.label || "", INNER - 40, 1)[0] || "", PAD + 20, y + 36);
      ctx.fillStyle = C.text;
      ctx.font = `400 21px ${FONT}`;
      const vLines = wrapCanvasText(ctx, p.value || p.content || "", INNER - 40, 2);
      vLines.forEach((ln, idx) => ctx.fillText(ln, PAD + 20, y + 68 + idx * 30));
      y += pH + 14;
    });

    y += 12;
    ctx.fillStyle = C.muted;
    ctx.font = `700 18px ${FONT}`;
    ctx.fillText("智囊团 4 个分析视角", PAD, y + 18);
    y += 32;
    notes.forEach((n) => {
      const st = C.stance[n.stance] || { bg: C.pillBg, fg: C.muted, label: n.stance || "观点" };
      const nH = 116;
      roundRectPath(ctx, PAD, y, INNER, nH, 12);
      ctx.fillStyle = C.card;
      ctx.fill();
      ctx.strokeStyle = C.border;
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = C.text;
      ctx.font = `700 21px ${FONT}`;
      ctx.fillText(n.name || "视角", PAD + 20, y + 36);
      ctx.font = `700 16px ${FONT}`;
      const bw = ctx.measureText(st.label).width + 24;
      roundRectPath(ctx, W - PAD - 20 - bw, y + 14, bw, 30, 15);
      ctx.fillStyle = st.bg;
      ctx.fill();
      ctx.fillStyle = st.fg;
      ctx.fillText(st.label, W - PAD - 20 - bw + 12, y + 35);
      ctx.fillStyle = C.text;
      ctx.font = `400 20px ${FONT}`;
      const vLines = wrapCanvasText(ctx, n.verdict || n.note || "", INNER - 40, 2);
      vLines.forEach((ln, idx) => ctx.fillText(ln, PAD + 20, y + 68 + idx * 29));
      y += nH + 12;
    });

    ctx.fillStyle = C.muted;
    ctx.font = `600 18px ${FONT}`;
    ctx.fillText("Generated by CCagent · ccagent.mycici.top", PAD, H - 28);
    return canvas;
  }

  function initShareCard() {
    const copyBtn = $("btn-copy-md");
    if (!copyBtn || $("btn-share-card")) return;

    const btn = document.createElement("button");
    btn.id = "btn-share-card";
    btn.type = "button";
    btn.className = "btn-secondary";
    btn.textContent = "生成分享卡片";
    copyBtn.parentNode.insertBefore(btn, copyBtn);

    const modal = document.createElement("div");
    modal.id = "modal-share-card";
    modal.className = "modal-backdrop hidden";
    modal.innerHTML = `
      <div class="modal share-card-modal">
        <div class="modal-header">
          <h3>分享卡片预览</h3>
          <div class="share-theme-switch">
            <button type="button" class="btn-ghost share-ratio-btn share-theme-btn active" data-ratio="16:9">16:9 横图</button>
            <button type="button" class="btn-ghost share-ratio-btn share-theme-btn" data-ratio="4:5">4:5 竖图</button>
            <button type="button" class="btn-ghost share-color-btn share-theme-btn active" data-theme="light">纸感浅色</button>
            <button type="button" class="btn-ghost share-color-btn share-theme-btn" data-theme="dark">深色极客</button>
            <button type="button" class="btn-ghost" id="btn-close-share">关闭</button>
          </div>
        </div>
        <div class="modal-body share-card-body">
          <div id="share-card-preview"></div>
        </div>
        <div class="share-card-footer">
          <span id="share-card-status" class="muted"></span>
          <div class="share-card-actions">
            <button type="button" class="btn-secondary" id="btn-share-copy-img">复制图片</button>
            <button type="button" class="btn-primary" id="btn-share-dl-img">下载 PNG</button>
          </div>
        </div>
      </div>
    `;
    document.body.appendChild(modal);

    let currentTheme = "light";
    let currentRatio = "16:9";
    let currentCanvas = null;

    const redraw = () => {
      if (!state.currentResult) return;
      currentCanvas = renderShareCardCanvas(state.currentResult, currentTheme, currentRatio);
      const box = $("share-card-preview");
      box.innerHTML = "";
      box.appendChild(currentCanvas);
      $("share-card-status").textContent = "";
    };

    btn.addEventListener("click", () => {
      if (!state.currentResult) return;
      redraw();
      modal.classList.remove("hidden");
    });

    $("btn-close-share").addEventListener("click", () => modal.classList.add("hidden"));
    modal.addEventListener("click", (e) => { if (e.target === modal) modal.classList.add("hidden"); });

    modal.querySelectorAll(".share-ratio-btn").forEach((rb) => {
      rb.addEventListener("click", () => {
        currentRatio = rb.getAttribute("data-ratio") || "16:9";
        modal.querySelectorAll(".share-ratio-btn").forEach((x) => x.classList.toggle("active", x === rb));
        redraw();
      });
    });

    modal.querySelectorAll(".share-color-btn").forEach((tb) => {
      tb.addEventListener("click", () => {
        currentTheme = tb.getAttribute("data-theme") || "light";
        modal.querySelectorAll(".share-color-btn").forEach((x) => x.classList.toggle("active", x === tb));
        redraw();
      });
    });

    $("btn-share-dl-img").addEventListener("click", () => {
      if (!currentCanvas) return;
      const a = document.createElement("a");
      const safeTitle = (state.currentResult.title || "analysis").replace(/[\\/:*?"<>|]/g, "_").slice(0, 32);
      a.download = `CCagent-${safeTitle}.png`;
      a.href = currentCanvas.toDataURL("image/png");
      a.click();
      $("share-card-status").textContent = "已下载 PNG";
    });

    window.addEventListener("message", (e) => {
      const msg = e.data;
      if (!msg || msg.type !== "CCAGENT_COPY_IMAGE_RESULT") return;
      const st = $("share-card-status");
      if (!st) return;
      st.textContent = msg.ok ? "已复制图片，可直接 Ctrl+V 粘贴到 X" : "复制失败，请点击下载 PNG";
    });

    $("btn-share-copy-img").addEventListener("click", async () => {
      if (!currentCanvas) return;
      const st = $("share-card-status");
      if (navigator.clipboard && typeof ClipboardItem !== "undefined") {
        try {
          const blob = await new Promise((resolve) => currentCanvas.toBlob(resolve, "image/png"));
          await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
          st.textContent = "已复制图片，可直接 Ctrl+V 粘贴到 X";
          return;
        } catch (_) {}
      }
      if (window.parent && window.parent !== window) {
        st.textContent = "正在复制…";
        try {
          window.parent.postMessage({ type: "CCAGENT_COPY_IMAGE", dataUrl: currentCanvas.toDataURL("image/png") }, "*");
          return;
        } catch (_) {}
      }
      st.textContent = "当前环境不支持直接复制图片，请点击下载 PNG";
    });
  }

  function runDirectGenerate(rawText, images) {
    const raw = (rawText || $("raw-input").value || "").trim();
    if (!raw) return;
    state.rawText = raw;
    state.fields = {};
    state.images = Array.isArray(images) ? images.slice(0, 2) : [];
    $("raw-input").value = raw;
    $("desc-preview").textContent = raw.length > 60 ? raw.slice(0, 60) + "…" : raw;
    $("input-expanded").classList.add("hidden");
    $("input-collapsed").classList.remove("hidden");
    $("refine-section").classList.add("hidden");
    handleGenerate();
  }

  window.addEventListener("ccagent:direct-generate", (e) => {
    const raw = (e.detail && e.detail.text) || "";
    const imgs = (e.detail && e.detail.images) || [];
    runDirectGenerate(raw, imgs);
  });

  window.__THINKING_TEST__ = { esc, renderResult, buildMarkdown, renderForm, openHistory, state };

  init();
})();
