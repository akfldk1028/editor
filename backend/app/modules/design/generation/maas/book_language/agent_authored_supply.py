"""Fail-closed Codex OAuth typed GeometryProgram supply.

The Codex session authors the typed payload.  This module only authenticates
the persisted manifest lineage and delegates AST parsing, compiler validation,
and clean-geometry gating to the same boundary used by the paid author.
"""

from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Mapping, Sequence

from backend.app.modules.design.generation.maas.geometry_language import GeometryAuthorError, GeometryProgram, geometry_author_validation_context, geometry_programs_from_author_payload
from backend.app.modules.design.generation.maas.program_massing import program_seed_sequences


CODEX_OAUTH_AUTHOR_PROVIDER = "codex_oauth_llm_geometry_author"
AGENT_AUTHORED_MANIFEST_SCHEMA = (
    "arr.maas.codex_oauth_geometry_manifest.v1"
)
AGENT_AUTHORED_BOOK_PATH_MANIFEST_SCHEMA = (
    "arr.maas.codex_oauth_geometry_manifest.v2_book_composition_paths"
)
AGENT_AUTHORED_CAUSAL_BOOK_PATH_MANIFEST_SCHEMA = (
    "arr.maas.codex_oauth_geometry_manifest.v3_causal_book_paths"
)
AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA = (
    "arr.maas.codex_oauth_geometry_manifest.v4_offered_book_paths"
)
CODEX_OAUTH_AUTHOR_RESPONSE_SCHEMA = (
    "arr.maas.codex_oauth_author_response.v1"
)
CODEX_OAUTH_OFFER_BOUND_AUTHOR_RESPONSE_SCHEMA = (
    "arr.maas.codex_oauth_author_response.v2_offered_path_membership"
)
CODEX_BOOK_PATH_EXECUTION_BINDING_SCHEMA = (
    "arr.maas.codex_book_path_execution_binding.v1"
)

_PROCEDURAL_AUTHOR_MARKERS = (
    "procedural",
    "deterministic",
    "universal_form",
    "executable_language_probe",
)
_FORBIDDEN_PAYLOAD_KEYS = frozenset({
    "mesh",
    "meshes",
    "completed_mesh",
    "vertices",
    "triangles",
    "faces",
    "surfaces",
    "volumes",
    "parcel_coordinates",
    "site_coordinates",
    "world_coordinates",
    "parcel_polygon",
    "site_polygon",
})


class AgentAuthoredSupplyError(ValueError):
    """The persisted author manifest is not admissible typed LLM supply."""


def _is_sha256(value: Any) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


@dataclass(frozen=True)
class AgentAuthoredAdmission:
    """Operator-supplied trust contract independent of manifest contents."""

    authoring_session_id: str
    request_id: str
    manifest_sha256: str
    admitted_program_hashes: frozenset[str] | tuple[str, ...]

    def __post_init__(self) -> None:
        session_id = str(self.authoring_session_id or "").strip()
        request_id = str(self.request_id or "").strip()
        manifest_hash = str(self.manifest_sha256 or "").strip().lower()
        program_hashes = frozenset(
            str(value or "").strip().lower()
            for value in self.admitted_program_hashes
        )
        if not session_id or not request_id:
            raise AgentAuthoredSupplyError(
                "trusted admission session and request are required"
            )
        if not _is_sha256(manifest_hash):
            raise AgentAuthoredSupplyError(
                "trusted admission manifest SHA-256 is invalid"
            )
        if not program_hashes or not all(
            _is_sha256(value) for value in program_hashes
        ):
            raise AgentAuthoredSupplyError(
                "trusted admission program hashes are invalid"
            )
        object.__setattr__(self, "authoring_session_id", session_id)
        object.__setattr__(self, "request_id", request_id)
        object.__setattr__(self, "manifest_sha256", manifest_hash)
        object.__setattr__(self, "admitted_program_hashes", program_hashes)

    def evidence(self) -> dict[str, Any]:
        payload = {
            "schema_version": "arr.maas.codex_oauth_author_admission.v1",
            "provider": CODEX_OAUTH_AUTHOR_PROVIDER,
            "authoring_session_id": self.authoring_session_id,
            "request_id": self.request_id,
            "manifest_sha256": self.manifest_sha256,
            "admitted_program_hashes": sorted(self.admitted_program_hashes),
        }
        canonical = json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return {
            **payload,
            "admission_contract_sha256": hashlib.sha256(canonical).hexdigest(),
        }


def filter_agent_authored_replay_programs(
    programs: Sequence[GeometryProgram],
    requested_program_hashes: Sequence[str],
) -> tuple[GeometryProgram, ...]:
    """Replay an admitted subset without altering the signed source manifest."""

    validated = tuple(programs)
    requested = tuple(
        str(value or "").strip().lower()
        for value in requested_program_hashes
    )
    if not requested:
        return validated
    if len(set(requested)) != len(requested) or not all(
        _is_sha256(value) for value in requested
    ):
        raise AgentAuthoredSupplyError(
            "replay program hashes must be unique SHA-256 values"
        )
    requested_set = frozenset(requested)
    available = {
        program.program_hash(): program
        for program in validated
    }
    if not requested_set.issubset(available):
        raise AgentAuthoredSupplyError(
            "replay program hash is not in the validated manifest"
        )
    return tuple(
        program
        for program in validated
        if program.program_hash() in requested_set
    )


def _contains_forbidden_geometry_payload(value: Any) -> bool:
    if isinstance(value, Mapping):
        for key, nested in value.items():
            normalized = str(key).strip().lower()
            if normalized in _FORBIDDEN_PAYLOAD_KEYS:
                return True
            if normalized in {
                "parcel_coordinates_in_program",
                "completed_building_template",
            }:
                if nested is not False:
                    return True
                continue
            if _contains_forbidden_geometry_payload(nested):
                return True
    elif isinstance(value, (list, tuple)):
        return any(_contains_forbidden_geometry_payload(item) for item in value)
    return False


def _declares_procedural_authorship(item: Mapping[str, Any]) -> bool:
    metadata = item.get("metadata")
    if isinstance(metadata, Mapping):
        identity_values = (
            metadata.get("author_provider"),
            metadata.get("author_source"),
            metadata.get("language_layer"),
        )
        if any(
            marker in str(value or "").strip().lower()
            for value in identity_values
            for marker in _PROCEDURAL_AUTHOR_MARKERS
        ):
            return True
        if metadata.get("llm_geometry_author_active") is False:
            return True
    for node in item.get("nodes") or ():
        if not isinstance(node, Mapping):
            continue
        provenance = node.get("provenance")
        source = (
            provenance.get("source")
            if isinstance(provenance, Mapping)
            else ""
        )
        if any(
            marker in str(source or "").strip().lower()
            for marker in _PROCEDURAL_AUTHOR_MARKERS
        ):
            return True
    return False


def _required_identity(manifest: Mapping[str, Any]) -> tuple[str, str]:
    if manifest.get("schema_version") not in {
        AGENT_AUTHORED_MANIFEST_SCHEMA,
        AGENT_AUTHORED_BOOK_PATH_MANIFEST_SCHEMA,
        AGENT_AUTHORED_CAUSAL_BOOK_PATH_MANIFEST_SCHEMA,
        AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA,
    }:
        raise AgentAuthoredSupplyError("unsupported agent-authored manifest schema")
    if manifest.get("provider") != CODEX_OAUTH_AUTHOR_PROVIDER:
        raise AgentAuthoredSupplyError("invalid Codex OAuth author provider")
    session_id = str(manifest.get("authoring_session_id") or "").strip()
    request_id = str(manifest.get("request_id") or "").strip()
    if not session_id or not request_id:
        raise AgentAuthoredSupplyError(
            "authoring session ID and request ID are required"
        )
    return session_id, request_id


def _structured_parameter(name: str, value: Any) -> dict[str, Any]:
    record: dict[str, Any] = {"name": str(name)}
    if isinstance(value, bool):
        return {**record, "value_type": "boolean", "boolean_value": value}
    if isinstance(value, (int, float)):
        return {**record, "value_type": "number", "numeric_value": value}
    if isinstance(value, str):
        return {**record, "value_type": "string", "string_value": value}
    if isinstance(value, (list, tuple)) and all(
        isinstance(component, (int, float)) and not isinstance(component, bool)
        for component in value
    ):
        return {
            **record,
            "value_type": "vector",
            "vector_value": list(value),
        }
    return {
        **record,
        "value_type": "structured_json",
        "structured_json": json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
    }


def _paid_parser_item(item: Mapping[str, Any]) -> dict[str, Any]:
    """Adapt a persisted GeometryProgram dict to the paid parser schema."""

    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, Mapping) else {}
    nodes = []
    for raw_node in item.get("nodes") or ():
        node = dict(raw_node)
        parameters = node.get("parameters")
        if isinstance(parameters, Mapping):
            node["parameters"] = [
                _structured_parameter(key, value)
                for key, value in sorted(parameters.items())
            ]
        nodes.append(node)
    return {
        **dict(item),
        "base_seed": str(
            item.get("base_seed") or metadata.get("base_seed") or ""
        ),
        "intent_tags": list(
            item.get("intent_tags") or metadata.get("intent_tags") or ()
        ),
        "nodes": nodes,
    }


def load_agent_authored_geometry_programs(
    manifest_path: Path | str,
    *,
    admission: AgentAuthoredAdmission | None = None,
    author_context: dict[str, Any] | None = None,
) -> tuple[GeometryProgram, ...]:
    """Load exact typed Codex-authored programs without provider requests.

    One invalid or non-typed member rejects the whole manifest.  In
    particular, the importer never turns a partially valid batch into a
    smaller supply that could hide a forged or malformed authored member.
    """

    if not isinstance(admission, AgentAuthoredAdmission):
        raise AgentAuthoredSupplyError(
            "trusted admission contract is required"
        )
    path = Path(manifest_path).resolve()
    try:
        raw = path.read_bytes()
        manifest = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AgentAuthoredSupplyError(
            "agent-authored manifest could not be read"
        ) from exc
    if not isinstance(manifest, dict):
        raise AgentAuthoredSupplyError("agent-authored manifest must be an object")
    manifest_hash = hashlib.sha256(raw).hexdigest()
    if manifest_hash != admission.manifest_sha256:
        raise AgentAuthoredSupplyError("agent-authored manifest digest mismatch")
    session_id, request_id = _required_identity(manifest)
    if session_id != admission.authoring_session_id:
        raise AgentAuthoredSupplyError("agent-authored manifest session mismatch")
    if request_id != admission.request_id:
        raise AgentAuthoredSupplyError("agent-authored manifest request mismatch")
    items = manifest.get("programs")
    if not isinstance(items, list) or not items:
        raise AgentAuthoredSupplyError(
            "agent-authored manifest requires typed programs"
        )
    book_path_manifest = (
        manifest.get("schema_version") in {
            AGENT_AUTHORED_BOOK_PATH_MANIFEST_SCHEMA,
            AGENT_AUTHORED_CAUSAL_BOOK_PATH_MANIFEST_SCHEMA,
            AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA,
        }
    )
    causal_book_path_manifest = (
        manifest.get("schema_version") in {
            AGENT_AUTHORED_CAUSAL_BOOK_PATH_MANIFEST_SCHEMA,
            AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA,
        }
    )
    offer_bound_manifest = (
        manifest.get("schema_version")
        == AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA
    )
    author_response_hash = ""
    response_bindings: dict[str, str] = {}
    response_offer_bindings: dict[str, tuple[str, ...]] = {}
    if causal_book_path_manifest:
        response = manifest.get("oauth_author_response")
        if not isinstance(response, dict):
            raise AgentAuthoredSupplyError(
                "causal BOOK composition binding is missing"
            )
        author_response_hash = str(
            response.get("response_sha256") or ""
        ).strip().lower()
        canonical_response = {
            key: value
            for key, value in response.items()
            if key != "response_sha256"
        }
        measured_response_hash = hashlib.sha256(json.dumps(
            canonical_response,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        raw_bindings = response.get("selected_bindings")
        expected_response_schema = (
            CODEX_OAUTH_OFFER_BOUND_AUTHOR_RESPONSE_SCHEMA
            if offer_bound_manifest
            else CODEX_OAUTH_AUTHOR_RESPONSE_SCHEMA
        )
        if (
            response.get("schema_version")
            != expected_response_schema
            or not str(response.get("response_id") or "").strip()
            or author_response_hash != measured_response_hash
            or not isinstance(raw_bindings, list)
            or len(raw_bindings) != len(items)
        ):
            raise AgentAuthoredSupplyError(
                "causal BOOK composition binding is invalid"
            )
        for binding in raw_bindings:
            if not isinstance(binding, dict):
                raise AgentAuthoredSupplyError(
                    "causal BOOK composition binding is invalid"
                )
            name = str(binding.get("program_name") or "").strip()
            path_id = str(
                binding.get("book_composition_path_id") or ""
            ).strip()
            if not name or not path_id or name in response_bindings:
                raise AgentAuthoredSupplyError(
                    "causal BOOK composition binding is invalid"
                )
            if offer_bound_manifest:
                raw_offered_path_ids = binding.get(
                    "offered_book_composition_path_ids"
                )
                if (
                    not isinstance(raw_offered_path_ids, list)
                    or not 1 <= len(raw_offered_path_ids) <= 96
                    or any(
                        not isinstance(value, str) or not value.strip()
                        for value in raw_offered_path_ids
                    )
                    or not _is_sha256(binding.get("prompt_sha256"))
                    or not str(
                        binding.get("direct_llm_response_id") or ""
                    ).strip()
                ):
                    raise AgentAuthoredSupplyError(
                        "persisted LLM BOOK offer is invalid"
                    )
                offered_path_ids = tuple(
                    value.strip() for value in raw_offered_path_ids
                )
                measured_offer_hash = hashlib.sha256(json.dumps(
                    list(offered_path_ids),
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                if (
                    len(set(offered_path_ids)) != len(offered_path_ids)
                    or binding.get("offered_path_ids_sha256")
                    != measured_offer_hash
                ):
                    raise AgentAuthoredSupplyError(
                        "persisted LLM BOOK offer is invalid"
                    )
                if path_id not in offered_path_ids:
                    raise AgentAuthoredSupplyError(
                        "selected BOOK path is not in persisted LLM offer"
                    )
                response_offer_bindings[name] = offered_path_ids
            response_bindings[name] = path_id
    if book_path_manifest:
        from backend.app.modules.design.generation.maas.book_language.composition_lattice import book_composition_path_by_id
        if offer_bound_manifest and any(
            book_composition_path_by_id(path_id) is None
            for offered_path_ids in response_offer_bindings.values()
            for path_id in offered_path_ids
        ):
            raise AgentAuthoredSupplyError(
                "persisted LLM BOOK offer is invalid"
            )
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("nodes"), list):
            raise AgentAuthoredSupplyError(
                "agent-authored manifest accepts typed AST programs only"
            )
        if _declares_procedural_authorship(item):
            raise AgentAuthoredSupplyError(
                "procedural authorship cannot be relabelled as Codex OAuth"
            )
        if _contains_forbidden_geometry_payload(item):
            raise AgentAuthoredSupplyError(
                "mesh or parcel-coordinate payload is forbidden"
            )
        if book_path_manifest:
            path_id = str(
                item.get("book_composition_path_id") or ""
            ).strip()
            if (
                not path_id
                or book_composition_path_by_id(path_id) is None
            ):
                raise AgentAuthoredSupplyError(
                    "agent-authored BOOK composition path binding is invalid"
                )
            if causal_book_path_manifest:
                execution_contract = item.get("execution_contract")
                item_name = str(item.get("name") or "").strip()
                if (
                    not isinstance(execution_contract, dict)
                    or frozenset(execution_contract) != frozenset({
                        "schema_version",
                        "book_composition_path_id",
                        "author_response_sha256",
                    })
                    or execution_contract.get("schema_version")
                    != CODEX_BOOK_PATH_EXECUTION_BINDING_SCHEMA
                    or execution_contract.get(
                        "book_composition_path_id"
                    ) != path_id
                    or execution_contract.get(
                        "author_response_sha256"
                    ) != author_response_hash
                    or response_bindings.get(item_name) != path_id
                ):
                    raise AgentAuthoredSupplyError(
                        "causal BOOK composition binding is invalid"
                    )
    try:
        parser_items = [_paid_parser_item(item) for item in items]
        parser_context = geometry_author_validation_context(
            author_context or {}
        )
        if causal_book_path_manifest:
            # In a compositional author response the same typed base AST may
            # be selected with different BOOK paths.  The path/response pair
            # is part of the program hash, so pre-contract batch deduplication
            # would incorrectly erase valid authored compositions.
            parsed = tuple(
                geometry_programs_from_author_payload(
                    {"programs": [parser_item]},
                    expected_count=1,
                    program_context=parser_context,
                )[0]
                for parser_item in parser_items
            )
        else:
            parsed = geometry_programs_from_author_payload(
                {"programs": parser_items},
                expected_count=len(items),
                program_context=parser_context,
            )
        if causal_book_path_manifest:
            parsed = tuple(
                replace(
                    program,
                    execution_contract=deepcopy(
                        item["execution_contract"]
                    ),
                )
                for item, program in zip(items, parsed)
            )
            if any(program.validate() for program in parsed):
                raise ValueError("invalid causal execution contract")
    except (GeometryAuthorError, TypeError, ValueError) as exc:
        raise AgentAuthoredSupplyError(
            "agent-authored typed program failed parser or compiler gate"
        ) from exc

    parsed_hashes = frozenset(
        program.program_hash() for program in parsed
    )
    if parsed_hashes != admission.admitted_program_hashes:
        raise AgentAuthoredSupplyError(
            "agent-authored admitted program hash set mismatch"
        )
    programs: list[GeometryProgram] = []
    for manifest_index, (item, parsed_program) in enumerate(zip(items, parsed)):
        program_hash = parsed_program.program_hash()
        raw_provenance = {
            str(node.get("id") or ""): deepcopy(node.get("provenance"))
            for node in item.get("nodes") or ()
            if isinstance(node, Mapping)
            and isinstance(node.get("provenance"), Mapping)
        }
        nodes = tuple(
            replace(
                node,
                provenance={
                    **{
                        key: value
                        for key, value in node.provenance.items()
                        if key not in {"source", "representation"}
                    },
                    **raw_provenance.get(node.id, {}),
                },
            )
            for node in parsed_program.nodes
        )
        programs.append(replace(
            parsed_program,
            nodes=nodes,
            metadata={
                **parsed_program.metadata,
                "author_provider": CODEX_OAUTH_AUTHOR_PROVIDER,
                "author_source": CODEX_OAUTH_AUTHOR_PROVIDER,
                "authoring_session_id": session_id,
                "author_session_id": session_id,
                "author_request_id": request_id,
                "request_id": request_id,
                "author_manifest_sha256": manifest_hash,
                "author_manifest_schema_version": str(
                    manifest.get("schema_version") or ""
                ),
                "author_manifest_index": manifest_index,
                "author_program_hash": program_hash,
                "author_representation": "typed_json_ast",
                "authorship_validation_status": (
                    "validated_typed_parser_compiler_gate"
                ),
                "authorship_admission": admission.evidence(),
                "llm_geometry_author_active": True,
                "parcel_coordinates_in_program": False,
                "completed_building_template": False,
            },
        ))
    return tuple(programs)


def is_validated_codex_oauth_program_payload(
    payload: Any,
    *,
    admission: AgentAuthoredAdmission | None,
) -> bool:
    """Verify the exact lineage fields required for Codex OAuth authorship."""

    if not isinstance(payload, dict):
        return False
    try:
        program = GeometryProgram.from_dict(payload)
    except (TypeError, ValueError):
        return False
    if not isinstance(admission, AgentAuthoredAdmission):
        return False
    metadata = program.metadata
    authored_hash = str(metadata.get("author_program_hash") or "")
    return bool(
        _has_valid_codex_oauth_identity(
            program,
            admission=admission,
        )
        and authored_hash == program.program_hash()
    )


def _has_valid_codex_oauth_identity(
    program: GeometryProgram,
    *,
    admission: AgentAuthoredAdmission | None,
) -> bool:
    """Validate immutable Codex identity fields independent of BOOK rewrites."""

    if not isinstance(admission, AgentAuthoredAdmission):
        return False
    metadata = program.metadata
    authored_hash = str(metadata.get("author_program_hash") or "")
    return bool(
        metadata.get("author_provider") == CODEX_OAUTH_AUTHOR_PROVIDER
        and metadata.get("llm_geometry_author_active") is True
        and metadata.get("author_representation") == "typed_json_ast"
        and metadata.get("authorship_validation_status")
        == "validated_typed_parser_compiler_gate"
        and str(metadata.get("authoring_session_id") or "")
        and str(metadata.get("author_request_id") or "")
        and metadata.get("authorship_admission") == admission.evidence()
        and metadata.get("authoring_session_id")
        == admission.authoring_session_id
        and metadata.get("author_request_id") == admission.request_id
        and metadata.get("author_manifest_sha256")
        == admission.manifest_sha256
        and authored_hash in admission.admitted_program_hashes
        and metadata.get("parcel_coordinates_in_program") is False
        and metadata.get("completed_building_template") is False
    )


def is_validated_codex_oauth_candidate(
    candidate: Any,
    *,
    admission: AgentAuthoredAdmission | None,
) -> bool:
    """Bind a selected post-BOOK candidate to trusted pre-BOOK admission."""

    source = getattr(candidate, "source", None)
    source_metadata = getattr(source, "metadata", {})
    if not isinstance(source_metadata, dict):
        return False
    payload = source_metadata.get("authored_geometry_program")
    if not isinstance(payload, dict):
        payload = source_metadata.get("geometry_program")
    try:
        current_hash = GeometryProgram.from_dict(payload).program_hash()
    except (TypeError, ValueError):
        return False
    program = GeometryProgram.from_dict(payload)
    if not _has_valid_codex_oauth_identity(
        program,
        admission=admission,
    ):
        return False
    metadata = program.metadata
    admitted_hash = str(metadata.get("author_program_hash") or "")
    bridge = source_metadata.get("geometry_program_bridge_evidence") or {}
    proof = bridge.get("pre_book_lineage_parent_proof") or {}
    return bool(
        isinstance(bridge, dict)
        and isinstance(proof, dict)
        and bridge.get("llm_geometry_author_active") is True
        and bridge.get("author_provider") == CODEX_OAUTH_AUTHOR_PROVIDER
        and bridge.get("initial_llm_authored_pre_book_program_hash")
        == admitted_hash
        and bridge.get("post_book_authored_program_hash") == current_hash
        and proof.get("program_hash") == admitted_hash
        and proof.get("compiler_clean") is True
        and proof.get("contained") is True
    )


def build_agent_authored_program_seeds(
    programs: Sequence[GeometryProgram],
    *,
    building_type: str,
    admission: AgentAuthoredAdmission | None,
) -> tuple[Any, ...]:
    """Embed only validated Codex programs in the existing pre-BOOK lane."""

    source_seeds = tuple(program_seed_sequences(building_type))
    if not source_seeds:
        raise AgentAuthoredSupplyError("no program-role seed is available")
    seeds = []
    # The typed AST owns the candidate geometry.  The legacy program seed is
    # only its semantic-role carrier, so changing that carrier by list index
    # makes identical author contracts pass or fail for an unrelated reason.
    # The first profile seed is the canonical carrier; the remaining seeds are
    # legacy geometry alternatives used by the non-authored search lane.
    semantic_carrier = source_seeds[0]
    for index, program in enumerate(programs):
        payload = program.to_dict()
        if not is_validated_codex_oauth_program_payload(
            payload,
            admission=admission,
        ) or program.program_hash() not in admission.admitted_program_hashes:
            raise AgentAuthoredSupplyError(
                "unvalidated program cannot enter agent-authored supply"
            )
        source = semantic_carrier
        program_metadata = getattr(program, "metadata", {})
        manifest_index = int(
            program_metadata.get("author_manifest_index", index)
            if isinstance(program_metadata, Mapping)
            else index
        )
        serialized = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        seeds.append(replace(
            source,
            name=(
                f"{source.name}__codex_oauth_{manifest_index}_"
                f"{program.program_hash()[:10]}"
            ),
            notes=tuple((*source.notes,
                f"geometry_program_payload={serialized}",
                f"geometry_program_source_seed={source.name}",
                "geometry_program_edits=[]",
                "geometry_program_rationale=Codex OAuth LLM-authored typed AST manifest",
                "geometry_program_legal_fit_strength=0.0",
                f"geometry_program_source={CODEX_OAUTH_AUTHOR_PROVIDER}",
                "geometry_program_synthesis_request_source=codex_oauth_manifest",
                "geometry_program_vlm_status=not_requested",
                "geometry_program_llm_author_status=validated_manifest",
                "geometry_program_llm_author_request_executed=False",
                "geometry_program_llm_author_active=True",
                "geometry_program_prebook_vlm_quarantined=False",
            )),
        ))
    return tuple(seeds)


__all__ = [
    "AGENT_AUTHORED_MANIFEST_SCHEMA",
    "AGENT_AUTHORED_BOOK_PATH_MANIFEST_SCHEMA",
    "AGENT_AUTHORED_CAUSAL_BOOK_PATH_MANIFEST_SCHEMA",
    "AGENT_AUTHORED_OFFER_BOUND_MANIFEST_SCHEMA",
    "AgentAuthoredAdmission",
    "AgentAuthoredSupplyError",
    "CODEX_OAUTH_AUTHOR_PROVIDER",
    "build_agent_authored_program_seeds",
    "is_validated_codex_oauth_candidate",
    "is_validated_codex_oauth_program_payload",
    "load_agent_authored_geometry_programs",
]
