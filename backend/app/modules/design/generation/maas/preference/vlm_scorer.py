"""OpenAI VLM scorer for MAAS second-stage preference distillation."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import hashlib
from contextlib import contextmanager
from contextvars import ContextVar
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Mapping

from backend.app.modules.design.generation.maas.grammar.vocab import SUPPORTED_VERBS
from backend.app.modules.design.generation.maas.paid_provider_budget import PaidProviderBudgetError, reserve_paid_provider_request

from backend.app.modules.design.generation.maas.preference.reference_paths import reference_image_preview_url, resolve_reference_image_path, workspace_root


VLM_SCORE_SCHEMA_VERSION = "arr.maas.vlm_concept_scores.v1"
VLM_PROMPT_CONTRACT_VERSION = (
    "arr.maas.vlm_prompt.site_visible_program_concept_graph_edit_geometry_edit."
    "v21_capacity_floor_context"
)
DEFAULT_VLM_MODEL = "gpt-5.4-mini"
REFERENCE_IMAGE_AUDIT_SCHEMA_VERSION = "arr.maas.reference_image_massing_audit.v2"
REFERENCE_IMAGE_AUDIT_PROMPT_VERSION = "arr.maas.reference_image_massing_prompt.v2"
PORTFOLIO_VLM_SCHEMA_VERSION = "arr.maas.portfolio_visual_audit.v2"
PORTFOLIO_VLM_PROMPT_VERSION = "arr.maas.portfolio_visual_prompt.v2_typed_family_feedback"
_REFERENCE_IMAGE_AUDIT_LOCK = threading.Lock()
_LIVE_VLM_REQUEST_LOCK = threading.Lock()
_LIVE_VLM_REQUEST_COUNT = 0

_ARCHITECTURAL_GEOMETRY_MACROS = frozenset({
    "courtyard", "carve_void", "notch", "setback", "terrace", "cantilever",
    "bridge", "cross_mass", "bent_bar", "split_wing", "attach_volume",
    "tapered_tower", "leaning_tower", "cut_corner", "stepped_mass",
    "profiled_hall", "lift", "puncture",
})

_PORTFOLIO_GEOMETRY_FAMILIES = (
    "bent_linear_mass", "radial_fan", "l_mass", "u_mass", "courtyard",
    "attached_volume", "overlapping_mass", "setback", "cross_mass",
    "tapered_tower", "leaning_tower", "notch", "diagonal_slice",
    "cut_corner", "lofted_envelope", "swept_bar", "split_bridge",
    "twisted_mass", "carve_void", "terrace", "cantilever", "lift",
    "puncture", "stepped_mass", "profiled_hall",
)


class VlmScoringError(RuntimeError):
    pass


class VlmBudgetExhaustedError(VlmScoringError):
    """Stable typed failure raised before an over-budget provider request."""

    code = "provider_quota_exhausted"

    def __init__(
        self,
        message: str,
        *,
        request_kind: str,
        quota: str,
        budget_code: str = "provider_quota_exhausted",
        used: int | None = None,
        limit: int | None = None,
        remaining: int | None = None,
    ):
        self.request_kind = request_kind
        self.quota = quota
        self.budget_code = budget_code
        self.used = used
        self.limit = limit
        self.remaining = remaining
        super().__init__(
            f"vlm_budget_exhausted:code={self.code}:kind={request_kind}:"
            f"quota={quota}:{str(message)[:500]}"
        )

    @classmethod
    def from_provider_error(cls, error: PaidProviderBudgetError):
        return cls(
            str(error),
            request_kind=error.request_kind,
            quota=error.quota,
            budget_code=error.code,
            used=error.used,
            limit=error.limit,
            remaining=error.remaining,
        )


_VLM_REQUEST_KIND = ContextVar("maas_vlm_request_kind", default=None)


@contextmanager
def vlm_request_kind_scope(kind: str):
    token = _VLM_REQUEST_KIND.set(str(kind or "").strip() or None)
    try:
        yield
    finally:
        _VLM_REQUEST_KIND.reset(token)


@contextmanager
def live_vlm_request_count_scope():
    """Give one command an isolated transport count and restore its caller."""

    global _LIVE_VLM_REQUEST_COUNT
    with _LIVE_VLM_REQUEST_LOCK:
        previous = _LIVE_VLM_REQUEST_COUNT
        _LIVE_VLM_REQUEST_COUNT = 0
    try:
        yield
    finally:
        with _LIVE_VLM_REQUEST_LOCK:
            _LIVE_VLM_REQUEST_COUNT = previous


def _consume_live_vlm_request_budget(*, kind: str = "vlm") -> int:
    """Reserve one real HTTP request under a process-wide cost ceiling."""

    global _LIVE_VLM_REQUEST_COUNT
    try:
        limit = max(1, min(256, int(os.getenv("MAAS_LIVE_VLM_MAX_REQUESTS", "24"))))
    except (TypeError, ValueError):
        limit = 24
    with _LIVE_VLM_REQUEST_LOCK:
        if _LIVE_VLM_REQUEST_COUNT >= limit:
            raise VlmBudgetExhaustedError(
                f"live_vlm_request_budget_exhausted:{_LIVE_VLM_REQUEST_COUNT}/{limit}",
                request_kind=kind,
                quota="live_vlm_global",
            )
        try:
            reserve_paid_provider_request(kind)
        except PaidProviderBudgetError as exc:
            raise VlmBudgetExhaustedError.from_provider_error(exc) from exc
        _LIVE_VLM_REQUEST_COUNT += 1
        return _LIVE_VLM_REQUEST_COUNT


def score_portfolio_board_with_openai_vlm(
    *,
    image_path: str | Path,
    program_context: dict[str, Any],
    candidate_summaries: list[dict[str, Any]],
    reference_matches: list[dict[str, Any]] | None = None,
    model: str | None = None,
    timeout: float = 150.0,
    image_detail: str = "high",
    expected_candidate_count: int = 20,
) -> dict[str, Any]:
    """Judge sibling repetition on the final board, never law or parking.

    Per-candidate critics cannot see that twenty individually plausible masses
    all share one footprint/roof family.  This final board critic sees the
    actual selected siblings together and returns causal replacement guidance.
    """

    path = Path(image_path).resolve()
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VlmScoringError("OPENAI_API_KEY is not set")
    selected_model = model or os.getenv("MAAS_PREFERENCE_VLM_MODEL") or DEFAULT_VLM_MODEL
    image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    resolved_expected_count = max(1, min(20, int(expected_candidate_count)))
    selected_image_detail = str(image_detail or "high").lower()
    if selected_image_detail not in {"low", "high", "auto"}:
        raise ValueError("image_detail must be low, high, or auto")
    compact_candidates = [
        {
            key: item.get(key)
            for key in (
                "candidate_id", "book_scope", "base_seed", "body_phenotype",
                "roof_archetype", "ground_strategy", "design_concept_key",
                "geometry_family", "form_bank_lane", "chassis_family",
                "program_hash", "geometry_hash",
            )
        }
        for item in candidate_summaries
        if isinstance(item, dict)
    ]
    reference_content, reference_input_records = _reference_image_inputs(
        reference_matches or [],
    )
    compact_reference_identities = [
        {
            key: item.get(key)
            for key in (
                "source_id", "source", "local_path", "sha256",
                "selection_role", "input_order",
            )
        }
        for item in reference_input_records
    ]
    configured_cache = os.getenv("MAAS_PORTFOLIO_VLM_CACHE_DIR", "").strip()
    cache_root = (
        Path(configured_cache).resolve()
        if configured_cache
        else workspace_root()
        / "docs"
        / "ai-session-memory"
        / "reference-corpus"
        / "portfolio-vlm-cache"
    )
    cache_key = hashlib.sha256(json.dumps({
        "schema": PORTFOLIO_VLM_SCHEMA_VERSION,
        "prompt": PORTFOLIO_VLM_PROMPT_VERSION,
        "model": selected_model,
        "image_hash": image_hash,
        "program_context": program_context,
        "candidates": compact_candidates,
        "references": compact_reference_identities,
        "expected_candidate_count": resolved_expected_count,
    }, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    cache_path = cache_root / f"{cache_key}.json"
    try:
        cached = json.loads(cache_path.read_text(encoding="utf-8"))
        if cached.get("schema_version") == PORTFOLIO_VLM_SCHEMA_VERSION:
            return {**cached, "cache_hit": True}
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass

    failure_values = [
        "too_few_candidates", "family_resemblance", "repeated_footprint",
        "repeated_roof", "program_language_weak", "fragmented_lego",
        "box_dominated", "pyramid_dominated", "card_unreadable",
    ]
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "portfolio_hard_pass", "visible_family_count", "dominant_family_share",
            "failure_reasons", "repeated_family_groups", "candidate_actions",
            "required_next_relations", "required_geometry_families", "rationale",
        ],
        "properties": {
            "portfolio_hard_pass": {"type": "boolean"},
            "visible_family_count": {"type": "integer", "minimum": 0, "maximum": 20},
            "dominant_family_share": {"type": "number", "minimum": 0.0, "maximum": 1.0},
            "failure_reasons": {
                "type": "array", "items": {"type": "string", "enum": failure_values},
            },
            "repeated_family_groups": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["candidate_ids", "shared_language", "severity"],
                    "properties": {
                        "candidate_ids": {"type": "array", "items": {"type": "string"}},
                        "shared_language": {"type": "string"},
                        "severity": {"type": "string", "enum": ["low", "medium", "high"]},
                    },
                },
            },
            "candidate_actions": {
                "type": "array",
                "items": {
                    "type": "object", "additionalProperties": False,
                    "required": ["candidate_id", "decision", "reasons"],
                    "properties": {
                        "candidate_id": {"type": "string"},
                        "decision": {"type": "string", "enum": ["keep", "replace"]},
                        "reasons": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
            "required_next_relations": {"type": "array", "items": {"type": "string"}},
            "required_geometry_families": {
                "type": "array",
                "maxItems": 10,
                "items": {"type": "string", "enum": list(_PORTFOLIO_GEOMETRY_FAMILIES)},
            },
            "rationale": {"type": "string"},
        },
    }
    card_count_phrase = (
        "three separate candidate cards"
        if len(compact_candidates) == 3
        else f"{len(compact_candidates)} separate candidate cards"
    )
    prompt = (
        "Inspect the final architecture massing contact sheet as one portfolio, not as isolated cards. "
        f"The first image is one contact sheet containing {card_count_phrase}. "
        "Return one candidate action for every visible candidate ID. "
        "The card IDs correspond to candidate_summaries. Judge visible three-dimensional spatial language only; "
        "do not judge zoning, FAR, parking, facade materials, or render polish. A portfolio fails when the same "
        "footprint, roof, box/bar chassis, pyramidal tier, or Lego-fragment family repeats despite different labels. "
        f"For this {resolved_expected_count}-candidate audit require every card to have a materially legible "
        "form/spatial identity, no repeated dominant family, and a clearly program-specific "
        "mass/section/threshold language. Mark replacement candidates "
        "and describe transferable relations for the next typed graph author; never request a copied famous form. "
        "Also choose required_geometry_families only from the typed catalog in the response schema. Select families "
        "that are materially missing from this board; these are next-run review anchors, never automatic approvals. "
        f"Program context: {json.dumps(program_context, ensure_ascii=False, sort_keys=True)}\n"
        f"Candidate summaries: {json.dumps(compact_candidates, ensure_ascii=False, sort_keys=True)}"
    )
    body = {
        "model": selected_model,
        "input": [{
            "role": "system",
            "content": [{
                "type": "input_text",
                "text": "You are a competition-level architectural portfolio massing critic.",
            }],
        }, {
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {
                    "type": "input_image",
                    "image_url": _image_data_url(path),
                    "detail": selected_image_detail,
                },
                *reference_content,
            ],
        }],
        "text": {"format": {
            "type": "json_schema", "name": "maas_portfolio_visual_audit",
            "strict": True, "schema": schema,
        }},
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        _consume_live_vlm_request_budget(kind="portfolio_vlm")
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise VlmScoringError(f"OpenAI portfolio VLM response failed: {exc}") from exc
    output_text = _extract_text(response_data)
    if not output_text:
        raise VlmScoringError("OpenAI portfolio VLM response did not include output text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise VlmScoringError("OpenAI portfolio VLM response was not valid JSON") from exc
    visible_family_count = max(0, min(20, int(parsed.get("visible_family_count") or 0)))
    dominant_family_share = max(0.0, min(1.0, float(parsed.get("dominant_family_share") or 0.0)))
    enough_candidates = len(compact_candidates) == resolved_expected_count
    minimum_visible_families = min(10, resolved_expected_count)
    maximum_dominant_share = max(
        0.30,
        round((1.0 / resolved_expected_count) + 0.01, 3),
    )
    hard_pass = bool(
        parsed.get("portfolio_hard_pass")
        and enough_candidates
        and visible_family_count >= minimum_visible_families
        and dominant_family_share <= maximum_dominant_share
    )
    failures = [str(item) for item in parsed.get("failure_reasons") or () if item in failure_values]
    if not enough_candidates and "too_few_candidates" not in failures:
        failures.append("too_few_candidates")
    submitted_references = _bind_submitted_reference_identity(
        reference_input_records,
        response_id=str(response_data.get("id") or ""),
        program_hash="",
        geometry_hash="",
    )
    result = {
        "schema_version": PORTFOLIO_VLM_SCHEMA_VERSION,
        "prompt_contract_version": PORTFOLIO_VLM_PROMPT_VERSION,
        "status": "pass" if hard_pass else "fail",
        "hard_pass": hard_pass,
        "candidate_count": len(compact_candidates),
        "expected_candidate_count": resolved_expected_count,
        "visible_family_count": visible_family_count,
        "dominant_family_share": round(dominant_family_share, 3),
        "failure_reasons": failures,
        "repeated_family_groups": list(parsed.get("repeated_family_groups") or ()),
        "candidate_actions": list(parsed.get("candidate_actions") or ()),
        "required_next_relations": [str(item) for item in parsed.get("required_next_relations") or ()],
        "required_geometry_families": list(dict.fromkeys(
            str(item) for item in parsed.get("required_geometry_families") or ()
            if str(item) in _PORTFOLIO_GEOMETRY_FAMILIES
        )),
        "rationale": str(parsed.get("rationale") or ""),
        "model": selected_model,
        "response_id": str(response_data.get("id") or ""),
        "image_hash": image_hash,
        "cache_hit": False,
        "legal_or_parking_score": False,
        "api_usage": dict(response_data.get("usage") or {}),
        "vlm_image_inputs": {
            "schema_version": "arr.maas.portfolio_vlm_image_inputs.v1",
            "board": {
                "input_id": "portfolio:board",
                "role": "candidate_portfolio_board",
                "local_path": str(path),
                "sha256": image_hash,
                "input_order": 0,
                "used_by_vlm": True,
                "response_id": str(response_data.get("id") or ""),
                "image_detail": selected_image_detail,
            },
            "references": submitted_references,
            "reference_count": len(submitted_references),
            "candidate_program_hashes": [
                str(item.get("program_hash") or "")
                for item in compact_candidates
            ],
            "candidate_geometry_hashes": [
                str(item.get("geometry_hash") or "")
                for item in compact_candidates
            ],
        },
    }
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    return result


def audit_reference_image_for_massing(
    image_path: str | Path,
    *,
    model: str | None = None,
    timeout: float = 120.0,
    max_retries: int | None = None,
) -> dict[str, Any]:
    """Hard-audit whether one precedent image can teach exterior massing.

    Program relevance and image usefulness are independent.  A sports project
    can still expose an interior stair or facade detail as its featured image;
    sending that frame to the mass critic creates false precedent evidence.
    The immutable image hash is cached, and credentials never enter the cache.
    """

    path = Path(image_path).resolve()
    if not path.exists() or not path.is_file():
        raise VlmScoringError(f"reference image does not exist: {path}")
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VlmScoringError("OPENAI_API_KEY is not set")
    selected_model = model or os.getenv("MAAS_PREFERENCE_VLM_MODEL") or DEFAULT_VLM_MODEL
    image_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    configured_cache = os.getenv("MAAS_REFERENCE_IMAGE_VLM_CACHE_DIR", "").strip()
    cache_root = (
        Path(configured_cache).resolve()
        if configured_cache
        else workspace_root()
        / "docs"
        / "ai-session-memory"
        / "reference-corpus"
        / "reference-image-vlm-cache"
    )
    cache_key = hashlib.sha256(json.dumps({
        "schema": REFERENCE_IMAGE_AUDIT_SCHEMA_VERSION,
        "prompt": REFERENCE_IMAGE_AUDIT_PROMPT_VERSION,
        "model": selected_model,
        "image_hash": image_hash,
    }, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    cache_path = cache_root / f"{cache_key}.json"
    with _REFERENCE_IMAGE_AUDIT_LOCK:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("schema_version") == REFERENCE_IMAGE_AUDIT_SCHEMA_VERSION
                and cached.get("image_hash") == image_hash
            ):
                return {**cached, "cache_hit": True}
        except (OSError, ValueError, TypeError, json.JSONDecodeError):
            pass

        schema = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "view_type", "whole_building_visible", "massing_legibility",
                "operation_clarity", "usable_for_massing_reference",
                "building_scale_typology", "primary_building_typology", "typology_confidence",
                "failure_reasons", "visible_form_traits", "rationale",
            ],
            "properties": {
                "view_type": {"type": "string", "enum": [
                    "exterior_massing", "aerial_site", "physical_model_or_diagram",
                    "interior", "detail", "plan_or_section", "obscured",
                ]},
                "whole_building_visible": {"type": "boolean"},
                "massing_legibility": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "operation_clarity": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "usable_for_massing_reference": {"type": "boolean"},
                "building_scale_typology": {"type": "string", "enum": [
                    "pavilion_lowrise", "midrise", "highrise_tower",
                    "large_span_hall", "campus_complex", "unknown",
                ]},
                "primary_building_typology": {"type": "string", "enum": [
                    "retail_hospitality", "housing", "office", "mixed_use",
                    "sports", "cultural", "education", "infrastructure", "unknown",
                ]},
                "typology_confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "failure_reasons": {
                    "type": "array",
                    "items": {"type": "string", "enum": [
                        "interior_only", "detail_only", "building_obscured",
                        "too_close_to_read_whole", "no_whole_building",
                        "flat_orthographic_without_volume", "not_architecture",
                    ]},
                },
                "visible_form_traits": {"type": "array", "items": {"type": "string"}},
                "rationale": {"type": "string"},
            },
        }
        body = {
            "model": selected_model,
            "input": [
                {
                    "role": "system",
                    "content": [{
                        "type": "input_text",
                        "text": (
                            "You audit architectural precedent images before they are shown to a massing critic. "
                            "Reject interiors, details, obscured buildings, and frames that cannot reveal the whole "
                            "three-dimensional building mass. Do not reward facade beauty or photography."
                        ),
                    }],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "Classify this single image. usable_for_massing_reference may be true only when "
                                "a whole exterior mass, aerial/site mass, or clear physical model/diagram is visible. "
                             "operation_clarity measures whether a transform such as bend, court, split, bridge, "
                                "setback, taper, roof section, or attachment can be read from this image. Also classify "
                                "the visible building scale and primary typology from the image itself. Do not infer a "
                                "low-rise neighborhood precedent merely because its metadata might mention retail."
                            ),
                        },
                        {"type": "input_image", "image_url": _image_data_url(path), "detail": "low"},
                    ],
                },
            ],
            "text": {"format": {
                "type": "json_schema",
                "name": "maas_reference_image_massing_audit",
                "strict": True,
                "schema": schema,
            }},
        }
        request = urllib.request.Request(
            "https://api.openai.com/v1/responses",
            data=json.dumps(body).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        data: dict[str, Any] | None = None
        last_error: Exception | None = None
        retry_count = (
            max(0, int(max_retries))
            if max_retries is not None
            else max(0, int(os.getenv("MAAS_PREFERENCE_VLM_RETRIES", "1")))
        )
        for attempt in range(retry_count + 1):
            _consume_live_vlm_request_budget(
                kind="reference_audit_vlm" if attempt == 0 else "provider_retry"
            )
            try:
                with urllib.request.urlopen(request, timeout=timeout) as response:
                    data = json.loads(response.read().decode("utf-8"))
                break
            except Exception as exc:
                last_error = exc
                if attempt < retry_count:
                    time.sleep(1.25 * (attempt + 1))
        if data is None:
            raise VlmScoringError(
                f"OpenAI reference image audit failed after {retry_count + 1} attempts: {last_error}"
            ) from last_error
        output_text = _extract_text(data)
        try:
            parsed = json.loads(output_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise VlmScoringError("OpenAI reference image audit was not valid JSON") from exc
        view_type = str(parsed.get("view_type") or "obscured")
        massing_legibility = max(0.0, min(1.0, float(parsed.get("massing_legibility") or 0.0)))
        operation_clarity = max(0.0, min(1.0, float(parsed.get("operation_clarity") or 0.0)))
        typology_confidence = max(0.0, min(1.0, float(parsed.get("typology_confidence") or 0.0)))
        hard_pass = bool(
            parsed.get("usable_for_massing_reference")
            and parsed.get("whole_building_visible")
            and view_type in {"exterior_massing", "aerial_site", "physical_model_or_diagram"}
            and massing_legibility >= 0.55
            and operation_clarity >= 0.30
        )
        result = {
            "schema_version": REFERENCE_IMAGE_AUDIT_SCHEMA_VERSION,
            "prompt_contract_version": REFERENCE_IMAGE_AUDIT_PROMPT_VERSION,
            "provider": "openai",
            "model": selected_model,
            "response_id": str(data.get("id") or ""),
            "image_hash": image_hash,
            "view_type": view_type,
            "whole_building_visible": bool(parsed.get("whole_building_visible")),
            "massing_legibility": round(massing_legibility, 3),
            "operation_clarity": round(operation_clarity, 3),
            "building_scale_typology": str(parsed.get("building_scale_typology") or "unknown"),
            "primary_building_typology": str(parsed.get("primary_building_typology") or "unknown"),
            "typology_confidence": round(typology_confidence, 3),
            "hard_pass": hard_pass,
            "failure_reasons": [str(value) for value in parsed.get("failure_reasons") or ()],
            "visible_form_traits": [str(value) for value in parsed.get("visible_form_traits") or ()],
            "rationale": str(parsed.get("rationale") or "")[:600],
            "cache_hit": False,
            "api_usage": dict(data.get("usage") or {}),
        }
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = cache_path.with_suffix(f".{os.getpid()}.tmp")
            temporary.write_text(json.dumps(result, ensure_ascii=False, sort_keys=True), encoding="utf-8")
            temporary.replace(cache_path)
        except OSError:
            pass
        return result


def score_candidate_with_openai_vlm(
    *,
    feature: dict[str, Any],
    image_path: str | Path,
    reference_matches: list[dict[str, Any]] | None = None,
    model: str | None = None,
    timeout: float = 120.0,
    max_retries: int | None = None,
    image_detail: str = "high",
    program_hash: str = "",
    geometry_hash: str = "",
    request_kind: str | None = None,
) -> dict[str, Any]:
    """Score a candidate PNG with OpenAI's Responses API.

    The VLM is not asked to judge law or parking. It returns architecture
    concept scores only.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise VlmScoringError("OPENAI_API_KEY is not set")
    image_data_url = _image_data_url(Path(image_path))
    selected_model = model or os.getenv("MAAS_PREFERENCE_VLM_MODEL") or DEFAULT_VLM_MODEL
    program_hash, geometry_hash = _review_identity_hashes(
        feature,
        program_hash=program_hash,
        geometry_hash=geometry_hash,
    )
    selected_image_detail = str(image_detail or "high").lower()
    if selected_image_detail not in {"low", "high", "auto"}:
        raise ValueError("image_detail must be low, high, or auto")
    user_content: list[dict[str, Any]] = [
        {
            "type": "input_text",
            "text": _prompt_text(feature, reference_matches or []),
        },
        {
            "type": "input_image",
            "image_url": image_data_url,
            "detail": selected_image_detail,
        },
    ]
    reference_content, reference_input_records = _reference_image_inputs(reference_matches or [])
    user_content.extend(reference_content)
    body = {
        "model": selected_model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are an architectural massing critic. Score only visible massing quality. "
                            "Do not judge legal compliance, zoning, parking approval, facade beauty, or rendering polish."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": user_content,
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "maas_architecture_preference_scores",
                "strict": True,
                "schema": _response_schema(),
            }
        },
    }
    request = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    retry_count = (
        max(0, int(max_retries))
        if max_retries is not None
        else max(0, int(os.getenv("MAAS_PREFERENCE_VLM_RETRIES", "1")))
    )
    data: dict[str, Any] | None = None
    last_error: Exception | None = None
    initial_request_kind = (
        str(request_kind or "").strip()
        or _VLM_REQUEST_KIND.get()
        or "candidate_vlm"
    )
    for attempt in range(retry_count + 1):
        _consume_live_vlm_request_budget(
            kind=initial_request_kind if attempt == 0 else "provider_retry"
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                data = json.loads(response.read().decode("utf-8"))
            break
        except urllib.error.HTTPError as exc:
            last_error = exc
            if exc.code < 500 and exc.code != 429:
                try:
                    detail = exc.read().decode("utf-8")[:500]
                except Exception:
                    detail = str(exc)
                raise VlmScoringError(f"OpenAI VLM response failed: HTTP {exc.code}: {detail}") from exc
        except Exception as exc:
            last_error = exc
        if attempt < retry_count:
            time.sleep(1.25 * (attempt + 1))
    if data is None:
        raise VlmScoringError(f"OpenAI VLM response failed after {retry_count + 1} attempts: {last_error}") from last_error
    output_text = _extract_text(data)
    if not output_text:
        raise VlmScoringError("OpenAI VLM response did not include output text")
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as exc:
        raise VlmScoringError("OpenAI VLM response was not valid JSON") from exc
    normalized = _normalize_vlm_result(
        parsed,
        model=selected_model,
        response_id=str(data.get("id") or ""),
        feature=feature,
    )
    normalized["api_usage"] = dict(data.get("usage") or {})
    candidate_path = Path(image_path).resolve()
    submitted_references = _bind_submitted_reference_identity(
        reference_input_records,
        response_id=str(data.get("id") or ""),
        program_hash=program_hash,
        geometry_hash=geometry_hash,
    )
    _unused_content, retrieved_reference_records = _reference_image_inputs(
        reference_matches or [],
        limit=5,
    )
    submitted_ids = {
        str(item.get("input_id") or item.get("source_id") or "")
        for item in submitted_references
    }
    normalized["vlm_image_inputs"] = {
        "schema_version": "arr.maas.vlm_image_inputs.v1",
        "candidate": {
            "input_id": "candidate:render",
            "role": "candidate_mass",
            "local_path": str(candidate_path),
            "sha256": hashlib.sha256(candidate_path.read_bytes()).hexdigest(),
            "input_order": 0,
            "used_by_vlm": True,
            "response_id": str(data.get("id") or ""),
            "program_hash": str(program_hash),
            "geometry_hash": str(geometry_hash),
        },
        "references": submitted_references,
        "reference_count": len(submitted_references),
        "retrieved_references": [
            {
                **item,
                "used_by_vlm": str(
                    item.get("input_id") or item.get("source_id") or ""
                ) in submitted_ids,
            }
            for item in retrieved_reference_records
        ],
        "retrieved_reference_count": len(retrieved_reference_records),
        "candidate_image_detail": selected_image_detail,
    }
    return normalized


def _prompt_text(feature: dict[str, Any], reference_matches: list[dict[str, Any]]) -> str:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    geometry_only_critic_mode = bool(props.get("geometry_only_critic_mode"))
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    component_graph = source.get("component_graph") if isinstance(source.get("component_graph"), dict) else {}
    if not component_graph and isinstance(props.get("component_graph"), dict):
        component_graph = props["component_graph"]
    # The exact post-BOOK repair stage edits the recursive compiler AST only.
    # Showing the legacy program-role graph in that stage created two node-ID
    # namespaces and caused the VLM to target component IDs such as `hall` or
    # `primary_1_courtyard` in GeometryEdit records. Keep role semantics in the
    # design-concept graph, but remove the non-executable edit namespace.
    if geometry_only_critic_mode:
        component_graph = {}
    graph_nodes = component_graph.get("nodes") if isinstance(component_graph.get("nodes"), list) else []
    editable_nodes = [
        {
            "node_id": str(node.get("node_id") or ""),
            "role": str(node.get("role") or ""),
            "verb": str((node.get("operation") or {}).get("verb") or ""),
            "parent_id": node.get("parent_id"),
        }
        for node in graph_nodes
        if isinstance(node, dict) and str(node.get("role") or "") != "root"
    ]
    primary_node_id = next(
        (node["node_id"] for node in editable_nodes if node["role"] == "primary"),
        "",
    )
    geometry_program = props.get("geometry_program") if isinstance(props.get("geometry_program"), dict) else {}
    geometry_graph_notes = props.get("geometry_graph_notes") if isinstance(props.get("geometry_graph_notes"), list) else []
    geometry_graph_snapshot = props.get("geometry_graph_snapshot") if isinstance(props.get("geometry_graph_snapshot"), dict) else {}
    outcome_memory_context = props.get("outcome_memory_context") if isinstance(props.get("outcome_memory_context"), dict) else {}
    mass_execution_agent_context = props.get("mass_execution_agent_context") if isinstance(props.get("mass_execution_agent_context"), dict) else {}
    program_context = props.get("program_context") if isinstance(props.get("program_context"), dict) else {}
    geometry_nodes = geometry_program.get("nodes") if isinstance(geometry_program.get("nodes"), list) else []
    geometry_editable_nodes = [
        {
            "node_id": str(node.get("id") or ""),
            "kind": str(node.get("kind") or ""),
            "operator": str(node.get("operator") or ""),
            "parameters": sorted((node.get("parameters") or {}).keys()),
            "semantic_role": str(node.get("semantic_role") or ""),
        }
        for node in geometry_nodes[:96]
        if isinstance(node, dict) and node.get("id")
    ]
    geometry_language_contract = (
        program_context.get("geometry_language_contract")
        if isinstance(program_context.get("geometry_language_contract"), dict)
        else {}
    )
    allowed_geometry_macro_operators = [
        str(value)
        for value in geometry_language_contract.get("allowed_macro_operators") or ()
        if str(value)
    ]
    compact_geometry_program = {
        "root_id": str(geometry_program.get("root_id") or ""),
        "nodes": [
            {
                "id": str(node.get("id") or ""),
                "kind": str(node.get("kind") or ""),
                "operator": str(node.get("operator") or ""),
                "inputs": [str(item) for item in node.get("inputs") or []],
                "parameters": node.get("parameters") if isinstance(node.get("parameters"), dict) else {},
                "semantic_role": str(node.get("semantic_role") or ""),
                "provenance_note": str((node.get("provenance") or {}).get("rationale") or (node.get("provenance") or {}).get("architectural_use") or ""),
            }
            for node in geometry_nodes[:96]
            if isinstance(node, dict)
        ],
    } if geometry_program else {}
    summary = {
        "variant_id": props.get("variant_id"),
        "mass_shape": props.get("mass_shape"),
        "family": source.get("family") or props.get("operator_family"),
        "formal_principle": ambition.get("formal_principle") or source.get("formal_principle"),
        "dominant_gesture": ambition.get("dominant_gesture") or source.get("dominant_gesture"),
        "primary_language": source.get("primary_language"),
        "secondary_language": source.get("secondary_language"),
        "reference_matches": reference_matches[:5],
        "component_graph": component_graph,
        "editable_graph_nodes": editable_nodes,
        "primary_node_id": primary_node_id,
        "geometry_program": compact_geometry_program,
        "geometry_only_critic_mode": geometry_only_critic_mode,
        "geometry_editable_nodes": geometry_editable_nodes,
        "allowed_geometry_macro_operators": allowed_geometry_macro_operators,
        "geometry_graph_notes": geometry_graph_notes[:96],
        "geometry_graph_snapshot": geometry_graph_snapshot,
        "outcome_memory_context": outcome_memory_context,
        "mass_execution_agent_context": mass_execution_agent_context,
        "program_context": program_context,
        "base_seed_catalog": props.get("base_seed_catalog") if isinstance(props.get("base_seed_catalog"), list) else [],
        "site_boundary_source": props.get("site_boundary_source"),
        "site_access_context": props.get("site_access_context") or {},
        "site_design_field": ambition.get("site_design_field") or source.get("site_design_field"),
    }
    geometry_only_instruction = (
        "GEOMETRY-ONLY CRITIC MODE IS ACTIVE. Return graph_edits=[]; the legacy component_graph edit "
        "namespace is intentionally absent. geometry_edits may target existing nodes ONLY by exact node_id "
        "from geometry_editable_nodes. Do not use architectural role labels, component IDs, reference IDs, "
        "or invented aliases as target_node_id. add_node.node_id is the only new ID you may invent; its "
        "input_ids must name the current geometry_program root or another exact geometry node. Follow an "
        "add_node with set_parameter edits for that same new node and set_root to that node.\n"
        if geometry_only_critic_mode else ""
    )
    program_geometry_instruction = (
        "PROGRAM-CONDITIONED GEOMETRY CONTRACT: any macro used by add_node or replace_operator must be "
        f"one of allowed_geometry_macro_operators={allowed_geometry_macro_operators}. This is a hard typed "
        "vocabulary boundary. Do not propose a gym profiled_hall/tower for neighborhood or museum unless "
        "that operator is explicitly listed. Read operator_parameter_contracts and emit only parameters "
        "supported by the exact target/new operator.\n"
        if allowed_geometry_macro_operators else ""
    )
    return (
        "Score this MAAS candidate four-view PNG as an early-stage architectural massing diagram. "
        "Reject a form when it is coherent in only one view or when solids visibly collide across views.\n"
        "When a thin green polygon is present it is the actual parcel boundary. Judge whether the dominant "
        "gesture, open-space figure, and orientation respond coherently to that parcel; do not reward a mass "
        "that merely fills a bounding box. Parcel containment itself remains a deterministic hard gate.\n"
        "A thick blue segment marks the verified primary road frontage/access edge. Reward a public void, "
        "court, undercut, entry seam, or other legible ground response to that edge; penalize a sealed or "
        "semantically opposite access response.\n"
        "The first image is the candidate. Any following images are external architectural reference images "
        "retrieved from the reference corpus. References marked similar explain the candidate's current language. "
        "A reference marked counterfactual intentionally demonstrates a different spatial principle; use it to "
        "propose a transferable graph operation, never to copy its building. Do not reward facade rendering, "
        "photography quality, or materials.\n"
        "program_context is a hard semantic brief, not a style suggestion. First decide whether the visible mass "
        "can plausibly support that program and its semantic_invariants. A formally novel silhouette that erases "
        "the dominant program relation must fail program_fit_hard_pass. For a gymnasium, an arbitrary cascading "
        "pyramid is not a long-span hall merely because metadata says hall; for a museum, an unusual object without "
        "gallery/public-sequence and controlled-light logic is not program-fit; for neighborhood living, a generic "
        "sealed box without an active ground threshold is not program-fit. Judge relationships, not facade style.\n"
        "Every primary reference is program-filtered. Inspect each supplied image yourself and return one "
        "reference_assessment per visible reference. If a source is mislabeled or visually irrelevant, record a "
        "low program_relevance and mismatch_warning instead of imitating it.\n"
        "outcome_memory_context is measured graph evidence from prior compilations and hard gates for this exact "
        "genotype. Use successful parameters as bounded priors and explicitly avoid repeated common_failed_gates; "
        "it is observation memory, not permission to bypass any current hard gate. "
        "downstream_projection_failure_patterns belong to a particular BOOK operation/scope context: use them to "
        "choose or revise that projection, never as a global ban on the authored body or geometry family. "
        "suggested_projection_edits are critic evidence from a prior post-BOOK AST. Do not copy their node IDs "
        "blindly; retarget the same spatial intent to an editable node in the current geometry_graph_snapshot, then "
        "rely on semantic validation, recompile, rerender, and all hard gates.\n"
        "mass_execution_agent_context is the compact causal trace of this exact rendered MASS. Read stage_status, "
        "active_nodes and active_edges before scoring. failed_stages are observed failures to repair; "
        "pending_required_stages are unknown and must never be treated as passes. geometry_edits may target only "
        "exact node IDs shared by editable_ast_nodes and the current geometry_graph_snapshot edit contract.\n"
        f"{geometry_only_instruction}"
        f"{program_geometry_instruction}"
        "Return strict JSON. Each concept score must be between 0 and 1. Use component_graph node_id values "
        "when proposing graph edits; do not invent parcel coordinates. Never target the base/root node. For a "
        "dominant-form correction, target primary_node_id. replace_operation, set_parameter, remove_optional, "
        "and reparent target_node_id must be one of editable_graph_nodes. add_operation parent_node_id must be "
        "root or one of editable_graph_nodes, and its node_id must be new.\n"
        "Concepts:\n"
        "- gesture_clarity: one readable dominant massing idea.\n"
        "- hierarchy: clear main/support relationship, not random fragments.\n"
        "- non_stair_silhouette (legacy field name): score silhouette resolution, not a blanket ban on steps. "
        "Give a high score to a coherent capacity-bearing stepped landform, inhabited terrace section, or one "
        "continuous cascading mass. Give a low score only to repetitive code-minimum stepbacks, arbitrary cake tiers, "
        "or stairs without program/ground/void consequence.\n"
        "- void_publicness: meaningful void/courtyard/undercut/open ground logic.\n"
        "- repair_integrity: visually coherent and likely not over-clipped by legal repair.\n"
        "- precedent_resonance: resonates with reference massing principles without copying.\n"
        "- program_appropriateness: visible mass and hierarchy plausibly support program_context.\n"
        "- section_program_fit: section/roof/void relationships support the program rather than arbitrary sculpture.\n"
        "Critic actions: return any applicable structured actions from this set: "
        "too_fragmented, weak_primary_mass, needs_clean_anchor, too_many_surface_pieces, overlapping_volumes, "
        "too_box_like, weak_form_continuity, needs_profiled_surface, needs_carved_void, "
        "good_void, good_step_mass, preserve_dominant_gesture, wrong_program_typology, missing_program_section. "
        "Use wrong_program_typology when the visible mass belongs to a different building use, and "
        "missing_program_section when its roof/section contradicts the program contract. Use too_box_like when the proposal is mainly "
        "generic rectangular extrusion/stacking; use weak_form_continuity when pieces do not form one spatial "
        "rule; use needs_profiled_surface for a flat roof/section that should become folded or ribbon-like; "
        "use needs_carved_void when solid/void organization is missing. These actions must describe "
        "geometry changes for the next MassDSL generation, not legal or parking judgments.\n"
        "For graph_edits return only bounded genotype edits: set_parameter, set_control_point, replace_operation, "
        "add_operation, remove_optional, or reparent. For numeric parameters use numeric_value and leave "
        "string_value empty. set_control_point is valid for an existing bend/sloped_roof_mass node with control_points, "
        "or a taper node with plan_control_points. For taper set parameter_name=plan_control_points. Supply its zero-based "
        "control_point_index plus normalized control_point_u and control_point_v. Keep u ordered only for bend/section. "
        "For bend, [u,v] edits the visible plan path; for sloped_roof_mass it edits normalized "
        "[section_position,height]; for taper it edits one executable plan-envelope polygon vertex. "
        "For axis/side/corner/open_side/field_topology/vertical_mode use string_value. For center, bridge, or "
        "ground_spine use boolean_value; never encode booleans as strings. A replace_operation or "
        "add_operation must be immediately followed by at least one valid set_parameter for the affected node; "
        "empty-default topology edits are rejected. add_operation may add only support, void, or connector nodes, "
        "and must identify a new node_id and an existing parent_node_id. Geometry and hard gates validate every edit.\n"
        "When you apply too_box_like, needs_profiled_surface, or weak_form_continuity, scalar parameter tuning alone "
        "is not an adequate correction. Include at least one replace_operation or add_operation followed by valid "
        "set_parameter edits. If the existing primary is bend, one or more set_control_point edits are also a valid "
        "structural correction because they change the executable spatial path. "
        "Use only supported verbs from the response schema and preserve a good simple anchor when no structural "
        "failure applies. A sloped_roof_mass with authored control_points or taper with authored plan_control_points "
        "may also be structurally corrected by set_control_point because it changes executable geometry, not facade styling.\n"
        "When geometry_program is present, also return geometry_edits that mutate its recursive solid AST. "
        "Read geometry_graph_snapshot as the machine-readable node/edge/edit contract and geometry_graph_notes as "
        "non-executable intent and compiled evidence attached to exact node IDs. "
        "Read geometry_graph_snapshot.design_concept_graph before proposing edits. Its causal_bindings identify which "
        "geometry nodes control dominant program space, public threshold, and structure/daylight section. A concept "
        "with missing_controller=true is an explicit deficit: add one compatible typed controller and bind it by "
        "making the new node the root; do not compensate with unrelated surface decoration. "
        "Use those notes to understand why a node exists and what must be preserved, but target only the authoritative "
        "geometry_program node IDs and parameters in edits. Distinguish site scope fraction from normalized base seed: "
        "scope chooses how much parcel envelope is available, while BLOCK/SLAB/BAR/TOWER/PROFILED PRISM chooses the "
        "starting proportion before recursive operations. "
        "Nodes listed in geometry_graph_snapshot.agent_edit_contract.protected_geometry_node_ids are program invariants. "
        "Never replace_operator, remove_node, or rewire_input on them. For profiled_hall only section_family or span_axis "
        "may be set. To add a courtyard or public void, add the new macro with input_ids=[protected hall node] and set it "
        "as root so the hall remains in the new root's ancestry; do not replace the hall itself. "
        "Respect geometry_graph_snapshot.agent_edit_contract.operator_parameter_contracts. In particular, courtyard "
        "and carve_void use margin_ratio (not void_ratio) plus optional open_side. When the site access edge is "
        "visible, set open_side to the matching normalized east/west/north/south side from "
        "program_context.site_access_side_in_program_frame; use closed only for an intentional internal court. "
        "A smaller public entry carve may use notch.side with the same normalized access side, plus bounded "
        "width_ratio, ratio and height_ratio. "
        "For profiled_hall, section_family must be one of ridge, shed, folded, sawtooth, stepped, barrel; "
        "the compiler regenerates the normalized section_controls from that typed family. "
        "Read program_context.portfolio_diversity_contract. Its preferred_section_family is a stable balanced "
        "portfolio slot, not a finished-form template: prefer it when compatible with the program and retrieved "
        "references, and do not collapse every candidate back to ridge/gable. "
        "profiled_hall uses section_family or span_axis. "
        "Do not require an explicit special roof/section from every building type. Read semantic_invariants: "
        "missing_program_section is a blocking action only when the program explicitly requires a roof/section "
        "invariant (for example a gymnasium long-span hall). A neighborhood commercial mass may satisfy its "
        "program through active frontage, a court/notch, hierarchy, or cantilever with a calm roof. "
        "When portfolio_diversity_context is present, judge this exact post-BOOK solid as one portfolio member. "
        "If candidate_pyramidal_like is true and the measured pool is already saturated with pyramidal/stepped "
        "forms, do not emit good_step_mass merely because the object is coherent; reserve it for an exceptional, "
        "program-meaningful stepped section. Otherwise mark the arbitrary tier or typology problem explicitly. "
        "When capacity_review_context is present, treat its measured floor schedule and requested/realized "
        "capacity bands as immutable numeric evidence. Judge whether the visible form expresses that floor "
        "organization, but never visually waive, invent, or increase a hard-gate capacity result. "
        "Use set_parameter for bounded deformation/cutting/pattern parameters. To wrap the current solid in a new "
        "operator, emit add_node with input_ids=[current root], then any set_parameter edits for that new node, then "
        "set_root targeting the new node. Use replace_operator only within the same node kind. Geometry edits support "
        "primitive, transform, modifier, boolean, pattern, composition, and macro nodes. Prefer bend, taper, twist, "
        "slice, cut_corner, radial_array, courtyard, cantilever, split_wing, or bridge when visible evidence calls for "
        "them. Never encode parcel coordinates or copy a completed building. If geometry_program is absent return an "
        "empty geometry_edits array. Every geometry edit is semantically validated, recompiled into a manifold solid, "
        "rendered again, and rejected when its geometry hash does not change.\n"
        f"Candidate JSON summary:\n{json.dumps(summary, ensure_ascii=False, sort_keys=True)}"
    )


def _reference_image_content(
    reference_matches: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    content, _records = _reference_image_inputs(reference_matches, limit=limit)
    return content


def _reference_image_inputs(
    reference_matches: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    if limit is None:
        try:
            limit = max(0, min(
                3,
                int(os.getenv("MAAS_PREFERENCE_VLM_REFERENCE_LIMIT", "2")),
            ))
        except (TypeError, ValueError):
            limit = 2
    content: list[dict[str, Any]] = []
    records: list[dict[str, Any]] = []
    for index, match in enumerate(reference_matches[:limit], start=1):
        image_url = _reference_image_url(match)
        if not image_url:
            continue
        content.append({
            "type": "input_text",
            "text": (
                f"Reference image {index}: {match.get('title') or match.get('source_id') or 'architecture reference'}; "
                f"selection_role={match.get('selection_role') or 'similar'}; "
                f"matched_tags={match.get('matched_tags') or []}; "
                f"program_id={match.get('program_id') or ''}; "
                f"program_match_tier={match.get('program_match_tier') or ''}; "
                f"reference_collection={match.get('reference_collection') or ''}; "
                f"program_matched_terms={match.get('program_matched_terms') or []}; source={match.get('source') or ''}."
            ),
        })
        content.append({
            "type": "input_image",
            "image_url": image_url,
            "detail": "low",
        })
        local_path = resolve_reference_image_path(str(match.get("local_path") or ""))
        records.append({
            "input_id": f"reference:{str(match.get('source_id') or index)}",
            "role": "reference_image",
            "source_id": str(match.get("source_id") or ""),
            "title": str(match.get("title") or ""),
            "source": str(match.get("source") or ""),
            "source_url": str(match.get("source_url") or match.get("page_url") or ""),
            "image_url": str(match.get("image_url") or ""),
            "preview_url": _reference_preview_url(match, local_path),
            "local_path": str(local_path) if local_path is not None else "",
            "sha256": (
                hashlib.sha256(local_path.read_bytes()).hexdigest()
                if local_path is not None
                else str(match.get("sha256") or "")
            ),
            "selection_role": str(match.get("selection_role") or "similar"),
            "matched_tags": list(match.get("matched_tags") or ()),
            "program_id": str(match.get("program_id") or ""),
            "program_match_tier": str(match.get("program_match_tier") or ""),
            "reference_collection": str(match.get("reference_collection") or ""),
            "program_matched_terms": list(match.get("program_matched_terms") or ()),
            "score": match.get("score"),
            "program_relevance_score": match.get("program_relevance_score"),
            "input_order": index,
            "used_by_vlm": True,
        })
    return content, records


def _bind_submitted_reference_identity(
    records: list[dict[str, Any]],
    *,
    response_id: str,
    program_hash: str,
    geometry_hash: str,
) -> list[dict[str, Any]]:
    """Attach the immutable critic and geometry identity to exact inputs."""

    return [
        {
            **dict(record),
            "response_id": str(response_id),
            "program_hash": str(program_hash),
            "geometry_hash": str(geometry_hash),
            "used_by_vlm": True,
        }
        for record in records
    ]


def _review_identity_hashes(
    feature: Mapping[str, Any],
    *,
    program_hash: str,
    geometry_hash: str,
) -> tuple[str, str]:
    properties = feature.get("properties")
    properties = properties if isinstance(properties, Mapping) else {}
    compilation = properties.get("geometry_program_compilation")
    compilation = compilation if isinstance(compilation, Mapping) else {}
    artifact = properties.get("geometry_artifact")
    artifact = artifact if isinstance(artifact, Mapping) else {}
    artifact_identity = artifact.get("identity")
    artifact_identity = (
        artifact_identity if isinstance(artifact_identity, Mapping) else {}
    )
    certificate = artifact.get("projectedVisualCertificate")
    certificate = certificate if isinstance(certificate, Mapping) else {}
    return (
        str(
            program_hash
            or properties.get("program_hash")
            or compilation.get("program_hash")
            or artifact_identity.get("programHash")
            or certificate.get("final_program_hash")
            or ""
        ),
        str(
            geometry_hash
            or properties.get("geometry_hash")
            or compilation.get("geometry_hash")
            or artifact_identity.get("geometryHash")
            or artifact.get("projectedVisualGeometryHash")
            or artifact_identity.get("finalLegalGeometryHash")
            or certificate.get("final_geometry_hash")
            or ""
        ),
    )


def _reference_image_url(match: dict[str, Any]) -> str:
    local = str(match.get("local_path") or "")
    if local:
        path = resolve_reference_image_path(local)
        if path is not None:
            return _image_data_url(path)
    remote = str(match.get("image_url") or "")
    if remote.startswith(("http://", "https://", "data:")):
        return remote
    return ""


def _reference_preview_url(match: dict[str, Any], local_path: Path | None) -> str:
    local_preview = reference_image_preview_url(str(local_path or match.get("local_path") or ""))
    if local_preview:
        return local_preview
    remote = str(match.get("image_url") or "")
    if remote.startswith(("http://", "https://", "data:")):
        return remote
    return ""


def _response_schema() -> dict[str, Any]:
    score_schema = {"type": "number", "minimum": 0, "maximum": 1}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["concept_scores", "program_fit_hard_pass", "reference_assessments", "rationale", "warnings", "critic_actions", "graph_edits", "geometry_edits"],
        "properties": {
            "concept_scores": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "gesture_clarity",
                    "hierarchy",
                    "non_stair_silhouette",
                    "void_publicness",
                    "repair_integrity",
                    "precedent_resonance",
                    "program_appropriateness",
                    "section_program_fit",
                ],
                "properties": {
                    "gesture_clarity": score_schema,
                    "hierarchy": score_schema,
                    "non_stair_silhouette": score_schema,
                    "void_publicness": score_schema,
                    "repair_integrity": score_schema,
                    "precedent_resonance": score_schema,
                    "program_appropriateness": score_schema,
                    "section_program_fit": score_schema,
                },
            },
            "program_fit_hard_pass": {"type": "boolean"},
            "reference_assessments": {
                "type": "array",
                "maxItems": 5,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["source_id", "program_relevance", "transferable_principle", "mismatch_warning"],
                    "properties": {
                        "source_id": {"type": "string", "maxLength": 120},
                        "program_relevance": score_schema,
                        "transferable_principle": {"type": "string", "maxLength": 300},
                        "mismatch_warning": {"type": "string", "maxLength": 300},
                    },
                },
            },
            "rationale": {"type": "string"},
            "warnings": {"type": "array", "items": {"type": "string"}},
            "critic_actions": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "too_fragmented",
                        "weak_primary_mass",
                        "needs_clean_anchor",
                        "too_many_surface_pieces",
                        "overlapping_volumes",
                        "too_box_like",
                        "weak_form_continuity",
                        "needs_profiled_surface",
                        "needs_carved_void",
                        "good_void",
                        "good_step_mass",
                        "preserve_dominant_gesture",
                        "wrong_program_typology",
                        "missing_program_section",
                    ],
                },
            },
            "graph_edits": {
                "type": "array",
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "operation", "target_node_id", "parent_node_id", "node_id", "role",
                        "verb", "parameter_name", "numeric_value", "string_value",
                        "control_point_index", "control_point_u", "control_point_v", "rationale",
                    ],
                    "properties": {
                        "operation": {"type": "string", "enum": ["set_parameter", "set_control_point", "replace_operation", "add_operation", "remove_optional", "reparent"]},
                        "target_node_id": {"type": "string"},
                        "parent_node_id": {"type": "string"},
                        "node_id": {"type": "string"},
                        "role": {"type": "string", "enum": ["", "primary", "support", "void", "connector"]},
                        "verb": {
                            "type": "string",
                            "enum": ["", *sorted(verb for verb in SUPPORTED_VERBS if verb != "base")],
                        },
                        "parameter_name": {"type": "string"},
                        "numeric_value": {"type": "number", "minimum": -70, "maximum": 70},
                        "string_value": {"type": "string"},
                        "control_point_index": {"type": "integer", "minimum": 0, "maximum": 7},
                        "control_point_u": {"type": "number", "minimum": 0.03, "maximum": 0.97},
                        "control_point_v": {"type": "number", "minimum": 0.03, "maximum": 0.97},
                        "rationale": {"type": "string"},
                    },
                },
            },
            "geometry_edits": {
                "type": "array",
                "maxItems": 8,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "operation", "target_node_id", "node_id", "node_kind", "operator",
                        "input_ids", "input_index", "input_node_id", "parameter_name",
                        "numeric_value", "string_value", "boolean_value", "vector_value", "semantic_role", "rationale",
                    ],
                    "properties": {
                        "operation": {
                            "type": "string",
                            "enum": ["set_parameter", "replace_operator", "add_node", "remove_node", "rewire_input", "set_root"],
                        },
                        "target_node_id": {"type": "string", "maxLength": 80},
                        "node_id": {"type": "string", "maxLength": 80},
                        "node_kind": {
                            "type": "string",
                            "enum": ["", "primitive", "transform", "modifier", "boolean", "pattern", "composition", "macro"],
                        },
                        "operator": {
                            "type": "string",
                            "enum": [
                                "", "box", "cylinder", "extruded_polygon", "wedge", "sweep", "loft",
                                "translate", "rotate", "scale", "mirror", "shear", "bend", "taper", "twist",
                                "slice", "clip", "cut_corner", "union", "difference", "intersection", "duplicate",
                                "linear_array", "radial_array", "mirror_array", "stack", "attach", "bridge",
                                "courtyard", "carve_void", "notch", "setback", "terrace", "cantilever", "cross_mass",
                                "bent_bar", "split_wing", "attach_volume", "tapered_tower", "leaning_tower", "stepped_mass", "profiled_hall", "lift", "puncture",
                            ],
                        },
                        "input_ids": {"type": "array", "maxItems": 8, "items": {"type": "string", "maxLength": 80}},
                        "input_index": {"type": "integer", "minimum": 0, "maximum": 23},
                        "input_node_id": {"type": "string", "maxLength": 80},
                        "parameter_name": {"type": "string", "maxLength": 64},
                        "numeric_value": {"type": "number", "minimum": -1000, "maximum": 1000},
                        "string_value": {"type": "string", "maxLength": 80},
                        "boolean_value": {"type": "boolean"},
                        "vector_value": {"type": "array", "maxItems": 4, "items": {"type": "number", "minimum": -1000, "maximum": 1000}},
                        "semantic_role": {"type": "string", "maxLength": 80},
                        "rationale": {"type": "string", "maxLength": 500},
                    },
                },
            },
        },
    }


def _normalize_vlm_result(
    data: dict[str, Any],
    *,
    model: str,
    response_id: str,
    feature: dict[str, Any] | None = None,
) -> dict[str, Any]:
    properties = (
        feature.get("properties")
        if isinstance(feature, dict) and isinstance(feature.get("properties"), dict)
        else {}
    )
    program_context = (
        properties.get("program_context")
        if isinstance(properties.get("program_context"), dict)
        else {}
    )
    program_id = str(program_context.get("program_id") or "").strip().lower()
    semantic_invariants = [
        item for item in program_context.get("semantic_invariants") or ()
        if isinstance(item, dict)
    ]
    invariant_text = " ".join(
        " ".join(str(item.get(key) or "") for key in ("id", "subject_role", "relation", "object_role"))
        for item in semantic_invariants
    ).lower()
    explicit_section_required = bool(
        program_id == "gymnasium"
        or any(token in invariant_text for token in ("roof_section", "roof section", "span_or_daylight"))
    )
    raw_scores = data.get("concept_scores") if isinstance(data.get("concept_scores"), dict) else {}
    scores = {
        key: round(max(0.0, min(1.0, float(raw_scores.get(key, 0.0)))), 3)
        for key in (
            "gesture_clarity",
            "hierarchy",
            "non_stair_silhouette",
            "void_publicness",
            "repair_integrity",
            "precedent_resonance",
            "program_appropriateness",
            "section_program_fit",
        )
    }
    actions = [str(item) for item in data.get("critic_actions") or [] if str(item) in {
        "too_fragmented", "weak_primary_mass", "needs_clean_anchor",
        "too_many_surface_pieces", "overlapping_volumes", "good_void", "good_step_mass",
        "too_box_like", "weak_form_continuity", "needs_profiled_surface", "needs_carved_void",
        "preserve_dominant_gesture",
        "wrong_program_typology", "missing_program_section",
    } and (str(item) != "missing_program_section" or explicit_section_required)]
    provider_actions = list(dict.fromkeys(actions))
    locally_derived_actions: list[str] = []

    def add_local_action(action: str) -> None:
        locally_derived_actions.append(action)
        actions.append(action)

    if scores["hierarchy"] < 0.55:
        add_local_action("weak_primary_mass")
    if scores["gesture_clarity"] < 0.60:
        add_local_action("needs_clean_anchor")
    if scores["hierarchy"] < 0.60 or scores["repair_integrity"] < 0.55:
        add_local_action("too_fragmented")
    if scores["gesture_clarity"] >= 0.75 and scores["hierarchy"] >= 0.70:
        add_local_action("preserve_dominant_gesture")
    if scores["program_appropriateness"] < 0.55:
        add_local_action("wrong_program_typology")
    if explicit_section_required and scores["section_program_fit"] < 0.50:
        add_local_action("missing_program_section")
    # A low non-stair score means the critic sees arbitrary cake-tier
    # repetition, unless it explicitly recognizes a program-related stepped
    # mass.  Waiting until the post-BOOK audit to reject it archives the bad
    # parent and teaches the next generation only on a later benchmark run.
    # Mark the parent as structurally unresolved here; its typed edits are
    # still applied and only a recompiled child may enter the archive.
    if scores["non_stair_silhouette"] < 0.55 and "good_step_mass" not in actions:
        add_local_action("weak_form_continuity")
    actions = list(dict.fromkeys(actions))
    locally_derived_actions = list(dict.fromkeys(locally_derived_actions))
    blocking_visual_actions = {
        "too_fragmented",
        "weak_primary_mass",
        "needs_clean_anchor",
        "too_many_surface_pieces",
        "overlapping_volumes",
        "too_box_like",
        "weak_form_continuity",
        "wrong_program_typology",
        "missing_program_section",
    }
    provider_program_fit_hard_pass = bool(data.get("program_fit_hard_pass"))
    program_fit_hard_pass = (
        scores["program_appropriateness"] >= 0.55
        and (not explicit_section_required or scores["section_program_fit"] >= 0.50)
        and provider_program_fit_hard_pass
        and not blocking_visual_actions.intersection(actions)
    )
    reference_assessments = [
        {
            "source_id": str(item.get("source_id") or "")[:120],
            "program_relevance": round(max(0.0, min(1.0, float(item.get("program_relevance") or 0.0))), 3),
            "transferable_principle": str(item.get("transferable_principle") or "")[:300],
            "mismatch_warning": str(item.get("mismatch_warning") or "")[:300],
        }
        for item in data.get("reference_assessments") or ()
        if isinstance(item, dict) and item.get("source_id")
    ][:5]
    graph_edits = []
    geometry_only_critic_mode = bool(properties.get("geometry_only_critic_mode"))
    # Critic language is intentionally architectural, while the executable
    # genotype has a smaller typed vocabulary.  Translate common architectural
    # edit words at this single boundary instead of silently dropping them in
    # the graph reviser.
    verb_aliases = {
        "carve": "courtyard",
        "bridge": "diagonal_connect",
        "fold": "sloped_roof_mass",
        "sweep": "bend",
        "terrace": "terrace_link",
    }
    editable_control_nodes = _editable_control_node_ids(feature or {})
    for item in (() if geometry_only_critic_mode else (data.get("graph_edits") or [])):
        if not isinstance(item, dict) or str(item.get("operation") or "") not in {
            "set_parameter", "set_control_point", "replace_operation", "add_operation", "remove_optional", "reparent",
        }:
            continue
        operation = str(item.get("operation") or "")
        target_node_id = str(item.get("target_node_id") or "")[:80]
        if operation == "set_control_point" and target_node_id not in editable_control_nodes:
            continue
        verb = str(item.get("verb") or "")[:48].strip().lower()
        graph_edits.append({
            "operation": operation,
            "target_node_id": target_node_id,
            "parent_node_id": str(item.get("parent_node_id") or "")[:80],
            "node_id": str(item.get("node_id") or "")[:80],
            "role": str(item.get("role") or ""),
            "verb": verb_aliases.get(verb, verb),
            "parameter_name": str(item.get("parameter_name") or "")[:64],
            "numeric_value": max(-70.0, min(70.0, float(item.get("numeric_value") or 0.0))),
            "string_value": str(item.get("string_value") or "")[:64].strip().lower(),
            "control_point_index": max(0, min(7, int(item.get("control_point_index") or 0))),
            "control_point_u": max(0.03, min(0.97, float(item.get("control_point_u") or 0.03))),
            "control_point_v": max(0.03, min(0.97, float(item.get("control_point_v") or 0.03))),
            "rationale": str(item.get("rationale") or "")[:500],
        })
    geometry_edits = []
    valid_geometry_operations = {
        "set_parameter", "replace_operator", "add_node", "remove_node", "rewire_input", "set_root",
    }
    valid_geometry_kinds = {"primitive", "transform", "modifier", "boolean", "pattern", "composition", "macro"}
    raw_geometry_program = (
        properties.get("geometry_program")
        if isinstance(properties.get("geometry_program"), dict)
        else {}
    )
    geometry_language_contract = (
        program_context.get("geometry_language_contract")
        if isinstance(program_context.get("geometry_language_contract"), dict)
        else {}
    )
    allowed_geometry_macros = {
        str(value).strip().lower()
        for value in geometry_language_contract.get("allowed_macro_operators") or ()
        if str(value).strip()
    }
    geometry_graph_snapshot = (
        properties.get("geometry_graph_snapshot")
        if isinstance(properties.get("geometry_graph_snapshot"), dict)
        else {}
    )
    agent_edit_contract = (
        geometry_graph_snapshot.get("agent_edit_contract")
        if isinstance(geometry_graph_snapshot.get("agent_edit_contract"), dict)
        else {}
    )
    operator_parameter_contracts = {
        str(operator): {str(parameter) for parameter in parameters or ()}
        for operator, parameters in (
            agent_edit_contract.get("operator_parameter_contracts") or {}
        ).items()
    }
    protected_geometry_node_ids = {
        str(value)
        for value in agent_edit_contract.get("protected_geometry_node_ids") or ()
    }
    geometry_operator_by_id = {
        str(node.get("id") or ""): str(node.get("operator") or "").strip().lower()
        for node in raw_geometry_program.get("nodes") or ()
        if isinstance(node, dict) and node.get("id")
    }
    known_geometry_node_ids = {
        str(node.get("id") or "")
        for node in raw_geometry_program.get("nodes") or ()
        if isinstance(node, dict) and node.get("id")
    }
    for item in data.get("geometry_edits") or []:
        if not isinstance(item, dict) or str(item.get("operation") or "") not in valid_geometry_operations:
            continue
        operation = str(item.get("operation") or "")
        target_node_id = str(item.get("target_node_id") or "")[:80]
        new_node_id = str(item.get("node_id") or "")[:80]
        input_ids = [str(value)[:80] for value in item.get("input_ids") or []][:8]
        input_node_id = str(item.get("input_node_id") or "")[:80]
        proposed_operator = str(item.get("operator") or "")[:64].strip().lower()
        if geometry_only_critic_mode:
            if operation == "add_node":
                if (
                    not new_node_id
                    or new_node_id in known_geometry_node_ids
                    or not input_ids
                    or any(value not in known_geometry_node_ids for value in input_ids)
                ):
                    continue
                if (
                    proposed_operator in _ARCHITECTURAL_GEOMETRY_MACROS
                    and allowed_geometry_macros
                    and proposed_operator not in allowed_geometry_macros
                ):
                    continue
                # Later parameter/root edits may address a node introduced
                # earlier in this same ordered batch.
                known_geometry_node_ids.add(new_node_id)
                geometry_operator_by_id[new_node_id] = proposed_operator
            elif not target_node_id or target_node_id not in known_geometry_node_ids:
                continue
            if (
                operation in {"replace_operator", "remove_node", "rewire_input"}
                and target_node_id in protected_geometry_node_ids
            ):
                continue
            if operation == "replace_operator":
                if (
                    proposed_operator in _ARCHITECTURAL_GEOMETRY_MACROS
                    and allowed_geometry_macros
                    and proposed_operator not in allowed_geometry_macros
                ):
                    continue
                geometry_operator_by_id[target_node_id] = proposed_operator
            if operation == "rewire_input" and (
                not input_node_id or input_node_id not in known_geometry_node_ids
            ):
                continue
            if operation == "set_parameter":
                parameter_name = str(item.get("parameter_name") or "")[:64]
                target_operator = geometry_operator_by_id.get(target_node_id, "")
                supported_parameters = operator_parameter_contracts.get(target_operator)
                if (
                    not parameter_name
                    or supported_parameters is not None
                    and parameter_name not in supported_parameters
                ):
                    continue
        kind = str(item.get("node_kind") or "").strip().lower()
        if kind and kind not in valid_geometry_kinds:
            continue
        vector_value = []
        for value in item.get("vector_value") or []:
            try:
                vector_value.append(max(-1000.0, min(1000.0, float(value))))
            except (TypeError, ValueError):
                continue
        geometry_edits.append({
            "operation": operation,
            "target_node_id": target_node_id,
            "node_id": new_node_id,
            "node_kind": kind,
            "operator": proposed_operator,
            "input_ids": input_ids,
            "input_index": max(0, min(23, int(item.get("input_index") or 0))),
            "input_node_id": input_node_id,
            "parameter_name": str(item.get("parameter_name") or "")[:64],
            "numeric_value": max(-1000.0, min(1000.0, float(item.get("numeric_value") or 0.0))),
            "string_value": str(item.get("string_value") or "")[:80].strip().lower(),
            "boolean_value": bool(item.get("boolean_value")),
            "vector_value": vector_value[:4],
            "semantic_role": str(item.get("semantic_role") or "")[:80],
            "rationale": str(item.get("rationale") or "")[:500],
        })
    if geometry_only_critic_mode and geometry_edits:
        # An added solid that is not in the final root ancestry is not a
        # geometry proposal; it is an unreachable AST fragment. Resolve the
        # ordered edit program here so the compiler-safe lane spends its
        # budget only on executable graph mutations.
        input_map = {
            str(node.get("id") or ""): [str(value) for value in node.get("inputs") or ()]
            for node in raw_geometry_program.get("nodes") or ()
            if isinstance(node, dict) and node.get("id")
        }
        added_node_ids: set[str] = set()
        final_root_id = str(raw_geometry_program.get("root_id") or "")
        explicit_root_edit = False
        for edit in geometry_edits:
            operation = edit["operation"]
            if operation == "add_node":
                added_node_ids.add(edit["node_id"])
                input_map[edit["node_id"]] = list(edit["input_ids"])
            elif operation == "rewire_input" and edit["target_node_id"] in input_map:
                inputs = list(input_map[edit["target_node_id"]])
                index = int(edit["input_index"])
                if 0 <= index < len(inputs):
                    inputs[index] = edit["input_node_id"]
                    input_map[edit["target_node_id"]] = inputs
            elif operation == "set_root":
                final_root_id = edit["target_node_id"]
                explicit_root_edit = True
        if added_node_ids and not explicit_root_edit:
            # Recover only the unambiguous shorthand:
            # current root -> unary new node -> ... -> terminal new node.
            # Parallel additions are architectural alternatives, not a chain,
            # so choosing one would invent design intent and remains invalid.
            remaining = set(added_node_ids)
            cursor = final_root_id
            while remaining:
                successors = [
                    node_id for node_id in remaining
                    if input_map.get(node_id) == [cursor]
                ]
                if len(successors) != 1:
                    break
                cursor = successors[0]
                remaining.remove(cursor)
            if not remaining and cursor != final_root_id:
                final_root_id = cursor
                geometry_edits.append({
                    "operation": "set_root",
                    "target_node_id": cursor,
                    "node_id": "",
                    "node_kind": "",
                    "operator": "",
                    "input_ids": [],
                    "input_index": 0,
                    "input_node_id": "",
                    "parameter_name": "",
                    "numeric_value": 0.0,
                    "string_value": "",
                    "boolean_value": False,
                    "vector_value": [],
                    "semantic_role": "",
                    "rationale": "canonical root recovery for one unambiguous unary add-node chain",
                })
        reachable: set[str] = set()
        stack = [final_root_id]
        while stack:
            node_id = stack.pop()
            if not node_id or node_id in reachable:
                continue
            reachable.add(node_id)
            stack.extend(input_map.get(node_id, ()))
        unreachable_added = added_node_ids - reachable
        if unreachable_added:
            geometry_edits = [
                edit for edit in geometry_edits
                if edit.get("node_id") not in unreachable_added
                and edit.get("target_node_id") not in unreachable_added
            ]
    return {
        "schema_version": VLM_SCORE_SCHEMA_VERSION,
        "prompt_contract_version": VLM_PROMPT_CONTRACT_VERSION,
        "provider": "openai",
        "model": model,
        "response_id": response_id,
        "concept_scores": scores,
        "provider_program_fit_hard_pass": provider_program_fit_hard_pass,
        "program_fit_hard_pass": program_fit_hard_pass,
        "explicit_program_section_required": explicit_section_required,
        "reference_assessments": reference_assessments,
        "rationale": str(data.get("rationale") or ""),
        "warnings": [str(item) for item in data.get("warnings") or []],
        "critic_actions": actions,
        "provider_critic_actions": provider_actions,
        "locally_derived_critic_actions": locally_derived_actions,
        "graph_edits": graph_edits[:6],
        "geometry_edits": geometry_edits[:8],
    }


def _editable_control_node_ids(feature: dict[str, Any]) -> set[str]:
    """Return path/section nodes whose authored controls can be mutated."""
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    component_graph = source.get("component_graph") if isinstance(source.get("component_graph"), dict) else {}
    if not component_graph and isinstance(props.get("component_graph"), dict):
        component_graph = props["component_graph"]
    nodes = component_graph.get("nodes") if isinstance(component_graph.get("nodes"), list) else []
    editable: set[str] = set()
    for node in nodes:
        operation = node.get("operation") if isinstance(node, dict) and isinstance(node.get("operation"), dict) else {}
        params = operation.get("params") if isinstance(operation.get("params"), dict) else {}
        controls = params.get("control_points")
        plan_controls = params.get("plan_control_points")
        if operation.get("verb") in {"bend", "sloped_roof_mass"} and isinstance(controls, list) and 4 <= len(controls) <= 6:
            editable.add(str(node.get("node_id") or ""))
        if operation.get("verb") == "taper" and isinstance(plan_controls, list) and 3 <= len(plan_controls) <= 8:
            editable.add(str(node.get("node_id") or ""))
    return editable


def _extract_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output") or []:
        if not isinstance(item, dict):
            continue
        for content in item.get("content") or []:
            if isinstance(content, dict):
                text = content.get("text")
                if isinstance(text, str):
                    chunks.append(text)
    return "\n".join(chunks)


def _image_data_url(path: Path) -> str:
    if not path.exists():
        raise VlmScoringError(f"Image file does not exist: {path}")
    mime = mimetypes.guess_type(str(path))[0] or "image/png"
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


__all__ = [
    "DEFAULT_VLM_MODEL",
    "PORTFOLIO_VLM_PROMPT_VERSION",
    "PORTFOLIO_VLM_SCHEMA_VERSION",
    "REFERENCE_IMAGE_AUDIT_PROMPT_VERSION",
    "REFERENCE_IMAGE_AUDIT_SCHEMA_VERSION",
    "VLM_PROMPT_CONTRACT_VERSION",
    "VLM_SCORE_SCHEMA_VERSION",
    "VlmScoringError",
    "audit_reference_image_for_massing",
    "score_candidate_with_openai_vlm",
    "score_portfolio_board_with_openai_vlm",
]
