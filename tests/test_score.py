"""Unit tests for score.py (v2)."""

import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import score

FIELDS_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "prompts", "fields_career.json")
with open(FIELDS_PATH, "r", encoding="utf-8") as _f:
    REGISTRY = json.load(_f)


def _g(val, cat="自报"):
    return {"value": val, "status": "given", "category": cat, "source": "form"}


class TestScore(unittest.TestCase):
    def test_1_all_unknown(self):
        res = score.compute_score({}, REGISTRY)
        sc = res["score"]
        self.assertEqual(sc["low"], 15)
        self.assertEqual(sc["high"], 95)
        self.assertEqual(sc["point"], 55)
        self.assertEqual(sc["confidence"], 0.0)
        self.assertEqual(sc["label"], "还看不出来")

    def test_2_monotonicity(self):
        base = {"paid_evidence": _g("asked", "自报")}
        r1 = score.compute_score(base, REGISTRY)
        w1 = r1["score"]["high"] - r1["score"]["low"]

        more = dict(base, precedent=_g("yes", "自报"))
        r2 = score.compute_score(more, REGISTRY)
        w2 = r2["score"]["high"] - r2["score"]["low"]
        self.assertLessEqual(w2, w1)
        self.assertGreaterEqual(r2["score"]["confidence"], r1["score"]["confidence"])

        guess = {"paid_evidence": _g("asked", "猜测")}
        r3 = score.compute_score(guess, REGISTRY)
        w3 = r3["score"]["high"] - r3["score"]["low"]
        self.assertGreaterEqual(w3, w1)

    def test_3_evidence_half_width_order(self):
        widths = []
        for cat in ("事实", "自报", "估计", "猜测"):
            r = score.compute_score({"paid_evidence": _g("paid", cat)}, REGISTRY)
            f = [x for x in r["factors"] if x["id"] == "MONETIZATION"][0]
            widths.append(f["interval"][1] - f["interval"][0])
        self.assertTrue(widths[0] < widths[1] < widths[2] < widths[3])

    def test_4_coverage(self):
        r1 = score.compute_score({"first_paid_month": _g(3), "validation_months": _g(6)}, REGISTRY)
        r2 = score.compute_score({"first_paid_month": _g(3), "validation_months": _g(6), "will_really_stop": _g(True)}, REGISTRY)
        f1 = [x for x in r1["factors"] if x["id"] == "STOPLOSS"][0]
        f2 = [x for x in r2["factors"] if x["id"] == "STOPLOSS"][0]
        self.assertLessEqual(f2["interval"][1] - f2["interval"][0], f1["interval"][1] - f1["interval"][0])

    def test_5_red_line_and_early_stoploss(self):
        r = score.compute_score({"borrowing_or_essential_funds": _g(True)}, REGISTRY)
        self.assertLessEqual(r["score"]["high"], 25)
        self.assertEqual(r["score"]["label"], "偏低")
        self.assertEqual(r["score"]["action"], "不建议投入")

        # early stoploss does NOT trigger red line
        r2 = score.compute_score({"first_paid_month": _g(3), "validation_months": _g(2)}, REGISTRY)
        self.assertNotEqual(r2["score"]["action"], "不建议投入")

    def test_6_pure_time_removes_safety_net(self):
        r = score.compute_score({"needs_cash": _g(False), "affects_main_job": _g(False)}, REGISTRY)
        ids = {f["id"] for f in r["factors"]}
        self.assertNotIn("SAFETY_NET", ids)

    def test_7_purpose_learn_removes_monetization_opportunity(self):
        r = score.compute_score({"purpose": _g("learn")}, REGISTRY)
        ids = {f["id"] for f in r["factors"]}
        self.assertNotIn("MONETIZATION", ids)
        self.assertNotIn("OPPORTUNITY", ids)

    def test_8_confidence_cap_95(self):
        all_facts = {
            f["id"]: _g(f["neutral_value"], "事实")
            for f in REGISTRY
            if f.get("neutral_value") is not None
        }
        r = score.compute_score(all_facts, REGISTRY)
        self.assertLessEqual(r["score"]["confidence_pct"], 95)

    def test_9_group_gains(self):
        r_empty = score.compute_score({}, REGISTRY)
        groups = score.build_groups({}, REGISTRY, r_empty["_raw_confidence"])
        by_name = {g["name"]: g for g in groups}
        self.assertEqual(by_name["基本情况"]["gain"], 0)
        self.assertGreater(by_name["变现与需求"]["gain"], 0)

        done_state = {"paid_evidence": _g("paid"), "precedent": _g("yes")}
        r_done = score.compute_score(done_state, REGISTRY)
        groups2 = score.build_groups(done_state, REGISTRY, r_done["_raw_confidence"])
        by_name2 = {g["name"]: g for g in groups2}
        self.assertEqual(by_name2["变现与需求"]["gain"], 0)

    def test_10_label_boundaries(self):
        # confidence < 0.25 -> 还看不出来
        r0 = score.compute_score({}, REGISTRY)
        self.assertEqual(r0["score"]["label"], "还看不出来")

    def test_11_exclusion_toggle_and_synthesis(self):
        r = score.compute_score({
            "excl_MONETIZATION": _g(True),
            "paid_evidence": _g("none"),
            "precedent": _g("no"),
            "skill_evidence": _g("direct"),
            "channel_access": _g("has"),
        }, REGISTRY)
        excl_ids = [e["id"] for e in r["score"]["excluded"]]
        self.assertIn("MONETIZATION", excl_ids)
        self.assertEqual(r["score"]["excluded"][0]["rating_if_included"], "低")
        self.assertIsInstance(r.get("synthesis"), dict)

    def test_12_purpose_learn_excludes_capability(self):
        r = score.compute_score({"purpose": _g("learn")}, REGISTRY)
        excl_ids = [e["id"] for e in r["score"]["excluded"]]
        self.assertIn("CAPABILITY", excl_ids)
        for e in r["score"]["excluded"]:
            self.assertIsNone(e["rating_if_included"])
        groups = score.build_groups({"purpose": _g("learn")}, REGISTRY, r["_raw_confidence"])
        gnames = [g["name"] for g in groups]
        self.assertNotIn("能力与渠道", gnames)

    def test_13_red_line_flag_in_score(self):
        r_red = score.compute_score({"borrowing_or_essential_funds": _g(True)}, REGISTRY)
        self.assertTrue(r_red["score"]["red_line"])
        r_ok = score.compute_score({"needs_cash": _g(False), "affects_main_job": _g(False)}, REGISTRY)
        self.assertFalse(r_ok["score"]["red_line"])


if __name__ == "__main__":
    unittest.main()

