"""Data-backed MAAS grammar sequence library.

The sequence definitions live in ``grammar/data/maas_sequences.v0.json`` so
architectural vocabulary can grow without editing Python code. This module keeps
the old public API (`SEQUENCES`, `get_sequence_label`) stable for optimizer and
test callers.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.grammar.verb_sequence import VerbSequence, call
from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS


DATA_DIR = _design_paths.package_root('design/maas/grammar') / "data"
SEQUENCE_LIBRARY_PATH = DATA_DIR / "maas_sequences.v0.json"


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def _validate_sequence_record(record: dict[str, Any], index: int) -> list[str]:
    errors: list[str] = []
    name = record.get("name")
    label = record.get("label")
    calls = record.get("calls")
    if not isinstance(name, str) or not name.startswith("grammar_"):
        errors.append(f"sequence {index}: name must start with grammar_")
    if not isinstance(label, str) or not label:
        errors.append(f"sequence {index}: label is required")
    if not isinstance(calls, list) or len(calls) < 2:
        errors.append(f"sequence {index}: calls must contain at least base + one verb")
        return errors
    for call_index, item in enumerate(calls):
        if not isinstance(item, dict):
            errors.append(f"{name}: call {call_index} must be an object")
            continue
        verb = item.get("verb")
        params = item.get("params", {})
        if verb not in SUPPORTED_VERBS:
            errors.append(f"{name}: unsupported verb {verb!r}")
        if params is not None and not isinstance(params, dict):
            errors.append(f"{name}: call {call_index} params must be an object")
    if calls and isinstance(calls[0], dict) and calls[0].get("verb") != "base":
        errors.append(f"{name}: first call must be base")
    return errors


def _record_to_sequence(record: dict[str, Any]) -> VerbSequence:
    calls = tuple(
        call(str(item["verb"]), **dict(item.get("params") or {}))
        for item in record["calls"]
    )
    sequence = VerbSequence(
        name=str(record["name"]),
        label=str(record["label"]),
        calls=calls,
        notes=tuple(str(note) for note in record.get("notes") or ()),
    )
    errors = sequence.validate()
    if errors:
        raise ValueError(f"{sequence.name}: {'; '.join(errors)}")
    return sequence


@lru_cache(maxsize=1)
def load_sequence_library(path: str | Path = SEQUENCE_LIBRARY_PATH) -> tuple[VerbSequence, ...]:
    """Load and validate the data-backed grammar sequence library."""
    data = _load_json(Path(path))
    if data.get("schema_version") != "arr.maas.sequence_library.v0":
        raise ValueError("unsupported MAAS sequence library schema_version")
    records = data.get("sequences")
    if not isinstance(records, list) or not records:
        raise ValueError("MAAS sequence library must contain at least one sequence")
    errors: list[str] = []
    seen: set[str] = set()
    for index, record in enumerate(records):
        if not isinstance(record, dict):
            errors.append(f"sequence {index}: record must be an object")
            continue
        name = record.get("name")
        if isinstance(name, str):
            if name in seen:
                errors.append(f"duplicate sequence name {name!r}")
            seen.add(name)
        errors.extend(_validate_sequence_record(record, index))
    if errors:
        raise ValueError("invalid MAAS sequence library: " + "; ".join(errors))
    return tuple(_record_to_sequence(record) for record in records)


@lru_cache(maxsize=1)
def load_sequence_metadata(path: str | Path = SEQUENCE_LIBRARY_PATH) -> dict[str, dict[str, Any]]:
    """Return metadata not represented by ``VerbSequence``."""
    data = _load_json(Path(path))
    records = data.get("sequences") or []
    return {
        str(record["name"]): {
            "label": record.get("label"),
            "aliases": list(record.get("aliases") or []),
            "intent_tags": list(record.get("intent_tags") or []),
            "notes": list(record.get("notes") or []),
        }
        for record in records
        if isinstance(record, dict) and isinstance(record.get("name"), str)
    }


SEQUENCES = load_sequence_library()
SEQUENCE_LABELS = {sequence.name: sequence.label for sequence in SEQUENCES}


def get_sequence_label(name: str) -> str | None:
    return SEQUENCE_LABELS.get(name)


def get_sequence_metadata(name: str) -> dict[str, Any] | None:
    return load_sequence_metadata().get(name)


__all__ = [
    "SEQUENCES",
    "SEQUENCE_LABELS",
    "SEQUENCE_LIBRARY_PATH",
    "get_sequence_label",
    "get_sequence_metadata",
    "load_sequence_library",
    "load_sequence_metadata",
]
