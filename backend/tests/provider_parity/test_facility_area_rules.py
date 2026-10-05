import copy
import unittest
from backend.app.modules.law.reference.facility_area_rules import FACILITY_AREA_RULES, bind_snapshot_evidence, source_snapshot
from backend.app.modules.law.reference.facility_area_engine import evaluate_facility_areas


class KoreanRulesTests(unittest.TestCase):
    def evaluate(self, key, quantities, area, *, date="2026-09-13", **changes):
        rule = next(r for r in FACILITY_AREA_RULES if r["rule_id"] == key)
        facts = {"facility_type": rule["facility_types"][0], "quantities": quantities,
                 "conditions": copy.deepcopy(rule["required_conditions"]),
                 "condition_evidence": {key: {"source_ref": "test-applicability-assessment"} for key in rule["required_conditions"]},
                 "areas": {rule["area_fact"]: {"value": area, "unit": "m2", "basis": rule["area_basis"], "source_ref": "test-drawing"}}}
        facts.update(changes)
        return evaluate_facility_areas(bind_snapshot_evidence(facts, [rule], date), [rule], date)["checks"][0]

    def test_childcare_equal_threshold_and_under_area_are_distinct(self):
        self.assertEqual(self.evaluate("kr.childcare.facility", {"children": 20}, 85.8)["status"], "meets_area_minimum")
        self.assertEqual(self.evaluate("kr.childcare.rooms", {"children": 20}, 52.79)["status"], "below_area_minimum")
        self.assertEqual(self.evaluate("kr.childcare.rooms", {"children": 20}, 52.8)["status"], "meets_area_minimum")

    def test_mixed_disabled_children_sum_not_single_coefficient(self):
        check = self.evaluate("kr.childcare.disabled.facility", {"disabled_children": 12, "other_children": 5}, 120)
        self.assertAlmostEqual(check["required_area_m2"], 12 * 7.83 + 5 * 4.29)
        self.assertEqual(check["status"], "meets_area_minimum")

    def test_school_boundary_uses_correct_affine_branch(self):
        for key, students, expected in [("kr.school.kindergarten.1", 40, 200), ("kr.school.kindergarten.41", 41, 203),
                                        ("kr.school.elementary_school.1", 240, 1680), ("kr.school.elementary_school.241", 241, 1684)]:
            with self.subTest(key=key):
                result = self.evaluate(key, {"authorized_students": students}, expected)
                self.assertEqual(result["required_area_m2"], expected)
                self.assertEqual(result["status"], "meets_area_minimum")

    def test_user_boolean_cannot_confirm_future_edition(self):
        check = self.evaluate("kr.childcare.facility", {"children": 20}, 100, date="2027-01-01",
                              source_edition_confirmed={"kr.childcare.facility": True})
        self.assertEqual(check["status"], "needs_evidence")
        self.assertIn("source_edition_unconfirmed", check["reason_codes"])

    def test_net_area_cannot_satisfy_elderly_gfa(self):
        result = self.evaluate("kr.elderly.nursing_gfa", {"residents": 10}, 300,
            areas={"facility_gfa": {"value": 300, "unit": "m2", "basis": "net", "source_ref": "plan"}})
        self.assertEqual(result["status"], "needs_input")

    def test_each_registered_rule_has_exact_source_and_runs_with_scoped_facts(self):
        for rule in FACILITY_AREA_RULES:
            with self.subTest(rule=rule["rule_id"]):
                document = source_snapshot(rule["source"]["source_id"])
                self.assertEqual(document["annex_text_sha256"], rule["source"]["sha256"])
                quantity = max(rule["minimum_quantity"], rule.get("quantity_range", {}).get("minimum", 1))
                quantities = {rule["quantity_fact"]: quantity}
                for term in rule.get("area_terms", []):
                    quantities.setdefault(term["quantity_fact"], 0)
                check = self.evaluate(rule["rule_id"], quantities, 100000)
                self.assertEqual(check["status"], "meets_area_minimum", check)
