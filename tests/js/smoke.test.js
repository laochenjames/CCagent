import { describe, it } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { JSDOM } from "jsdom";

const ROOT = path.resolve(import.meta.dirname, "../..");
const HTML = fs.readFileSync(path.join(ROOT, "index.html"), "utf-8");
const APP_JS = fs.readFileSync(path.join(ROOT, "app.js"), "utf-8");

function makeEvalResponse(extra = {}) {
  return {
    session_id: "s_smoke_1",
    score: {
      label: "可考虑",
      low: 55,
      high: 75,
      confidence_pct: 42,
      red_line: false,
      red_line_reasons: [],
      bottleneck: "",
      groups: [],
    },
    fields: [],
    clarify: [],
    ...extra,
  };
}

function bootPage({ hosted = false, fetchImpl } = {}) {
  const calls = [];
  const uncaught = [];

  const dom = new JSDOM(HTML, {
    url: "http://127.0.0.1:8000/",
    runScripts: "dangerously",
    beforeParse(window) {
      window.addEventListener("error", (e) => uncaught.push(e.error || e.message));
      window.IntersectionObserver = class {
        observe() {}
        disconnect() {}
      };
      window.confirm = () => true;
      window.fetch = async (url, opts = {}) => {
        calls.push({ url: String(url), opts });
        const jsonResp = (obj, status = 200) => ({
          ok: status >= 200 && status < 300,
          status,
          text: async () => JSON.stringify(obj),
          json: async () => obj,
        });
        if (fetchImpl) {
          const custom = await fetchImpl(String(url), opts);
          if (custom) return custom;
        }
        if (String(url) === "/api/mode") {
          return jsonResp({
            hosted,
            retention_days: 30,
            default_models: { gemini: "gemini-3.5-flash", xai: "grok-3-mini-fast", deepseek: "deepseek-flash" },
            quota: hosted ? { used: 0, limit: 10, remaining: 10 } : null,
          });
        }
        if (String(url) === "/api/quota") {
          return jsonResp({ used: 0, limit: 10, remaining: 10 });
        }
        if (String(url) === "/api/evaluate") {
          return jsonResp(
            makeEvalResponse(hosted ? { quota: { used: 1, limit: 10, remaining: 9 } } : {})
          );
        }
        if (String(url).endsWith("/analysis")) {
          return jsonResp({
            analysis: {
              model: "gemini / gemini-2.5-flash",
              advisors: [{ name: "财务顾问", stance: "谨慎", advice: "控制前期投入" }],
              critique: ["注意现金流"],
              two_week_checks: ["访谈 5 个潜在客户"],
            },
            analysis_html: "<div>财务顾问：控制前期投入</div>",
          });
        }
        if (String(url).includes("format=fragment")) {
          return jsonResp({ html: "<div>财务顾问：控制前期投入</div>" });
        }
        return jsonResp({});
      };
    },
  });

  const scriptEl = dom.window.document.createElement("script");
  scriptEl.textContent = APP_JS;
  dom.window.document.body.appendChild(scriptEl);

  return { dom, window: dom.window, document: dom.window.document, calls, uncaught };
}

const tick = () => new Promise((r) => setTimeout(r, 20));

describe("CCagent frontend smoke tests", () => {
  it("1. loads without uncaught exceptions", async () => {
    const { uncaught } = bootPage();
    await tick();
    assert.deepEqual(uncaught, []);
  });

  it("2. clicking evaluate sends Content-Type and renders result", async () => {
    const { document, calls, uncaught } = bootPage();
    await tick();
    document.getElementById("raw-input").value = "我想做个副业";
    document.getElementById("btn-evaluate").click();
    await tick();

    assert.deepEqual(uncaught, []);
    const evalCall = calls.find((c) => c.url === "/api/evaluate");
    assert.ok(evalCall, "expected /api/evaluate call");
    assert.equal(evalCall.opts.headers["Content-Type"], "application/json");
    assert.equal(document.getElementById("result-section").classList.contains("hidden"), false);
    assert.ok(document.getElementById("score-label").textContent.length > 0);
  });

  it("3. hosted mode shows quota badge and updates after evaluate", async () => {
    const { document } = bootPage({ hosted: true });
    await tick();
    const badge = document.getElementById("quota-badge");
    assert.equal(badge.classList.contains("hidden"), false);
    assert.match(badge.textContent, /10\/10/);

    document.getElementById("raw-input").value = "副业测试";
    document.getElementById("btn-evaluate").click();
    await tick();
    assert.match(badge.textContent, /9\/10/);
  });

  it("4. BYOK save with remember persists cc_byok, sends X-LLM-Key, and clear removes it", async () => {
    const { document, window, calls } = bootPage({ hosted: true });
    await tick();
    document.getElementById("btn-settings").click();
    document.getElementById("byok-provider").value = "xai";
    document.getElementById("byok-key").value = "xai-test-secret-1234";
    document.getElementById("byok-remember").checked = true;
    document.getElementById("btn-byok-save").click();

    assert.ok(window.localStorage.getItem("cc_byok"), "cc_byok should be saved");

    document.getElementById("raw-input").value = "BYOK 测试";
    document.getElementById("btn-evaluate").click();
    await tick();

    const withKey = calls.filter((c) => c.url === "/api/evaluate").at(-1);
    assert.equal(withKey.opts.headers["X-LLM-Key"], "xai-test-secret-1234");
    assert.equal(withKey.opts.headers["X-LLM-Provider"], "xai");

    document.getElementById("btn-byok-clear").click();
    assert.equal(window.localStorage.getItem("cc_byok"), null);

    document.getElementById("btn-evaluate").click();
    await tick();
    const withoutKey = calls.filter((c) => c.url === "/api/evaluate").at(-1);
    assert.equal(withoutKey.opts.headers["X-LLM-Key"], undefined);
  });

  it("5. clicking analysis sends POST with Content-Type and renders analysis", async () => {
    const { document, calls } = bootPage();
    await tick();
    document.getElementById("raw-input").value = "分析测试";
    document.getElementById("btn-evaluate").click();
    await tick();

    document.getElementById("btn-analysis").click();
    await tick();

    const anaCall = calls.find((c) => c.url.endsWith("/analysis"));
    assert.ok(anaCall);
    assert.equal(anaCall.opts.method, "POST");
    assert.equal(anaCall.opts.headers["Content-Type"], "application/json");
    assert.match(document.getElementById("analysis-body").textContent, /财务顾问/);
  });

  it("6. switching provider preserves #privacy-notice <summary> and never shows '7 天'", async () => {
    const { document } = bootPage({ hosted: true });
    await tick();
    document.getElementById("byok-provider").value = "deepseek";
    document.getElementById("byok-key").value = "ds-key-1234";
    document.getElementById("btn-byok-save").click();
    await tick();

    const notice = document.getElementById("privacy-notice");
    assert.ok(notice.querySelector("summary"), "<summary> must still exist");
    assert.equal(document.body.textContent.includes("7 天"), false);
  });

  it("7. btn-byok-test shows '抽取质量不足' when ok=true and extracted_ok=false", async () => {
    const { document } = bootPage({
      hosted: true,
      fetchImpl: async (url) => {
        if (url === "/api/test-connection") {
          return {
            ok: true,
            status: 200,
            text: async () =>
              JSON.stringify({
                ok: true,
                parsed_ok: true,
                extracted_ok: false,
                provider: "xai",
                model: "grok-3-mini-fast",
                message: "连接成功",
              }),
          };
        }
        return null;
      },
    });
    await tick();
    document.getElementById("byok-key").value = "xai-test-key";
    document.getElementById("btn-byok-test").click();
    await tick();

    assert.match(document.getElementById("byok-status").textContent, /抽取质量不足/);
  });

  it("8. editing number sends /fields and clearing sends clear:true", async () => {
    const { document, window, calls } = bootPage({
      fetchImpl: async (url) => {
        if (url === "/api/evaluate") {
          const resp = makeEvalResponse({
            groups: [
              {
                id: "SAFETY_NET",
                name: "财务安全垫",
                state: "部分填写",
                gain: 0,
                fields: [
                  {
                    id: "cash_reserve",
                    label: "现金储备",
                    type: "number",
                    unit: "元",
                    value: 50000,
                    status: "known",
                    source: "llm",
                  },
                ],
              },
            ],
          });
          return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify(resp),
            json: async () => resp,
          };
        }
        if (url.endsWith("/fields")) {
          return {
            ok: true,
            status: 200,
            text: async () => JSON.stringify(makeEvalResponse({ server_ms: 5 })),
            json: async () => makeEvalResponse({ server_ms: 5 }),
          };
        }
        return null;
      },
    });
    await tick();
    document.getElementById("raw-input").value = "测试";
    document.getElementById("btn-evaluate").click();
    await tick();

    const input = document.querySelector("#groups-container input");
    assert.ok(input, "number input should render");
    input.value = "80000";
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 450));

    const f1 = calls.filter((c) => c.url.endsWith("/fields")).at(-1);
    assert.ok(f1, "expected /fields call after number change");
    assert.ok(f1.opts.body.includes("80000"), "expected 80000 in /fields body");

    input.value = "";
    input.dispatchEvent(new window.Event("change", { bubbles: true }));
    await new Promise((r) => setTimeout(r, 450));

    const f2 = calls.filter((c) => c.url.endsWith("/fields")).at(-1);
    assert.ok(f2.opts.body.includes("clear"), "expected clear in /fields body");
  });

  it("9. red_line=true shows #conf-redline and hides #conf-row", async () => {
    const { document } = bootPage({
      fetchImpl: async (url) => {
        if (url === "/api/evaluate") {
          const resp = makeEvalResponse({
            score: {
              label: "偏低",
              low: 15,
              high: 25,
              confidence_pct: 20,
              red_line: true,
              red_line_reasons: ["涉及借贷"],
              bottleneck: "",
              groups: [],
            },
          });
          return { ok: true, status: 200, text: async () => JSON.stringify(resp), json: async () => resp };
        }
        return null;
      },
    });
    await tick();
    document.getElementById("raw-input").value = "借钱";
    document.getElementById("btn-evaluate").click();
    await tick();

    assert.equal(document.getElementById("conf-redline").classList.contains("hidden"), false);
    assert.equal(document.getElementById("conf-row").classList.contains("hidden"), true);
  });

  it("10. 429 with category '额度用完' opens settings modal", async () => {
    const { document } = bootPage({
      hosted: true,
      fetchImpl: async (url) => {
        if (url === "/api/evaluate") {
          const err = { error: "今日免费额度已用完", category: "额度用完" };
          return { ok: false, status: 429, text: async () => JSON.stringify(err), json: async () => err };
        }
        return null;
      },
    });
    await tick();
    document.getElementById("raw-input").value = "超额测试";
    document.getElementById("btn-evaluate").click();
    await tick();

    assert.equal(document.getElementById("settings-modal").classList.contains("hidden"), false);
  });

  it("11. history list shows '· 红线' when red_line is true", async () => {
    const { document } = bootPage({
      fetchImpl: async (url) => {
        if (url === "/api/sessions") {
          const data = { sessions: [{ id: "s1", title: "借钱开店", label: "偏低", confidence_pct: 20, red_line: true }] };
          return { ok: true, status: 200, text: async () => JSON.stringify(data), json: async () => data };
        }
        return null;
      },
    });
    await tick();
    document.getElementById("btn-history").click();
    await tick();

    assert.match(document.getElementById("history-list").textContent, /· 红线/);
  });

  it("12. saving DeepSeek key updates #privacy-provider to 'DeepSeek'", async () => {
    const { document } = bootPage({ hosted: true });
    await tick();
    document.getElementById("byok-provider").value = "deepseek";
    document.getElementById("byok-key").value = "ds-key-9999";
    document.getElementById("btn-byok-save").click();
    await tick();

    assert.equal(document.getElementById("privacy-provider").textContent, "DeepSeek");
  });

  it("13. reloading page with cc_byok in localStorage keeps #privacy-provider", async () => {
    const { document } = bootPage({
      hosted: true,
      fetchImpl: async () => null,
    });
    // Simulate persisted cc_byok before boot via a fresh JSDOM
    const dom2 = new JSDOM(HTML, {
      url: "http://127.0.0.1:8000/",
      runScripts: "dangerously",
      beforeParse(window) {
        window.IntersectionObserver = class { observe() {} disconnect() {} };
        window.localStorage.setItem("cc_byok", JSON.stringify({ provider: "deepseek", key: "ds-saved", model: "deepseek-flash" }));
        window.fetch = async (url) => ({
          ok: true,
          status: 200,
          text: async () => JSON.stringify(url === "/api/mode" ? { hosted: true, retention_days: 30 } : { used: 0, limit: 10, remaining: 10 }),
          json: async () => (url === "/api/mode" ? { hosted: true, retention_days: 30 } : { used: 0, limit: 10, remaining: 10 }),
        });
      },
    });
    const s = dom2.window.document.createElement("script");
    s.textContent = APP_JS;
    dom2.window.document.body.appendChild(s);
    await tick();

    assert.equal(dom2.window.document.getElementById("privacy-provider").textContent, "DeepSeek");
    assert.ok(document);
  });

  it("14. xai and deepseek options show '测试中', gemini does not", async () => {
    const { document } = bootPage();
    await tick();
    const opts = Array.from(document.querySelectorAll("#byok-provider option"));
    const byVal = Object.fromEntries(opts.map((o) => [o.value, o.textContent]));
    assert.equal(byVal.gemini.includes("测试中"), false);
    assert.equal(byVal.xai.includes("测试中"), true);
    assert.equal(byVal.deepseek.includes("测试中"), true);
  });
});
