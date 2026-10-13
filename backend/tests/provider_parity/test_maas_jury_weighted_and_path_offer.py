from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory, mkdtemp
from unittest import TestCase as SimpleTestCase

# vlm_shortlist resolves its workspace at import; a scratch one is enough here.
os.environ.setdefault("MASSV2_WS", mkdtemp(prefix="massv2-ws-"))

from backend.app.modules.massing.workspace_tools.vlm_shortlist import (
    VerdictError,
    read_verdict,
    rubric_weights,
)
from backend.app.modules.design.generation.maas.geometry_language.llm_adapter import (
    _book_composition_path_slice,
)

_PROMPT = (
    "**CONCEPT (weight 0.35)** - a\n"
    "**FEASIBILITY (weight 0.25)** - b\n"
    "**SITE (weight 0.20)** - c\n"
    "**EDITABILITY (weight 0.20)** - d\n"
)


def _ballot(weighted: str, concept: str = "4") -> str:
    return (
        "TILE t01\n"
        f"CONCEPT {concept} | strong\n"
        "FEASIBILITY 3 | fine\n"
        "SITE 2 | weak\n"
        "EDITABILITY 4 | ok\n"
        f"WEIGHTED {weighted}\n"
    )


class JuryWeightedIsTheCountsMean(SimpleTestCase):
    def _read(self, text: str, weights=None):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "r1.txt"
            path.write_text(text, encoding="utf-8")
            return read_verdict(path, {"t01"}, weights)

    def test_prompt_weights_are_read(self):
        self.assertEqual(rubric_weights(_PROMPT),
                         {"CONCEPT": 0.35, "FEASIBILITY": 0.25, "SITE": 0.20, "EDITABILITY": 0.20})

    def test_wrong_arithmetic_is_replaced_by_the_counts(self):
        # 0.35*4 + 0.25*3 + 0.20*2 + 0.20*4 = 3.35, the juror wrote 4.50
        self.assertEqual(self._read(_ballot("4.50"), rubric_weights(_PROMPT)), {"t01": 3.35})

    def test_rounding_is_not_an_error(self):
        self.assertEqual(self._read(_ballot("3.35"), rubric_weights(_PROMPT)), {"t01": 3.35})

    def test_without_weights_the_written_number_stands(self):
        self.assertEqual(self._read(_ballot("4.50")), {"t01": 4.5})

    def test_count_outside_the_scale_refuses(self):
        with self.assertRaises(VerdictError):
            self._read(_ballot("3.35", concept="7"), rubric_weights(_PROMPT))


class PathOfferCoversTheRequest(SimpleTestCase):
    def test_offer_is_never_smaller_than_the_request(self):
        context = {"book_graph_vocabulary": {}, "book_path_sampling_version": 2, "creative_portfolio_run_id": "t"}
        for count in (20, 96, 120):
            offered = _book_composition_path_slice(context, count)
            if not offered:
                self.skipTest("BOOK composition lattice unavailable")
            self.assertGreaterEqual(len(offered), min(count, 13662))


class BookParametersReachTheGeometry(SimpleTestCase):
    """puncture spacing and offset pitch used to be dropped or clamped flat."""

    def _compile(self, operator, parameters):
        from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
        from backend.app.modules.design.generation.maas.geometry_language.programs import GeometryProgramBuilder

        builder = GeometryProgramBuilder("book_parameter_probe")
        body = builder.add("primitive", "box", parameters={"width": 20.0, "depth": 12.0, "height": 8.0})
        root = builder.add("macro", operator, inputs=(body,), parameters=parameters)
        result = compile_geometry_program(builder.build(root))
        self.assertEqual(result.status, "compiled")
        return result

    def test_puncture_spacing_changes_the_holes(self):
        near = self._compile("puncture", {"axis": "x", "count": 2, "ratio": 0.12, "spacing_ratio": 0.16})
        far = self._compile("puncture", {"axis": "x", "count": 2, "ratio": 0.12, "spacing_ratio": 0.40})
        self.assertNotEqual(near.geometry_hash, far.geometry_hash)

    def test_offset_variations_are_distinct(self):
        from backend.app.modules.design.generation.maas.geometry_language import book_adapter  # noqa: F401
        hashes = {
            self._compile("book_array", {
                "mode": "offset", "axis": "x", "count": 2,
                "pitch_ratio": round(0.25 + 0.35 * (d + 0.34) / 0.68, 4),
            }).geometry_hash
            for d in (-0.34, -0.2, 0.0, 0.2, 0.34)
        }
        self.assertEqual(len(hashes), 5)
