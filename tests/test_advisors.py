import json
import os
import threading
import unittest
import urllib.request

import engine
import llm
import report
import server


class TestAdvisorsLibraryAndAPI(unittest.TestCase):
    def test_advisors_library_validation_and_lengths(self):
        advisors = llm.load_advisors_library()
        self.assertEqual(len(advisors), 8)
        errors = server.validate_advisors_library(advisors)
        self.assertEqual(errors, [], f"Validation errors: {errors}")
        for a in advisors:
            if a.get("rated"):
                self.assertLessEqual(len(a["rule_public"]), 100, f"{a['id']} rule_public > 100 chars")

    def test_rule_public_boundaries(self):
        def g(val):
            return {"value": val, "status": "given"}

        # MONETIZATION
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("paid_stranger")})[0], "高")
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("paid_acquaintance")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("asked")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("none"), "precedent": g("yes")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("none"), "precedent": g("no")})[0], "低")
        self.assertEqual(engine.rate_monetization({"paid_evidence": g("none")})[0], "无法判断")
        self.assertEqual(engine.rate_monetization({})[0], "无法判断")

        # CAPABILITY
        self.assertEqual(engine.rate_capability({"skill_evidence": g("direct"), "channel_access": g("has")})[0], "高")
        self.assertEqual(engine.rate_capability({"skill_evidence": g("direct"), "channel_access": g("untested")})[0], "中")
        self.assertEqual(engine.rate_capability({"skill_evidence": g("none"), "channel_access": g("has")})[0], "低")
        self.assertEqual(engine.rate_capability({})[0], "无法判断")

        # EXECUTION
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": g(4), "weekly_hours_planned": g(10)})[0], "低")
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": g(5), "weekly_hours_planned": g(10)})[0], "中")
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": g(8), "weekly_hours_planned": g(10)})[0], "高")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": g(15)})[0], "低")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": g(16)})[0], "中")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": g(31)})[0], "高")
        # 信号C：过去项目持续率 <0.5 低, 0.5-0.67 中, >=0.67 高，且三信号取最低
        p_done = {"actual_months": 6, "planned_months": 6, "still_running": False, "had_income": True}
        p_fail = {"actual_months": 1, "planned_months": 6, "still_running": False, "had_income": False}
        self.assertEqual(engine.rate_execution({"past_projects": g([p_done, p_fail, p_fail])})[0], "低")
        self.assertEqual(engine.rate_execution({"past_projects": g([p_done, p_fail])})[0], "中")
        self.assertEqual(engine.rate_execution({"past_projects": g([p_done, p_done, p_done, p_fail])})[0], "高")
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": g(10), "weekly_hours_planned": g(10), "continuity_weeks_12m": g(10)})[0], "低")

        # OPPORTUNITY
        self.assertEqual(engine.rate_opportunity({"unit_price": g(79), "take_home_ratio": g(1), "floor_take_home_per_unit": g(100)})[0], "低")
        self.assertEqual(engine.rate_opportunity({"unit_price": g(80), "take_home_ratio": g(1), "floor_take_home_per_unit": g(100)})[0], "中")
        self.assertEqual(engine.rate_opportunity({"unit_price": g(150), "take_home_ratio": g(1), "floor_take_home_per_unit": g(100)})[0], "高")

        # SAFETY_NET
        self.assertEqual(engine.rate_safety_net({"needs_cash": g(False), "affects_main_job": g(False)})[0], "不适用")
        self.assertEqual(engine.rate_safety_net({"borrowing_or_essential_funds": g(True)})[0], "低")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(200), "monthly_expense": g(100), "income_after_monthly": g(0)})[0], "低")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(300), "monthly_expense": g(100), "income_after_monthly": g(0)})[0], "中")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(600), "monthly_expense": g(100), "income_after_monthly": g(0)})[0], "高")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(1000), "cash_outlay": g(260)})[0], "低")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(1000), "cash_outlay": g(100)})[0], "中")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(1000), "cash_outlay": g(99)})[0], "高")
        self.assertEqual(engine.rate_safety_net({"cash_free": g(100), "monthly_expense": g(100), "cash_outlay": g(5)})[0], "高")

        # STOPLOSS
        self.assertEqual(engine.rate_stoploss({"first_paid_month": g(2), "validation_months": g(3), "will_really_stop": g(True)})[0], "低")
        self.assertEqual(engine.rate_stoploss({"first_paid_month": g(2), "validation_months": g(4), "will_really_stop": g(False)})[0], "低")
        self.assertEqual(engine.rate_stoploss({"first_paid_month": g(2), "validation_months": g(4)})[0], "中")
        self.assertEqual(engine.rate_stoploss({"first_paid_month": g(2), "validation_months": g(4), "will_really_stop": g(True)})[0], "高")

    def test_get_api_advisors_whitelist_and_cache(self):
        srv = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
        port = srv.server_address[1]
        t = threading.Thread(target=srv.serve_forever, daemon=True)
        t.start()
        try:
            req = urllib.request.Request(f"http://127.0.0.1:{port}/api/advisors")
            with urllib.request.urlopen(req, timeout=5) as resp:
                self.assertEqual(resp.status, 200)
                self.assertIn("max-age=", resp.headers.get("Cache-Control", ""))
                data = json.loads(resp.read().decode("utf-8"))
            self.assertEqual(data.get("disclaimer"), "智囊是分析视角，不是持证顾问。")
            self.assertEqual(len(data.get("advisors", [])), 8)
            for a in data["advisors"]:
                for forbidden in ("rule_summary", "reads_fields", "common_pitfall", "advice_style"):
                    self.assertNotIn(forbidden, a)
                self.assertIn("code", a)
                self.assertIn("seal", a)
                self.assertIn("ask", a)
                self.assertIn("watch", a)
                self.assertIn("rule_public", a)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_report_fragment_and_full_consistency_and_cover(self):
        advisors = llm.load_advisors_library()
        registry = llm.load_fields_registry()
        result = {
            "headline": "**不建议**直接投入",
            "synthesis": {"sentence": "**综合**：先验证。", "weakest": {"id": "MONETIZATION", "name": "变现与需求", "rating": "低", "delta": 8}},
            "factors": [
                {"id": "MONETIZATION", "name": "变现与需求", "rating": "低", "rule_note": "尚无付费", "interval": [15, 50], "missing": ["price"]},
                {"id": "CAPABILITY", "name": "能力与渠道", "rating": "无法判断", "rule_note": "缺渠道", "interval": [15, 95], "missing": ["channel_access"]},
            ],
            "groups": [
                {"id": "能力与渠道", "name": "能力与渠道", "fields": [{"id": "channel_access", "ui_label": "渠道", "status": "unknown"}]},
            ],
            "score": {
                "excluded": [
                    {"id": "EXECUTION", "name": "时间与执行", "reason": "学习型不适用", "rating_if_included": "无法判断"},
                    {"id": "OPPORTUNITY", "name": "划算程度", "reason": "你标记为不适用", "rating_if_included": "高"},
                ]
            },
            "flags": [{"level": "黄", "text": "时间偏紧"}],
        }
        analysis = {
            "advisors": [
                {"id": "MONETIZATION", "insight": "先找陌生人测试", "next_step": "收1笔预付款"},
            ],
            "critique": [
                {"target": "MONETIZATION", "text": "智囊id归位"},
                {"target": "channel_access", "text": "字段id归位"},
                {"target": "unknown_target", "text": "未知归位"},
                {"target": "unknown_target", "text": "   "},
            ],
            "two_week_checks": [{"side": "demand", "text": "访谈3人"}],
            "validation_design": {"supply": ["写大纲"], "demand": ["收定金"], "threshold": ["0单停"]},
        }
        frag = report.build_fragment(result, analysis, registry, advisors)
        self.assertIn("分项会诊", frag)
        self.assertIn("程序规则判定", frag)
        self.assertIn("AI 解读", frag)
        self.assertIn("学习型不适用", frag)
        self.assertNotIn("若计入将评为无法判断", frag)
        self.assertIn("你标记为不适用（若计入将评为高）", frag)
        self.assertIn("当前情形不适用该项", frag)
        self.assertIn("针对本智囊的假设批判", frag)
        self.assertIn("其他假设批判", frag)
        self.assertIn("智囊id归位", frag)
        self.assertIn("字段id归位", frag)
        self.assertIn("未知归位", frag)
        self.assertNotIn("<li></li>", frag)

        full_html = report.build_full_html(result, analysis, registry, advisors, {"title": "测试"}, "")
        self.assertIn("本报告由智市、智配、智续、智衡、智守、智断六位智囊会诊", full_html)
        self.assertNotIn("**不建议**", full_html)
        self.assertIn("不建议直接投入", full_html)

        old_analysis = {"critique": ["旧字符串批判"]}
        old_frag = report.build_fragment(result, old_analysis, registry, advisors)
        self.assertIn("本次分析未包含该智囊的解读", old_frag)
        self.assertIn("旧字符串批判", old_frag)

        md = report.build_markdown(result, {"advisors": [], "critique": []}, registry, advisors, {"title": "测试"})
        self.assertNotIn("其他假设批判", md)
        self.assertIn("## 4. 分项会诊", md)
        self.assertIn("## 5. 两周内可验证的 3 件事", md)
        self.assertIn("## 6. 验证设计", md)
        self.assertIn("## 7. 说明", md)
        self.assertNotIn("**不建议**", md)

        xss = '<script>alert(1)</script>|*'
        xss_frag = report.build_fragment(
            {"factors": [{"id": "MONETIZATION", "name": "变现", "rating": "低", "rule_note": xss, "interval": [10, 20]}], "groups": [], "score": {"excluded": []}},
            {"advisors": [{"id": "MONETIZATION", "insight": xss, "next_step": xss}], "critique": [{"target": "MONETIZATION", "text": xss}]},
            registry,
            advisors,
        )
        self.assertNotIn("<script>", xss_frag)
        self.assertIn("&lt;script&gt;", xss_frag)

    def test_js_fixtures_match_generator(self):
        from tests.generate_fixtures import build_fixtures

        fixtures_dir = os.path.join(os.path.dirname(__file__), "fixtures")
        expected = build_fixtures()
        for filename, payload in expected.items():
            path = os.path.join(fixtures_dir, filename)
            self.assertTrue(os.path.exists(path), f"Missing fixture: {filename}")
            with open(path, "r", encoding="utf-8") as f:
                actual = json.load(f)
            self.assertEqual(actual, payload, f"Fixture {filename} out of sync; run tests/generate_fixtures.py")
        self.assertTrue(any(g["id"] == "时间与执行" for g in expected["advisors_eval.json"]["groups"]))
        self.assertIn("analysis", expected["advisors_analysis.json"])


if __name__ == "__main__":
    unittest.main()
