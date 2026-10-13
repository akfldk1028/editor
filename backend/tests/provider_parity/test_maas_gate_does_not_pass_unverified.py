"""Counterexamples from the 2026-10-13 external review: a pass must not exceed what was measured."""
from __future__ import annotations

from unittest import TestCase as SimpleTestCase

from shapely.geometry import Polygon, box

from backend.app.modules.design.generation.maas.book_language.downstream_hard_gate import _metrics
from backend.app.modules.design.generation.maas.preference.concept_schema import (
    _concept_scores_from_geometry,
    build_preference_distillation,
)
from backend.app.modules.design.generation.maas.preference.reranker import _hard_gate_pass
from backend.app.modules.design.generation.maas.source_geometry.ir import SourceVolume


class BuildingAreaIsTheHorizontalProjection(SimpleTestCase):
    def test_upper_overhang_counts(self):
        # site 1,600 m2, base 100 m2 on the ground, upper floor 900 m2 above it
        site = box(0, 0, 40, 40)
        base = SourceVolume("body", box(0, 0, 10, 10), 0.0, 0.5, "probe")
        upper = SourceVolume("body", box(0, 0, 30, 30), 0.5, 1.0, "probe")
        metrics = _metrics((base, upper), site, height_m=8.0, floors=2)
        self.assertAlmostEqual(metrics["bcr_pct"], 56.25, places=2)
        self.assertAlmostEqual(metrics["ground_contact_area_m2"], 100.0, places=1)


class MissingEvidenceIsNotAPass(SimpleTestCase):
    def test_absent_legal_pass_does_not_preserve_the_legal_gate(self):
        result = build_preference_distillation({"properties": {}})
        self.assertIs(result["hard_gates"]["legal_gate_preserved"], False)

    def test_reranker_refuses_a_feature_without_hard_gate_evidence(self):
        self.assertFalse(_hard_gate_pass({"properties": {"legal_pass": False}}))
        self.assertFalse(_hard_gate_pass({"properties": {}}))


class ErasedFormScoresZero(SimpleTestCase):
    def test_zero_retention_is_not_full_marks(self):
        scores = _concept_scores_from_geometry({"properties": {"repair_delta": {"area_retention": 0.0}}})
        self.assertEqual(scores["repair_integrity"], 0.0)

    def test_absent_retention_is_an_untouched_form(self):
        scores = _concept_scores_from_geometry({"properties": {}})
        self.assertEqual(scores["repair_integrity"], 1.0)


class DiagonalSetbackAcceptsEitherNearSide(SimpleTestCase):
    """684-1: setback cut sits to the NE (13.7, 14.5); road (0.98, 0.17); author said access east, north north."""

    class _Site:
        def plan_at(self, height):
            ground = box(0, 0, 50, 50)
            return ground if height <= 0 else ground.difference(Polygon([(30, 50), (50, 50), (50, 30)]))

    def test_north_is_accepted_for_a_diagonal_setback(self):
        from backend.app.modules.design.generation.maas.delivered.book_rebuild import _resolve_facing
        angle, evidence = _resolve_facing({"access_side": "east", "north_side": "north"}, self._Site(), 19.0,
                                          road_direction=(0.9847, 0.1744))
        self.assertEqual(evidence["north_status"], "verified_nearest_side")

    def test_a_side_facing_away_is_refused(self):
        from backend.app.modules.design.generation.maas.delivered.book_rebuild import _resolve_facing
        with self.assertRaises(ValueError):
            _resolve_facing({"access_side": "east", "north_side": "south"}, self._Site(), 19.0,
                            road_direction=(0.9847, 0.1744))
