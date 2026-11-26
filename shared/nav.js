(function () {
  const NAV_ITEMS = [
    { href: "/", label: "职业投入体检" },
    { href: "/agent2/", label: "个人任务分诊" },
    { href: "/agent3/", label: "原子习惯生成" },
    { href: "/agent4/", label: "第一性原理" },
    { href: "/agent5/", label: "辩证抽象" },
    { href: "/agent6/", label: "一法多解" },
    { href: "/agent7/", label: "双轨分析" },
    { href: "/agent8/", label: "反向思考" },
    { href: "/agent9/", label: "激励机制" },
    { href: "/agent10/", label: "Lollapalooza" },
  ];

  const isEmbedded = window.self !== window.top;

  // Inject responsive horizontal-scroll support (and compact mode when embedded in Side Panel)
  if (!document.getElementById("cc-shared-nav-style")) {
    const st = document.createElement("style");
    st.id = "cc-shared-nav-style";
    const embeddedCss = isEmbedded
      ? ".agent-nav{display:none !important;}" +
        ".topbar,.header{padding:8px 10px !important;gap:6px !important;}" +
        ".topbar-left{gap:6px !important;min-width:0;}" +
        ".brand{font-size:14px !important;white-space:nowrap;}" +
        ".engine-badge{display:none !important;}" +
        ".top-actions{gap:4px !important;flex-wrap:wrap;}" +
        ".top-actions .btn-ghost,.top-actions button{padding:4px 8px !important;font-size:12px !important;white-space:nowrap;}" +
        ".container,main{margin:10px auto !important;padding:0 10px 28px !important;}" +
        ".card{padding:12px !important;margin-bottom:10px !important;}" +
        "textarea{font-size:13.5px !important;padding:8px 10px !important;}" +
        ".input-footer,.refine-footer,.result-actions,.section-header{flex-direction:column !important;align-items:stretch !important;gap:8px !important;}" +
        ".input-footer .btn-primary,.refine-footer .btn-primary,.refine-actions .btn-primary{width:100% !important;text-align:center;}" +
        ".refine-actions{display:flex;flex-direction:column;gap:6px;width:100%;}" +
        ".examples{gap:5px !important;}" +
        ".chip{font-size:11.5px !important;padding:3px 8px !important;}" +
        ".form-groups,.council-synthesis,.grid-2{grid-template-columns:1fr !important;}" +
        ".modal{width:calc(100vw - 20px) !important;max-width:none !important;}"
      : "";
    st.textContent =
      ".agent-nav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;max-width:100%;}" +
      ".agent-nav::-webkit-scrollbar{display:none;}" +
      ".agent-nav-link{flex-shrink:0;white-space:nowrap;}" +
      embeddedCss;
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
