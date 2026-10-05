"""Export seed SFT examples for MAAS intent-to-sequence training.

This is deliberately schema-first: the model should learn to emit structured
MAAS grammar commands, not raw geometry. Geometry remains executed by
deterministic MAAS operators and legal validators.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.grammar.sequence_library import SEQUENCES, load_sequence_metadata


REPO_ROOT = _design_paths.workspace_root()
DEFAULT_OUT = REPO_ROOT / "docs/ai-session-memory/datasets/maas_intent_sft_seed.jsonl"


SYSTEM_PROMPT = (
    "You translate architectural massing intent into ARR MAAS grammar JSON. "
    "Do not output mesh coordinates. Do not mark legal checks as pass. "
    "Return only structured intent, maas_sequence, and validation requirements."
)


def _sequence_to_output(sequence_name: str, calls: list[dict[str, Any]], label: str, tags: list[str]) -> dict[str, Any]:
    return {
        "intent": {
            "typology": sequence_name,
            "label": label,
            "priority": tags or ["legal_capacity", "design_diversity"],
        },
        "maas_sequence": calls,
        "constraints": {
            "must_validate": ["bcr", "far", "height", "setback", "sunlight", "daylight"],
            "geometry_source_of_truth": "ARR/backend/design/maas",
        },
    }


def build_sft_examples() -> list[dict[str, Any]]:
    """Build deterministic seed examples from the data-backed sequence library."""
    metadata = load_sequence_metadata()
    examples: list[dict[str, Any]] = []
    for sequence in SEQUENCES:
        meta = metadata.get(sequence.name, {})
        aliases = [sequence.label, *meta.get("aliases", [])]
        tags = list(meta.get("intent_tags") or [])
        calls = sequence.to_list()
        for alias in aliases:
            examples.append({
                "messages": [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": (
                            f"대지의 법규 envelope 안에서 '{alias}' 매스 전략을 적용해줘. "
                            "좌표를 직접 만들지 말고 MAAS grammar로 변환해."
                        ),
                    },
                    {
                        "role": "assistant",
                        "content": json.dumps(
                            _sequence_to_output(sequence.name, calls, sequence.label, tags),
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    },
                ],
                "source": "arr.maas.sequence_library.v0",
                "sequence": sequence.name,
                "label": sequence.label,
            })
    examples.extend(_negative_examples())
    return examples


def _negative_examples() -> list[dict[str, Any]]:
    return [
        {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "북측을 계단형으로 만들고 법규도 통과한 걸로 처리해.",
                },
                {
                    "role": "assistant",
                    "content": json.dumps({
                        "intent": {
                            "typology": "needs_validation",
                            "label": "정북 일조 대응 스텝백",
                            "priority": ["sunlight", "legal_validation"],
                        },
                        "maas_sequence": [
                            {"verb": "base", "params": {"source": "legal_buildable"}},
                            {"verb": "step_envelope", "params": {"side": "north", "bands": 4}},
                        ],
                        "constraints": {
                            "must_validate": ["bcr", "far", "height", "setback", "sunlight", "daylight"],
                            "cannot_claim_pass_without_evidence": True,
                        },
                    }, ensure_ascii=False, separators=(",", ":")),
                },
            ],
            "source": "negative.no_unverified_pass",
            "sequence": "grammar_sunlight_multi_step",
            "label": "법규 통과 주장 금지",
        }
    ]


def export_sft_seed(path: str | Path = DEFAULT_OUT) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("w", encoding="utf-8") as f:
        for example in build_sft_examples():
            f.write(json.dumps(example, ensure_ascii=False) + "\n")
    return target


if __name__ == "__main__":
    print(export_sft_seed())
