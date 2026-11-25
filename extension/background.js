const AGENTS = [
  { id: "agent4", path: "/agent4/", label: "第一性原理（马斯克）" },
  { id: "agent5", path: "/agent5/", label: "辩证抽象（矛盾论）" },
  { id: "agent6", path: "/agent6/", label: "一法多解（芒格）" },
  { id: "agent7", path: "/agent7/", label: "双轨分析（芒格）" },
  { id: "agent8", path: "/agent8/", label: "反向思考（事前验尸）" },
  { id: "agent9", path: "/agent9/", label: "激励机制诊断（芒格）" },
  { id: "agent10", path: "/agent10/", label: "Lollapalooza 共振雷达" },
  { id: "agent3", path: "/agent3/", label: "原子习惯生成" },
  { id: "agent2", path: "/agent2/", label: "个人任务分诊" },
  { id: "agent1", path: "/", label: "职业投入体检" },
];

function setupContextMenus() {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "ccagent-root",
      title: "发送到 CCagent 智囊团",
      contexts: ["selection"],
    });
    AGENTS.forEach((a) => {
      chrome.contextMenus.create({
        id: `ccagent-send-${a.id}`,
        parentId: "ccagent-root",
        title: a.label,
        contexts: ["selection"],
      });
    });
    chrome.contextMenus.create({
      id: "ccagent-sep",
      parentId: "ccagent-root",
      type: "separator",
      contexts: ["selection"],
    });
    chrome.contextMenus.create({
      id: "ccagent-clip",
      parentId: "ccagent-root",
      title: "＋ 追加到暂存篮（用于一法多解）",
      contexts: ["selection"],
    });
  });
}

chrome.runtime.onInstalled.addListener(() => {
  setupContextMenus();
  if (chrome.sidePanel && chrome.sidePanel.setPanelBehavior) {
    chrome.sidePanel.setPanelBehavior({ openPanelOnActionClick: true }).catch(() => {});
  }
});

async function dispatchToSidePanel(windowId, payload) {
  await chrome.storage.local.set({ pendingPayload: { ...payload, ts: Date.now() } });
  if (windowId && chrome.sidePanel && chrome.sidePanel.open) {
    try {
      await chrome.sidePanel.open({ windowId });
    } catch (_) {}
  }
  chrome.runtime.sendMessage({ type: "CCAGENT_NEW_PAYLOAD", payload }).catch(() => {});
}

async function addToClipTray(text, url, windowId) {
  const { clipTray = [] } = await chrome.storage.local.get("clipTray");
  clipTray.push({
    id: String(Date.now()),
    text: text.trim(),
    url: url || "",
  });
  await chrome.storage.local.set({ clipTray });
  if (windowId && chrome.sidePanel && chrome.sidePanel.open) {
    try {
      await chrome.sidePanel.open({ windowId });
    } catch (_) {}
  }
  chrome.runtime.sendMessage({ type: "CCAGENT_CLIP_UPDATED", clipTray }).catch(() => {});
}

chrome.contextMenus.onClicked.addListener((info, tab) => {
  const text = (info.selectionText || "").trim();
  if (!text) return;
  const url = info.pageUrl || (tab && tab.url) || "";
  const windowId = tab && tab.windowId;

  if (info.menuItemId === "ccagent-clip") {
    addToClipTray(text, url, windowId);
    return;
  }

  const matched = AGENTS.find((a) => `ccagent-send-${a.id}` === info.menuItemId);
  if (matched) {
    dispatchToSidePanel(windowId, {
      agentId: matched.id,
      text: url ? `${text}\n\n（来源：${url}）` : text,
      autoExtract: false,
    });
  }
});

chrome.commands.onCommand.addListener(async (command) => {
  if (command !== "send-selection-to-ccagent") return;
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.id) return;
  let selected = "";
  try {
    const res = await chrome.scripting.executeScript({
      target: { tabId: tab.id },
      func: () => (window.getSelection ? window.getSelection().toString() : ""),
    });
    selected = (res && res[0] && res[0].result ? res[0].result : "").trim();
  } catch (_) {}

  const { lastAgentId = "agent4" } = await chrome.storage.local.get("lastAgentId");
  dispatchToSidePanel(tab.windowId, {
    agentId: lastAgentId,
    text: selected ? `${selected}\n\n（来源：${tab.url || ""}）` : "",
    autoExtract: false,
  });
});

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (!msg || typeof msg !== "object") return;
  const windowId = sender.tab && sender.tab.windowId;
  if (msg.type === "CCAGENT_TWEET_SEND") {
    chrome.storage.local.get("lastAgentId").then(({ lastAgentId = "agent4" }) => {
      dispatchToSidePanel(windowId, {
        agentId: msg.agentId || lastAgentId,
        text: msg.text || "",
        autoExtract: false,
      });
    });
    sendResponse({ ok: true });
    return true;
  }
  if (msg.type === "CCAGENT_TWEET_CLIP") {
    addToClipTray(msg.text || "", msg.url || "", windowId);
    sendResponse({ ok: true });
    return true;
  }
});
