"""Playwright E2E verification for CCagent advisor roster, council, and detail card.

Usage:
  cd CCagent
  npm run e2e
"""
import json
import os
import sys
import tempfile
import threading
from unittest.mock import patch

from playwright.sync_api import sync_playwright

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import llm
import server
import store


def run_e2e(screenshot_dir=None):
    if screenshot_dir is None:
        screenshot_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "screenshots")
    os.makedirs(screenshot_dir, exist_ok=True)

    mock_extract = {
        "decision": "业余做技能陪跑副业",
        "extracted": [
            {"id": "purpose", "value": "money", "status": "given", "confidence": "high", "evidence": "副业"},
            {"id": "paid_evidence", "value": "asked", "status": "given", "confidence": "high", "evidence": "有人问过"},
            {"id": "skill_evidence", "value": "direct", "status": "given", "confidence": "high", "evidence": "做过交付"},
            {"id": "channel_access", "value": "has", "status": "given", "confidence": "high", "evidence": "有直接客源"},
            {"id": "borrowing_or_essential_funds", "value": False, "status": "given", "confidence": "high", "evidence": "不借钱"},
            {"id": "needs_cash", "value": True, "status": "given", "confidence": "high", "evidence": "预算5千"},
            {"id": "cash_outlay", "value": 5, "status": "given", "confidence": "high", "evidence": "5千"},
            {"id": "cash_free", "value": 100, "status": "given", "confidence": "high", "evidence": "10万"},
            {"id": "monthly_expense", "value": 100, "status": "given", "confidence": "high", "evidence": "1万"},
            {"id": "income_after_monthly", "value": 100, "status": "given", "confidence": "high", "evidence": "1万"},
            {"id": "weekly_hours_actual_recent", "value": 2, "status": "given", "confidence": "high", "evidence": "每周2小时"},
        ],
        "clarify": [],
    }
    mock_analysis = {
        "critique": "当前主要风险在于尚未形成陌生人付费闭环，且每周实际投入时间偏少。",
        "two_week_checks": [
            "找 3 位陌生目标用户完成付费意愿访谈或预售测试",
            "记录连续两周实际可投入小时数是否稳定超过 4 小时",
        ],
        "validation_design": "两周内发布 1 个最小可交付服务页，以收到至少 1 笔真实预付款为通过线。",
        "advisors": [
            {
                "id": "MONETIZATION",
                "insight": "当前尚无陌生人付费验证，建议先用最小样本测试付费意愿。",
                "next_step": "找 3 位目标用户做预售或付费访谈。",
            },
            {
                "id": "AI_IMPACT",
                "insight": "AI 工具可显著降低内容生产成本，但也加剧同质化竞争。",
                "next_step": "明确自身不可替代的真实经历或数据视角。",
            },
        ],
        "summary": "整体可行，优先补齐付费验证与时间投入。",
    }

    def fake_call_model(*args, **kwargs):
        schema = kwargs.get("schema")
        if schema is None and len(args) >= 5:
            schema = args[4]
        if schema is llm.ANALYSIS_SCHEMA:
            return mock_analysis
        return mock_extract

    with tempfile.TemporaryDirectory() as tmpdir:
        old_db = store.DB_PATH
        store.DB_PATH = os.path.join(tmpdir, "e2e.db")
        store.init_db()
        httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        port = httpd.server_address[1]
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        try:
            with patch.object(llm, "call_model", side_effect=fake_call_model):
                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    page = browser.new_page(viewport={"width": 1280, "height": 900})
                    page.goto(f"http://127.0.0.1:{port}/", wait_until="networkidle")
                    page.evaluate(
                        """() => {
                            localStorage.setItem("cc_byok", JSON.stringify({
                                provider: "gemini", model: "gemini-2.5-flash", key: "test-e2e-key"
                            }));
                        }"""
                    )
                    page.reload(wait_until="networkidle")
                    page.click("#btn-advisors")
                    page.wait_for_selector("#advisors-modal:not(.hidden) .advisors-modal-item", timeout=10000)
                    page.screenshot(path=os.path.join(screenshot_dir, "desktop_modal.png"))
                    page.click("#btn-advisors-close")

                    page.fill("#raw-input", "想业余做技能陪跑副业，每周2小时，预算5千，已有直接客源且做过交付。")
                    page.click("#btn-evaluate")
                    page.wait_for_selector("#result-section:not(.hidden)", timeout=15000)

                    with page.expect_response(lambda r: "/analysis" in r.url and r.request.method == "POST") as resp_info:
                        page.click("#btn-analysis")
                    _ = resp_info.value.json()
                    page.wait_for_selector(".rp-fragment .rp-advisor", timeout=15000)
                    page.locator(".rp-fragment .rp-advisor").first.scroll_into_view_if_needed()
                    page.screenshot(path=os.path.join(screenshot_dir, "desktop_report.png"))

                    page.locator(".rp-fragment .rp-advisor").nth(4).scroll_into_view_if_needed()
                    page.screenshot(path=os.path.join(screenshot_dir, "desktop_excluded.png"))

                    page.set_viewport_size({"width": 390, "height": 844})
                    page.locator(".rp-fragment .rp-advisor").first.scroll_into_view_if_needed()
                    page.screenshot(path=os.path.join(screenshot_dir, "mobile_report.png"))
                    page.click("#btn-advisors")
                    page.wait_for_selector("#advisors-modal:not(.hidden) .advisors-modal-item", timeout=5000)
                    page.screenshot(path=os.path.join(screenshot_dir, "mobile_modal.png"))
                    browser.close()
        finally:
            httpd.shutdown()
            httpd.server_close()
            store.DB_PATH = old_db
    print("E2E_SCREENSHOTS_OK")


if __name__ == "__main__":
    run_e2e()
