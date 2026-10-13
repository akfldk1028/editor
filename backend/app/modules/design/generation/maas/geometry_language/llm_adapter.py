"""OpenAI LLM author for bounded architectural geometry programs."""

from __future__ import annotations

from backend.app.modules.design.generation.maas.dimensional_intent import intent_schema, validate_intent

import json
import hashlib
from math import atan2, degrees, hypot
import os
from dataclasses import replace
from datetime import timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
import urllib.error
import urllib.request
import uuid
from typing import Any

from shapely.affinity import rotate as rotate_geometry
from shapely.geometry import Polygon, shape


def _safe_retry_after_http_date(value: Any) -> str:
    try:
        parsed = parsedate_to_datetime(str(value or "").strip())
    except (TypeError, ValueError, OverflowError):
        return ""
    if parsed.tzinfo is None:
        return ""
    return format_datetime(parsed.astimezone(timezone.utc), usegmt=True)

from backend.app.modules.design.generation.maas.geometry_language.ast import GeometryNode, GeometryProgram, OPERATORS_BY_KIND
from backend.app.modules.design.generation.maas.geometry_language.assembly_budget import assembly_budget_nodes as _assembly_budget_nodes
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_FORM_SPECS, BASE_SEED_SPECS
from backend.app.modules.design.generation.maas.geometry_language.compiler import compile_geometry_program
from backend.app.modules.design.generation.maas.geometry_language.dsl import GeometryDslError, parse_geometry_dsl, program_to_dsl
from backend.app.modules.design.generation.maas.geometry_language.gate import GeometryGatePolicy, compilation_gate
from backend.app.modules.design.generation.maas.geometry_language.mutation import OPERATOR_PARAMETER_CONTRACTS
from backend.app.modules.design.generation.maas.geometry_language.author_output_schema import author_node_schema as _author_node_schema, schema_value_types as _schema_value_types
from backend.app.modules.design.generation.maas.geometry_language.legal_envelope import normalized_legal_field_design_context
from backend.app.modules.design.generation.maas.geometry_language.author_parameter_contract import author_parameter_value_contract as _author_parameter_value_contract
from backend.app.modules.design.generation.maas.paid_provider_budget import PaidProviderBudgetError, reserve_paid_provider_request
from backend.app.modules.design.generation.maas.book_language.paid_provider_admission import admit_paid_provider_program


DEFAULT_GEOMETRY_AUTHOR_MODEL = "gpt-5.4-mini"
GEOMETRY_AUTHOR_PROMPT_CONTRACT = "arr.maas.geometry_llm_author.v35_occupied_surface_bounds"
LEGACY_GEOMETRY_AUTHOR_PROMPT_CONTRACT = "arr.maas.geometry_llm_author.v24_nonfragmenting_relation_pairs"
MAX_AUTHOR_COMPILER_REPAIR_GENERATIONS = 3

SEMANTIC_MACRO_BASE_SEEDS: dict[str, frozenset[str]] = {
    "leaning_tower": frozenset({"tower"}),
    "tapered_tower": frozenset({"tower"}),
    "profiled_hall": frozenset({"bar", "slab", "profiled_prism"}),
    "bent_bar": frozenset({"bar", "slab", "profiled_prism"}),
    "cross_mass": frozenset({"bar", "slab", "profiled_prism"}),
    "grid_mass": frozenset({"bar"}),
    "split_wing": frozenset({"bar", "slab", "profiled_prism"}),
}

CANONICAL_OPERATOR_KIND: dict[str, str] = {
    # These names exist in both a low-level and architectural layer. The AST
    # stores one executable node, so a wrong redundant kind label must lower to
    # a deterministic compiler kind instead of becoming an unknown operator.
    "bridge": "composition",
    "cut_corner": "modifier",
}

AUTHOR_GEOMETRY_GATE_POLICY = GeometryGatePolicy(maximum_components=1)

_AUTHOR_REJECTION_CATEGORIES = frozenset({
    "schema", "ast_decode", "compiler_or_gate", "duplicate", "other",
})
_AUTHOR_REJECTION_CODES = frozenset({
    "non_object_program",
    "ast_decode_error",
    "compiler_gate_rejected",
    "declared_base_seed_mismatch",
    "declared_base_form_mismatch",
    "semantic_macro_base_seed_mismatch",
    "program_relation_not_terminal_suffix",
    "program_access_relation_not_bound",
    "program_geometry_language_contract_failed",
    "duplicate_program",
    "uncategorized_rejection",
    "kernel_unavailable",
    "non_manifold",
    "multiple_components",
    "empty_geometry",
    "degenerate_geometry",
    "invalid_volume",
    "unknown_operator",
})
_AUTHOR_PROVIDER_ERROR_CATEGORIES = frozenset({
    "rate_limited",
    "http_error",
    "network_error",
    "timeout",
    "provider_response_json_decode",
})
_AUTHOR_PAYLOAD_ERROR_CATEGORIES = frozenset({
    "provider_response_schema",
    "author_payload_json_decode",
    "author_payload_schema",
})
_AUTHOR_BUDGET_CODES = frozenset({
    "total_budget_exhausted",
    "request_quota_exhausted",
    "request_kind_unpartitioned",
})


def _safe_nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _sanitize_author_failure_diagnostics(
    diagnostics: dict[str, Any] | None,
) -> dict[str, Any]:
    source = diagnostics if isinstance(diagnostics, dict) else {}
    result: dict[str, Any] = {
        "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
    }
    provider = source.get("provider_error")
    if isinstance(provider, dict):
        category = str(provider.get("category") or "")
        if category in _AUTHOR_PROVIDER_ERROR_CATEGORIES:
            record: dict[str, Any] = {"category": category}
            if provider.get("http_status") is not None:
                record["http_status"] = _safe_nonnegative_int(
                    provider.get("http_status")
                )
            if provider.get("retry_after_seconds") is not None:
                retry_after = _safe_nonnegative_int(
                    provider.get("retry_after_seconds")
                )
                if retry_after <= 86400:
                    record["retry_after_seconds"] = retry_after
            retry_after_http_date = _safe_retry_after_http_date(
                provider.get("retry_after_http_date")
            )
            if retry_after_http_date:
                record["retry_after_http_date"] = retry_after_http_date
            result["provider_error"] = record
    payload_error = source.get("payload_error")
    if isinstance(payload_error, dict):
        category = str(payload_error.get("category") or "")
        if category in _AUTHOR_PAYLOAD_ERROR_CATEGORIES:
            result["payload_error"] = {"category": category}
    batches: list[dict[str, Any]] = []
    for batch in source.get("batches") or ():
        if not isinstance(batch, dict):
            continue
        role = str(batch.get("batch_role") or "")
        if role not in {"initial", "repair"}:
            continue
        category_counts = {
            str(code): _safe_nonnegative_int(count)
            for code, count in dict(
                batch.get("rejection_category_counts") or {}
            ).items()
            if str(code) in _AUTHOR_REJECTION_CATEGORIES
        }
        code_counts = {
            str(code): _safe_nonnegative_int(count)
            for code, count in dict(
                batch.get("rejection_code_counts") or {}
            ).items()
            if str(code) in _AUTHOR_REJECTION_CODES
        }
        batches.append({
            "batch_role": role,
            "repair_generation": _safe_nonnegative_int(
                batch.get("repair_generation")
            ),
            "raw_program_count": _safe_nonnegative_int(
                batch.get("raw_program_count")
            ),
            "valid_program_count": _safe_nonnegative_int(
                batch.get("valid_program_count")
            ),
            "rejected_program_count": _safe_nonnegative_int(
                batch.get("rejected_program_count")
            ),
            "rejection_category_counts": dict(sorted(category_counts.items())),
            "rejection_code_counts": dict(sorted(code_counts.items())),
        })
    if batches:
        result["batches"] = batches
    secondary: list[dict[str, Any]] = []
    for failure in source.get("secondary_failures") or ():
        if not isinstance(failure, dict):
            continue
        category = str(failure.get("category") or "")
        if category == "retry_budget":
            code = str(failure.get("code") or "")
            record = {"category": category}
            if code in _AUTHOR_BUDGET_CODES:
                record["code"] = code
            for field in ("used", "limit", "remaining"):
                if failure.get(field) is not None:
                    record[field] = _safe_nonnegative_int(failure.get(field))
            secondary.append(record)
        elif category == "repair_author_failure":
            secondary.append({
                "category": category,
                "diagnostics": _sanitize_author_failure_diagnostics(
                    failure.get("diagnostics")
                ),
            })
    if secondary:
        result["secondary_failures"] = secondary
    return result


class GeometryAuthorError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.diagnostics = _sanitize_author_failure_diagnostics(diagnostics)


def _provider_failure_diagnostics(
    *,
    category: str,
    http_status: int | None = None,
    retry_after: Any = None,
) -> dict[str, Any]:
    provider_error: dict[str, Any] = {"category": category}
    if http_status is not None:
        provider_error["http_status"] = int(http_status)
    try:
        retry_after_seconds = int(str(retry_after).strip())
    except (TypeError, ValueError):
        retry_after_seconds = -1
    if 0 <= retry_after_seconds <= 86400:
        provider_error["retry_after_seconds"] = retry_after_seconds
    else:
        retry_after_http_date = _safe_retry_after_http_date(retry_after)
        if retry_after_http_date:
            provider_error["retry_after_http_date"] = retry_after_http_date
    return {
        "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
        "provider_error": provider_error,
    }


def _author_batch_failure_diagnostics(
    payload: dict[str, Any],
    compiler_diagnostics: list[dict[str, Any]],
    *,
    valid_program_count: int,
    batch_role: str,
    repair_generation: int,
    repair_batches: list[dict[str, Any]] | None = None,
    secondary_failures: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw_programs = payload.get("programs")
    raw_program_count = len(raw_programs) if isinstance(raw_programs, list) else 0
    category_counts: dict[str, int] = {}
    code_counts: dict[str, int] = {}
    rejected_program_count = max(
        0, raw_program_count - max(0, int(valid_program_count))
    )
    classified_count = 0
    for diagnostic in compiler_diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        category = str(diagnostic.get("category") or "other")
        if category not in _AUTHOR_REJECTION_CATEGORIES:
            category = "other"
        category_counts[category] = category_counts.get(category, 0) + 1
        classified_count += 1
        for value in diagnostic.get("rejection_codes") or ():
            code = str(value)
            if code in _AUTHOR_REJECTION_CODES:
                code_counts[code] = code_counts.get(code, 0) + 1
    if classified_count < rejected_program_count:
        missing = rejected_program_count - classified_count
        category_counts["other"] = category_counts.get("other", 0) + missing
        code_counts["uncategorized_rejection"] = (
            code_counts.get("uncategorized_rejection", 0) + missing
        )
    batch = {
        "batch_role": batch_role,
        "repair_generation": max(0, int(repair_generation)),
        "raw_program_count": raw_program_count,
        "valid_program_count": max(0, int(valid_program_count)),
        "rejected_program_count": rejected_program_count,
        "rejection_category_counts": dict(sorted(category_counts.items())),
        "rejection_code_counts": dict(sorted(code_counts.items())),
    }
    result: dict[str, Any] = {
        "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
        "batches": [batch, *(repair_batches or [])],
    }
    if secondary_failures:
        result["secondary_failures"] = json.loads(json.dumps(secondary_failures))
    return _sanitize_author_failure_diagnostics(result)


def _geometry_author_request_identity(
    context: dict[str, Any],
) -> tuple[str, str]:
    stage = str(context.get("author_stage") or "initial").strip().lower()
    expected = {
        "initial": "geometry_author_initial",
        "replenishment": "geometry_author_replenishment",
    }
    if stage not in expected:
        raise GeometryAuthorError(f"invalid geometry author stage: {stage}")
    request_kind = str(
        context.get("author_request_kind") or expected[stage]
    ).strip()
    if request_kind != expected[stage]:
        raise GeometryAuthorError(
            "geometry author request kind does not match stage:"
            f"{stage}:{request_kind}"
        )
    return stage, request_kind


def author_geometry_programs_with_openai(
    context: dict[str, Any],
    *,
    target_count: int = 8,
    model: str | None = None,
    timeout: float = 150.0,
) -> tuple[GeometryProgram, ...]:
    """Generate explicit DSL programs; never accept prose or uncompiled labels."""
    count = max(1, min(20, int(target_count)))
    author_stage, author_request_kind = _geometry_author_request_identity(
        context
    )
    repair_generation = int(
        context.get("author_compiler_repair_generation") or 0
    )
    provider_request_kind = (
        "provider_retry"
        if author_stage == "replenishment" and repair_generation > 0
        else author_request_kind
    )
    book_principle_ids: tuple[str, ...] = ()
    author_program_context = _author_validation_context(context)
    selected_model = model or os.getenv("MAAS_GEOMETRY_AUTHOR_MODEL") or DEFAULT_GEOMETRY_AUTHOR_MODEL
    explicit_replay_path = os.getenv(
        "MAAS_GEOMETRY_AUTHOR_REPLAY_CACHE_PATH",
        "",
    ).strip()
    cache_path = (
        Path(explicit_replay_path).resolve()
        if explicit_replay_path
        else _author_cache_path(
            context=context,
            count=count,
            model=selected_model,
        )
    )
    cached = _load_author_cache(cache_path)
    if (
        cached is None
        and not explicit_replay_path
        and "book_graph_vocabulary" not in context
    ):
        legacy_cache_path = _author_cache_path(
            context=context,
            count=count,
            model=selected_model,
            prompt_contract=LEGACY_GEOMETRY_AUTHOR_PROMPT_CONTRACT,
        )
        cached = _load_author_cache(legacy_cache_path)
    if cached is not None and "book_graph_vocabulary" in context:
        try:
            book_principle_ids = _canonical_book_principle_ids(
                context,
                cached,
            )
        except GeometryAuthorError:
            cached = None
    if cached is not None:
        if isinstance(cached.get("compiled_programs"), list):
            programs = tuple(
                GeometryProgram.from_dict(item)
                for item in cached["compiled_programs"]
                if isinstance(item, dict)
            )
        else:
            programs = geometry_programs_from_author_payload(
                cached["payload"], expected_count=1,
            )
        replay_program_name = os.getenv(
            "MAAS_GEOMETRY_AUTHOR_REPLAY_PROGRAM_NAME",
            "",
        ).strip()
        if replay_program_name:
            programs = tuple(
                program
                for program in programs
                if program.name == replay_program_name
            )
            if not programs:
                raise GeometryAuthorError(
                    "named geometry author replay program was not found: "
                    f"{replay_program_name}"
                )
        if (
            "book_graph_vocabulary" in context
            and not _valid_program_book_path_bindings(
                context,
                programs,
                count=count,
            )
        ):
            cached = None
        if cached is None:
            programs = ()
        else:
            decorated = _decorate_author_programs(
                programs,
                model=str(cached.get("model") or selected_model),
                response_id=str(cached.get("response_id") or ""),
                cache_hit=True,
                book_principle_ids=book_principle_ids,
            )
            return _admit_paid_author_programs(decorated)
    rejected_cache = _load_revalidatable_kernel_rejection(
        cache_path.with_suffix(".rejected.json")
    )
    if rejected_cache is not None and "book_graph_vocabulary" in context:
        try:
            book_principle_ids = _canonical_book_principle_ids(
                context,
                rejected_cache,
            )
        except GeometryAuthorError:
            rejected_cache = None
    if rejected_cache is not None:
        try:
            programs = geometry_programs_from_author_payload(
                rejected_cache["payload"],
                expected_count=1,
                program_context=author_program_context,
            )
        except GeometryAuthorError:
            programs = ()
        if programs:
            decorated = _decorate_author_programs(
                programs,
                model=str(rejected_cache.get("model") or selected_model),
                response_id=str(rejected_cache.get("response_id") or ""),
                cache_hit=True,
                book_principle_ids=book_principle_ids,
            )
            _save_author_cache(cache_path, {
                "cache_schema_version": "arr.maas.geometry_llm_author_cache.v3",
                "validation_status": "accepted",
                "model": str(rejected_cache.get("model") or selected_model),
                "response_id": str(rejected_cache.get("response_id") or ""),
                "payload": rejected_cache["payload"],
                "compiled_programs": [program.to_dict() for program in decorated],
                "revalidated_from": "kernel_unavailable_rejection",
            })
            return _admit_paid_author_programs(decorated)
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise GeometryAuthorError("OPENAI_API_KEY is not set")
    body = {
        "model": selected_model,
        "input": [
            {
                "role": "system",
                "content": [{
                    "type": "input_text",
                    "text": (
                        "You author executable architectural mass programs. Return deterministic assignment-only DSL, "
                        "not prose and not a completed-building coordinate template. Each candidate must have a materially "
                        "different operator-tree topology and architectural spatial idea."
                    ),
                }],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": _author_prompt(context, count)}],
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "maas_geometry_program_batch",
                "strict": True,
                "schema": _author_schema(
                    count,
                    allowed_base_seeds=_allowed_author_base_seeds(context),
                    allowed_operators=_allowed_author_operators(context),
                    book_principle_vocabulary=(
                        _book_graph_principle_vocabulary(context)
                    ),
                    book_composition_path_ids=tuple(
                        item["path_id"]
                        for item in _book_composition_path_slice(
                            context,
                            count,
                        )
                    ),
                ),
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        reserve_paid_provider_request(provider_request_kind)
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise GeometryAuthorError(
            "geometry author provider request failed",
            diagnostics=_provider_failure_diagnostics(
                category="rate_limited" if exc.code == 429 else "http_error",
                http_status=exc.code,
                retry_after=(exc.headers or {}).get("Retry-After"),
            ),
        ) from exc
    except urllib.error.URLError as exc:
        raise GeometryAuthorError(
            "geometry author request failed",
            diagnostics=_provider_failure_diagnostics(category="network_error"),
        ) from exc
    except TimeoutError as exc:
        raise GeometryAuthorError(
            "geometry author request failed",
            diagnostics=_provider_failure_diagnostics(category="timeout"),
        ) from exc
    except json.JSONDecodeError as exc:
        raise GeometryAuthorError(
            "geometry author provider response was invalid JSON",
            diagnostics=_provider_failure_diagnostics(
                category="provider_response_json_decode"
            ),
        ) from exc
    try:
        raw_text = _response_output_text(response_data)
    except GeometryAuthorError as exc:
        raise GeometryAuthorError(
            "geometry author provider response failed schema validation",
            diagnostics={
                "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
                "payload_error": {"category": "provider_response_schema"},
            },
        ) from exc
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise GeometryAuthorError(
            "geometry author returned invalid JSON",
            diagnostics={
                "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
                "payload_error": {"category": "author_payload_json_decode"},
            },
        ) from exc
    response_id = str(response_data.get("id") or "")
    try:
        book_principle_ids = _canonical_book_principle_ids(context, payload)
        book_composition_path_ids = _canonical_book_composition_path_ids(
            context,
            payload,
            count=count,
        )
    except GeometryAuthorError as exc:
        raise GeometryAuthorError(
            "geometry author payload failed schema validation: " + str(exc),
            diagnostics={
                "schema_version": "arr.maas.geometry_author_failure_diagnostics.v1",
                "payload_error": {"category": "author_payload_schema"},
            },
        ) from exc
    parse_error: GeometryAuthorError | None = None
    try:
        initial_programs = geometry_programs_from_author_payload(
            payload,
            expected_count=1,
            program_context=author_program_context,
        )
    except GeometryAuthorError as exc:
        initial_programs = ()
        parse_error = exc
    programs = list(_decorate_author_programs(
        initial_programs,
        model=selected_model,
        response_id=response_id,
        cache_hit=False,
        book_principle_ids=book_principle_ids,
    ))
    programs = [replace(program, metadata={
        **program.metadata,
        "author_compiler_repair_generation": repair_generation,
        "author_provider_request_kind": provider_request_kind,
    }) for program in programs]
    initial_valid_program_count = len(programs)
    repair_diagnostics = _author_payload_compiler_diagnostics(
        payload,
        program_context=author_program_context,
    )
    repair_request_count = 0
    repair_budget_failure: dict[str, Any] | None = None
    repair_author_failure: dict[str, Any] | None = None
    repair_batches: list[dict[str, Any]] = []
    repair_secondary_failures: list[dict[str, Any]] = []
    if (
        len(programs) < count
        and repair_generation < MAX_AUTHOR_COMPILER_REPAIR_GENERATIONS
    ):
        repair_context = {
            **context,
            "author_compiler_repair_generation": repair_generation + 1,
            "compiler_repair_feedback": repair_diagnostics,
            "already_valid_programs": [
                {
                    "name": program.name,
                    "base_seed": str(program.metadata.get("base_seed") or ""),
                    "operator_path": list(program.metadata.get("operator_path") or ()),
                }
                for program in programs
            ],
            "instruction": (
                "Author only the missing valid programs. Use the compiler feedback as negative constraints; "
                "do not repeat invalid node-kind/operator pairs, degenerate relations, or invalid parameter types."
            ),
        }
        try:
            repaired = author_geometry_programs_with_openai(
                repair_context,
                target_count=count - len(programs),
                model=selected_model,
                timeout=timeout,
            )
            repair_request_count = 1 + max((
                int(program.metadata.get(
                    "author_compiler_repair_request_count"
                ) or 0)
                for program in repaired
            ), default=0)
            repaired_diagnostics = next((
                program.metadata.get("author_failure_diagnostics")
                for program in repaired
                if isinstance(
                    program.metadata.get("author_failure_diagnostics"), dict
                )
            ), {})
            repair_batches = list(repaired_diagnostics.get("batches") or ())
            repair_secondary_failures = list(
                repaired_diagnostics.get("secondary_failures") or ()
            )
        except PaidProviderBudgetError as exc:
            repair_budget_failure = {
                "code": exc.code,
                "request_kind": exc.request_kind,
                "quota": exc.quota,
                "used": exc.used,
                "limit": exc.limit,
                "remaining": exc.remaining,
                "author_stage": author_stage,
            }
            repaired = ()
        except GeometryAuthorError as exc:
            repair_batches = list(exc.diagnostics.get("batches") or ())
            repair_author_failure = {
                "category": "repair_author_failure",
                "diagnostics": exc.diagnostics,
            }
            repaired = ()
        seen_hashes = {program.program_hash() for program in programs}
        for program in repaired:
            if program.program_hash() in seen_hashes:
                continue
            seen_hashes.add(program.program_hash())
            programs.append(program)
        if repair_budget_failure is not None:
            programs = [replace(program, metadata={
                **program.metadata,
                "author_compiler_repair_budget_failure": (
                    repair_budget_failure
                ),
            }) for program in programs]
    programs = [replace(program, metadata={
        **program.metadata,
        "author_compiler_repair_request_count": repair_request_count,
    }) for program in programs]
    secondary_failures = list(repair_secondary_failures)
    if repair_budget_failure is not None:
        secondary_failures.append({
            "category": "retry_budget",
            "code": repair_budget_failure.get("code"),
            "used": repair_budget_failure.get("used"),
            "limit": repair_budget_failure.get("limit"),
            "remaining": repair_budget_failure.get("remaining"),
        })
    if repair_author_failure is not None:
        secondary_failures.append(repair_author_failure)
    failure_diagnostics = _author_batch_failure_diagnostics(
        payload,
        repair_diagnostics,
        valid_program_count=initial_valid_program_count,
        batch_role="repair" if repair_generation else "initial",
        repair_generation=repair_generation,
        repair_batches=repair_batches,
        secondary_failures=secondary_failures,
    )
    if not programs:
        exc = GeometryAuthorError(
            "geometry author and compiler repair yielded no valid programs",
            diagnostics=failure_diagnostics,
        )
        _save_author_cache(cache_path.with_suffix(".rejected.json"), {
            "cache_schema_version": "arr.maas.geometry_llm_author_cache.v3",
            "validation_status": "rejected",
            "validation_error": "geometry_author_batch_rejected",
            "model": selected_model,
            "response_id": response_id,
            "payload": payload,
            "compiler_repair_feedback": repair_diagnostics,
            "failure_diagnostics": failure_diagnostics,
        })
        raise exc
    programs = [replace(program, metadata={
        **program.metadata,
        "author_failure_diagnostics": failure_diagnostics,
    }) for program in programs]
    _save_author_cache(cache_path, {
        "cache_schema_version": "arr.maas.geometry_llm_author_cache.v3",
        "validation_status": "accepted",
        "model": selected_model,
        "response_id": response_id,
        "payload": payload,
        "compiled_programs": [program.to_dict() for program in programs],
        "compiler_repair_feedback": repair_diagnostics,
        "compiler_repair_generation_count": max((
            int(program.metadata.get("author_compiler_repair_generation") or 0)
            for program in programs
        ), default=0),
        "book_principle_ids": list(book_principle_ids),
        "book_composition_path_ids": list(book_composition_path_ids),
    })
    return _admit_paid_author_programs(programs)


def _admit_paid_author_programs(
    programs: tuple[GeometryProgram, ...] | list[GeometryProgram],
) -> tuple[GeometryProgram, ...]:
    """Record only programs emitted by this paid-provider boundary."""

    admitted = tuple(programs)
    for program in admitted:
        admit_paid_provider_program(program)
    return admitted


def _decorate_author_programs(
    programs: tuple[GeometryProgram, ...] | list[GeometryProgram],
    *,
    model: str,
    response_id: str,
    cache_hit: bool,
    book_principle_ids: tuple[str, ...] = (),
) -> tuple[GeometryProgram, ...]:
    return tuple(replace(program, metadata={
        **program.metadata,
        "author_provider": "openai_llm_geometry_author",
        "author_model": model,
        "author_response_id": response_id or str(program.metadata.get("author_response_id") or ""),
        "author_cache_hit": bool(cache_hit),
        "author_prompt_contract": GEOMETRY_AUTHOR_PROMPT_CONTRACT,
        **(
            {"book_principle_ids": list(book_principle_ids)}
            if book_principle_ids
            else {}
        ),
    }) for program in programs)


def _book_graph_principle_vocabulary(
    context: dict[str, Any],
) -> tuple[str, ...]:
    if "book_graph_vocabulary" not in context:
        return ()
    vocabulary = context.get("book_graph_vocabulary")
    if not isinstance(vocabulary, (dict, list)):
        raise GeometryAuthorError("book_graph_vocabulary must be a JSON object or array")

    canonical_ids: set[str] = set()

    def collect(value: Any) -> None:
        if isinstance(value, dict):
            principle_id = value.get("principle_id")
            if isinstance(principle_id, str) and principle_id.strip():
                canonical_ids.add(principle_id.strip())
            for nested in value.values():
                collect(nested)
        elif isinstance(value, list):
            for nested in value:
                collect(nested)

    collect(vocabulary)
    if not canonical_ids:
        raise GeometryAuthorError(
            "book_graph_vocabulary contains no canonical book principle ids"
        )
    return tuple(sorted(canonical_ids))


def _canonical_book_principle_ids(
    context: dict[str, Any],
    provenance: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    canonical_ids = set(_book_graph_principle_vocabulary(context))
    if not canonical_ids:
        return ()
    requested = (
        provenance.get("book_principle_ids")
        if isinstance(provenance, dict)
        else None
    )
    if not isinstance(requested, (list, tuple)) or not requested:
        raise GeometryAuthorError(
            "book_principle_ids are required in vocabulary-bearing author provenance"
        )
    normalized: list[str] = []
    for value in requested:
        principle_id = value.strip() if isinstance(value, str) else ""
        if not principle_id or principle_id not in canonical_ids:
            raise GeometryAuthorError(
                f"unknown canonical book principle id: {value!r}"
            )
        if principle_id not in normalized:
            normalized.append(principle_id)
    return tuple(normalized)


def _canonical_book_composition_path_ids(
    context: dict[str, Any],
    provenance: dict[str, Any],
    *,
    count: int,
) -> tuple[str, ...]:
    offered = {
        item["path_id"]
        for item in _book_composition_path_slice(context, count)
    }
    if not offered:
        return ()
    programs = provenance.get("programs")
    if not isinstance(programs, list) or not programs:
        raise GeometryAuthorError(
            "book composition path bindings require authored programs"
        )
    selected: list[str] = []
    for item in programs:
        path_id = (
            str(item.get("book_composition_path_id") or "").strip()
            if isinstance(item, dict)
            else ""
        )
        if not path_id or path_id not in offered:
            raise GeometryAuthorError(
                f"unknown offered BOOK composition path id: {path_id!r}"
            )
        if path_id in selected:
            raise GeometryAuthorError(
                "BOOK composition path ids must be unique within an authored batch"
            )
        selected.append(path_id)
    return tuple(selected)


def _valid_program_book_path_bindings(
    context: dict[str, Any],
    programs: tuple[GeometryProgram, ...],
    *,
    count: int,
) -> bool:
    offered = {
        item["path_id"]
        for item in _book_composition_path_slice(context, count)
    }
    if not offered or not programs:
        return False
    selected = [
        str(program.metadata.get("book_composition_path_id") or "").strip()
        for program in programs
    ]
    return bool(
        all(path_id in offered for path_id in selected)
        and len(selected) == len(set(selected))
    )


def _author_payload_compiler_diagnostics(
    payload: dict[str, Any],
    *,
    program_context: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    diagnostics: list[dict[str, Any]] = []
    seen_hashes: set[str] = set()
    for index, item in enumerate(payload.get("programs") or ()):
        if not isinstance(item, dict):
            diagnostics.append({
                "raw_index": index,
                "category": "schema",
                "rejection_codes": ["non_object_program"],
            })
            continue
        try:
            if isinstance(item.get("nodes"), list):
                program = _program_from_structured_author_item(
                    item, index=index
                )
            else:
                program = parse_geometry_dsl(
                    str(item.get("dsl") or ""),
                    name=str(item.get("name") or f"llm_geometry_{index + 1:02d}"),
                )
            program = _canonicalize_program_relation_suffix(program)
            compilation = compile_geometry_program(program)
            issues = tuple(
                compilation.issues
                or compilation_gate(compilation, AUTHOR_GEOMETRY_GATE_POLICY)
            )
            inferred_seed = _infer_base_seed(program)
            incompatible_macro = next((
                node.operator
                for node in program.topological_nodes()
                if node.operator in SEMANTIC_MACRO_BASE_SEEDS
                and inferred_seed not in SEMANTIC_MACRO_BASE_SEEDS[node.operator]
            ), "")
            nonterminal_relation = _nonterminal_program_relation(program)
            access_relation_issue = _misaligned_access_relation(program, program_context or {})
            language_contract_issue = _program_language_contract_issue(program, program_context or {})
            known_seeds = {spec.seed_id for spec in BASE_SEED_SPECS}
            declared_seed = str(item.get("base_seed") or "").strip().lower()
            declared_seed_mismatch = bool(
                declared_seed in known_seeds and declared_seed != inferred_seed
            )
            known_forms = {spec.form_id for spec in BASE_FORM_SPECS}
            inferred_form = _infer_base_form(program)
            declared_form = str(item.get("base_form_id") or "").strip().lower()
            declared_form_mismatch = bool(
                declared_form in known_forms and declared_form != inferred_form
            )
            if (
                compilation.status == "compiled"
                and not issues
                and not incompatible_macro
                and not nonterminal_relation
                and not access_relation_issue
                and not language_contract_issue
                and not declared_seed_mismatch
                and not declared_form_mismatch
            ):
                program_hash = program.program_hash()
                if program_hash in seen_hashes:
                    diagnostics.append({
                        "raw_index": index,
                        "category": "duplicate",
                        "rejection_codes": ["duplicate_program"],
                    })
                else:
                    seen_hashes.add(program_hash)
                continue
            rejection_codes = [
                str(issue.code)
                if str(issue.code) in _AUTHOR_REJECTION_CODES
                else "compiler_gate_rejected"
                for issue in issues[:6]
            ]
            if compilation.status != "compiled" and not rejection_codes:
                rejection_codes.append("compiler_gate_rejected")
            if incompatible_macro:
                rejection_codes.append("semantic_macro_base_seed_mismatch")
            if nonterminal_relation:
                rejection_codes.append("program_relation_not_terminal_suffix")
            if access_relation_issue:
                rejection_codes.append("program_access_relation_not_bound")
            if language_contract_issue:
                rejection_codes.append("program_geometry_language_contract_failed")
            if declared_seed_mismatch:
                rejection_codes.append("declared_base_seed_mismatch")
            if declared_form_mismatch:
                rejection_codes.append("declared_base_form_mismatch")
            diagnostics.append({
                "raw_index": index,
                "category": "compiler_or_gate",
                "rejection_codes": sorted(set(rejection_codes)),
            })
        except (GeometryDslError, TypeError, ValueError, json.JSONDecodeError):
            diagnostics.append({
                "raw_index": index,
                "category": "ast_decode",
                "rejection_codes": ["ast_decode_error"],
            })
    return diagnostics


def geometry_programs_from_author_payload(
    payload: dict[str, Any],
    *,
    expected_count: int | None = None,
    program_context: dict[str, Any] | None = None,
) -> tuple[GeometryProgram, ...]:
    programs: list[GeometryProgram] = []
    seen_hashes: set[str] = set()
    rejected: list[str] = []
    for index, item in enumerate(payload.get("programs") or []):
        if not isinstance(item, dict):
            continue
        try:
            facing = item.get("facing")
            if facing is not None:
                sides = ("east", "west", "north", "south")
                if (not isinstance(facing, dict)
                        or set(facing) - {"access_side", "north_side"}
                        or facing.get("access_side") not in sides
                        or facing.get("north_side") not in (*sides, None)):
                    raise ValueError("invalid authored facing sides")
            if item.get("site_fit") not in (None, "inherit", "impose"):
                raise ValueError("invalid authored site_fit")
            if isinstance(item.get("nodes"), list):
                program = _program_from_structured_author_item(item, index=index)
            else:
                # v4 cache/test compatibility. Live v5 responses are typed
                # node graphs and never rely on a free-form DSL string.
                program = parse_geometry_dsl(
                    str(item.get("dsl") or ""),
                    name=str(item.get("name") or f"llm_geometry_{index + 1:02d}"),
                )
            program = _canonicalize_program_relation_suffix(program)
        except (GeometryDslError, TypeError, ValueError, json.JSONDecodeError) as exc:
            rejected.append(f"{index + 1}:{exc}")
            continue
        compilation = compile_geometry_program(program)
        gate_issues = compilation_gate(compilation, AUTHOR_GEOMETRY_GATE_POLICY)
        if compilation.status != "compiled" or gate_issues:
            # "compile_failed" alone names nothing the author can fix; the
            # compiler's issue says which node and why, and the gate knows
            # how many pieces a disconnected mass came apart into.
            if compilation.status != "compiled":
                reason = compilation.status + "".join(
                    f"[{issue.code}@{issue.node_id}: {issue.message}]".replace(";", ",")
                    for issue in (compilation.issues or ())[:2]
                )
            else:
                reason = ",".join(issue.code for issue in gate_issues[:4])
                components = (compilation.metrics or {}).get("component_count")
                if components and "disconnected_component_budget_exceeded" in reason:
                    reason += f"[components={int(components)}]"
            rejected.append(f"{index + 1}:compile_or_clean_gate:{reason}")
            continue
        known_seeds = {spec.seed_id for spec in BASE_SEED_SPECS}
        declared_seed = str(item.get("base_seed") or "").strip().lower()
        inferred_seed = _infer_base_seed(program)
        if declared_seed in known_seeds and declared_seed != inferred_seed:
            rejected.append(
                f"{index + 1}:declared_base_seed_{declared_seed}_does_not_match_{inferred_seed}"
            )
            continue
        base_seed = inferred_seed
        known_forms = {spec.form_id for spec in BASE_FORM_SPECS}
        declared_form = str(item.get("base_form_id") or "").strip().lower()
        inferred_form = _infer_base_form(program)
        if declared_form in known_forms and declared_form != inferred_form:
            rejected.append(
                f"{index + 1}:declared_base_form_{declared_form}_does_not_match_{inferred_form}"
            )
            continue
        base_form_id = inferred_form
        incompatible_macro = next((
            node.operator
            for node in program.topological_nodes()
            if node.operator in SEMANTIC_MACRO_BASE_SEEDS
            and base_seed not in SEMANTIC_MACRO_BASE_SEEDS[node.operator]
        ), "")
        if incompatible_macro:
            rejected.append(
                f"{index + 1}:semantic_macro_{incompatible_macro}_incompatible_with_{base_seed}_seed"
            )
            continue
        nonterminal_relation = _nonterminal_program_relation(program)
        if nonterminal_relation:
            rejected.append(
                f"{index + 1}:program_relation_must_be_terminal_suffix:{nonterminal_relation}"
            )
            continue
        access_relation_issue = _misaligned_access_relation(program, program_context or {})
        if access_relation_issue:
            rejected.append(f"{index + 1}:program_access_relation_not_bound:{access_relation_issue}")
            continue
        language_contract_issue = _program_language_contract_issue(program, program_context or {})
        if language_contract_issue:
            rejected.append(
                f"{index + 1}:program_geometry_language_contract_failed:{language_contract_issue}"
            )
            continue
        base_seed_controller_id = _base_seed_controller_id(program, base_seed)
        if base_seed_controller_id:
            program = program.with_nodes(
                replace(node, semantic_role="base_seed")
                if node.id == base_seed_controller_id
                else node
                for node in program.nodes
            )
        program = program.with_nodes(
            replace(node, provenance={
                **(node.provenance or {}),
                "program_invariant": True,
                "program_invariant_kind": (
                    "section" if node.operator == "profiled_hall" else "access_relation"
                ),
            })
            if _is_program_relation_node(node)
            else node
            for node in program.nodes
        )
        operator_path = [
            node.operator for node in program.topological_nodes()
            if node.kind != "primitive" and node.semantic_role != "base_seed"
        ]
        program = replace(program, metadata={
            **program.metadata,
            "language_layer": "llm_authored_recursive_geometry",
            "family": "llm_" + ("_".join(operator_path) if operator_path else "prismatic"),
            "base_seed": base_seed,
            "base_form_id": base_form_id,
            "intent_tags": [str(value) for value in item.get("intent_tags") or ()][:12],
            **({"dimensional_intent": validate_intent(item["dimensional_intent"])} if item.get("dimensional_intent") is not None else {}),
            **({"facing": dict(facing)} if facing is not None else {}),
            **({"site_fit": item["site_fit"]} if item.get("site_fit") is not None else {}),
            "operator_path": operator_path or ["prismatic"],
            "author_provider": "structured_geometry_dsl_payload",
            "parcel_coordinates_in_program": False,
            "completed_building_template": False,
            **(
                {
                    "book_composition_path_id": str(
                        item["book_composition_path_id"]
                    ),
                }
                if str(item.get("book_composition_path_id") or "").strip()
                else {}
            ),
            "author_representation": (
                "typed_json_ast" if isinstance(item.get("nodes"), list) else "legacy_dsl"
            ),
            "canonical_dsl": program_to_dsl(program),
        })
        program_hash = program.program_hash()
        if program_hash in seen_hashes:
            rejected.append(f"{index + 1}:duplicate_program")
            continue
        seen_hashes.add(program_hash)
        programs.append(program)
    minimum = max(1, int(expected_count or 1))
    if len(programs) < minimum:
        raise GeometryAuthorError(
            # The whole list. Twelve of it went to the author, the author
            # fixed twelve, and the next twelve surfaced - the retry read
            # "still twelve" as no progress and stopped the round.
            "geometry author batch yielded insufficient valid unique programs"
            + (": " + "; ".join(rejected) if rejected else "")
        )
    input_count = len(payload.get("programs") or ())
    return tuple(replace(program, metadata={
        **program.metadata,
        "author_batch_requested_count": input_count,
        "author_batch_valid_count": len(programs),
        "author_batch_rejected_count": max(0, input_count - len(programs)),
    }) for program in programs)


def _program_from_structured_author_item(item: dict[str, Any], *, index: int) -> GeometryProgram:
    """Decode the strict Responses schema directly into a typed AST.

    Parameter values are discriminated JSON fields. This removes the v4
    failure mode where the outer response was valid JSON but its embedded DSL
    string contained variable-valued parameters or other non-literals.
    """
    raw_nodes = [raw for raw in item.get("nodes") or () if isinstance(raw, dict)]
    identity_aliases: dict[str, str] = {}
    kind_corrections: list[dict[str, str]] = []
    parameter_type_corrections: list[dict[str, str]] = []
    for raw in raw_nodes:
        inputs = [str(value) for value in raw.get("inputs") or ()]
        if (
            str(raw.get("operator") or "") in {"union", "intersection"}
            and len(inputs) == 1
            and not (raw.get("parameters") or ())
        ):
            identity_aliases[str(raw.get("id") or "")] = inputs[0]

    def resolve_alias(node_id: str) -> str:
        visited: set[str] = set()
        while node_id in identity_aliases and node_id not in visited:
            visited.add(node_id)
            node_id = identity_aliases[node_id]
        return node_id

    for raw in raw_nodes:
        operator = str(raw.get("operator") or "")
        inputs = [resolve_alias(str(value)) for value in raw.get("inputs") or ()]
        if operator in {
            "union", "difference", "intersection", "attach", "bridge", "attach_volume",
        } and len(inputs) > 1 and len(set(inputs)) != len(inputs):
            node_id = str(raw.get("id") or "")
            raise ValueError(
                f"{node_id}:{operator}:composition inputs must reference distinct earlier solids"
            )

    nodes: list[GeometryNode] = []
    for raw in raw_nodes:
        if not isinstance(raw, dict):
            raise TypeError("structured author node must be an object")
        if str(raw.get("id") or "") in identity_aliases:
            continue
        operator = str(raw.get("operator") or "")
        raw_kind = str(raw.get("kind") or "")
        compatible_kinds = [
            kind for kind, operators in OPERATORS_BY_KIND.items()
            if operator in operators
        ]
        kind = raw_kind
        if raw_kind not in compatible_kinds and (
            len(compatible_kinds) == 1 or operator in CANONICAL_OPERATOR_KIND
        ):
            kind = CANONICAL_OPERATOR_KIND.get(operator, compatible_kinds[0])
            kind_corrections.append({
                "node_id": str(raw.get("id") or ""),
                "declared_kind": raw_kind,
                "contract_kind": kind,
                "operator": operator,
            })
        parameters: dict[str, Any] = {}
        for parameter in raw.get("parameters") or ():
            if not isinstance(parameter, dict):
                raise TypeError("structured author parameter must be an object")
            name = str(parameter.get("name") or "").strip()
            if not name:
                raise ValueError("structured author parameter name is required")
            allowed_parameters = OPERATOR_PARAMETER_CONTRACTS.get(operator)
            if allowed_parameters is not None and name not in allowed_parameters:
                raise ValueError(
                    f"unknown_author_parameter:{operator}.{name}"
                )
            declared_value_type = str(parameter.get("value_type") or "")
            value_contract = _author_parameter_value_contract(operator, name)
            contract_type = str(value_contract.get("type") or "")
            value_type = {
                "numeric_vector": "vector",
                "structured_literal": "structured_json",
                "matrix4": "matrix4",
                "literal": declared_value_type,
            }.get(contract_type, contract_type)
            if contract_type == "matrix4" and declared_value_type == "structured_json":
                # Read older cached/provider payloads while all new schemas use
                # a real nested numeric array instead of a token-heavy string.
                value_type = "structured_json"
            if value_type not in {"number", "string", "boolean", "vector", "structured_json"}:
                if value_type != "matrix4":
                    value_type = declared_value_type
            if value_type != declared_value_type:
                parameter_type_corrections.append({
                    "node_id": str(raw.get("id") or ""),
                    "operator": operator,
                    "parameter": name,
                    "declared_value_type": declared_value_type,
                    "contract_value_type": value_type,
                })
            if value_type == "number":
                value: Any = float(parameter.get("numeric_value") or 0.0)
            elif value_type == "string":
                value = str(parameter.get("string_value") or "")
            elif value_type == "boolean":
                value = bool(parameter.get("boolean_value"))
            elif value_type == "vector":
                value = [float(component) for component in parameter.get("vector_value") or ()]
            elif value_type == "structured_json":
                value = json.loads(str(parameter.get("structured_json") or "null"))
            elif value_type == "matrix4":
                value = parameter.get("matrix4_value")
            else:
                raise ValueError(f"unsupported structured parameter value_type {value_type}")
            if value_type == "number":
                minimum = value_contract.get("minimum")
                maximum = value_contract.get("maximum")
                if minimum is not None and value < float(minimum):
                    raise ValueError(
                        f"author_parameter_below_minimum:{operator}.{name}"
                    )
                if maximum is not None and value > float(maximum):
                    raise ValueError(
                        f"author_parameter_above_maximum:{operator}.{name}"
                    )
            elif value_type == "string" and "enum" in value_contract:
                if value not in value_contract["enum"]:
                    raise ValueError(
                        f"author_parameter_outside_enum:{operator}.{name}"
                    )
            elif value_type == "vector" and "lengths" in value_contract:
                allowed_lengths = tuple(int(length) for length in value_contract["lengths"])
                if len(value) not in allowed_lengths:
                    raise ValueError(
                        f"author_parameter_vector_length:{operator}.{name}"
                    )
            parameters[name] = value
        nodes.append(GeometryNode(
            id=str(raw.get("id") or ""),
            kind=kind,
            operator=operator,
            inputs=tuple(resolve_alias(str(value)) for value in raw.get("inputs") or ()),
            parameters=parameters,
            semantic_role=str(raw.get("semantic_role") or ""),
            provenance={
                "source": "openai_llm_geometry_author",
                "representation": "typed_json_ast",
            },
        ))
    return GeometryProgram(
        nodes=tuple(nodes),
        root_id=resolve_alias(str(item.get("root_id") or "")),
        name=str(item.get("name") or f"llm_geometry_{index + 1:02d}"),
        metadata={
            "authored_structured_ast": True,
            **(
                {
                    "book_composition_path_id": str(
                        item["book_composition_path_id"]
                    ),
                }
                if str(item.get("book_composition_path_id") or "").strip()
                else {}
            ),
            "canonicalized_identity_boolean_node_ids": sorted(identity_aliases),
            "contract_lowered_node_kind_corrections": kind_corrections,
            "contract_lowered_parameter_type_corrections": parameter_type_corrections,
        },
    )


def _book_composition_path_slice(
    context: dict[str, Any],
    count: int,
) -> list[dict[str, Any]]:
    """Offer a deterministic, stratified slice; the LLM chooses within it."""

    if "book_graph_vocabulary" not in context:
        return []
    from backend.app.modules.design.generation.maas.book_language.composition_lattice import iter_book_composition_paths

    paths = tuple(
        item for item in iter_book_composition_paths()
        if item.executable
    )
    if not paths:
        return []
    # Every program must bind a distinct offered path, so the offer can never
    # be smaller than the request: a 120-program request offered 96 paths and
    # could not pass its own uniqueness check.
    path_cap = max(96, int(count))
    wanted = min(path_cap, max(16, int(count) * 4))
    identity = json.dumps({
        "program_id": context.get("program_id") or context.get("building_type"),
        "author_stage": context.get("author_stage"),
        "author_request_kind": context.get("author_request_kind"),
        "failure_feedback": context.get("compiler_repair_feedback"),
        "author_batch_index": context.get("author_batch_index"),
        "author_batch_count": context.get("author_batch_count"),
        "author_variation_offset": context.get("author_variation_offset"),
        "legal_fit_repair_feedback": context.get("legal_fit_repair_feedback"),
        "capacity_authoring_deficits": context.get("capacity_authoring_deficits"),
        "family_supply_deficits": context.get("family_supply_deficits"),
        "book_graph_supply": context.get("book_graph_supply"),
    }, sort_keys=True, separators=(",", ":"), default=str)
    if context.get("book_path_sampling_version") == 2:
        # A stride through fraction/orientation/variation-major lattice order
        # aliases the principle axis: 24 paths could expose only six principles.
        # Offer each executable principle before adding any second variant.
        # This is author vocabulary supply, not a quota on returned designs.
        identity = json.dumps({
            "legacy_context_identity": identity,
            "creative_portfolio_run_id": context.get("creative_portfolio_run_id"),
            "book_path_sampling_version": 2,
        }, sort_keys=True, separators=(",", ":"), default=str)
        groups: dict[str, list[Any]] = {}
        for path in paths:
            groups.setdefault(path.principle_id, []).append(path)
        # Rank groups with the request identity, so a future vocabulary larger
        # than the cap does not always lose the same alphabetical tail.
        principle_ids = sorted(groups, key=lambda principle_id: (
            hashlib.sha256(f"{identity}:{principle_id}".encode("utf-8")).hexdigest(),
            principle_id,
        ))
        wanted = min(path_cap, len(paths), max(wanted, len(principle_ids)))
        variant_offsets = {
            principle_id: int(hashlib.sha256(
                f"{identity}:{principle_id}".encode("utf-8")
            ).hexdigest()[:12], 16) % len(groups[principle_id])
            for principle_id in principle_ids
        }
        selected = []
        variant_index = 0
        while len(selected) < wanted:
            for principle_id in principle_ids:
                variants = groups[principle_id]
                if variant_index < len(variants):
                    selected.append(variants[
                        (variant_offsets[principle_id] + variant_index) % len(variants)
                    ])
                    if len(selected) == wanted:
                        break
            variant_index += 1
    else:
        # Frozen contexts without the version opt-in must keep their exact offer.
        stride = max(1, len(paths) // wanted)
        offset = int(
            hashlib.sha256(identity.encode("utf-8")).hexdigest()[:12],
            16,
        ) % stride
        selected = [
            paths[(offset + index * stride) % len(paths)]
            for index in range(wanted)
        ]
    compact: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in selected:
        if item.path_id in seen:
            continue
        seen.add(item.path_id)
        path_contract = item.to_dict()
        compact.append({
            "path_id": item.path_id,
            "base_volume_label": item.base_volume_label,
            "orientation": item.orientation,
            "variation_index": item.variation_index,
            "principle_id": item.principle_id,
            "principle_kind": item.principle_kind,
            "ordered_operations": list(item.ordered_operations),
            "graph_edges": [list(edge) for edge in item.graph_edges],
            "topology_class": item.topology_class,
            "matrix4_contract": path_contract["matrix4_contract"],
            "parameter_state": path_contract["parameter_state"],
        })
    return compact


def author_rules_text() -> str:
    """The rules the importer enforces that a schema cannot express, in the author's terms.

    Derived from the tables the importer itself reads, so the prompt, the
    cycle's rejection feedback and the check cannot drift apart. Each line
    cost comp18 a rejected program the author could not have foreseen: seven
    declared seeds the nodes contradicted, two `split_wing` on a block seed,
    two `intersect_related` on axis z, one `shear` with axis == direction,
    seven compositions that came apart.
    """

    seed_scales = ", ".join(
        f"{spec.seed_id} ({', '.join(f'{v:.2f}' for v in spec.normalized_scale)})"
        for spec in BASE_SEED_SPECS if spec.primitive_operator == "box")
    macro_seeds = "; ".join(
        f"{macro} needs a {' / '.join(sorted(seeds))} seed"
        for macro, seeds in sorted(SEMANTIC_MACRO_BASE_SEEDS.items()))
    return (
        "- `base_seed` is checked against the proportions your nodes build. The importer reads the first "
        "`scale` node on the seed `box` and matches it within 0.08 per axis to " + seed_scales + "; a "
        "`matrix4` node is not read as a scale. Without one it reads the box's own width/depth/height: "
        "taller than 1.35x its widest side is tower, plan aspect 2.2 or more is bar, lower than 0.48x its "
        "narrowest side is slab, otherwise block. Declare the seed those numbers imply." + chr(10) +
        "- Some macros only fit some seeds: " + macro_seeds + ". On any other seed the program is rejected." + chr(10) +
        "- `intersect_related` and the other *_related relations take `axis` x or y only; the compiler "
        "rejects z even where a schema branch lists it." + chr(10) +
        "- `shear` needs `axis` and `direction` to be different axes; equal ones are an invalid affine "
        "transform." + chr(10) +
        "- A parameter's `value_type` is one of number, string, boolean, vector, structured_json - exactly "
        "what its schema branch names. `literal` is a parameter KIND in the catalogue, never a value_type; "
        "a literal-kind parameter is written with the value_type and single value field the schema "
        "branch shows for it." + chr(10) +
        "- Structural Support & Grounding Invariant: Architectural massing defines the external building envelope and volumetric "
        "hierarchy (internal cores, rooms, and circulation belong to schematic floor plans, not massing). A mass should sit directly "
        "on the ground; if an elevated undercroft or cantilever is authored (e.g. lift, piloti), it must not float unsupported in air "
        "and should include structural columns (semantic_role='column') or anchored mass volume so that the solid reaches the ground. "
        "Ungrounded floating components are rejected by the maximum_components=1 gate." + chr(10) +
        "- Dynamic Storey Evaluation (1F to 5F): 5 storeys is the legal maximum ceiling, NOT a mandatory target. The author should evaluate "
        "2F, 3F, 4F, or 5F based on program requirements and daylight setback. Proposing a 2F or 3F low-rise scheme (height <= 10m) has the "
        "architectural advantage of completely avoiding North sunlight setback cuts (which only take effect above 10m), while maximizing "
        "ground public courtyards and open piloti."
    )


def _author_prompt(context: dict[str, Any], count: int) -> str:
    # Source-level graph memory is already bounded and coordinate-free. Keep
    # enough room for transferable post-BOOK repair priors; the previous 12k
    # cut could silently drop the final keys after successful genotype priors.
    bounded_context = {
        key: value
        for key, value in context.items()
        if key not in {
            "book_graph_vocabulary",
            "book_principle_ids",
            "base_capacity_contract",
            "design_reference",
        }
    }
    program_context = (
        dict(bounded_context.get("program_context"))
        if isinstance(bounded_context.get("program_context"), dict)
        else {}
    )
    nested_capacity = program_context.pop("base_capacity_contract", None)
    if "program_context" in bounded_context:
        bounded_context["program_context"] = program_context
    capacity_contract = (
        context.get("base_capacity_contract")
        if isinstance(context.get("base_capacity_contract"), dict)
        else nested_capacity
    )
    if isinstance(capacity_contract, dict):
        bounded_context["capacity_design_budget"] = {
            key: capacity_contract.get(key)
            for key in (
                "feasible_maximum_floor_area_m2",
                "minimum_utilization",
                "target_utilization",
                "target_floor_areas_m2",
                "legal_floor_section_areas_m2",
            )
            if capacity_contract.get(key) is not None
        }
        legal_design_context = normalized_legal_field_design_context(
            capacity_contract
        )
        if legal_design_context:
            bounded_context["legal_field_design_context"] = (
                legal_design_context
            )
            site_relation = (
                dict(bounded_context.get("site_relation"))
                if isinstance(bounded_context.get("site_relation"), dict)
                else {}
            )
            site_relation.update({
                "absolute_coordinates_available_to_author": False,
                "normalized_legal_constraint_context_available": True,
            })
            bounded_context["site_relation"] = site_relation
    # The frozen reference is a bounded package. Render it separately so a large
    # unrelated memory cannot truncate its actual image paths and objective.
    design_reference_text = (
        "Frozen design reference (inspect the actual image files before authoring):\n"
        + json.dumps(context["design_reference"], ensure_ascii=False, sort_keys=True)
        if context.get("design_reference") else ""
    )
    context_text = json.dumps(
        bounded_context,
        ensure_ascii=False,
        sort_keys=True,
    )[:24000]
    book_graph_vocabulary_text = (
        json.dumps(
            context["book_graph_vocabulary"],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if "book_graph_vocabulary" in context
        else "not supplied (legacy context)"
    )
    offered_book_paths = _book_composition_path_slice(context, count)
    offered_book_paths_text = (
        json.dumps(
            offered_book_paths,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        if offered_book_paths
        else "not supplied (legacy context)"
    )
    # The catalogue the author reads and the enum the schema enforces must be
    # one list. This dumped every operator contract while `_author_schema`
    # took its operators from `_allowed_author_operators`, which withholds
    # `book_base_volume` - the scope the cycle sets, not a word an author
    # says. Measured on comp18: the author read the word here, used it, and
    # its whole batch failed the schema it was also told to obey.
    allowed_operator_set = set(_allowed_author_operators(context))
    # Rendered in the schema's vocabulary. The catalogue's own word for a
    # parameter is its contract kind - `literal` for an unbounded ratio - and
    # printing that raw put a word in front of the author that no schema
    # branch accepts and the importer rejects: comp18 carried `value_type:
    # literal` in 110 of 120 programs. Each entry now names the value_type(s)
    # its schema branch will take, through the same translation the schema uses.
    def rendered(operator, parameter):
        contract = dict(_author_parameter_value_contract(operator, parameter))
        kind = contract.pop("type", "literal")
        contract["value_type"] = _schema_value_types(kind)
        return contract

    parameter_contracts = json.dumps({
        operator: {
            parameter: rendered(operator, parameter)
            for parameter in sorted(parameters)
        }
        for operator, parameters in sorted(OPERATOR_PARAMETER_CONTRACTS.items())
        if operator in allowed_operator_set
    }, ensure_ascii=False, sort_keys=True)
    author_rules = author_rules_text()
    allowed_base_seeds = ", ".join(_allowed_author_base_seeds(context))
    allowed_base_forms = ", ".join(spec.form_id for spec in BASE_FORM_SPECS)
    allowed_macro_operators = ", ".join(_allowed_author_macro_operators(context))
    program_context = (
        context.get("program_context")
        if isinstance(context.get("program_context"), dict)
        else {}
    )
    semantic_invariants = [
        item
        for item in program_context.get("semantic_invariants") or ()
        if isinstance(item, dict)
    ]
    program_role_vocabulary = sorted({
        str(item.get(key) or "").strip()
        for item in semantic_invariants
        for key in ("subject_role", "object_role")
        if str(item.get(key) or "").strip()
    })
    role_vocabulary_text = ", ".join(program_role_vocabulary) or (
        "dominant_mass, public_threshold, program_space"
    )
    program_id = str(
        program_context.get("program_id")
        or context.get("building_type")
        or "program"
    )
    return f"""Create exactly {count} executable and materially different architectural mass programs as typed AST node graphs.

NON-NEGOTIABLE MASS MEMORY:
- The causal representation is UnitBox -> authored base-form capability -> one global homogeneous 4x4 Matrix4
  -> BOOK p.3 fraction scope -> orientation -> typed BOOK operations
  -> typed CSG -> deterministic legal projection. In this AST, the normalized base scale is the BaseVolume and every
  translate/rotate/scale/shear is lowered into that explicit Matrix4 chain. Do not author parcel coordinates or a
  separately recentered floor stack.
- The LLM owns architectural authorship. Deterministic code owns zoning, setbacks, height, FAR/GFA, parking,
  connectivity, mesh validity, and final admission; it may reject a design but must never replace it with a generic mass.
- Qatar National Library and other references contribute capabilities only: continuous public space, circulation-section,
  span, void, and aggregation. Never copy their completed outline. Translate a capability into executable topology.
- The BOOK is a compositional graph, not a checklist. Compose its BaseVolume fractions, orientations, thirty base
  operatives, bounded variations, combination edges, aggregation methods, and case-study relation paths into a broad
  lattice containing thousands of executable possibilities; author and rank materially distinct AST paths from that
  lattice before choosing the requested portfolio. The requested twenty are selections from this large graph space.
- Never assign one required language per output and never force one law-friendly operator across the batch. Taper is only
  one possible graph node beside expand, branch, merge, nest, offset, bend, skew, split, twist, interlock, intersect,
  lift, lodge, overlap, rotate, shift, carve, compress, fracture, grade, notch, pinch, shear, embed, extract, inscribe,
  puncture, plus valid combination and aggregation paths. Labels and parameter-only variants do not count.
- Candidate identity binds BaseVolume scope, orientation, ordered operative nodes, combination/aggregation edges,
  topology, and parameters. Measure diversity both in graph/topology space before BOOK and in certified visible-mesh
  space after legal projection. A maximum-FAR staircase or repeated cake-tier envelope is failure even when inputs differ.
- Preserve the authored inter-floor pose with one global plan transform. Continuous taper, shear, wing, bridge, court,
  void and section profiles are encouraged; independent floor inflation, per-floor recentering, and forced legal steps
  are forbidden. Never numerically inverse-compensate for the known legal floor contraction in the reusable AST.
- Treat sunlight/setback contraction as a continuous legal-envelope condition, not a command to emit separately extruded
  floor bands. Start continuous section transitions before a contracting legal height where necessary, so the closed
  solid band—not merely its midpoint slice—remains contained. Use one coherent authored section/profile that can survive
  continuous legal CSG; law-derived floor plates remain the deterministic GFA measurement authority and must not become
  the visible design language.
- Capacity is a whole-building design budget, not a maximum-FAR shape generator. Repair a measured capacity deficit with
  authored compactness, section profile, void ratio, or the one global Matrix4 while keeping the architectural concept;
  never fill the deficit by adding algorithmic tiers or independently scaling floors.
- A source-only compiler check is insufficient. Each candidate must survive its final production BOOK/program/legal projection,
  keep an authoritative nonempty certified visual mesh, use zero pose fallback, and remain visibly identifiable there.
  Meet explicit required programme and area using the supplied capacity_design_budget and its acceptance contract;
  legal ceilings are not automatic design targets. Missing programme or target area remains unknown: do not invent
  a minimum FAR share or claim programme compliance. Where supplied, distinguish minimum_utilization from
  target_utilization; only the deterministic contract determines admission. A lower-area alternative must establish
  a visible spatial benefit, not a prose-only exception or an automatic density bonus.
- For the requested portfolio, every selected candidate must remain LLM-authored, legal, capacity-passing, and
  materially diverse in the combined PNG. Count never authorizes a deterministic fallback or weakened diversity cap.

If mass_execution_agent_context is present, it is the measured causal trace from a prior candidate: preserve
successful active relations, repair failed_stages, never assume pending_required_stages passed, and target only
exact editable_ast_nodes that remain valid in the current program contract. It is not hidden-neuron evidence.

Use the response schema's nodes array. Nodes are ordered acyclic SSA: every input id must refer to an earlier node,
and root_id must reference the final intended solid. Encode every parameter through one discriminated value_type:
number, string, boolean, vector, or structured_json. Unused value fields stay at their schema defaults.
Do not create a one-input union/intersection merely to name result; root_id may point directly to the last meaningful node.
Architectural form names and BOOK operative names are different levels. A missing operative named
gable, mansard, butterfly or vault does not forbid those occupied geometries: use the supported
typed primitives and profiles/surfaces, then the actual transforms and compositions. For example,
an occupied body's upper profile can have one ridge, several folds, a central valley or a curved
crown; independently posed bodies can intersect, bridge or join into a different spatial hierarchy.
These illustrate available capabilities, not a required shape menu, a room programme or portfolio quota.
The set is for architects and clients to choose between architectural possibilities. Use the entire
live implemented repertoire as the available design space; do not narrow it to whichever example
was mentioned most recently. Compare actual ground/support relations, plan organization, occupied
body and section, solid/void and assembly/repetition across the whole set. Several roof variants
or several court variants can still offer the same choice. Names, source hashes, operator totals
and per-candidate acceptance do not prove portfolio breadth. Review the set visually and address
overlapping or missing requested relations before submission; inspect additional exact-mesh
views when the default view conceals supports or connections. Distinguish available, attempted
and delivered capabilities rather than claiming all registered operations were used.
Read the schema for the actual parameter contract. Do not append a courtyard/notch merely to match
an example or automatically replace a refused relation with one: preserve the intended source form
through targeted repair and inspect the delivered silhouette. A shaped solid without a court and
a composed assembly without a decorative roof are equally legitimate when they answer the brief.

Allowed primitives: box, cylinder, extruded_polygon, wedge, sweep, loft.
Allowed transforms: translate/move, rotate, scale, mirror, shear.
Allowed modifiers: ellipsoidize, tetrahedralize, bend, taper, twist, pinch, inflate, slice, clip, clip_fraction, cut_corner, bound_surfaces.
Allowed booleans: union, subtract/difference, intersection.
Allowed patterns: duplicate, linear_array, radial_array, mirror_array, stack.
Allowed compositions: attach, bridge.
Program-conditioned allowed macros: {allowed_macro_operators}.

Rules:
- Every node is one typed function call; parameters are explicit typed JSON values.
- A prior node can be reused; input references must remain acyclic.
- bound_surfaces intersects its existing input with typed top_surface and/or bottom_surface records carried
  as structured_json. Defaults are constant height 1 above and 0 below. Coordinates u,v are [0,1] across the
  input's current axis-aligned XY bounds; surface heights are shares of its current Z band. All values must
  remain in [0,1], with top provably above bottom. Types: constant (height), polynomial (terms [u_power,v_power,
  coefficient]), profile (points, axis, span), affine (surface, world_to_authored [a,b,d,e,xoff,yoff], scale, offset).
  Bound each occupied body separately before composing halls and connectors; a following underside represents
  a plate with air below, not a ground-filled hall. Existing holes and profiles are retained by intersection.
  Later transforms carry the finished mesh. Earlier transforms define the current axis-aligned surface frame;
  apply bounds before rotation when the surface must follow a body's local axes. No other operator accepts
  top_surface or bottom_surface. Surface bounds are body shaping and precede the terminal access suffix.
  Apply model/dimensional sizing before bound_surfaces. Enlarging a coarsely sampled curved body afterwards
  is explicitly refused; later rigid poses carry its mesh and preserve its occupied measurements.
  Apply nonlinear body warps and stack patterns before bound_surfaces. Their post-surface sampling transport
  is unsupported and refused; a constant taper has an affine proof and uses the ordinary scaling check.
  Attach resolves guest sizing from the host: size and bound the guest sufficiently before attachment too.
- semantic_role must name the architectural job carried by that executable node, using program_context
  semantic-invariant roles where applicable. The current program is {program_id}; its role vocabulary is:
  {role_vocabulary_text}. Do not borrow hall, gallery, tower, roof-section, or other roles from another program
  profile. Labels never substitute for geometry: the named role must be supported by
  that node's operator, ancestry and visible relation in the compiled solid.
- root_id may point directly to the final meaningful body or access-relation node. Never append a fake result,
  hall, bridge, lift, union or attach node merely to rename the solid or give it a terminal semantic label.
  `profiled_hall` and hall/roof-section roles are valid only when profiled_hall appears in the program-conditioned
  allowed macro list and the program semantic invariants require a long-span hall.
- Program public-threshold/court/entry nodes are terminal invariants: place courtyard, carve_void, notch, lift,
  cantilever or split_wing nodes with threshold/public/court/entry semantic roles after all body transforms and
  modifiers. A required profiled_hall section comes last. The BOOK compiler inserts its body mutations before
  this suffix so later transforms cannot erase or rotate the verified access relation.
- All body shaping, cut_corner, taper, bend, array, union, attach and bridge work must precede that terminal
  access suffix. If more than one public relation is used, they must form one unary ancestry chain; never put a
  public court/entry on a parallel branch and never transform, cut, union or attach after it.
- When program_context.site_access_side_in_program_frame is east/west/north/south, every public courtyard or
  carve_void must explicitly set open_side to that side, and every entry/public notch must explicitly set side to
  that side. An access-bound lift or split_wing must set access_side to that same side. A corner label alone is not
  an access binding. Use open_side="closed" only for a node whose semantic
  role is explicitly an internal environmental court, not the public threshold.
- Use bounded local normalized dimensions, not parcel coordinates and not a copied famous building.
- Optional placement: facing.access_side names the local east(+x)/north(+y)/west(-x)/south(-y)
  side to align exactly with the supplied world access direction. facing.north_side names the nearest local
  side toward the legal sunlight-setback removal; incompatible declarations are refused. Without directional
  legal evidence it remains an explicitly unverified preference. It does not assert true-north measurement.
  site_fit=inherit permits legal trimming; impose permits uniform plan shrink before trimming. Legal gates remain.
  Use null for either optional placement field to retain legacy placement, or omit them in local legacy payloads.
- Optional per-program dimensional_intent states an explicit physical proposal using the supplied schema:
  storey_count, storey_height_m, target_gfa_m2, delivery_policy=preserve_physical_dimensions, programme_status=unknown.
  This soft authored target is not a required project programme or a legal exemption. The importer must preserve
  the already physicalized dimensions or refuse the fit; it does not preserve the normalized source XYZ proportions.
  Use different explicit schedules and density targets across alternatives where the spatial idea calls for them.
  Use null in structured output (or omit in a local legacy payload) to retain legacy exploratory sizing. Never freeze all heights or maximize every FAR by default.
  Unsupported automatic growth policies are rejected. Actual project programme requirements remain separately binding.
- For book_branch or related_array, vertical_anchor=input_base preserves the incoming base during vertical scaling;
  center keeps legacy centered scaling. Choose input_base for grounded assemblies, center for deliberate relative
  elevation only when actual support remains valid. This never creates support beneath an intentionally elevated input.
- Keep parcel scope and base seed separate. Scope is supplied by the site graph. Select a normalized
  base_form_id from this independent authoring axis: {allowed_base_forms}. Its executable operator must occur before
  the one global Matrix4, and it is independent from the later BOOK fraction scope.
  Select a normalized
  base seed only from this program-profile allow-list: {allowed_base_seeds}. BLOCK is [1,1,1],
  SLAB is [2.2,1.45,0.28], BAR is [2.8,0.62,0.48], and TOWER is [0.68,0.68,2.5], all made
  by scaling the same UnitBox; PROFILED PRISM uses an explicit extruded_polygon. Never introduce
  a base seed omitted from the allow-list even if it exists in the global language.
- Do not produce parameter-only variants. Vary tree structure, topology, void/section/roof/composition language.
- Use at most {_author_body_rule_budget(context)} dominant body rules, from distinct
  effect families, plus exactly one access-bound court/carve/notch threshold when the program requires one.
  This is the same cross-layer budget applied after BOOK projection; do not stack courtyard+notch or
  carve_void+notch merely to make the graph look more detailed.
- For this request, BODY RULE BUDGET = {_author_body_rule_budget(context)} and PUBLIC ACCESS RULE BUDGET = 1.
  Count architectural effect families, not rationale words. A connected constructive assembly counts as one
  composition principle: distinct solid operands may use repeated scale/rotate/translate/matrix4 placement chains
  and nested union/attach/bridge joins. This exception is determined from executable graph edges, never semantic labels.
  Deformation and void operations on those operands still count; difference/intersection cutters are not assembly
  placement. A transform shared with a cutting branch does not receive the placement exception.
  A valid chain uses only the necessary distinct body effect families
  within that budget, followed by one ACCESS rule when required. Do not exceed the declared BODY RULE BUDGET and do not
  stack courtyard+notch, carve_void+lift, or lift+notch. The compiler rejects the whole candidate when either count
  is exceeded; extra nodes are not extra design quality.
{author_rules}
- The compiled author mesh must be one connected solid. Split/array/duplicate wings require an explicit physical
  bridge, spine or overlapping union; disconnected pieces are invalid. A connected material mesh may still contain
  several legible architectural volumes; material connectivity is not an architectural volume-count limit.
  Height bands are measurement proxies, not an authoring limit on that hierarchy.
- Cantilever is a horizontal backspan relation, so its vector z component must be 0. Use lift as a separate
  terminal relation when vertical clearance is intended.
- Use a stable final node id such as result and set root_id to it.
- Use only the executable parameter names in this compiler contract; an unknown or decorative parameter is rejected:
  {parameter_contracts}
- vector3 means a literal such as [0.04, 0, 0], never a scalar. Corner values are ne/nw/se/sw.
- setback/terrace/stepped_mass direction is x or y, never z. A composition bridge takes two prior solids.
- Every boolean/composition input must reference a distinct prior solid. `bridge(A, A)`, `attach(A, A)` and
  `union(A, A)` are invalid. A split_wing is already one relational solid: either use ground_spine=true or create
  two genuinely distinct transformed branches before bridge; never bridge the split_wing node to itself.
- Macro inputs are semantically typed: leaning_tower/tapered_tower require a TOWER seed; profiled_hall,
  bent_bar, cross_mass and split_wing require BAR, SLAB, or PROFILED PRISM. Prefer BAR for cross_mass,
  split_wing and bent_bar when it is available so the relation reads as long architectural wings instead
  of rotated or separated cube fragments. To make an oblique block, use shear, rotate, cantilever,
  cut_corner, or another compatible operator instead of mislabelling it as a tower or wing system.
- Never follow cross_mass, radial_array, or split_wing with an access-bound open courtyard/carve_void.
  Cutting an already repeated footprint through one edge produces separated toy fragments. split_wing must
  carry its own access_side; cross_mass should use one access-bound lift or a shallow side notch instead.
- Read outcome_graph_memory causally. Successful genotype operator paths are reusable relation priors,
  not completed-form templates. common_authored_body_failures are hard negative evidence for the new body.
  conditional_book_projection_failures identify relations the new body must make legible before projection.
- Do not repeat a topology associated with frequent final VLM failure merely because it compiles. For example,
  when the measured memory reports repeated box-like, pyramidal, fragmented, weak-threshold, or wrong-typology
  failures, choose a materially different tree and explicitly resolve that relation. A topology with zero
  visually verified projections is not a positive precedent.
- `author_forbidden_body_rule_families` is measured retry feedback, not a permanent language ban. Do not emit any
  source operator from a listed family; the typed parser rejects it before compilation so repeated failed families
  cannot consume BOOK-path search time.
- `author_forbidden_operators` is the finer-grained form of the same measured retry feedback. It suppresses only
  explicitly repeated operators while leaving other architectural languages in the same family available.
- outcome_graph_memory.portfolio_visual_feedback is the board-level sibling verdict. Treat repeated_family_groups
  as a batch-level negative constraint and distribute new tree topologies toward required_next_relations; it is not
  permission to reject an otherwise valid individual without compiling and rendering the new portfolio.
- Read reference_vlm_language before authoring. It contains only VLM-audited whole-building traits from
  program-compatible precedent images. Translate those traits into relations and executable operators; never
  copy one reference's completed silhouette, dimensions, or coordinates. If its hard_pass is false, do not
  invent precedent evidence and rely on the program semantic invariants instead.
- Across the requested batch, distribute primary ideas across continuous deformation, carved void, wing/court,
  sectional profile, overlap/bridge, and oblique cut where the program context permits. Do not let setback,
  terrace, roof pitch, or any single macro dominate the batch.

Program/site context:
{context_text}
{design_reference_text}

Select and return a non-empty `book_principle_ids` array using exact canonical ids from the vocabulary below.
These ids record transferable principles used by the authored AST; they are not completed-form labels.

The complete BOOK lattice contains 13,662 content-addressed executable paths. For this request, choose one
`book_composition_path_id` per program from the bounded cross-lattice offer below. Multiple programs may inspect the
same offer, but each returned program must select a different path id. The selected path binds its BaseVolume fraction,
orientation, one global Matrix4 contract, ordered operations, graph edges, topology class, and variation state; do not
substitute a hand-assigned language label or a path not present in this offer.

BOOK composition path offer:
{offered_book_paths_text}

Complete compact BOOK graph vocabulary (relation vocabulary only; never copy a completed form):
{book_graph_vocabulary_text}
"""


def _allowed_author_base_seeds(context: dict[str, Any]) -> list[str]:
    known = {spec.seed_id for spec in BASE_SEED_SPECS}
    requested = [
        str(value).strip().lower()
        for value in context.get("base_seeds") or ()
        if str(value).strip().lower() in known
    ]
    return list(dict.fromkeys(requested)) or [spec.seed_id for spec in BASE_SEED_SPECS]


def _geometry_language_contract(context: dict[str, Any]) -> dict[str, Any]:
    program_context = context.get("program_context")
    if not isinstance(program_context, dict):
        return {}
    contract = program_context.get("geometry_language_contract")
    return dict(contract) if isinstance(contract, dict) else {}


def _allowed_author_macro_operators(context: dict[str, Any]) -> list[str]:
    known = set(OPERATORS_BY_KIND["macro"])
    requested = [
        str(value).strip().lower()
        for value in _geometry_language_contract(context).get("allowed_macro_operators") or ()
        if str(value).strip().lower() in known
    ]
    return list(dict.fromkeys(requested)) or sorted(known)


def _allowed_author_operators(context: dict[str, Any]) -> list[str]:
    core = {
        operator
        for kind, values in OPERATORS_BY_KIND.items()
        if kind != "macro"
        for operator in values
        if operator != "book_base_volume"
    }
    return sorted(core | set(_allowed_author_macro_operators(context)))


def _author_schema(
    count: int,
    *,
    allowed_base_seeds: list[str] | tuple[str, ...] | None = None,
    allowed_operators: list[str] | tuple[str, ...] | None = None,
    book_principle_vocabulary: tuple[str, ...] = (),
    book_composition_path_ids: tuple[str, ...] = (),
) -> dict[str, Any]:
    operators = list(allowed_operators or sorted({
        operator
        for values in OPERATORS_BY_KIND.values()
        for operator in values
    }))
    node_schema = _author_node_schema(operators)
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["programs"],
        "properties": {
            "programs": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "name", "base_form_id", "base_seed", "intent_tags", "nodes", "root_id", "rationale", "dimensional_intent", "facing", "site_fit",
                    ],
                    "properties": {
                        "facing": {"anyOf": [{
                            "type": "object", "additionalProperties": False,
                            "required": ["access_side", "north_side"],
                            "properties": {
                                "access_side": {"enum": ["east", "west", "north", "south"]},
                                "north_side": {"enum": ["east", "west", "north", "south", None]},
                            },
                        }, {"type": "null"}]},
                        "site_fit": {"enum": ["inherit", "impose", None]},
                        "dimensional_intent": {"anyOf": [intent_schema(), {"type": "null"}]},
                        "name": {"type": "string", "minLength": 1, "maxLength": 120},
                        "base_form_id": {
                            "enum": [spec.form_id for spec in BASE_FORM_SPECS],
                        },
                        "base_seed": {
                            "enum": list(allowed_base_seeds or [spec.seed_id for spec in BASE_SEED_SPECS]),
                        },
                        "intent_tags": {
                            "type": "array",
                            "maxItems": 12,
                            "items": {"type": "string", "maxLength": 80},
                        },
                        "nodes": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 24,
                            "items": node_schema,
                        },
                        "root_id": {"type": "string", "minLength": 1, "maxLength": 80},
                        "rationale": {"type": "string", "maxLength": 600},
                    },
                },
            }
        },
    }
    if book_principle_vocabulary:
        schema["properties"]["book_principle_ids"] = {
            "type": "array",
            "items": {
                "type": "string",
                "enum": list(book_principle_vocabulary),
            },
            "minItems": 1,
        }
        schema["required"].append("book_principle_ids")
    if book_composition_path_ids:
        program_schema = schema["properties"]["programs"]["items"]
        program_schema["properties"]["book_composition_path_id"] = {
            "type": "string",
            "enum": list(book_composition_path_ids),
        }
        program_schema["required"].append("book_composition_path_id")
    return schema


def _response_output_text(data: dict[str, Any]) -> str:
    if isinstance(data.get("output_text"), str):
        return data["output_text"]
    for output in data.get("output") or []:
        if not isinstance(output, dict):
            continue
        for content in output.get("content") or []:
            if isinstance(content, dict) and isinstance(content.get("text"), str):
                return content["text"]
    raise GeometryAuthorError("geometry author response contained no output text")


def _infer_base_form(program: GeometryProgram) -> str:
    """Infer the form immediately upstream of the one global Matrix4."""

    matrices = [
        node for node in program.topological_nodes()
        if node.kind == "transform" and node.operator == "matrix4"
    ]
    if len(matrices) != 1 or len(matrices[0].inputs) != 1:
        return "unknown"
    carrier = program.node_map.get(matrices[0].inputs[0])
    if carrier is None:
        return "unknown"
    # A non-block normalized base seed is an independent proportion axis.
    # For the unmodified cube form its executable ``scale`` necessarily sits
    # between UnitBox and the one global Matrix4.  Do not misclassify that
    # seed controller as an unknown base-form operator.
    if carrier.operator == "scale" and len(carrier.inputs) == 1:
        parent = program.node_map.get(carrier.inputs[0])
        try:
            vector = tuple(
                float(value)
                for value in (
                    carrier.parameters.get("scale")
                    or carrier.parameters.get("vector")
                    or ()
                )
            )
        except (TypeError, ValueError):
            vector = ()
        normalized_seed_scale = bool(
            parent is not None
            and parent.operator == "box"
            and len(vector) == 3
            and min(vector) > 0.0
            and any(
                spec.primitive_operator == "box"
                and max(
                    abs(vector[index] - spec.normalized_scale[index])
                    for index in range(3)
                ) <= 0.08
                for spec in BASE_SEED_SPECS
            )
        )
        if normalized_seed_scale:
            carrier = parent
    return {
        "ellipsoidize": "elliptical",
        "tetrahedralize": "tetrahedral",
        "box": "cube",
    }.get(carrier.operator, "unknown")


def _infer_base_seed(program: GeometryProgram) -> str:
    ordered = program.topological_nodes()
    node_map = program.node_map
    for node in ordered:
        if node.operator != "scale" or len(node.inputs) != 1:
            continue
        parent = node_map.get(node.inputs[0])
        if parent is None or parent.operator != "box":
            continue
        try:
            vector = tuple(float(value) for value in (
                node.parameters.get("scale")
                or node.parameters.get("vector")
                or ()
            ))
        except (TypeError, ValueError):
            vector = ()
        if len(vector) != 3 or min(vector) <= 0:
            continue
        for spec in BASE_SEED_SPECS:
            if spec.primitive_operator != "box":
                continue
            if max(abs(vector[index] - spec.normalized_scale[index]) for index in range(3)) <= 0.08:
                return spec.seed_id
    primitive = next((node for node in ordered if node.kind == "primitive"), None)
    if primitive is None:
        return "block"
    if primitive.operator == "extruded_polygon":
        return "profiled_prism"
    if primitive.operator != "box":
        return "block"
    try:
        width = float(primitive.parameters.get("width") or 1.0)
        depth = float(primitive.parameters.get("depth") or 1.0)
        height = float(primitive.parameters.get("height") or 1.0)
    except (TypeError, ValueError):
        return "block"
    plan_aspect = max(width, depth) / max(min(width, depth), 1e-9)
    if height > max(width, depth) * 1.35:
        return "tower"
    if plan_aspect >= 2.2:
        return "bar"
    if height < min(width, depth) * 0.48:
        return "slab"
    return "block"


_PROGRAM_RELATION_OPERATORS = frozenset({
    "courtyard", "carve_void", "notch", "lift", "cantilever", "split_wing",
})


def _is_program_relation_node(node: GeometryNode) -> bool:
    if node.operator == "profiled_hall":
        return True
    role = str(node.semantic_role or "").strip().lower()
    return bool(
        node.operator in _PROGRAM_RELATION_OPERATORS
        and any(
            token in role
            for token in (
                "threshold", "entry", "public", "court", "atrium", "ground",
                "void", "terrace", "access",
            )
        )
    )


def _nonterminal_program_relation(program: GeometryProgram) -> str:
    """Return relation node IDs that body operations can still erase."""

    relation_ids = {
        node.id for node in program.topological_nodes()
        if _is_program_relation_node(node)
    }
    if not relation_ids:
        return ""
    terminal_ids: set[str] = set()
    cursor = program.node_map.get(program.root_id)
    while cursor is not None and _is_program_relation_node(cursor) and len(cursor.inputs) == 1:
        terminal_ids.add(cursor.id)
        cursor = program.node_map.get(cursor.inputs[0])
    return ",".join(sorted(relation_ids - terminal_ids))


def _canonicalize_program_relation_suffix(program: GeometryProgram) -> GeometryProgram:
    """Lower one linear architectural modifier stack to the semantic order.

    The high-level author may list a court before a setback even though the
    executable Core AST must shape the body first. Only a graph whose complete
    root ancestry is one unary chain can be reordered without inventing branch
    semantics. Branched/composition graphs remain explicit and are rejected by
    the terminal-relation validator when their public relation is misplaced.
    """

    if not _nonterminal_program_relation(program):
        return program
    node_map = program.node_map
    chain: list[GeometryNode] = []
    cursor = node_map.get(program.root_id)
    while cursor is not None:
        chain.append(cursor)
        if not cursor.inputs:
            break
        if len(cursor.inputs) != 1:
            return program
        cursor = node_map.get(cursor.inputs[0])
    chain.reverse()
    if len(chain) != len(program.nodes) or not chain or chain[0].kind != "primitive":
        return program
    primitive = chain[0]
    operators = chain[1:]
    body = [
        node for node in operators
        if not _is_program_relation_node(node) and node.operator != "profiled_hall"
    ]
    relations = [
        node for node in operators
        if _is_program_relation_node(node) and node.operator != "profiled_hall"
    ]
    sections = [node for node in operators if node.operator == "profiled_hall"]
    ordered = [primitive, *body, *relations, *sections]
    previous_id = ""
    rebuilt: list[GeometryNode] = []
    for node in ordered:
        rebuilt.append(replace(node, inputs=(() if not previous_id else (previous_id,))))
        previous_id = node.id
    old_order = [node.id for node in chain]
    new_order = [node.id for node in ordered]
    if old_order == new_order:
        return program
    return replace(
        program,
        nodes=tuple(rebuilt),
        root_id=previous_id,
        metadata={
            **program.metadata,
            "architectural_relation_suffix_canonicalized": True,
            "precanonical_node_order": old_order,
            "canonical_node_order": new_order,
            "canonicalization_contract": "body_then_access_relation_suffix_then_section",
        },
    )


def _misaligned_access_relation(
    program: GeometryProgram,
    program_context: dict[str, Any],
) -> str:
    target = str(program_context.get("site_access_side_in_program_frame") or "closed").lower()
    language_contract = program_context.get("geometry_language_contract")
    requires_access = bool(
        isinstance(language_contract, dict)
        and language_contract.get("requires_access_bound_relation")
    )
    access_nodes = [
        node for node in program.topological_nodes()
        if _is_program_relation_node(node)
        and node.operator in {"courtyard", "carve_void", "notch", "lift", "split_wing"}
    ]
    if requires_access and not access_nodes:
        return "program:missing_access_bound_relation"
    if target not in {"east", "west", "north", "south"}:
        return ""
    for node in access_nodes:
        role = str(node.semantic_role or "").lower()
        if node.operator in {"courtyard", "carve_void"}:
            if "internal" in role and "public" not in role and "threshold" not in role:
                continue
            actual = str(node.parameters.get("open_side") or "closed").lower()
            if actual != target:
                return f"{node.id}:open_side={actual}:required={target}"
        if node.operator == "notch" and any(
            token in role for token in ("threshold", "entry", "public", "ground")
        ):
            actual = str(node.parameters.get("side") or "missing").lower()
            if actual != target:
                return f"{node.id}:side={actual}:required={target}"
        if node.operator in {"lift", "split_wing"}:
            actual = str(node.parameters.get("access_side") or "missing").lower()
            if actual != target:
                return f"{node.id}:access_side={actual}:required={target}"
    return ""


def _program_language_contract_issue(
    program: GeometryProgram,
    program_context: dict[str, Any],
) -> str:
    language_contract = program_context.get("geometry_language_contract")
    has_forbidden_family_feedback = bool(
        program_context.get("author_forbidden_body_rule_families")
    )
    has_forbidden_operator_feedback = bool(
        program_context.get("author_forbidden_operators")
    )
    if (
        not isinstance(language_contract, dict)
        and not has_forbidden_family_feedback
        and not has_forbidden_operator_feedback
    ):
        return ""
    if not isinstance(language_contract, dict):
        language_contract = {}
    forbidden_operators = {
        str(value).strip().lower()
        for value in program_context.get("author_forbidden_operators") or ()
        if str(value).strip()
    }
    blocked_operator = next((
        node.operator
        for node in program.topological_nodes()
        if node.operator in forbidden_operators
    ), "")
    if blocked_operator:
        return f"author_operator_forbidden:{blocked_operator}"
    known_macros = set(OPERATORS_BY_KIND["macro"])
    actual = [node for node in program.topological_nodes() if node.kind == "macro"]
    repeated_plan_relation = next((
        node for node in program.topological_nodes()
        if node.operator in {"cross_mass", "grid_mass", "radial_array", "split_wing"}
    ), None)
    open_court_relation = next((
        node for node in program.topological_nodes()
        if node.operator in {"courtyard", "carve_void"}
        and str(node.parameters.get("open_side") or "closed") != "closed"
    ), None)
    if repeated_plan_relation is not None and open_court_relation is not None:
        return (
            f"{open_court_relation.id}:open_court_after_{repeated_plan_relation.operator}"
            ":fragments_repeated_plan_use_lift_or_side_notch"
        )
    allowed = {
        str(value).strip().lower()
        for value in language_contract.get("allowed_macro_operators") or ()
        if str(value).strip().lower() in known_macros
    }
    if allowed:
        disallowed = next((node for node in actual if node.operator not in allowed), None)
        if disallowed is not None:
            return f"{disallowed.id}:macro={disallowed.operator}:not_allowed_for_program"
    actual_operators = {node.operator for node in actual}
    required_all = {
        str(value).strip().lower()
        for value in language_contract.get("required_macro_operators_all") or ()
        if str(value).strip()
    }
    missing_all = sorted(required_all - actual_operators)
    if missing_all:
        return f"program:missing_required_macros={','.join(missing_all)}"
    required_any = {
        str(value).strip().lower()
        for value in language_contract.get("required_macro_operators_any") or ()
        if str(value).strip()
    }
    if required_any and not (required_any & actual_operators):
        return f"program:missing_any_required_macro={','.join(sorted(required_any))}"
    base_controller_id = _base_seed_controller_id(program, _infer_base_seed(program))
    assembly_roots, assembly_implementation = _assembly_budget_nodes(program)
    body_families: list[str] = []
    public_threshold_count = 0
    for node in program.topological_nodes():
        if node.id == base_controller_id or node.operator == "profiled_hall":
            continue
        if node.id in assembly_implementation:
            continue
        family = ("composition" if node.id in assembly_roots
                  else _AUTHOR_BODY_RULE_FAMILIES.get(node.operator))
        if family is None:
            continue
        public_threshold = bool(
            node.operator in {"courtyard", "carve_void"}
            and str(node.parameters.get("open_side") or "closed") != "closed"
        ) or bool(node.operator == "notch" and node.parameters.get("side")) \
            or bool(
                node.operator in {"lift", "split_wing"}
                and str(node.parameters.get("access_side") or "closed") != "closed"
            )
        if public_threshold:
            public_threshold_count += 1
        else:
            body_families.append(family)
    maximum_body_rules = max(0, int(program_context.get("author_maximum_body_rule_count") or 0))
    maximum_threshold_rules = max(0, int(program_context.get("author_maximum_public_threshold_rule_count") or 0))
    if maximum_body_rules and len(body_families) > maximum_body_rules:
        return f"program:body_rule_budget={len(body_families)}:maximum={maximum_body_rules}"
    duplicated_body_families = sorted({
        family for family in body_families if body_families.count(family) > 1
    })
    if duplicated_body_families:
        return f"program:body_rule_family_repeated={','.join(duplicated_body_families)}"
    forbidden_body_families = {
        str(value).strip().lower()
        for value in program_context.get("author_forbidden_body_rule_families") or ()
        if str(value).strip()
    }
    blocked_body_families = sorted(
        forbidden_body_families.intersection(body_families)
    )
    if blocked_body_families:
        return (
            "author_body_rule_family_forbidden:"
            + ",".join(blocked_body_families)
        )
    if maximum_threshold_rules and public_threshold_count > maximum_threshold_rules:
        return (
            f"program:public_threshold_rule_budget={public_threshold_count}:"
            f"maximum={maximum_threshold_rules}"
        )
    return ""


_AUTHOR_BODY_RULE_FAMILIES = {
    "bend": "deformation", "bent_bar": "deformation", "twist": "deformation",
    "inflate": "deformation", "pinch": "deformation", "taper": "deformation",
    "shear": "deformation", "setback": "step", "stepped_mass": "step",
    "terrace": "step", "courtyard": "void", "carve_void": "void",
    "notch": "void", "puncture": "void", "cut_corner": "void",
    "slice": "cut", "clip": "cut", "radial_array": "array",
    "linear_array": "array", "mirror_array": "array", "cross_mass": "array", "grid_mass": "array",
    "split_wing": "array", "cantilever": "support", "lift": "support",
    "scale": "transform", "translate": "transform", "rotate": "transform",
    "union": "composition", "intersection": "composition", "difference": "composition",
}


def _author_validation_context(context: dict[str, Any]) -> dict[str, Any]:
    """Align the LLM author with the unchanged downstream body-rule gate."""
    program_context = (
        dict(context.get("program_context"))
        if isinstance(context.get("program_context"), dict)
        else {}
    )
    maximum_body_rules = _author_body_rule_budget(context)
    program_context.update({
        "author_maximum_body_rule_count": maximum_body_rules,
        "author_maximum_public_threshold_rule_count": 1,
        "author_forbidden_body_rule_families": sorted({
            str(value).strip().lower()
            for value in context.get("author_forbidden_body_rule_families") or ()
            if str(value).strip()
        }),
        "author_forbidden_operators": sorted({
            str(value).strip().lower()
            for value in context.get("author_forbidden_operators") or ()
            if str(value).strip()
        }),
    })
    return program_context


def geometry_author_validation_context(
    context: dict[str, Any],
) -> dict[str, Any]:
    """Return the exact contextual gate input shared by every LLM author."""

    return _author_validation_context(context)


def _author_body_rule_budget(context: dict[str, Any]) -> int:
    """Return the source share of the cross-layer visual-rule budget."""
    try:
        maximum_depth = max(1, min(3, int(context.get("maximum_operator_depth") or 2)))
        downstream_reserve = max(
            0,
            min(2, int(context.get("downstream_body_rule_reserve") or 0)),
        )
    except (TypeError, ValueError):
        maximum_depth, downstream_reserve = 2, 0
    return max(1, maximum_depth - downstream_reserve)


def _base_seed_controller_id(program: GeometryProgram, seed_id: str) -> str:
    """Return the typed node that establishes the normalized start proportion."""
    ordered = program.topological_nodes()
    node_map = program.node_map
    matching_spec = next((spec for spec in BASE_SEED_SPECS if spec.seed_id == seed_id), None)
    if matching_spec is not None and matching_spec.primitive_operator == "box":
        for node in ordered:
            if node.operator != "scale" or len(node.inputs) != 1:
                continue
            parent = node_map.get(node.inputs[0])
            if parent is None or parent.operator != "box":
                continue
            try:
                vector = tuple(float(value) for value in (
                    node.parameters.get("scale")
                    or node.parameters.get("vector")
                    or ()
                ))
            except (TypeError, ValueError):
                continue
            if len(vector) == 3 and max(
                abs(vector[index] - matching_spec.normalized_scale[index])
                for index in range(3)
            ) <= 0.08:
                return node.id
    if seed_id == "profiled_prism":
        profiled = next(
            (node for node in ordered if node.operator in {"extruded_polygon", "wedge", "sweep", "loft", "profiled_hall"}),
            None,
        )
        if profiled is not None:
            return profiled.id
    primitive = next((node for node in ordered if node.kind == "primitive"), None)
    return primitive.id if primitive is not None else ""


def _author_cache_path(
    *,
    context: dict[str, Any],
    count: int,
    model: str,
    prompt_contract: str = GEOMETRY_AUTHOR_PROMPT_CONTRACT,
) -> Path:
    payload = json.dumps({
        "schema": prompt_contract,
        "model": model,
        "count": count,
        "context": context,
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    key = hashlib.sha256(payload).hexdigest()
    root = Path(os.getenv(
        "MAAS_GEOMETRY_AUTHOR_CACHE_DIR",
        "docs/ai-session-memory/reference-corpus/geometry-author-cache",
    ))
    return root / f"{key}.json"


def _load_author_cache(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if (
        isinstance(payload, dict)
        and payload.get("cache_schema_version") in {
            "arr.maas.geometry_llm_author_cache.v1",
            "arr.maas.geometry_llm_author_cache.v2",
            "arr.maas.geometry_llm_author_cache.v3",
        }
        and payload.get("validation_status", "accepted") == "accepted"
        and (
            isinstance(payload.get("payload"), dict)
            or isinstance(payload.get("compiled_programs"), list)
        )
    ):
        return payload
    return None


def _load_revalidatable_kernel_rejection(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    feedback = payload.get("compiler_repair_feedback")
    if not (
        isinstance(payload, dict)
        and payload.get("cache_schema_version")
        == "arr.maas.geometry_llm_author_cache.v3"
        and payload.get("validation_status") == "rejected"
        and isinstance(payload.get("payload"), dict)
        and isinstance(feedback, list)
        and any(
            isinstance(item, dict)
            and item.get("compile_status") == "kernel_unavailable"
            for item in feedback
        )
    ):
        return None
    return payload


def _save_author_cache(path: Path, payload: dict[str, Any]) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        temporary.replace(path)
    except OSError:
        pass


__all__ = [
    "GeometryAuthorError",
    "author_geometry_programs_with_openai",
    "geometry_programs_from_author_payload",
]
