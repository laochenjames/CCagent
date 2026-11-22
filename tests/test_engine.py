"""Unit tests for engine.py (v2)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine


def _given(val, cat="自报"):
    return {"value": val, "status": "given", "category": cat, "source": "text"}


class TestEngine(unittest.TestCase):
    def test_monetization_branches(self):
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("paid_stranger")})[0], "高")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("paid_acquaintance")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("paid")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("asked")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("none"), "precedent": _given("yes")})[0], "中")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("none"), "precedent": _given("no")})[0], "低")
        self.assertEqual(engine.rate_monetization({"paid_evidence": _given("none")})[0], "无法判断")
        self.assertEqual(engine.rate_monetization({})[0], "无法判断")

    def test_execution_boundaries(self):
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": _given(4), "weekly_hours_planned": _given(10)})[0], "低")
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": _given(5), "weekly_hours_planned": _given(10)})[0], "中")
        self.assertEqual(engine.rate_execution({"weekly_hours_actual_recent": _given(8), "weekly_hours_planned": _given(10)})[0], "高")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": _given(15)})[0], "低")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": _given(16)})[0], "中")
        self.assertEqual(engine.rate_execution({"continuity_weeks_12m": _given(31)})[0], "高")

    def test_opportunity_boundaries(self):
        self.assertEqual(engine.rate_opportunity({"unit_price": _given(400), "take_home_ratio": _given(1), "floor_take_home_per_unit": _given(600)})[0], "低")
        self.assertEqual(engine.rate_opportunity({"unit_price": _given(480), "take_home_ratio": _given(1), "floor_take_home_per_unit": _given(600)})[0], "中")
        self.assertEqual(engine.rate_opportunity({"unit_price": _given(900), "take_home_ratio": _given(1), "floor_take_home_per_unit": _given(600)})[0], "高")

    def test_safety_net_and_pure_time(self):
        self.assertEqual(engine.rate_safety_net({"needs_cash": _given(False), "affects_main_job": _given(False)})[0], "不适用")
        self.assertEqual(engine.rate_safety_net({"borrowing_or_essential_funds": _given(True)})[0], "低")
        # 未填 income_after_monthly 时：信号 S 不评，无支出时返回无法判断；有支出占比<10%时返回高
        self.assertEqual(engine.rate_safety_net({"cash_free": _given(20000), "monthly_expense": _given(10000)})[0], "无法判断")
        self.assertEqual(engine.rate_safety_net({"cash_free": _given(20000), "monthly_expense": _given(10000), "cash_outlay": _given(1000)})[0], "高")
        self.assertEqual(engine.rate_safety_net({"cash_free": _given(20000), "monthly_expense": _given(10000), "income_after_monthly": _given(0)})[0], "低")
        self.assertEqual(engine.rate_safety_net({"cash_free": _given(30000), "monthly_expense": _given(10000)})[0], "无法判断")
        self.assertEqual(engine.rate_safety_net({"cash_free": _given(60000), "monthly_expense": _given(10000), "income_after_monthly": _given(0), "cash_outlay": _given(5000)})[0], "高")

    def test_stoploss_boundaries(self):
        self.assertEqual(engine.rate_stoploss({"first_paid_month": _given(3), "validation_months": _given(4)})[0], "低")
        self.assertEqual(engine.rate_stoploss({"first_paid_month": _given(3), "validation_months": _given(5)})[0], "中")
        self.assertEqual(engine.rate_stoploss({"first_paid_month": _given(3), "validation_months": _given(5), "will_really_stop": _given(True)})[0], "高")

    def test_flags(self):
        fields = {
            "first_paid_month": _given(3),
            "validation_months": _given(2),
            "borrowing_or_essential_funds": _given(True),
        }
        flags = engine.compute_flags(fields)
        self.assertTrue(any(f["level"] == "红" and "止损月不要早于" in f["text"] for f in flags))
        self.assertTrue(any(f["level"] == "红" and "借贷" in f["text"] for f in flags))


    def test_rate_capability(self):
        r0, _ = engine.rate_capability({})
        self.assertEqual(r0, "无法判断")
        r_low, _ = engine.rate_capability({
            "skill_evidence": {"status": "given", "value": "none"},
            "channel_access": {"status": "given", "value": "none"},
        })
        self.assertEqual(r_low, "低")
        r_high, _ = engine.rate_capability({
            "skill_evidence": {"status": "given", "value": "direct"},
            "channel_access": {"status": "given", "value": "has"},
        })
        self.assertEqual(r_high, "高")

    def test_needs_cash_unanswered_no_red_line(self):
        reasons = engine.red_line_reasons({
            "cash_free": {"status": "given", "value": 10000},
            "monthly_expense": {"status": "given", "value": 5000},
        })
        self.assertEqual(reasons, [])

    def test_outlay_ratio_boundaries_and_red_line_reasons(self):
        r_ok = engine.red_line_reasons({
            "cash_free": {"status": "given", "value": 100000},
            "cash_outlay": {"status": "given", "value": 25000},
        })
        self.assertEqual(r_ok, [])
        r_bad = engine.red_line_reasons({
            "cash_free": {"status": "given", "value": 100000},
            "cash_outlay": {"status": "given", "value": 25001},
        })
        self.assertEqual(len(r_bad), 1)
        self.assertIn("花费占比", r_bad[0])


if __name__ == "__main__":
    unittest.main()
