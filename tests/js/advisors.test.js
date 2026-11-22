import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(import.meta.dirname, "../..");
const HTML = fs.readFileSync(path.join(ROOT, "index.html"), "utf-8");
const APP_JS = fs.readFileSync(path.join(ROOT, "app.js"), "utf-8");
const ADVISORS_DATA = JSON.parse(fs.readFileSync(path.join(ROOT, "prompts/advisory_career.json"), "utf-8"));
const EVAL_FIXTURE = JSON.parse(fs.readFileSync(path.join(ROOT, "tests/fixtures/advisors_eval.json"), "utf-8"));
const FRAGMENT_HTML = fs.readFileSync(path.join(ROOT, "tests/fixtures/advisors_fragment.html"), "utf-8");

function bootApp({ failAdvisors = false, evalResp = null } = {}) {
  const dom = new JSDOM(HTML, {
    url: "http://127.0.0.1:8100/",
    runScripts: "outside-only",
    pretendToBeVisual: true,
  });
  const { window } = dom;
  const fetchUrls = [];
  window.HTMLElement.prototype.scrollIntoView = () => {};
  window.fetch = async (url) => {
    const u = String(url);
    fetchUrls.push(u);
    if (u.startsWith("/api/advisors")) {
      if (failAdvisors) return new Response("err", { status: 500 });
      return new Response(JSON.stringify({ advisors: ADVISORS_DATA, disclaimer: "智囊是分析视角，不是持证顾问。" }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (u.startsWith("/api/mode")) {
      return new Response(JSON.stringify({ hosted: false }), { status: 200 });
    }
    if (u.startsWith("/api/sessions?")) {
      return new Response(JSON.stringify({ sessions: [] }), { status: 200 });
    }
    if (u === "/api/evaluate") {
      return new Response(JSON.stringify(evalResp || EVAL_FIXTURE), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }
    if (u.includes("/report")) {
      return new Response(FRAGMENT_HTML, { status: 200, headers: { "Content-Type": "text/html" } });
    }
    return new Response("{}", { status: 200 });
  };
  window.eval(APP_JS);
  return { window, fetchUrls };
}

describe("CCagent advisors modal & report fragment tests", () => {
  it("1. opens advisors modal with 6 rated + 2 observers, rule_public, no internal field names, and no session requests", async () => {
    const { window: w, fetchUrls } = bootApp();
    await new Promise((r) => setTimeout(r, 30));
    const beforeCount = fetchUrls.length;

    const btn = w.document.getElementById("btn-advisors");
    btn.click();

    const modal = w.document.getElementById("advisors-modal");
    assert.equal(modal.classList.contains("hidden"), false);
    const bodyText = w.document.getElementById("advisors-modal-body").textContent;
    assert.ok(bodyText.includes("评分智囊（6）"));
    assert.ok(bodyText.includes("旁听（2）"));
    assert.ok(bodyText.includes("判断规则："));
    assert.ok(!bodyText.includes("paid_evidence"));
    assert.ok(!bodyText.includes("skill_evidence"));

    const newFetches = fetchUrls.slice(beforeCount);
    assert.equal(
      newFetches.some((u) => /evaluate|fields|analysis|report/.test(u)),
      false,
    );

    // ESC closes modal and returns focus to #btn-advisors
    w.document.dispatchEvent(new w.KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
    assert.equal(modal.classList.contains("hidden"), true);
    assert.equal(w.document.activeElement, btn);
  });

  it("2. shows fallback message when /api/advisors fails", async () => {
    const { window: w } = bootApp({ failAdvisors: true });
    await new Promise((r) => setTimeout(r, 30));
    w.document.getElementById("btn-advisors").click();
    const bodyText = w.document.getElementById("advisors-modal-body").textContent;
    assert.ok(bodyText.includes("智囊名册暂时无法加载"));
  });

  it("3. strips ** from headline-text and renders real report fragment with 分项会诊", async () => {
    const evalResp = structuredClone(EVAL_FIXTURE);
    evalResp.headline = "**不建议**直接投入";
    const { window: w } = bootApp({ evalResp });
    await new Promise((r) => setTimeout(r, 30));

    w.document.getElementById("raw-input").value = "我想做自媒体";
    w.document.getElementById("btn-evaluate").click();
    await new Promise((r) => setTimeout(r, 40));

    const hl = w.document.getElementById("headline-text").textContent;
    assert.equal(hl.includes("**"), false);
    assert.ok(hl.includes("不建议直接投入"));

    assert.ok(FRAGMENT_HTML.includes("分项会诊"));
    assert.ok(FRAGMENT_HTML.includes("程序规则判定"));
    assert.ok(FRAGMENT_HTML.includes("AI 解读"));
  });
});
