"""Unit tests for report.py and /api/sessions/{id}/report (v2.2)."""

import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import llm
import report
import server
import store


def _sample_data():
    registry = llm.load_fields_registry()
    advisors = llm.load_advisors_library()
    result = {
        "session_id": "s_1",
        "decision": "做技能陪跑",
        "score": {"label": "一般", "action": "适合先小额试验", "confidence_pct": 55, "low": 35, "high": 70, "point": 52},
        "headline": "一般——适合先小额试验。",
        "flags": [{"level": "黄", "text": "已提供单价但未提供到手比例"}],
        "factors": [
            {"id": "MONETIZATION", "name": "变现与需求", "rating": "高", "rule_note": "已有人付过钱", "interval": [70, 95]},
            {"id": "STOPLOSS", "name": "止损设置", "rating": "无法判断", "rule_note": "缺少信息", "interval": [15, 95]},
        ],
        "groups": [
            {
                "id": "变现与需求",
                "name": "变现与需求",
                "state": "部分",
                "gain": 12,
                "fields": [
                    {"id": "paid_evidence", "ui_label": "有没有陌生人付过钱或主动问过价", "status": "given"},
                    {"id": "precedent", "ui_label": "有人用同样的方式做成过吗", "status": "missing"},
                ],
            }
        ],
        "disclaimer": "本评估仅供参考。",
    }
    analysis = {
        "advisors": [
            {"id": "MONETIZATION", "name": "变现与需求验证官", "rating": "高", "basis": "测试<script>alert(1)</script> & \"引号\"", "missing": ["precedent"], "note": "继续验证"},
            {"id": "AI_IMPACT", "name": "AI/行业冲击官", "rating": "不参与", "basis": "判断，不是数据", "missing": [], "note": ""},
        ],
        "critique": [
            {"target": "paid_evidence", "text": "样本量小"},
            {"target": "MONETIZATION", "text": "需持续复购"},
            {"target": "unknown_xyz", "text": "未知目标"},
        ],
        "two_week_checks": [
            {"side": "demand", "text": "找3个陌生人报价"},
            {"side": "supply", "text": "写好服务大纲"},
        ],
        "validation_design": {
            "supply": ["每周2小时"],
            "demand": ["收到1个询价"],
            "threshold": ["做满3个月没有付费就停【AI建议值】"],
        },
        "hidden_count": 2,
    }
    meta = {
        "title": "做技能陪跑",
        "generated_at": "2026-11-15 19:00",
        "stale": True,
        "raw_text": "<b>raw</b>",
        "fields_state": {
            "paid_evidence": {"status": "given", "value": "paid", "category": "事实"},
            "take_home_ratio": {"status": "given", "value": 0.7, "category": "自报"},
            "needs_cash": {"status": "given", "value": False, "category": "自报"},
            "past_projects": {"status": "given", "value": [{"planned_months": 6, "actual_months": 3, "still_running": False}], "category": "自报"},
        },
    }
    return registry, advisors, result, analysis, meta


class TestReport(unittest.TestCase):
    def test_escaping_and_labels_and_badges(self):
        reg, adv, res, ana, meta = _sample_data()
        frag = report.build_fragment(res, ana, reg, adv)
        self.assertNotIn("<script>alert(1)</script>", frag)
        self.assertIn("&lt;script&gt;alert(1)&lt;/script&gt;", frag)
        self.assertIn("针对：有人付过钱或主动问过价吗（陌生人/熟人）", frag)
        self.assertIn("针对：智市", frag)
        self.assertIn("缺少的信息：有人用同样的方式做成过吗", frag)
        self.assertNotIn("paid_evidence", frag)
        self.assertNotIn("precedent", frag)
        self.assertNotIn("【AI建议值】", frag)
        self.assertIn("AI 建议值", frag)

    def test_value_formatting(self):
        reg, _, _, _, _ = _sample_data()
        rmap = {f["id"]: f for f in reg}
        self.assertEqual(report.format_value(rmap["needs_cash"], False), "否")
        self.assertEqual(report.format_value(rmap["paid_evidence"], "paid_stranger"), "陌生人付过钱")
        self.assertEqual(report.format_value(rmap["take_home_ratio"], 0.7), "70%")
        self.assertEqual(report.format_value(rmap["unit_price"], 800), "800 元")
        self.assertIn("计划 6 月，实际 3 月，已结束", report.format_value(rmap["past_projects"], [{"planned_months": 6, "actual_months": 3, "still_running": False}]))
        self.assertEqual(report.format_value(rmap["unit_price"], None), "未提供")

    def test_full_html_self_contained_and_stale(self):
        reg, adv, res, ana, meta = _sample_data()
        html_str = report.build_full_html(res, ana, reg, adv, meta, "body{}")
        self.assertNotIn("http://", html_str)
        self.assertNotIn("https://", html_str)
        self.assertNotIn("<link", html_str)
        self.assertNotIn("<img", html_str)
        self.assertNotIn("<script src", html_str)
        self.assertIn("详细分析基于较早的信息", html_str)
        self.assertIn("另有 2 条 AI 文字因含未核实数字被隐藏", html_str)
        self.assertIn("&lt;b&gt;raw&lt;/b&gt;", html_str)

    def test_markdown_and_filename(self):
        reg, adv, res, ana, meta = _sample_data()
        md = report.build_markdown(res, ana, reg, adv, meta)
        self.assertIn("## 1. 评估摘要", md)
        self.assertIn("## 8. 如何让评估更准", md)
        self.assertIn("## 9. 说明", md)
        cd = report.safe_filename('测试/\\:*?"<>|标题', "20261115-1900", "html")
        self.assertIn('filename="report.html"', cd)
        self.assertIn("filename*=UTF-8''", cd)

    def test_report_api_409_404_and_fragment(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "test.db")
            store.init_db(db_path)
            sid = store.create_session("想做副业", "副业", {}, {"decision": "做副业", "score": {"label": "还看不出来", "confidence_pct": 0, "low": 15, "high": 95}, "factors": [], "groups": [], "flags": []}, db_path=db_path)

            orig_db = store.DB_PATH
            store.DB_PATH = db_path
            httpd = server.QuietThreadingHTTPServer(("127.0.0.1", 0), server.AppHandler)
            port = httpd.server_address[1]
            t = threading.Thread(target=httpd.serve_forever, daemon=True)
            t.start()
            try:
                for fmt in ("fragment", "html", "md"):
                    with self.assertRaises(urllib.error.HTTPError) as ctx:
                        urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/{sid}/report?format={fmt}")
                    self.assertEqual(ctx.exception.code, 409)

                with self.assertRaises(urllib.error.HTTPError) as ctx404:
                    urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/nonexistent/report?format=fragment")
                self.assertEqual(ctx404.exception.code, 404)

                store.save_analysis(sid, {"advisors": [], "critique": [], "two_week_checks": [], "validation_design": {}}, db_path=db_path)
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/sessions/{sid}/report?format=fragment") as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    self.assertIn("html", data)
            finally:
                httpd.shutdown()
                httpd.server_close()
                store.DB_PATH = orig_db

    def test_red_line_and_excluded_in_reports(self):
        import re
        reg, adv, res, ana, meta = _sample_data()
        res["score"]["red_line"] = True
        res["score"]["label"] = "偏低"
        res["score"]["action"] = "不建议投入"
        res["score"]["confidence_pct"] = 20
        res["score"]["excluded"] = [{"id": "MONETIZATION", "name": "变现与需求", "reason": "user", "rating_if_included": "低"}]

        html_str = report.build_full_html(res, ana, reg, adv, meta, "")
        md_str = report.build_markdown(res, ana, reg, adv, meta)

        self.assertNotRegex(html_str, r"置信度\s*(?:<[^>]+>)?\s*\d+%")
        self.assertIn("由规则直接判定", html_str)
        self.assertNotRegex(md_str, r"置信度：\d+%")
        self.assertIn("由规则直接判定", md_str)
        self.assertIn("评分未包含", md_str)
        self.assertIn("若计入将评为低", md_str)


if __name__ == "__main__":
    unittest.main()
