import copy
import hashlib
import unittest

from backend.app.modules.law.reference.design_review import compile_rules, review_design_state


def example():
    source = {"url": "https://www.law.go.kr/example", "article": "synthetic fixture",
              "excerpt": "Synthetic minimum clear width 1.2m, not a statutory rule.",
              "effective_from": "2026-01-01", "edition_checked_on": "2026-09-13"}
    source["excerpt_sha256"] = hashlib.sha256(source["excerpt"].encode()).hexdigest()
    rule = {"rule_id": "fixture-width", "scope": "plan", "source": source,
            "input_nodes": ["geometry.plan"], "applies_when": [],
            "requirements": [{"fact": "clear_width", "operator": "gte", "value": 1.2, "unit": "m", "basis": "clear"}]}
    state = {"assessment_date": "2026-09-13", "versions": {"geometry.plan": 2}, "review_scopes": ["plan"],
             "facts": [{"fact_id": "clear_width", "value": 1.2, "unit": "m", "basis": "clear",
                        "source_ref": "measurement-1", "input_node": "geometry.plan", "input_version": 2}]}
    return state, rule


class DesignReviewTests(unittest.TestCase):
    def test_request_hash_binds_rules_and_complete_design_state(self):
        from backend.app.modules.law.reference.design_review import _hash
        state, rule = example()
        initial = review_design_state(state, [rule])
        self.assertEqual(initial['request_hash'], _hash({'design_state': state, 'rules': [rule]}))
        rule['requirements'][0]['value'] = 1.3
        changed = review_design_state(state, [rule])
        self.assertEqual(initial['input_hash'], changed['input_hash'])
        self.assertNotEqual(initial['request_hash'], changed['request_hash'])
        state['project_id'] = 'different-project'
        self.assertNotEqual(changed['request_hash'], review_design_state(state, [rule])['request_hash'])

    def test_exact_boundary_and_violation_preserve_source(self):
        state, rule = example()
        result = review_design_state(state, [rule])
        self.assertEqual(result["checks"][0]["status"], "meets_constraint")
        self.assertFalse(result["permit_ready"])
        self.assertFalse(result["checks"][0]["source_verified"])
        state["facts"][0]["value"] = 1.1999
        result = review_design_state(state, [rule])
        self.assertEqual(result["checks"][0]["status"], "violates_constraint")
        self.assertEqual(result["violations"][0]["source"], rule["source"])

    def test_stale_measurement_cannot_pass(self):
        state, rule = example()
        state["versions"]["geometry.plan"] = 3
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_evidence")

    def test_missing_input_and_basis_do_not_pass(self):
        state, rule = example()
        state["facts"] = []
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_input")
        state, rule = example()
        state["facts"][0]["basis"] = "centerline"
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_evidence")

    def test_no_rules_is_not_reviewed_and_no_mutation(self):
        state, _ = example()
        before = copy.deepcopy(state)
        result = review_design_state(state, [])
        self.assertEqual(result["status"], "needs_evidence")
        self.assertEqual(result["coverage"]["uncovered_scopes"], ["plan"])
        self.assertEqual(state, before)

    def test_source_hash_and_future_edition_rejected(self):
        state, rule = example()
        rule["source"]["excerpt"] += " tamper"
        with self.assertRaises(ValueError):
            compile_rules([rule])
        state, rule = example()
        rule["source"]["effective_from"] = "2027-01-01"
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_evidence")

    def test_exception_needs_evidence_and_false_scope_is_not_applicable(self):
        state, rule = example()
        rule["applies_when"] = [{"fact": "exception_excluded", "operator": "eq", "value": True}]
        result = review_design_state(state, [rule])
        self.assertEqual(result["checks"][0]["status"], "needs_input")
        state["facts"].append({"fact_id": "exception_excluded", "value": False, "source_ref": "permit-doc",
                               "input_node": "geometry.plan", "input_version": 2})
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "not_applicable")

    def test_nonfinite_boolean_numeric_duplicate_ids_rejected(self):
        state, rule = example()
        rule["requirements"][0]["value"] = float("nan")
        with self.assertRaises(ValueError):
            compile_rules([rule])
        state, rule = example()
        state["facts"][0]["value"] = True
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_input")
        state, rule = example()
        with self.assertRaises(ValueError):
            compile_rules([rule, rule])

    def test_unbound_node_cannot_be_used(self):
        state, rule = example()
        state["facts"][0]["input_node"] = "geometry.mass"
        state["versions"]["geometry.mass"] = 2
        self.assertEqual(review_design_state(state, [rule])["checks"][0]["status"], "needs_evidence")

    def test_scope_filter_only_evaluates_requested_stage(self):
        state, rule = example()
        state["review_scopes"] = ["mass"]
        result = review_design_state(state, [rule])
        self.assertEqual(result["checks"], [])
        self.assertEqual(result["coverage"]["uncovered_scopes"], ["mass"])

    def test_known_violation_survives_another_missing_requirement(self):
        state, rule = example()
        state["facts"][0]["value"] = 0.5
        rule["requirements"].append({"fact": "height", "operator": "gte", "value": 2, "unit": "m"})
        result = review_design_state(state, [rule])
        self.assertEqual(result["status"], "conflict")
        self.assertEqual(len(result["violations"]), 1)
        self.assertEqual(result["missing_inputs"], ["height"])


if __name__ == "__main__":
    unittest.main()
