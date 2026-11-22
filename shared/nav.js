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

  // Inject responsive horizontal-scroll support for narrow screens
  if (!document.getElementById("cc-shared-nav-style")) {
    const st = document.createElement("style");
    st.id = "cc-shared-nav-style";
    st.textContent =
      ".agent-nav{flex-wrap:nowrap;overflow-x:auto;-webkit-overflow-scrolling:touch;scrollbar-width:none;max-width:100%;}" +
      ".agent-nav::-webkit-scrollbar{display:none;}" +
      ".agent-nav-link{flex-shrink:0;white-space:nowrap;}";
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

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderNav);
  } else {
    renderNav();
  }
})();
