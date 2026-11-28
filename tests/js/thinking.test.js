import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { JSDOM } from "jsdom";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const THINKING_JS = fs.readFileSync(
  path.resolve(__dirname, "..", "..", "shared", "thinking.js"),
  "utf8"
);

function createEnv() {
  const html = `<!doctype html><html><body>
    <div id="result-section" class="hidden">
      <span id="res-engine-tag"></span>
      <span id="res-fallback-tag" class="hidden"></span>
      <h1 id="res-title"></h1>
      <p id="res-summary"></p>
      <div id="res-pillars"></div>
      <div id="res-sections"></div>
      <div id="council-synthesis-wrap" class="hidden"></div>
      <div id="council-notes-grid"></div>
    </div>
  </body></html>`;
  const dom = new JSDOM(html, { url: "http://127.0.0.1:8777/", runScripts: "outside-only" });
  dom.window.eval(THINKING_JS);
  return { dom, T: dom.window.__THINKING_TEST__ };
}

test("A5: XSS payload in name/verdict/title does not create <img> or run onerror", () => {
  const { dom, T } = createEnv();
  const xss = `<img src=x onerror="window.__XSS=1">`;
  T.renderResult({
    model: "gemini-test",
    result: {
      title: `标题 ${xss}`,
      summary: "摘要",
      pillars: [{ label: "支柱", value: xss }],
      sections: [{ heading: "节", items: [{ name: xss, tag: "t", detail: xss }] }],
      council_notes: [
        { name: xss, stance: "hold", verdict: xss, based_on: xss, grounded: false, confidence: "low", action: xss },
      ],
    },
  });
  assert.equal(dom.window.document.querySelectorAll("img").length, 0);
  assert.equal(dom.window.__XSS, undefined);
});

test("A1: renderResult and buildMarkdown support both pillars[].content and pillars[].value", () => {
  const { dom, T } = createEnv();
  const res = {
    title: "双轨测试",
    summary: "摘要",
    pillars: [
      { label: "旧字段", content: "来自content" },
      { label: "新字段", value: "来自value" },
    ],
  };
  T.renderResult({ model: "m", result: res });
  const vals = Array.from(dom.window.document.querySelectorAll(".pillar-val")).map((el) => el.textContent);
  assert.deepEqual(vals, ["来自content", "来自value"]);
  const md = T.buildMarkdown(res);
  assert.ok(md.includes("来自content"));
  assert.ok(md.includes("来自value"));
  assert.ok(!md.includes("undefined"));
});

test("B2: legacy history record without new fields renders cleanly, and grounded=false shows grey badge", () => {
  const { dom, T } = createEnv();
  T.renderResult({
    model: "m",
    result: {
      title: "旧记录",
      summary: "旧摘要",
      council_notes: [
        { name: "旧顾问", verdict: "旧判断", action: "旧动作" },
        { name: "新顾问", stance: "oppose", verdict: "新判断", based_on: "不存在的依据", grounded: false, confidence: "low" },
      ],
    },
  });
  const cards = dom.window.document.querySelectorAll(".council-card");
  assert.equal(cards.length, 2);
  assert.ok(cards[0].textContent.includes("旧判断"));
  assert.ok(cards[1].textContent.includes("依据未能在输入中找到"));
  assert.ok(cards[1].textContent.includes("反对"));
});
