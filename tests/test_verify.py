"""Unit tests for verify.py."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import verify

FIELDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "fields_career.json")
with open(FIELDS_PATH, "r", encoding="utf-8") as _f:
    REGISTRY = json.load(_f)


class TestVerify(unittest.TestCase):
    def test_quote_and_chinese_numerals(self):
        raw = "我打算做三个月看看，预计最多花两万元。"
        extracted = [
            {"id": "validation_months", "value": "3", "unit": "月", "category": "估计", "quote": "做三个月", "status": "given", "readings": []},
            {"id": "cash_outlay", "value": "20000", "unit": "元", "category": "估计", "quote": "花两万元", "status": "given", "readings": []},
            {"id": "unit_price", "value": "500", "unit": "元", "category": "自报", "quote": "不存在的原话", "status": "given", "readings": []},
        ]
        verified, dropped = verify.verify_extracted(raw, extracted, REGISTRY)
        self.assertIn("validation_months", verified)
        self.assertEqual(verified["validation_months"]["value"], 3)
        self.assertIn("cash_outlay", verified)
        self.assertEqual(verified["cash_outlay"]["value"], 20000)
        self.assertNotIn("unit_price", verified)
        self.assertEqual(len(dropped), 1)

    def test_locked_field_not_overwritten(self):
        raw = "单价800元"
        existing = {"unit_price": {"id": "unit_price", "value": 1000, "status": "given", "source": "form", "category": "事实"}}
        extracted = [{"id": "unit_price", "value": "800", "unit": "元", "category": "自报", "quote": "单价800元", "status": "given", "readings": []}]
        verified, _ = verify.verify_extracted(raw, extracted, REGISTRY, existing_fields=existing)
        self.assertNotIn("unit_price", verified)

    def test_lint_rules(self):
        raw = "我打算做2个月"
        llm_out = {
            "advisors": [
                {"id": "AI_IMPACT", "basis": "行业变化快", "missing": [], "note": ""},
                {"id": "MONETIZATION", "basis": "你总是这样试试看，需要999元", "missing": [], "note": "建议先找1个人"},
            ],
            "critique": [{"target": "MONETIZATION", "text": "停。别再用老办法"}],
            "two_week_checks": [{"side": "demand", "text": "找88个陌生人问价"}],
            "validation_design": {
                "supply": ["每周发一篇"],
                "demand": ["收到1个询价"],
                "threshold": ["做2个月【用户确认】", "没有询价就停【用户确认】", "没有付费就暂停"],
            },
            "clarify": [],
        }
        cleaned, num_viol, hidden = verify.lint_output(raw, [], llm_out, allow_hide=True)
        self.assertGreater(num_viol, 0)
        self.assertGreater(hidden, 0)
        self.assertIn("判断，不是数据", cleaned["advisors"][0]["basis"])
        self.assertIn("已隐藏", cleaned["critique"][0]["text"])
        self.assertIn("已隐藏", cleaned["two_week_checks"][0]["text"])
        th = cleaned["validation_design"]["threshold"]
        self.assertTrue(th[0].endswith("【用户确认】"))
        self.assertTrue(th[1].endswith("【AI建议值】"))
        self.assertTrue(th[2].endswith("【AI建议值】"))


if __name__ == "__main__":
    unittest.main()
