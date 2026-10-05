"""Load agent-authored MassDSL proposals from the MAAS clone workspace."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence, call
from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS


WORKSPACE_ROOT = _design_paths.workspace_root()
DEFAULT_AGENT_PROPOSALS_PATH = (
    WORKSPACE_ROOT
    / "clone"
    / "MAAS"
    / "outputs"
    / "arr_agent_proposals"
    / "maas_arr_massdsl_proposals.v1.json"
)
AGENT_PARAMETER_SOURCE = "clone_maas_codex_agent_arch_language_proposal"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _record_to_sequence(record: dict[str, Any], source: str) -> VerbSequence:
    calls = []
    for index, item in enumerate(record.get("calls") or []):
        if not isinstance(item, dict):
            raise ValueError(f"{record.get('name')}: call {index} must be an object")
        verb = item.get("verb")
        if verb not in SUPPORTED_VERBS:
            raise ValueError(f"{record.get('name')}: unsupported verb {verb!r}")
        params = item.get("params") if isinstance(item.get("params"), dict) else {}
        calls.append(call(str(verb), **dict(params)))
    sequence = VerbSequence(
        name=str(record["name"]),
        label=str(record.get("label") or record["name"]),
        calls=tuple(calls),
        notes=(
            f"proposal_source={source}",
            "parameter_source=clone_maas_agent_arch_language",
            "requires_llm_authoring=false",
            str(record.get("rationale") or ""),
        ),
    )
    errors = sequence.validate()
    if errors:
        raise ValueError(f"{sequence.name}: {'; '.join(errors)}")
    return sequence


@lru_cache(maxsize=1)
def load_agent_proposal_sequences(
    path: str | Path = DEFAULT_AGENT_PROPOSALS_PATH,
) -> tuple[VerbSequence, ...]:
    """Return clone/MAAS agent proposals as ARR MassDSL sequences.

    The file is an external proposal artifact, not a legal source of truth.
    ARR still compiles, clips, scores, and rejects candidates through the
    deterministic legal optimizer.
    """
    proposal_path = Path(path)
    if not proposal_path.exists():
        return ()
    data = _load_json(proposal_path)
    if data.get("schema_version") != "arr.maas.agent_massdsl_proposals.v1":
        raise ValueError("unsupported MAAS agent proposal schema_version")
    source = str(data.get("proposal_source") or AGENT_PARAMETER_SOURCE)
    records = data.get("proposals")
    if not isinstance(records, list):
        raise ValueError("MAAS agent proposal file must contain proposals[]")
    sequences: list[VerbSequence] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            raise ValueError(f"proposal {index}: record must be an object")
        name = record.get("name")
        if not isinstance(name, str) or not name.startswith("agent_"):
            raise ValueError(f"proposal {index}: name must start with agent_")
        if name in seen:
            raise ValueError(f"duplicate agent proposal name {name!r}")
        seen.add(name)
        sequences.append(_record_to_sequence(record, source))
    return tuple(sequences)


__all__ = [
    "AGENT_PARAMETER_SOURCE",
    "DEFAULT_AGENT_PROPOSALS_PATH",
    "load_agent_proposal_sequences",
]
