from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from unittest import TestCase as SimpleTestCase

from backend.app.modules.design.generation.maas import creative_program_author
from backend.app.modules.design.generation.maas.creative_floor_portfolio import build_creative_floor_portfolio
from backend.app.modules.design.generation.maas.creative_program_author import CreativeAuthoredProgram, authored_programs_from_payload, normalize_authored_programs
from backend.app.modules.design.generation.maas.geometry_language.programs import GeometryProgramBuilder
from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram


def _authored_unitbox_program():
    builder = GeometryProgramBuilder("llm_authored_unclassified_mass")
    body = builder.add(
        "primitive",
        "box",
        parameters={
            "width": 1.0,
            "depth": 0.72,
            "height": 1.35,
        },
        semantic_role="llm_authored_body",
    )
    return builder.build(
        body,
        author_provider="test_structured_llm",
        author_model="test-model",
        author_response_id="response-001",
        author_prompt_contract="typed_ast_test",
    )


class CreativeProgramAuthorTests(SimpleTestCase):
    def test_cached_authored_program_lowers_affine_shorthands(self):
        program = GeometryProgram(
            nodes=(
                GeometryNode(
                    "unit",
                    "primitive",
                    "box",
                    parameters={
                        "width": 1.0,
                        "depth": 1.0,
                        "height": 1.0,
                    },
                ),
                GeometryNode(
                    "bar",
                    "transform",
                    "scale",
                    inputs=("unit",),
                    parameters={"vector": [2.8, 0.62, 0.48]},
                    semantic_role="base_seed",
                ),
            ),
            root_id="bar",
            name="cached_affine_shorthand",
        )
        cached = CreativeAuthoredProgram(
            program=program,
            author_evidence={"cache_hit": True},
        )

        normalized = normalize_authored_programs((cached,))[0]

        self.assertEqual(normalized.author_evidence, {"cache_hit": True})
        self.assertEqual(
            [node.operator for node in normalized.program.topological_nodes()],
            ["box", "matrix4"],
        )
        self.assertEqual(
            normalized.program.metadata["affine_authority"],
            "explicit_matrix4",
        )

    def _accepted_cache_programs(
        self,
    ) -> tuple[GeometryProgram, GeometryProgram]:
        first = _authored_unitbox_program()
        second_builder = GeometryProgramBuilder(
            "llm_authored_cut_corner_mass"
        )
        second_body = second_builder.add(
            "primitive",
            "box",
            parameters={"width": 1.0, "depth": 1.0, "height": 1.0},
        )
        second_root = second_builder.add(
            "macro",
            "cut_corner",
            inputs=(second_body,),
            parameters={"corner": "ne", "ratio": 0.24},
        )
        second = second_builder.build(
            second_root,
            author_provider="test_structured_llm",
            author_model="test-model",
            author_response_id="response-002",
            author_prompt_contract="typed_ast_test",
        )
        return first, second

    def _write_accepted_cache(
        self,
        cache_root: Path,
        programs: tuple[GeometryProgram, ...],
    ) -> None:
        cache_root.mkdir(parents=True, exist_ok=True)
        (cache_root / "accepted.json").write_text(
            json.dumps({
                "cache_schema_version": (
                    "arr.maas.geometry_llm_author_cache.v3"
                ),
                "validation_status": "accepted",
                "model": "cache-pool-model",
                "response_id": "resp-cache-pool",
                "compiled_programs": [
                    program.to_dict() for program in programs
                ],
            }),
            encoding="utf-8",
        )

    def test_cache_scan_returns_available_unique_programs_without_exact_count(
        self,
    ):
        with TemporaryDirectory() as temporary:
            cache_root = Path(temporary)
            first, second = self._accepted_cache_programs()
            self._write_accepted_cache(
                cache_root,
                (first, second),
            )

            programs = creative_program_author.cached_authored_programs(
                cache_root,
                limit=20,
            )

        self.assertEqual(len(programs), 2)
        self.assertTrue(
            all(item.author_evidence["cache_hit"] for item in programs)
        )

    def test_cache_scan_skips_legacy_program_without_unitbox_authority(self):
        legacy = GeometryProgram(
            nodes=(GeometryNode(
                "legacy_cylinder",
                "primitive",
                "cylinder",
                parameters={"radius": 1.0, "height": 1.0},
            ),),
            root_id="legacy_cylinder",
            name="legacy_non_unitbox_cache_record",
        )
        accepted = _authored_unitbox_program()
        with TemporaryDirectory() as temporary:
            cache_root = Path(temporary)
            self._write_accepted_cache(cache_root, (legacy, accepted))

            programs = creative_program_author.cached_authored_programs(
                cache_root,
                limit=20,
            )

        self.assertEqual(len(programs), 1)
        self.assertEqual(
            programs[0].program.metadata["base_volume_authority"],
            "1/1 UnitBox",
        )

    def test_exact_geometry_program_document_is_a_replayable_author_payload(
        self,
    ):
        program = _authored_unitbox_program()

        try:
            authored = authored_programs_from_payload(
                program.to_dict(),
                expected_count=1,
            )
        except Exception as exc:
            self.fail(f"exact program replay payload was rejected: {exc}")

        self.assertEqual(len(authored), 1)
        self.assertEqual(
            authored[0].program.program_hash(),
            program.program_hash(),
        )

    def test_llm_box_dimensions_lower_to_one_unitbox_plus_matrix4(self):
        program = GeometryProgram(
            nodes=(GeometryNode(
                "authored_box",
                "primitive",
                "box",
                parameters={
                    "width": 2.8,
                    "depth": 0.62,
                    "height": 0.48,
                },
            ),),
            root_id="authored_box",
            name="raw_llm_box",
            metadata={"author_provider": "structured_llm"},
        )

        try:
            portfolio = build_creative_floor_portfolio(
                count=1,
                authored_programs=(program,),
            )
        except ValueError as exc:
            self.fail(f"LLM box was not normalized to UnitBox: {exc}")

        nodes = portfolio["candidates"][0]["geometry_program"]["nodes"]
        unitboxes = [
            node for node in nodes
            if node["kind"] == "primitive"
            and node["operator"] == "box"
            and node["parameters"]
            == {"width": 1.0, "depth": 1.0, "height": 1.0}
        ]
        matrix_nodes = [
            node for node in nodes
            if node["operator"] == "matrix4"
        ]
        self.assertEqual(len(unitboxes), 1)
        self.assertGreaterEqual(len(matrix_nodes), 2)

    def test_injected_authored_program_never_consults_recipe_registry(self):
        program = _authored_unitbox_program()

        with patch(
            'backend.app.modules.design.generation.maas.creative_floor_portfolio.balanced_family_schedule',
            side_effect=AssertionError(
                "authored programs must not schedule recipes"
            ),
        ), patch(
            'backend.app.modules.design.generation.maas.creative_floor_portfolio.registered_creative_recipes',
            side_effect=AssertionError(
                "authored programs must not load recipes"
            ),
        ):
            try:
                portfolio = build_creative_floor_portfolio(
                    count=1,
                    authored_programs=(program,),
                )
            except TypeError as exc:
                self.fail(f"authored program input is unavailable: {exc}")

        candidate = portfolio["candidates"][0]
        self.assertEqual(portfolio["author_mode"], "authored_programs")
        self.assertTrue(candidate["family"].startswith("morph-"))
        self.assertEqual(
            candidate["author_evidence"],
            {
                "schema_version": "arr.maas.creative_author_evidence.v1",
                "source_kind": "llm_authored_geometry_program",
                "provider": "test_structured_llm",
                "model": "test-model",
                "response_id": "response-001",
                "cache_hit": False,
                "prompt_contract": "typed_ast_test",
            },
        )
        self.assertEqual(
            candidate["lineage"]["stages"][0],
            "llm_authored_geometry_program",
        )
