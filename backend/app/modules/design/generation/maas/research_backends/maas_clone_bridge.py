"""Bridge to the cloned MAAS reference code.

ARR keeps legal geometry in its own Shapely/legal pipeline, but the paper
baseline should still be executable from the checked-out ``clone/MAAS`` source.
This module imports the clone as an external reference and reports failures as
evidence instead of breaking ARR massing.
"""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import hashlib
import importlib
import json
import os
import sys
from functools import lru_cache
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return _design_paths.workspace_root()


def maas_clone_source_path() -> Path:
    return _repo_root() / "clone" / "MAAS" / "src"


def maas_clone_labels_path() -> Path:
    return _repo_root() / "clone" / "MAAS" / "data" / "case_studies" / "labels.json"


def maas_clone_recovered_book_case_eval_path() -> Path:
    return _repo_root() / "clone" / "MAAS" / "outputs" / "sprint15_coma" / "book_case_eval.json"


def maas_clone_reference_sequence() -> dict[str, Any]:
    return {
        "name": "arr_reference_simple_cave_taper",
        "calls": [
            {"verb": "base", "params": {"proportion": "1/1"}},
            {"verb": "cave", "params": {"face": "+y", "depth": 0.3}},
            {"verb": "taper", "params": {"top_ratio": 0.7}},
        ],
    }


DEFAULT_VERB_PARAMS: dict[str, dict[str, Any]] = {
    "bend": {"axis": "y", "angle": 35.0, "slices": 8},
    "branch": {"angle": 30.0, "length": 0.7, "thickness": 0.3},
    "cave": {"face": "+y", "depth": 0.3, "size": [0.55, 0.45]},
    "embed": {"guest_proportion": "5/8", "guest_scale": 0.45, "position": [0.1, 0.0, 0.0]},
    "expand": {"face": "+x", "distance": 0.45, "size": [0.45, 0.45]},
    "extrude": {"face": "+z", "length": 0.65, "size": [0.45, 0.45]},
    "lift": {"other": "6/8", "other_scale": 0.85, "height_above": 0.8},
    "nest": {"inner": "5/8", "inner_scale": 0.62},
    "overlap": {"other": "1/1", "other_scale": 0.72, "offset_vec": [0.45, 0.25, 0.0]},
    "rotate_part": {"angle": 25.0, "axis": "z"},
    "shift": {"axis": "x", "distance": 0.28},
    "stack": {"n": 3, "axis": "z", "gap": 0.03, "unit_size": 0.85},
    "taper": {"top_ratio": 0.7},
}


def maas_clone_license_summary() -> dict[str, Any]:
    return {
        "name": "MAAS",
        "source": "clone/MAAS",
        "mode": "external_clone_bridge",
        "integration_rule": "Use clone/MAAS/src directly as the reference baseline; ARR remains the legal geometry source.",
    }


@lru_cache(maxsize=2)
def _inspect_maas_clone_cached(should_import: bool) -> dict[str, Any]:
    src = maas_clone_source_path()
    labels = maas_clone_labels_path()
    info: dict[str, Any] = {
        **maas_clone_license_summary(),
        "source_path": str(src),
        "exists": src.exists(),
        "labels_path": str(labels),
        "labels_exists": labels.exists(),
        "labels_status": "available" if labels.exists() else "missing_artifact",
        "status": "missing" if not src.exists() else "available_not_imported",
        "interfaces": {
            "verb_sequence": "maas.grammar.verb_sequence.VerbSequence",
            "verb_call": "maas.grammar.verb_sequence.VerbCall",
            "compiler": "maas.grammar.compiler.compile_sequence",
            "metrics": "maas.eval.metrics.compare_sequences",
        },
    }
    if not src.exists() or not should_import:
        return info

    try:
        verb_sequence = importlib.import_module("maas.grammar.verb_sequence")
        compiler = importlib.import_module("maas.grammar.compiler")
        metrics = importlib.import_module("maas.eval.metrics")
        info["status"] = "imported"
        info["imported"] = {
            "VerbSequence": hasattr(verb_sequence, "VerbSequence"),
            "VerbCall": hasattr(verb_sequence, "VerbCall"),
            "compile_sequence": hasattr(compiler, "compile_sequence"),
            "compare_sequences": hasattr(metrics, "compare_sequences"),
            "token_f1": hasattr(metrics, "token_f1"),
            "ordered_lcs": hasattr(metrics, "ordered_lcs"),
        }
    except Exception as exc:  # pragma: no cover - dependency/path dependent.
        info["status"] = "import_failed"
        info["error"] = f"{type(exc).__name__}: {exc}"
    return info


def inspect_maas_clone_backend(*, enable_import: bool | None = None) -> dict[str, Any]:
    should_import = enable_import if enable_import is not None else os.getenv("MAAS_CLONE_IMPORT", "1") != "0"
    return dict(_inspect_maas_clone_cached(bool(should_import)))


def _recovered_case_gold_source() -> dict[str, Any]:
    path = maas_clone_recovered_book_case_eval_path()
    source: dict[str, Any] = {
        "path": str(path),
        "exists": path.exists(),
        "status": "available" if path.exists() else "missing_artifact",
        "description": "Recovered 10-case book-study gold verbs from clone/MAAS evaluation output.",
    }
    if not path.exists():
        source["cases"] = []
        return source

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        cases = []
        for item in data.get("per_case", []):
            if not isinstance(item, dict):
                continue
            case_id = str(item.get("id") or "").strip()
            gold = [str(verb) for verb in item.get("gold", []) if verb]
            if case_id and gold:
                cases.append({"case_id": case_id, "gold_verbs": gold})
        source["cases"] = cases
        source["case_count"] = len(cases)
    except Exception as exc:
        source["status"] = "read_failed"
        source["error"] = f"{type(exc).__name__}: {exc}"
        source["cases"] = []
    return source


def _sequence_from_verbs(name: str, verbs: list[str]) -> dict[str, Any]:
    calls = [{"verb": "base", "params": {"proportion": "1/1"}}]
    calls.extend({
        "verb": verb,
        "params": dict(DEFAULT_VERB_PARAMS.get(verb, {})),
    } for verb in verbs)
    return {"name": name, "calls": calls}


def _compile_sequence_data(
    *,
    verb_sequence_mod: Any,
    compiler: Any,
    metrics: Any,
    sequence_data: dict[str, Any],
) -> dict[str, Any]:
    seq = verb_sequence_mod.VerbSequence.from_dict(sequence_data)
    errors = seq.validate()
    compiled: dict[str, Any] = {
        "sequence": sequence_data,
        "validate_errors": errors,
        "status": "validation_failed" if errors else "validated",
    }
    if errors:
        return compiled

    scad = compiler.compile_sequence(seq)
    comparison = metrics.compare_sequences(seq, seq)
    compiled.update({
        "status": "compiled",
        "scad_compile_status": "compiled",
        "scad_text_hash": hashlib.sha256(scad.encode("utf-8")).hexdigest(),
        "scad_text_length": len(scad),
        "scad_contains": {
            "cube": "cube" in scad,
            "difference": "difference" in scad,
            "hull": "hull" in scad,
            "union": "union" in scad,
        },
        "metric_summary": {
            "pred_len": comparison.pred_len,
            "gold_len": comparison.gold_len,
            "jaccard": comparison.jaccard,
            "token_f1": comparison.f1,
            "ordered_lcs": comparison.lcs,
            "lcs_score": comparison.lcs_score,
            "pred_verbs": comparison.pred_verbs,
            "gold_verbs": comparison.gold_verbs,
        },
    })
    return compiled


def run_maas_clone_reference_baseline(*, enable_import: bool | None = None) -> dict[str, Any]:
    backend = inspect_maas_clone_backend(enable_import=enable_import)
    recovered_cases = _recovered_case_gold_source()
    result: dict[str, Any] = {
        "name": "MAAS",
        "source": "clone/MAAS",
        "backend": backend,
        "sequence_source": "clone/MAAS/tests/test_grammar.py::make_simple_seq",
        "case_gold_source": recovered_cases,
        "case_baseline": {
            "status": "not_run",
            "source": recovered_cases.get("path"),
            "case_count": recovered_cases.get("case_count", 0),
            "compiled_case_count": 0,
            "failed_case_count": 0,
            "unique_gold_verbs": [],
            "cases": [],
        },
        "missing_artifacts": [],
        "status": backend["status"],
    }
    if not backend.get("labels_exists"):
        result["missing_artifacts"].append({
            "path": backend.get("labels_path"),
            "expected_by": "clone/MAAS/src/maas/eval/case_studies.py",
            "impact": "book case-study labels cannot be used until restored",
        })
    if backend.get("status") != "imported":
        return result

    src = maas_clone_source_path()
    try:
        verb_sequence_mod = importlib.import_module("maas.grammar.verb_sequence")
        compiler = importlib.import_module("maas.grammar.compiler")
        metrics = importlib.import_module("maas.eval.metrics")
        sequence_data = maas_clone_reference_sequence()
        simple = _compile_sequence_data(
            verb_sequence_mod=verb_sequence_mod,
            compiler=compiler,
            metrics=metrics,
            sequence_data=sequence_data,
        )
        result.update(simple)
        if simple["status"] != "compiled":
            result["status"] = simple["status"]
            return result
        result["status"] = "compiled"

        case_results: list[dict[str, Any]] = []
        unique_gold_verbs: set[str] = set()
        for case in recovered_cases.get("cases", []):
            gold_verbs = [str(verb) for verb in case.get("gold_verbs", []) if verb]
            unique_gold_verbs.update(gold_verbs)
            case_result = {
                "case_id": case["case_id"],
                "gold_verbs": gold_verbs,
                "sequence_source": "clone/MAAS/outputs/sprint15_coma/book_case_eval.json::per_case.gold",
            }
            sequence_data = _sequence_from_verbs(f"book_case_{case['case_id']}", gold_verbs)
            try:
                case_result.update(_compile_sequence_data(
                    verb_sequence_mod=verb_sequence_mod,
                    compiler=compiler,
                    metrics=metrics,
                    sequence_data=sequence_data,
                ))
            except Exception as exc:
                case_result["status"] = "compile_failed"
                case_result["error"] = f"{type(exc).__name__}: {exc}"
            case_results.append(case_result)

        compiled_count = sum(1 for case in case_results if case.get("status") == "compiled")
        result["case_baseline"] = {
            "status": (
                "compiled"
                if case_results and compiled_count == len(case_results)
                else "partial"
                if compiled_count
                else "missing_artifact"
            ),
            "source": recovered_cases.get("path"),
            "source_status": recovered_cases.get("status"),
            "case_count": len(case_results),
            "compiled_case_count": compiled_count,
            "failed_case_count": len(case_results) - compiled_count,
            "unique_gold_verbs": sorted(unique_gold_verbs),
            "cases": case_results,
        }
    except Exception as exc:
        result["status"] = "baseline_failed"
        result["error"] = f"{type(exc).__name__}: {exc}"
    return result


__all__ = [
    "inspect_maas_clone_backend",
    "maas_clone_recovered_book_case_eval_path",
    "maas_clone_labels_path",
    "maas_clone_license_summary",
    "maas_clone_reference_sequence",
    "maas_clone_source_path",
    "run_maas_clone_reference_baseline",
]
