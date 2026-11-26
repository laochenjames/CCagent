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

  const DEFAULT_HOST = "https://ccagent.mycici.top";
  const $ = (id) => document.getElementById(id);

  let state = {
    host: DEFAULT_HOST,
    agentId: "agent4",
    byok: { provider: "xai", model: "", api_key: "" },
    autoExtract: false,
    iframeReady: false,
    queuedPrefill: null,
  };

  function agentUrl(agentId) {
    const base = (state.host || DEFAULT_HOST).replace(/\/+$/, "");
    return base + (AGENT_PATHS[agentId] || "/agent4/");
  }

  function postToFrame(msg) {
    const frame = $("agent-frame");
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
        autoExtract:
          state.queuedPrefill.autoExtract !== undefined
            ? state.queuedPrefill.autoExtract
            : state.autoExtract,
      });
      state.queuedPrefill = null;
    }
  }

  function loadAgent(agentId, prefillPayload) {
    const targetId = AGENT_PATHS[agentId] ? agentId : "agent4";
    const sameAgent = state.agentId === targetId && state.iframeReady && $("agent-frame").src === agentUrl(targetId);
    state.agentId = targetId;
    $("agent-select").value = targetId;
    chrome.storage.local.set({ lastAgentId: targetId });

    if (prefillPayload && prefillPayload.text) {
      state.queuedPrefill = prefillPayload;
    }

    if (sameAgent) {
      flushToFrame();
    } else {
      state.iframeReady = false;
      $("agent-frame").src = agentUrl(targetId);
    }
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
      state.iframeReady = true;
      flushToFrame();
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

  init();
})();
