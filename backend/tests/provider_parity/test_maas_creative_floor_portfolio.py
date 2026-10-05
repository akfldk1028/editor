from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

from collections import Counter
from dataclasses import replace
import importlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from backend.app.modules.design.generation.maas.creative_family_contract import CreativeRecipeContext
from backend.app.modules.design.generation.maas.creative_family_registry import balanced_family_schedule, registered_creative_recipes
from backend.app.modules.design.generation.maas.creative_book_supply import creative_book_schedule
from backend.app.modules.design.generation.maas.creative_program_author import CreativeAuthoredProgram, cached_authored_programs, normalize_authored_programs
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.programs import GeometryProgramBuilder


MODULE = 'backend.app.modules.design.generation.maas.creative_floor_portfolio'
EXPECTED_FAMILIES = {
    "bent",
    "carved_void",
    "courtyard",
    "cross",
    "grid",
    "inflated",
    "notch",
    "radial",
    "split_wing",
    "stepped",
    "triangular_shard",
    "oblique_crystal",
    "thin_disc_cluster",
    "interlocking_tilted_discs",
    "long_span_bridge",
}
EXPECTED_CAPACITY_BANDS = {
    "spatial_reserve",
    "balanced_yield",
    "brief_target",
    "maximum_target",
}
EXPECTED_BOOK_SCOPES = ("1/1", "1/2", "3/8", "1/4", "1/8", "1/16")


class CreativeFloorSetIdentityTests(unittest.TestCase):
    def test_marker_cannot_hide_an_unrelated_union_input(self):
        host = GeometryNode(
            "host",
            "primitive",
            "box",
            parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        )
        unrelated = GeometryNode(
            "unrelated",
            "transform",
            "matrix4",
            inputs=(host.id,),
            parameters={
                "matrix4": [
                    [1.0, 0.0, 0.0, 3.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
            },
        )
        marked_union = GeometryNode(
            "marked_union",
            "boolean",
            "union",
            inputs=(host.id, unrelated.id),
            provenance={
                "set_identity": "host_union_subsets_equals_host",
            },
        )
        compilation = compile_geometry_program(GeometryProgram(
            (host, unrelated, marked_union),
            marked_union.id,
            name="malformed_floor_subset_identity",
        ))

        self.assertFalse(compilation.issues)
        self.assertAlmostEqual(compilation.metrics["volume"], 2.0, places=6)
        self.assertEqual(compilation.metrics["component_count"], 2)
        self.assertAlmostEqual(
            compilation.metrics["bounds"][1][0],
            4.0,
            places=6,
        )


class CreativePortfolioScheduleAuthorityTests(unittest.TestCase):
    def test_each_scheduled_item_materializes_one_compatible_book_assignment(self):
        module = importlib.import_module(MODULE)
        schedule = balanced_family_schedule(15)
        calls: dict[str, list[CreativeRecipeContext]] = {
            item.family_id: [] for item in schedule
        }
        wrapped = []
        for recipe in registered_creative_recipes():
            original_builder = recipe.builder

            def recording_builder(context, *, _recipe=recipe, _builder=original_builder):
                calls[_recipe.family_id].append(context)
                return _builder(context)

            wrapped.append(replace(recipe, builder=recording_builder))

        with patch.object(
            module,
            "registered_creative_recipes",
            return_value=tuple(wrapped),
        ):
            portfolio = module.build_creative_floor_portfolio(
                count=15,
                capacity_ceiling_m2=332.322,
            )

        for item, candidate in zip(schedule, portfolio["candidates"]):
            evidence = candidate["book_language_evidence"]
            self.assertTrue(evidence["materialized"])
            self.assertTrue(any(
                context.variation_index == item.context.variation_index
                and context.capacity_band == item.context.capacity_band
                and context.book_principle_id == evidence["principle_id"]
                and context.book_scope_label == evidence["scope_label"]
                for context in calls[item.family_id]
            ))
            self.assertEqual(
                candidate["variation_index"],
                item.context.variation_index,
            )
            self.assertEqual(
                candidate["geometry_program"]["metadata"]["variation_index"],
                item.context.variation_index,
            )

    def test_invalid_scheduled_candidate_fails_once_with_context_diagnostic(self):
        module = importlib.import_module(MODULE)
        recipe = registered_creative_recipes()[0]
        calls = []

        def recording_builder(context):
            calls.append(context)
            return recipe.builder(context)

        wrapped = replace(recipe, builder=recording_builder)
        with (
            patch.object(
                module,
                "registered_creative_recipes",
                return_value=(wrapped,),
            ),
            patch.object(module, "_compile_candidate", return_value=None),
            self.assertRaisesRegex(
                RuntimeError,
                (
                    r"invalid scheduled creative candidate:"
                    r".*family=bent.*variation=0"
                    r".*book_scope=1/1.*capacity_band=spatial_reserve"
                ),
            ),
        ):
            module.build_creative_floor_portfolio(count=1)

        self.assertEqual(calls, [balanced_family_schedule(1)[0].context])

    def test_duplicate_scheduled_candidate_fails_once_with_hash_diagnostic(self):
        module = importlib.import_module(MODULE)
        recipes = registered_creative_recipes()[:2]
        calls = Counter()
        wrapped = []
        for recipe in recipes:
            original_builder = recipe.builder

            def recording_builder(context, *, _recipe=recipe, _builder=original_builder):
                calls[_recipe.family_id] += 1
                return _builder(context)

            wrapped.append(replace(recipe, builder=recording_builder))
        duplicate = {
            "candidate_id": "creative-test",
            "family": "test",
            "program_hash": "same-program",
            "geometry_hash": "same-geometry",
            "normalized_authored_mesh_hash": "same-normalized",
            "morphology_evidence": {
                "descriptor": {
                    "schema_version": "arr.maas.creative_morphology.v1",
                    "axis_ratios": [0.0] * 3,
                    "z_slice_occupancies": [0.0] * 8,
                    "floor_area_profile": [0.0] * 8,
                    "convexity": 0.0,
                    "void_fraction": 0.0,
                    "normal_bins": [0.0] * 12,
                    "radial_bins": [0.0] * 8,
                    "silhouette_front": [0.0] * 16,
                    "silhouette_side": [0.0] * 16,
                    "silhouette_isometric": [0.0] * 16,
                    "component_count": 1,
                    "contact_topology": "core",
                },
            },
        }

        with (
            patch.object(
                module,
                "registered_creative_recipes",
                return_value=tuple(wrapped),
            ),
            patch.object(
                module,
                "_compile_candidate",
                return_value=duplicate,
            ),
            self.assertRaisesRegex(
                RuntimeError,
                (
                    r"duplicate scheduled creative candidate:"
                    r".*family=carved_void.*variation=0"
                    r".*program_hash.*geometry_hash"
                ),
            ),
        ):
            module.build_creative_floor_portfolio(count=2)

        self.assertEqual(calls, Counter({"bent": 1, "carved_void": 1}))


class ThinDiscPortfolioRegressionTests(unittest.TestCase):
    def test_quarter_scope_variation_three_materializes_one_component(self):
        module = importlib.import_module(MODULE)
        recipes = {
            recipe.family_id: recipe
            for recipe in registered_creative_recipes()
        }
        recipe = recipes["thin_disc_cluster"]
        context = CreativeRecipeContext(
            variation_index=3,
            book_scope_label="1/4",
            capacity_band="balanced_yield",
        )
        result = recipe.builder(context)

        candidate = module._compile_candidate(
            result,
            family=recipe.family_id,
            source_family=recipe.family_id,
            family_index=12,
            variation_index=context.variation_index,
            candidate_index=57,
            capacity_band=context.capacity_band,
            capacity_ceiling_m2=332.322,
        )

        self.assertIsNotNone(candidate)
        assert candidate is not None
        self.assertEqual(
            candidate["mesh_evidence"]["component_count"],
            1,
        )
        self.assertEqual(
            candidate["connectivity_evidence"]["witness_node_id"],
            result.contact_node_id,
        )


class CreativeFloorPortfolioReportTests(unittest.TestCase):
    def test_author_original_survives_as_option_with_linked_exploration(self):
        module = importlib.import_module(MODULE)
        authored = self.valid_authored("only")
        report = module.build_creative_floor_portfolio_report(
            target_count=1, capacity_ceiling_m2=332.322,
            authored_programs=(authored,),
        )
        originals = [r for r in report.candidates if r.get("candidate_origin") == "authored_original"]
        children = [r for r in report.candidates if r.get("candidate_origin") == "book_exploration"]
        self.assertEqual(len(originals), 1)
        self.assertEqual(len(children), 1)
        self.assertEqual(originals[0]["source_program_hash"], authored.program.program_hash())
        self.assertEqual(originals[0]["authored_geometry_program"], authored.program.to_dict())
        self.assertEqual(
            originals[0]["normalized_authored_mesh_hash"],
            module._normalized_mesh_hash(module.compile_geometry_program(authored.program)),
        )
        self.assertEqual(children[0]["parent_program_hash"], originals[0]["source_program_hash"])
        self.assertEqual(children[0]["parent_geometry_program"], authored.program.to_dict())
        self.assertFalse(originals[0].get("book_language_evidence"))
        self.assertEqual(len({r["candidate_id"] for r in report.candidates}), 2)
        self.assertEqual(report.exploration_count, 1)

    def test_failed_exploration_cannot_erase_original_or_claim_completion(self):
        module = importlib.import_module(MODULE)
        with patch.object(module, "project_creative_book_program", side_effect=ValueError("no feasible projection")):
            report = module.build_creative_floor_portfolio_report(
                target_count=1, capacity_ceiling_m2=332.322,
                authored_programs=(self.valid_authored("only"),),
            )
        self.assertEqual(len(report.candidates), 1)
        self.assertEqual(report.candidates[0]["candidate_origin"], "authored_original")
        self.assertEqual(report.status, "partial")
        self.assertEqual(report.deficit, 1)
        self.assertEqual(report.language_coverage["materialized_count"], 0)

    @staticmethod
    def _author_evidence(label: str) -> dict:
        return {
            "schema_version": "arr.maas.creative_author_evidence.v1",
            "source_kind": "llm_authored_geometry_program",
            "provider": "test_structured_llm",
            "model": "test-model",
            "response_id": f"response-{label}",
            "cache_hit": False,
            "prompt_contract": "typed_ast_test",
        }

    def valid_authored(self, label: str) -> CreativeAuthoredProgram:
        ratios = {"first": 0.18, "second": 0.32, "only": 0.24}
        builder = GeometryProgramBuilder(f"valid_authored_{label}")
        body = builder.add(
            "primitive",
            "box",
            parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        )
        root = builder.add(
            "macro",
            "cut_corner",
            inputs=(body,),
            parameters={"corner": "ne", "ratio": ratios[label]},
        )
        return CreativeAuthoredProgram(
            program=builder.build(root),
            author_evidence=self._author_evidence(label),
        )

    def disconnected_authored(self, label: str) -> CreativeAuthoredProgram:
        builder = GeometryProgramBuilder(f"disconnected_authored_{label}")
        body = builder.add(
            "primitive",
            "box",
            parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        )
        root = builder.add(
            "pattern",
            "linear_array",
            inputs=(body,),
            parameters={"count": 2, "vector": [3.0, 0.0, 0.0]},
        )
        return CreativeAuthoredProgram(
            program=builder.build(root),
            author_evidence=self._author_evidence(label),
        )

    def same_mesh_different_metadata_programs(
        self,
    ) -> tuple[CreativeAuthoredProgram, CreativeAuthoredProgram]:
        first = self.valid_authored("only")
        identity = GeometryNode(
            "metadata_only_identity",
            "transform",
            "matrix4",
            inputs=(first.program.root_id,),
            parameters={
                "matrix4": [
                    [1.0, 0.0, 0.0, 0.0],
                    [0.0, 1.0, 0.0, 0.0],
                    [0.0, 0.0, 1.0, 0.0],
                    [0.0, 0.0, 0.0, 1.0],
                ],
            },
        )
        second_program = replace(
            first.program,
            nodes=(*first.program.nodes, identity),
            root_id=identity.id,
            name="same_mesh_different_family",
            metadata={
                **first.program.metadata,
                "family": "metadata_only_family",
            },
        )
        return first, CreativeAuthoredProgram(
            program=second_program,
            author_evidence=self._author_evidence("metadata"),
        )

    def test_report_counts_each_stage_and_retains_valid_candidates_after_rejections(
        self,
    ):
        module = importlib.import_module(MODULE)
        report = module.build_creative_floor_portfolio_report(
            target_count=2,
            capacity_ceiling_m2=332.322,
            authored_programs=(
                self.valid_authored("first"),
                self.disconnected_authored("invalid"),
                self.valid_authored("first"),
                self.valid_authored("second"),
            ),
        )

        self.assertEqual(report.status, "complete")
        self.assertEqual(report.stage_counts["author_input"], 4)
        self.assertEqual(report.stage_counts["unique_program_hash"], 3)
        self.assertEqual(report.stage_counts["canonical_compile_pass"], 3)
        self.assertEqual(report.stage_counts["structural_pass"], 2)
        self.assertEqual(report.rejection_counts["duplicate_program_hash"], 1)
        self.assertEqual(report.stage_counts["morphology_retained"], 2)
        self.assertEqual(len(report.candidates), 4)
        self.assertEqual(report.exploration_count, 2)
        eligible_source_ids = sorted({
            authored.program.program_hash()
            for authored in normalize_authored_programs((
                self.valid_authored("first"), self.valid_authored("second"),
            ))
        })
        self.assertEqual(report.schedule_evidence["source_ids"], eligible_source_ids)
        self.assertEqual(
            [
                row["book_language_evidence"]["principle_id"]
                for row in report.candidates
                if row["candidate_origin"] == "book_exploration"
            ],
            [
                item.principle_id
                for item in creative_book_schedule(
                    2, authored_source_ids=eligible_source_ids,
                )
            ],
        )

    def test_cached_target_twenty_materializes_distinct_book_lineage(self):
        module = importlib.import_module(MODULE)
        cache_root = (
            Path(__file__).parent
            / "fixtures"
            / "geometry-author-cache"
        )
        authored = cached_authored_programs(cache_root, limit=60)
        self.assertGreaterEqual(len(authored), 20)

        report = module.build_creative_floor_portfolio_report(
            target_count=20,
            capacity_ceiling_m2=332.322,
            authored_programs=authored,
        )

        self.assertEqual(report.status, "complete")
        self.assertEqual(len(report.candidates), 40)
        self.assertEqual(report.exploration_count, 20)
        self.assertEqual(len({r["candidate_id"] for r in report.candidates}), 40)
        self.assertEqual(len({r["geometry_hash"] for r in report.candidates}), 40)
        self.assertEqual(
            report.language_coverage["distinct_principle_count"],
            20,
        )
        self.assertEqual(
            set(report.language_coverage["scope_counts"]),
            {"1/1", "3/8", "1/2", "1/4", "1/8", "1/16"},
        )
        self.assertTrue(all(
            row["book_language_evidence"]["materialized"]
            for row in report.candidates
            if row["candidate_origin"] == "book_exploration"
        ))

    def test_report_returns_partial_instead_of_raising_when_supply_is_short(
        self,
    ):
        module = importlib.import_module(MODULE)
        report = module.build_creative_floor_portfolio_report(
            target_count=3,
            capacity_ceiling_m2=332.322,
            authored_programs=(self.valid_authored("only"),),
        )

        self.assertEqual(report.status, "partial")
        self.assertEqual(report.stage_counts["morphology_retained"], 1)
        self.assertEqual(report.deficit, 2)

    def test_distinct_book_principles_materially_separate_same_source_mesh(
        self,
    ):
        module = importlib.import_module(MODULE)
        report = module.build_creative_floor_portfolio_report(
            target_count=2,
            capacity_ceiling_m2=332.322,
            authored_programs=self.same_mesh_different_metadata_programs(),
        )

        self.assertEqual(report.status, "complete")
        self.assertEqual(len(report.candidates), 3)
        self.assertEqual(report.exploration_count, 2)
        self.assertEqual(
            len({
                row["normalized_authored_mesh_hash"]
                for row in report.candidates
            }),
            3,
        )
        self.assertEqual(
            len({
                row["book_language_evidence"]["principle_id"]
                for row in report.candidates
                if row["candidate_origin"] == "book_exploration"
            }),
            2,
        )


class CreativeFloorPortfolioTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        spec = importlib.util.find_spec(MODULE)
        if spec is None:
            cls.portfolio = None
            return
        module = importlib.import_module(MODULE)
        cls.portfolio = module.build_creative_floor_portfolio(
            count=100,
            capacity_ceiling_m2=332.322,
        )

    def _candidates(self) -> list[dict]:
        self.assertIsNotNone(
            self.portfolio,
            "creative floor portfolio module must exist",
        )
        assert self.portfolio is not None
        candidates = self.portfolio.get("candidates")
        self.assertIsInstance(candidates, list)
        return candidates

    def test_returns_exactly_one_hundred_unique_programs_and_meshes(self):
        candidates = self._candidates()

        self.assertEqual(len(candidates), 100)
        self.assertEqual(
            len({row["program_hash"] for row in candidates}),
            100,
        )
        self.assertEqual(
            len({row["geometry_hash"] for row in candidates}),
            100,
        )

    def test_count_hundred_covers_complete_executable_book_grammar(self):
        assert self.portfolio is not None
        coverage = self.portfolio["book_language_coverage"]

        self.assertEqual(coverage["base_operative_count"], 30)
        self.assertEqual(coverage["combination_count"], 20)
        self.assertEqual(coverage["aggregation_count"], 9)
        self.assertEqual(coverage["missing_principle_ids"], [])
        for row in self._candidates():
            operators = {
                node["operator"]
                for node in row["geometry_program"]["nodes"]
            }
            self.assertEqual(
                sum(
                    node["kind"] == "primitive"
                    and node["operator"] == "box"
                    for node in row["geometry_program"]["nodes"]
                ),
                1,
            )
            self.assertFalse(
                {"scale", "rotate", "translate", "mirror", "shear"}
                & operators
            )

    def test_fifteen_named_families_have_balanced_quotas(self):
        family_counts = Counter(row["family"] for row in self._candidates())

        self.assertEqual(set(family_counts), EXPECTED_FAMILIES)
        self.assertEqual(set(family_counts.values()), {6, 7})
        self.assertLessEqual(
            max(family_counts.values()) - min(family_counts.values()),
            1,
        )

    def test_four_capacity_bands_are_balanced_to_twenty_five_each(self):
        candidates = self._candidates()
        band_counts = Counter(row["capacity_band"] for row in candidates)

        self.assertEqual(set(band_counts), EXPECTED_CAPACITY_BANDS)
        self.assertEqual(set(band_counts.values()), {25})
        for family in EXPECTED_FAMILIES:
            self.assertEqual(
                {
                    row["capacity_band"]
                    for row in candidates
                    if row["family"] == family
                },
                EXPECTED_CAPACITY_BANDS,
                family,
            )
        self.assertTrue(all(
            row["storey_evidence"]["target_gfa_m2"] == 332.322
            for row in candidates
            if row["capacity_band"] == "maximum_target"
        ))
        self.assertEqual(
            self.portfolio["capacity_authority"],
            "user_supplied_prelegal_target",
        )

    def test_stepped_candidates_use_only_one_family_quota(self):
        stepped = [
            row
            for row in self._candidates()
            if row["family"] == "stepped"
        ]

        self.assertLessEqual(len(stepped), 7)
        self.assertTrue(all(row["form_class"] == "stepped" for row in stepped))
        self.assertTrue(all(
            row["form_class"] != "stepped"
            for row in self._candidates()
            if row["family"] != "stepped"
        ))

    def test_programs_keep_one_unitbox_and_a_physical_root_matrix4(self):
        for row in self._candidates():
            program = row["geometry_program"]
            nodes = program["nodes"]
            unitboxes = [
                node
                for node in nodes
                if (
                    node["kind"] == "primitive"
                    and node["operator"] == "box"
                    and node["parameters"]
                    == {"width": 1.0, "depth": 1.0, "height": 1.0}
                )
            ]
            matrices = [
                node
                for node in nodes
                if node["kind"] == "transform"
                and node["operator"] == "matrix4"
            ]
            root = next(
                node for node in nodes
                if node["id"] == program["root_id"]
            )
            physical_envelope = next(
                node for node in nodes
                if node["id"]
                == row["lineage"]["physical_envelope_node_id"]
            )

            self.assertEqual(len(unitboxes), 1, row["candidate_id"])
            self.assertGreaterEqual(len(matrices), 1, row["candidate_id"])
            self.assertEqual(root["operator"], "union")
            self.assertEqual(physical_envelope["operator"], "matrix4")
            self.assertEqual(
                physical_envelope["semantic_role"],
                "physical_storey_capacity_fit",
            )
            self.assertEqual(
                len([
                    trace
                    for trace in row["matrix4_trace"]
                    if trace["node_id"]
                    == row["lineage"]["physical_envelope_node_id"]
                ]),
                1,
            )

    def test_every_source_receives_active_book_projection_and_balanced_scopes(self):
        candidates = self._candidates()
        scope_counts = Counter()
        for row in candidates:
            program = row["geometry_program"]
            projection = program["metadata"]["book_recursive_projection"]
            operators = {node["operator"] for node in program["nodes"]}

            self.assertIs(projection["active"], True, row["candidate_id"])
            self.assertTrue(projection["ordered_verbs"], row["candidate_id"])
            scope_counts[projection["scope_label"]] += 1
            evidence = row["book_language_evidence"]
            self.assertTrue(evidence["materialized"], row["candidate_id"])
            self.assertTrue(evidence["projected_node_ids"], row["candidate_id"])
            if row["family"] == "stepped":
                self.assertIn("stepped_mass", operators)

        self.assertEqual(set(scope_counts), set(EXPECTED_BOOK_SCOPES))
        self.assertLessEqual(max(scope_counts.values()) - min(scope_counts.values()), 1)

    def test_every_compiled_mesh_is_connected_watertight_and_manifold(self):
        for row in self._candidates():
            evidence = row["mesh_evidence"]
            mesh = row["mesh"]

            self.assertTrue(evidence["connected"], row["candidate_id"])
            self.assertTrue(evidence["watertight"], row["candidate_id"])
            self.assertTrue(evidence["manifold"], row["candidate_id"])
            self.assertEqual(evidence["component_count"], 1)
            self.assertGreater(len(mesh["vertices"]), 0)
            self.assertGreater(len(mesh["triangles"]), 0)

    def test_floor_evidence_set_identity_preserves_the_physical_envelope(self):
        row = next(
            candidate
            for candidate in self._candidates()
            if (
                candidate["family"] == "cross"
                and candidate["variation_index"] == 0
            )
        )
        final_program = GeometryProgram.from_dict(row["geometry_program"])
        physical_root_id = row["lineage"]["physical_envelope_node_id"]
        node_map = final_program.node_map
        physical_ids: set[str] = set()

        def collect(node_id: str) -> None:
            if node_id in physical_ids:
                return
            physical_ids.add(node_id)
            for input_id in node_map[node_id].inputs:
                collect(input_id)

        collect(physical_root_id)
        physical_program = replace(
            final_program,
            nodes=tuple(
                node
                for node in final_program.nodes
                if node.id in physical_ids
            ),
            root_id=physical_root_id,
        )
        physical = compile_geometry_program(physical_program)
        final = compile_geometry_program(final_program)
        final_root = final_program.node_map[final_program.root_id]

        self.assertEqual(
            final_root.provenance["set_identity"],
            "host_union_subsets_equals_host",
        )
        self.assertEqual(final.geometry_hash, physical.geometry_hash)
        self.assertAlmostEqual(
            float(final.metrics["volume"]),
            float(physical.metrics["volume"]),
            places=6,
        )
        self.assertEqual(final.metrics["component_count"], 1)

    def test_every_candidate_has_physical_storeys_and_positive_floor_evidence(self):
        for row in self._candidates():
            evidence = row["storey_evidence"]
            storeys = evidence["storey_count"]
            floor_areas = evidence["actual_floor_areas_m2"]
            elevations = evidence["floor_elevations_m"]

            self.assertGreaterEqual(storeys, 3)
            self.assertEqual(len(floor_areas), storeys)
            self.assertEqual(len(elevations), storeys + 1)
            self.assertEqual(elevations[0], 0.0)
            self.assertAlmostEqual(
                elevations[-1],
                storeys * 3.3,
                places=6,
            )
            self.assertTrue(all(area > 0.0 for area in floor_areas))
            self.assertAlmostEqual(
                sum(floor_areas),
                evidence["actual_gfa_m2"],
                places=4,
            )
            self.assertGreater(evidence["target_gfa_m2"], 0.0)
            self.assertEqual(
                evidence["capacity_band"],
                row["capacity_band"],
            )
            self.assertEqual(
                evidence.get("authority"),
                "authored_prelegal_horizontal_sections",
            )
            self.assertIs(evidence.get("legal_certified"), False)
            bounds = row["mesh_evidence"]["bounds"]
            self.assertAlmostEqual(
                bounds[1][2] - bounds[0][2],
                storeys * 3.3,
                delta=1e-4,
            )
            program = row["geometry_program"]
            node_map = {node["id"]: node for node in program["nodes"]}
            unitbox_id = row["lineage"]["unitbox_node_id"]
            plate_ids = evidence["floor_plate_node_ids"]
            cutter_ids = evidence["floor_cutter_node_ids"]
            root = node_map[program["root_id"]]

            self.assertEqual(len(plate_ids), storeys)
            self.assertEqual(len(cutter_ids), storeys)
            self.assertEqual(
                len(evidence["floor_plate_compiled_volumes_m3"]),
                storeys,
            )
            self.assertTrue(all(
                volume > 0.0
                for volume in evidence["floor_plate_compiled_volumes_m3"]
            ))
            self.assertEqual(root["operator"], "union")
            self.assertTrue(set(plate_ids).issubset(set(root["inputs"])))
            for plate_id, cutter_id in zip(plate_ids, cutter_ids):
                plate = node_map[plate_id]
                cutter = node_map[cutter_id]
                self.assertEqual(plate["kind"], "boolean")
                self.assertEqual(plate["operator"], "intersection")
                self.assertEqual(
                    plate["semantic_role"],
                    "occupied_floor_plate",
                )
                self.assertEqual(cutter["kind"], "transform")
                self.assertEqual(cutter["operator"], "matrix4")
                self.assertEqual(cutter["inputs"], [unitbox_id])
                self.assertIn(cutter_id, plate["inputs"])

    def test_relational_families_have_a_typed_contact_witness(self):
        relational_families = {
            "split_wing",
            "radial",
            "courtyard",
            "cross",
            "grid",
        }
        allowed_witnesses = {
            "hub",
            "spine",
            "bridge",
            "core",
            "shared_edge",
        }
        preferred_operators = {
            "split_wing": {"split_wing", "bridge"},
            "radial": {"radial_array"},
            "courtyard": {"courtyard"},
            "cross": {"cross_mass"},
            "grid": {"grid_mass"},
        }
        for row in self._candidates():
            if row["family"] not in relational_families:
                continue
            evidence = row["connectivity_evidence"]
            node_ids = {
                node["id"]
                for node in row["geometry_program"]["nodes"]
            }

            self.assertTrue(evidence["hard_pass"], row["candidate_id"])
            self.assertIn(evidence["contact_type"], allowed_witnesses)
            self.assertIn(evidence["witness_node_id"], node_ids)
            self.assertIn(
                evidence["witness_operator"],
                preferred_operators[row["family"]],
            )
            self.assertGreater(evidence["witness_compiled_volume"], 0.0)
            self.assertEqual(evidence["final_component_count"], 1)
            self.assertEqual(
                evidence["measurement"],
                "compiler_trace_positive_volume_and_final_component_count",
            )

    def test_scale_invariant_authored_meshes_are_all_unique(self):
        candidates = self._candidates()
        hashes = [
            row["normalized_authored_mesh_hash"]
            for row in candidates
        ]

        self.assertEqual(len(hashes), 100)
        self.assertEqual(len(set(hashes)), 100)

    def test_every_candidate_persists_passing_morphology_evidence(self):
        candidates = self._candidates()
        for index, row in enumerate(candidates):
            evidence = row["morphology_evidence"]
            descriptor = evidence["descriptor"]
            decision = evidence["decision"]

            self.assertEqual(decision["decision"], "accepted")
            self.assertIs(decision["accepted"], True)
            self.assertEqual(len(descriptor["axis_ratios"]), 3)
            self.assertEqual(len(descriptor["z_slice_occupancies"]), 8)
            self.assertEqual(len(descriptor["floor_area_profile"]), 8)
            self.assertEqual(len(descriptor["normal_bins"]), 12)
            self.assertEqual(len(descriptor["radial_bins"]), 8)
            self.assertEqual(len(descriptor["silhouette_front"]), 16)
            self.assertEqual(len(descriptor["silhouette_side"]), 16)
            self.assertEqual(len(descriptor["silhouette_isometric"]), 16)
            self.assertEqual(descriptor["component_count"], 1)
            self.assertEqual(
                descriptor["contact_topology"],
                row["connectivity_evidence"]["contact_type"],
            )
            if index:
                self.assertGreaterEqual(
                    decision["nearest_distance"],
                    decision["threshold"],
                    row["candidate_id"],
                )
            if decision["nearest_within_family_distance"] is not None:
                self.assertGreaterEqual(
                    decision["nearest_within_family_distance"],
                    decision["within_family_threshold"],
                    row["candidate_id"],
                )

    def test_portfolio_summarizes_actual_morphology_distance_distribution(self):
        summary = self.portfolio["morphology_evidence"]
        distances = [
            row["morphology_evidence"]["decision"]["nearest_distance"]
            for row in self._candidates()[1:]
        ]

        self.assertEqual(summary["accepted_count"], 100)
        self.assertEqual(summary["rejected_count"], 0)
        self.assertEqual(summary["decision"], "accepted")
        self.assertEqual(summary["nearest_distance_distribution"]["count"], 99)
        self.assertAlmostEqual(
            summary["nearest_distance_distribution"]["minimum"],
            min(distances),
            places=12,
        )
        self.assertAlmostEqual(
            summary["nearest_distance_distribution"]["maximum"],
            max(distances),
            places=12,
        )
        self.assertTrue(
            summary["nearest_distance_distribution"]["minimum"]
            >= summary["global_threshold"]
        )

    def test_legal_review_is_pending_and_never_claims_approval(self):
        for row in self._candidates():
            review = row["legal_review"]

            self.assertEqual(review["status"], "not_evaluated")
            self.assertNotEqual(review["status"], "passed")
            self.assertFalse(review["hard_pass"])
            self.assertEqual(
                review["capacity_ceiling_m2"],
                332.322,
            )
            self.assertEqual(
                review["capacity_authority"],
                "user_supplied_prelegal_target",
            )
            self.assertEqual(
                row["storey_evidence"]["capacity_authority"],
                "user_supplied_prelegal_target",
            )
            self.assertEqual(
                row["lineage"]["stages"],
                [
                    "canonical_unitbox",
                    "physical_storey_capacity_matrix4",
                    "typed_book_relation",
                    "connected_mass",
                    "storey_contract",
                    "legal_review_pending",
                ],
            )


if __name__ == "__main__":
    unittest.main()
