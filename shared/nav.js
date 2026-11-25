(function () {
  const NAV_ITEMS = [
    { href: "/", label: "职业投入体检" },
    { href: "/agent2/", label: "个人任务分诊" },
    { href: "/agent3/", label: "原子习惯生成" },
    { href: "/agent4/", label: "第一性原理" },
    { href: "/agent5/", label: "辩证抽象" },
    { href: "/agent6/", label: "一法多解" },
    { href: "/agent7/", label: "双轨思维" },
  ];

  const isEmbedded = window.self !== window.top;

  // Inject responsive horizontal-scroll support (and compact mode when embedded in Side Panel)
  if (!document.getElementById("cc-shared-nav-style")) {
    const st = document.createElement("style");
    st.id = "cc-shared-nav-style";
    st.textContent =
      ".agent-nav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;max-width:100%;}" +
      ".agent-nav::-webkit-scrollbar{display:none;}" +
      ".agent-nav-link{flex-shrink:0;white-space:nowrap;}" +
      (isEmbedded ? ".agent-nav{display:none !important;}" : "");
    document.head.appendChild(st);
  }

  function renderNav() {
    const nav = document.querySelector("nav.agent-nav");
    if (!nav) return;
    const p = window.location.pathname || "/";
    nav.innerHTML = "";
    NAV_ITEMS.forEach((item) => {
      const a = document.createElement("a");
      const isActive =
        item.href === "/"
          ? p === "/" || p === "/index.html"
          : p === item.href.slice(0, -1) || p.startsWith(item.href);
      a.className = "agent-nav-link" + (isActive ? " active" : "");
      a.href = item.href;
      a.textContent = item.label;
      if (isActive) a.setAttribute("aria-current", "page");
      nav.appendChild(a);
    });
  }

  function applyPrefill(text, autoExtract) {
    if (!text) return false;
    const el =
      document.getElementById("raw-input") ||
      document.getElementById("task-raw-input") ||
      document.querySelector("textarea");
    if (!el) return false;
    el.value = text;
    el.dispatchEvent(new Event("input", { bubbles: true }));
    el.dispatchEvent(new Event("change", { bubbles: true }));
    el.focus();
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    if (autoExtract) {
      const btn =
        document.getElementById("btn-extract") ||
        document.getElementById("extract-btn");
      if (btn && !btn.disabled) {
        setTimeout(() => btn.click(), 120);
      }
    }
    return true;
  }

  function syncByok(byok) {
    if (!byok || typeof byok !== "object") return;
    const payload = JSON.stringify({
      provider: byok.provider || "xai",
      model: byok.model || "",
      api_key: byok.api_key || "",
      base_url: byok.base_url || "",
    });
    ["cc_byok", "ccagent_agent3_byok", "ccagent_shared_byok"].forEach((k) => {
      try {
        if (byok.api_key) {
          localStorage.setItem(k, payload);
        } else {
          localStorage.removeItem(k);
        }
      } catch (_) {}
    });
  }

  window.addEventListener("message", (event) => {
    const msg = event.data;
    if (!msg || typeof msg !== "object") return;
    if (msg.type === "CCAGENT_PREFILL") {
      applyPrefill(msg.text || "", Boolean(msg.autoExtract));
    } else if (msg.type === "CCAGENT_SYNC_BYOK") {
      syncByok(msg.byok);
    }
  });

  function onReady() {
    renderNav();
    if (isEmbedded) {
      try {
        window.parent.postMessage({ type: "CCAGENT_IFRAME_READY", path: window.location.pathname }, "*");
      } catch (_) {}
    }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", onReady);
  } else {
    onReady();
  }
})();
