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
