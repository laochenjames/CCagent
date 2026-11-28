(function () {
  const AGENT_PATHS = {
    agent1: "/",
    agent2: "/agent2/",
    agent3: "/agent3/",
    agent4: "/agent4/",
    agent5: "/agent5/",
    agent6: "/agent6/",
    agent7: "/agent7/",
    agent8: "/agent8/",
    agent9: "/agent9/",
    agent10: "/agent10/",
  };

  const AGENT_LABELS = {
    agent1: "职业投入体检",
    agent2: "个人任务分诊",
    agent3: "原子习惯生成",
    agent4: "第一性原理",
    agent5: "辩证抽象",
    agent6: "一法多解",
    agent7: "双轨分析",
    agent8: "反向思考",
    agent9: "激励机制诊断",
    agent10: "Lollapalooza",
  };

  const DEFAULT_HOST = "https://ccagent.mycici.top";
  const $ = (id) => document.getElementById(id);

  let state = {
    host: DEFAULT_HOST,
    agentId: "auto",
    activeFrameId: "",
    byok: { provider: "xai", model: "", api_key: "" },
    autoExtract: false,
    queuedPrefill: null,
    lastRoutedText: "",
    lastAltAgent: "",
  };

  const MAX_CACHED_FRAMES = 5;
  const framePool = new Map(); // agentId -> { el, ready, lastUsed }

  function getActiveFrame() {
    const entry = framePool.get(state.activeFrameId);
    return entry ? entry.el : $("agent-frame");
  }

  function hideAllFrames() {
    const baseFrame = $("agent-frame");
    if (baseFrame) baseFrame.classList.add("hidden");
    framePool.forEach((entry) => entry.el.classList.add("hidden"));
  }

  function clearFramePool() {
    framePool.forEach((entry) => {
      if (entry.el && entry.el.parentNode) entry.el.parentNode.removeChild(entry.el);
    });
    framePool.clear();
    state.activeFrameId = "";
  }

  function evictOldFrames(keepId) {
    while (framePool.size > MAX_CACHED_FRAMES) {
      let oldestId = null;
      let oldestTs = Infinity;
      framePool.forEach((entry, id) => {
        if (id !== keepId && entry.lastUsed < oldestTs) {
          oldestTs = entry.lastUsed;
          oldestId = id;
        }
      });
      if (!oldestId) break;
      const victim = framePool.get(oldestId);
      if (victim && victim.el && victim.el.parentNode) {
        victim.el.parentNode.removeChild(victim.el);
      }
      framePool.delete(oldestId);
    }
  }

  function showLoadingBar(show, label) {
    let bar = $("sp-loading-bar");
    if (!bar) {
      bar = document.createElement("div");
      bar.id = "sp-loading-bar";
      bar.className = "sp-loading-bar hidden";
      const main = document.querySelector(".sp-main");
      if (main) main.appendChild(bar);
    }
    if (show) {
      bar.textContent = label ? `正在加载「${label}」…` : "正在加载…";
      bar.classList.remove("hidden");
    } else {
      bar.classList.add("hidden");
    }
  }

  function agentUrl(agentId) {
    const base = (state.host || DEFAULT_HOST).replace(/\/+$/, "");
    return base + (AGENT_PATHS[agentId] || "/agent4/");
  }

  function postToFrame(msg) {
    const frame = getActiveFrame();
    if (!frame || !frame.contentWindow) return;
    try {
      frame.contentWindow.postMessage(msg, "*");
    } catch (_) {}
  }

  function flushToFrame() {
    if (state.byok && state.byok.api_key) {
      postToFrame({ type: "CCAGENT_SYNC_BYOK", byok: state.byok });
    }
    if (state.queuedPrefill && state.queuedPrefill.text) {
      postToFrame({
        type: "CCAGENT_PREFILL",
        text: state.queuedPrefill.text,
        images: Array.isArray(state.queuedPrefill.images) ? state.queuedPrefill.images.slice(0, 2) : [],
        directGenerate:
          state.queuedPrefill.directGenerate !== undefined
            ? state.queuedPrefill.directGenerate
            : true,
        autoExtract:
          state.queuedPrefill.autoExtract !== undefined
            ? state.queuedPrefill.autoExtract
            : state.autoExtract,
      });
      state.queuedPrefill = null;
    }
  }

  function showRouteBanner(text) {
    $("route-banner-text").textContent = text;
    $("btn-route-alt").classList.add("hidden");
    $("route-banner").classList.remove("hidden");
  }

  async function routeAndLoad(text, extraPayload) {
    const clean = (text || "").trim();
    if (!clean) return;
    state.lastRoutedText = clean;
    showRouteBanner("✨ 智能路由判断中…");

    const base = (state.host || DEFAULT_HOST).replace(/\/+$/, "");
    let target = "agent7";
    let reason = "已自动匹配最合适的思维模型。";

    try {
      const ctrl = new AbortController();
      const timer = setTimeout(() => ctrl.abort(), 6000);
      const body = { text: clean };
      if (state.byok && state.byok.api_key) {
        body.provider = state.byok.provider;
        body.model = state.byok.model;
        body.api_key = state.byok.api_key;
      }
      const res = await fetch(`${base}/api/route`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: ctrl.signal,
      });
      clearTimeout(timer);
      if (res.ok) {
        const data = await res.json();
        if (data.primary && AGENT_PATHS[data.primary]) target = data.primary;
        if (data.reason) reason = data.reason;
      }
    } catch (_) {}

    const label = AGENT_LABELS[target] || target;
    showRouteBanner(`✨ 已自动选定「${label}」并开始深度推演：${reason}`);
    loadAgent(target, { ...(extraPayload || {}), agentId: target, text: clean, directGenerate: true }, true);
  }

  function loadAgent(agentId, prefillPayload, keepAutoMode) {
    if (agentId === "auto") {
      state.agentId = "auto";
      $("agent-select").value = "auto";
      chrome.storage.local.set({ lastAgentId: "auto" });
      if (prefillPayload && prefillPayload.text) {
        routeAndLoad(prefillPayload.text, prefillPayload);
        return;
      }
      hideAllFrames();
      showLoadingBar(false);
      $("auto-panel").classList.remove("hidden");
      return;
    }

    $("auto-panel").classList.add("hidden");

    const targetId = AGENT_PATHS[agentId] ? agentId : "agent4";
    const targetUrl = agentUrl(targetId);
    state.agentId = keepAutoMode ? "auto" : targetId;
    state.activeFrameId = targetId;
    $("agent-select").value = keepAutoMode ? "auto" : targetId;
    chrome.storage.local.set({ lastAgentId: state.agentId });

    if (prefillPayload && prefillPayload.text) {
      state.queuedPrefill = prefillPayload;
    }

    hideAllFrames();

    let entry = framePool.get(targetId);
    if (entry && entry.el.src === targetUrl) {
      entry.lastUsed = Date.now();
      entry.el.classList.remove("hidden");
      showLoadingBar(!entry.ready, AGENT_LABELS[targetId]);
      if (entry.ready) {
        flushToFrame();
      }
      return;
    }

    if (entry && entry.el && entry.el.parentNode) {
      entry.el.parentNode.removeChild(entry.el);
      framePool.delete(targetId);
    }

    const iframe = document.createElement("iframe");
    iframe.className = "sp-agent-frame";
    iframe.title = AGENT_LABELS[targetId] || targetId;
    iframe.setAttribute("allow", "clipboard-write");
    iframe.dataset.agentId = targetId;
    const main = document.querySelector(".sp-main");
    if (main) main.appendChild(iframe);

    entry = { el: iframe, ready: false, lastUsed: Date.now() };
    framePool.set(targetId, entry);
    evictOldFrames(targetId);

    showLoadingBar(true, AGENT_LABELS[targetId]);
    iframe.addEventListener("load", () => {
      entry.ready = true;
      if (state.activeFrameId === targetId) {
        showLoadingBar(false);
        flushToFrame();
      }
    });
    iframe.src = targetUrl;
  }

  function renderClipTray(items) {
    const list = $("clip-list");
    const badge = $("clip-count");
    const arr = Array.isArray(items) ? items : [];
    badge.textContent = String(arr.length);
    badge.classList.toggle("hidden", arr.length === 0);

    list.innerHTML = "";
    if (!arr.length) {
      list.innerHTML = '<div class="sp-clip-empty">暂无暂存素材。在网页右键选择「追加到暂存篮」，或在 X 推文上按住 Shift 点击 CC 按钮。</div>';
      return;
    }
    arr.forEach((item, idx) => {
      const row = document.createElement("div");
      row.className = "sp-clip-item";
      const txt = document.createElement("div");
      txt.className = "sp-clip-text";
      txt.textContent = `${idx + 1}. ${item.text}`;
      const del = document.createElement("button");
      del.className = "sp-clip-del";
      del.textContent = "×";
      del.title = "删除";
      del.addEventListener("click", async () => {
        const { clipTray = [] } = await chrome.storage.local.get("clipTray");
        const next = clipTray.filter((c) => c.id !== item.id);
        await chrome.storage.local.set({ clipTray: next });
        renderClipTray(next);
      });
      row.appendChild(txt);
      row.appendChild(del);
      list.appendChild(row);
    });
  }

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (msg && msg.type === "CCAGENT_IFRAME_READY") {
      framePool.forEach((entry, id) => {
        if (entry.el.contentWindow === event.source) {
          entry.ready = true;
          if (state.activeFrameId === id) {
            showLoadingBar(false);
            flushToFrame();
          }
        }
      });
    }
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "CCAGENT_NEW_PAYLOAD" && msg.payload) {
      loadAgent(msg.payload.agentId || state.agentId, msg.payload);
      chrome.storage.local.remove("pendingPayload");
    } else if (msg.type === "CCAGENT_CLIP_UPDATED") {
      renderClipTray(msg.clipTray || []);
      $("clip-drawer").classList.remove("hidden");
    }
  });

  $("agent-select").addEventListener("change", (e) => {
    loadAgent(e.target.value, null);
  });

  $("btn-open-tab").addEventListener("click", () => {
    chrome.tabs.create({ url: agentUrl(state.agentId) });
  });

  $("btn-clip").addEventListener("click", async () => {
    $("settings-drawer").classList.add("hidden");
    $("clip-drawer").classList.toggle("hidden");
    const { clipTray = [] } = await chrome.storage.local.get("clipTray");
    renderClipTray(clipTray);
  });

  $("btn-clip-clear").addEventListener("click", async () => {
    await chrome.storage.local.set({ clipTray: [] });
    renderClipTray([]);
  });

  $("btn-clip-send").addEventListener("click", async () => {
    const { clipTray = [] } = await chrome.storage.local.get("clipTray");
    if (!clipTray.length) return;
    const merged = clipTray.map((c, i) => `【素材 ${i + 1}】\n${c.text}`).join("\n\n");
    $("clip-drawer").classList.add("hidden");
    loadAgent("agent6", { agentId: "agent6", text: merged });
  });

  $("btn-settings").addEventListener("click", () => {
    $("clip-drawer").classList.add("hidden");
    $("settings-drawer").classList.toggle("hidden");
  });

  $("btn-settings-close").addEventListener("click", () => {
    $("settings-drawer").classList.add("hidden");
  });

  $("btn-route-close").addEventListener("click", () => {
    $("route-banner").classList.add("hidden");
  });

  $("btn-route-alt").addEventListener("click", () => {
    if (!state.lastAltAgent) return;
    const alt = state.lastAltAgent;
    showRouteBanner(`✨ 已切换至备选模型「${AGENT_LABELS[alt] || alt}」`, "");
    loadAgent(alt, state.lastRoutedText ? { text: state.lastRoutedText } : null, state.agentId === "auto");
  });

  $("btn-auto-go").addEventListener("click", () => {
    const txt = ($("auto-input").value || "").trim();
    if (!txt) return;
    routeAndLoad(txt, {});
  });

  $("btn-guide").addEventListener("click", () => {
    $("clip-drawer").classList.add("hidden");
    $("settings-drawer").classList.add("hidden");
    $("guide-modal").classList.remove("hidden");
  });

  $("btn-guide-close").addEventListener("click", () => {
    $("guide-modal").classList.add("hidden");
  });

  $("guide-modal").addEventListener("click", (e) => {
    if (e.target === $("guide-modal")) {
      $("guide-modal").classList.add("hidden");
    }
  });

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape") {
      $("guide-modal").classList.add("hidden");
    }
  });

  document.querySelectorAll(".sp-agent-jump").forEach((btn) => {
    btn.addEventListener("click", () => {
      const target = btn.getAttribute("data-agent");
      if (target) loadAgent(target, null);
      $("guide-modal").classList.add("hidden");
    });
  });

  $("btn-save-settings").addEventListener("click", async () => {
    const host = ($("cfg-host").value || "").trim() || DEFAULT_HOST;
    const provider = $("cfg-provider").value || "xai";
    const model = ($("cfg-model").value || "").trim();
    const api_key = ($("cfg-key").value || "").trim();
    const autoExtract = $("cfg-auto-extract").checked;

    const hostChanged = host !== state.host;
    state.host = host;
    state.byok = { provider, model, api_key };
    state.autoExtract = autoExtract;

    await chrome.storage.local.set({
      ccHost: host,
      ccByok: state.byok,
      ccAutoExtract: autoExtract,
    });

    postToFrame({ type: "CCAGENT_SYNC_BYOK", byok: state.byok });
    if (hostChanged) {
      clearFramePool();
      loadAgent(state.agentId, null);
    }
    $("cfg-status").textContent = "已保存并同步到当前 Agent";
    setTimeout(() => {
      $("cfg-status").textContent = "";
    }, 2000);
  });

  async function init() {
    const data = await chrome.storage.local.get([
      "ccHost",
      "ccByok",
      "ccAutoExtract",
      "lastAgentId",
      "pendingPayload",
      "clipTray",
    ]);
    state.host = data.ccHost || DEFAULT_HOST;
    state.byok = data.ccByok || { provider: "xai", model: "", api_key: "" };
    state.autoExtract = Boolean(data.ccAutoExtract);
    state.agentId = data.lastAgentId || "agent4";

    $("cfg-host").value = state.host;
    $("cfg-provider").value = state.byok.provider || "xai";
    $("cfg-model").value = state.byok.model || "";
    $("cfg-key").value = state.byok.api_key || "";
    $("cfg-auto-extract").checked = state.autoExtract;
    renderClipTray(data.clipTray || []);

    const pending = data.pendingPayload;
    if (pending && Date.now() - (pending.ts || 0) < 30000) {
      await chrome.storage.local.remove("pendingPayload");
      loadAgent(pending.agentId || state.agentId, pending);
    } else {
      loadAgent(state.agentId, null);
    }
  }

  window.addEventListener("message", async (e) => {
    const msg = e.data;
    if (!msg || msg.type !== "CCAGENT_COPY_IMAGE" || !msg.dataUrl) return;
    let ok = false;
    try {
      const resp = await fetch(msg.dataUrl);
      const blob = await resp.blob();
      await navigator.clipboard.write([new ClipboardItem({ "image/png": blob })]);
      ok = true;
    } catch (_) {
      ok = false;
    }
    postToFrame({ type: "CCAGENT_COPY_IMAGE_RESULT", ok });
  });

  init();
})();
