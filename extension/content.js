(function () {
  const BTN_ATTR = "data-ccagent-injected";

  function extractTweet(article) {
    const textEls = article.querySelectorAll('[data-testid="tweetText"]');
    const text = textEls[0] ? textEls[0].innerText.trim() : "";
    const quoteText = textEls.length > 1 ? textEls[1].innerText.trim() : "";
    const userEl = article.querySelector('[data-testid="User-Name"]');
    const author = userEl ? userEl.innerText.replace(/\n+/g, " ").trim() : "";
    const timeLink = article.querySelector("time") && article.querySelector("time").closest("a");
    const url = timeLink ? timeLink.href : window.location.href;
    const images = [];
    const seen = new Set();
    article.querySelectorAll('[data-testid="tweetPhoto"] img, img[src*="pbs.twimg.com/media/"]').forEach((img) => {
      if (images.length >= 2) return;
      let src = (img.getAttribute("src") || "").trim();
      if (!src.startsWith("https://pbs.twimg.com/media/")) return;
      src = src.replace(/([?&]name=)(orig|large|4096x4096|small)/i, "$1medium");
      if (!seen.has(src)) {
        seen.add(src);
        images.push(src);
      }
    });
    const parts = [];
    if (author) parts.push(`作者：${author}`);
    if (text) parts.push(text);
    if (quoteText && quoteText !== text) parts.push(`【引用推文】\n${quoteText}`);
    if (url) parts.push(`链接：${url}`);
    return { formatted: parts.join("\n\n"), url, images };
  }

  function injectButtons() {
    const articles = document.querySelectorAll('article[data-testid="tweet"]');
    articles.forEach((article) => {
      if (article.getAttribute(BTN_ATTR)) return;
      const bar = article.querySelector('[role="group"]');
      if (!bar) return;
      article.setAttribute(BTN_ATTR, "1");

      const wrap = document.createElement("div");
      wrap.style.cssText = "display:inline-flex;align-items:center;margin-left:6px;";

      const btn = document.createElement("button");
      btn.type = "button";
      btn.textContent = "CC";
      btn.title = "发送到 CCagent 智囊团侧边栏（按住 Shift 追加到暂存篮）";
      btn.style.cssText =
        "border:1px solid rgba(154,52,18,0.35);background:rgba(250,247,242,0.92);" +
        "color:#9a3412;font-size:11px;font-weight:700;border-radius:999px;" +
        "padding:2px 8px;cursor:pointer;line-height:1.4;transition:all .15s;";

      btn.addEventListener("mouseenter", () => {
        btn.style.background = "#9a3412";
        btn.style.color = "#fff";
      });
      btn.addEventListener("mouseleave", () => {
        btn.style.background = "rgba(250,247,242,0.92)";
        btn.style.color = "#9a3412";
      });

      btn.addEventListener("click", (e) => {
        e.preventDefault();
        e.stopPropagation();
        const { formatted, url, images } = extractTweet(article);
        if (!formatted) return;
        const msgType = e.shiftKey ? "CCAGENT_TWEET_CLIP" : "CCAGENT_TWEET_SEND";
        chrome.runtime.sendMessage({ type: msgType, text: formatted, url, images });
        const oldText = btn.textContent;
        btn.textContent = e.shiftKey ? "已暂存" : "已发送";
        setTimeout(() => {
          btn.textContent = oldText;
        }, 1200);
      });

      wrap.appendChild(btn);
      bar.appendChild(wrap);
    });
  }

  injectButtons();
  const observer = new MutationObserver(() => injectButtons());
  observer.observe(document.body, { childList: true, subtree: true });
})();
