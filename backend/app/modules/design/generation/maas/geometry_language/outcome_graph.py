"""Append-only outcome graph for geometry-program mutation and selection.

The portable JSON graph is always available, including when Neo4j is off.
An optional Neo4j mirror can be enabled explicitly for interactive graph
inspection; failure to connect never blocks geometry diagnostics.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.geometry_language.chassis_taxonomy import core_chassis_families
from backend.app.modules.design.generation.maas.geometry_language.floorwise_visual_projection import projected_surface_visual_hash
from backend.app.modules.design.generation.maas.geometry_language.projected_visual_contract import CertifiedMassArtifact, FINAL_AUTHORITY_CERTIFICATION_MODE


SCHEMA_VERSION = "arr.maas.geometry_mutation_outcome_graph.v1"


class PortfolioRenderAuthorityError(ValueError):
    """Typed refusal of missing or mismatched immutable render authority."""

    def __init__(self, evidence: dict[str, Any]) -> None:
        self.evidence = dict(evidence)
        super().__init__(
            "portfolio_render_authority_invalid: "
            + str(self.evidence.get("reason") or "unknown")
        )


def _stable_id(kind: str, value: str) -> str:
    digest = hashlib.sha256(f"{kind}:{value}".encode("utf-8")).hexdigest()[:20]
    return f"{kind}:{digest}"


def _compact_typed_program_ast(program: dict[str, Any]) -> dict[str, Any]:
    """Persist editable normalized nodes without parcel or mesh coordinates."""
    nodes = []
    for raw in program.get("nodes") or ():
        if not isinstance(raw, dict) or not raw.get("id"):
            continue
        nodes.append({
            "id": str(raw.get("id") or ""),
            "kind": str(raw.get("kind") or ""),
            "operator": str(raw.get("operator") or ""),
            "inputs": [str(value) for value in raw.get("inputs") or ()],
            "parameters": deepcopy(raw.get("parameters") or {}),
            "semantic_role": str(raw.get("semantic_role") or ""),
        })
    return {
        "schema_version": str(program.get("schema_version") or "arr.maas.geometry_program.v1"),
        "name": str(program.get("name") or ""),
        "root_id": str(program.get("root_id") or ""),
        "nodes": nodes,
        "node_count": len(nodes),
        "contains_parcel_coordinates": False,
        "contains_mesh_payload": False,
        "mutation_contract": "read exact node ids; emit bounded typed child edits; never mutate observation in place",
    }


def _compact_reference_author_evidence(metadata: dict[str, Any]) -> dict[str, Any]:
    context = metadata.get("reference_vlm_author_context")
    if not isinstance(context, dict):
        return {}
    return {
        "reference_vlm_precedes_author": bool(metadata.get("reference_vlm_precedes_author")),
        "reference_vlm_author_evidence": {
            "schema_version": str(context.get("schema_version") or ""),
            "status": str(context.get("status") or ""),
            "program_id": str(context.get("program_id") or ""),
            "hard_pass": bool(context.get("hard_pass")),
            "whole_building_program_reference_count": int(
                context.get("whole_building_program_reference_count") or 0
            ),
            "copy_completed_form": False,
            "transfer_only_relations_and_operations": True,
            "references": [
                {
                    "source_id": str(item.get("source_id") or ""),
                    "visible_form_traits": [str(value) for value in item.get("visible_form_traits") or ()][:12],
                }
                for item in context.get("references") or ()
                if isinstance(item, dict)
            ],
        },
    }


def _source_program_identities(
    source: Any,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    str,
    str,
    str,
]:
    """Resolve authored genotype separately from final projected execution."""

    source_metadata = (
        source.metadata
        if isinstance(getattr(source, "metadata", None), dict)
        else {}
    )
    projected = source_metadata.get("geometry_program")
    projected = projected if isinstance(projected, dict) else {}
    authored = source_metadata.get("authored_geometry_program")
    authored = authored if isinstance(authored, dict) else projected
    bridge = source_metadata.get("geometry_program_bridge_evidence")
    bridge = bridge if isinstance(bridge, dict) else {}
    authored_metadata = (
        authored.get("metadata")
        if isinstance(authored.get("metadata"), dict)
        else {}
    )
    projected_metadata = (
        projected.get("metadata")
        if isinstance(projected.get("metadata"), dict)
        else {}
    )
    projected_hash = str(bridge.get("program_hash") or "")
    authored_book_hash = str(
        bridge.get("upstream_authored_program_hash")
        or projected_hash
    )
    reusable_hash = str(
        authored_metadata.get("pre_book_program_hash")
        or projected_metadata.get("pre_book_program_hash")
        or authored_book_hash
    )
    return (
        authored,
        projected,
        authored_metadata,
        projected_metadata,
        reusable_hash,
        authored_book_hash,
        projected_hash,
    )


@dataclass
class GeometryOutcomeGraph:
    path: Path
    pnu: str
    nodes: dict[str, dict[str, Any]] = field(default_factory=dict)
    edges: dict[str, dict[str, Any]] = field(default_factory=dict)
    observations: list[dict[str, Any]] = field(default_factory=list)
    _observation_index: dict[str, dict[str, Any]] = field(default_factory=dict, repr=False)
    _genotype_index: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict, repr=False)
    _indexed_observation_count: int = field(default=-1, repr=False)
    _observation_sequence_max: int = field(default=0, repr=False)

    @classmethod
    def load(cls, path: str | Path, *, pnu: str) -> "GeometryOutcomeGraph":
        graph = cls(Path(path), str(pnu))
        if not graph.path.exists():
            return graph
        try:
            payload = json.loads(graph.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return graph
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            return graph
        if str(payload.get("pnu") or "") != str(pnu):
            return graph
        graph.nodes = {
            str(item["id"]): deepcopy(item)
            for item in payload.get("nodes") or ()
            if isinstance(item, dict) and item.get("id")
        }
        graph.edges = {
            str(item["id"]): deepcopy(item)
            for item in payload.get("edges") or ()
            if isinstance(item, dict) and item.get("id")
        }
        graph.observations = [
            deepcopy(item) for item in payload.get("observations") or ()
            if isinstance(item, dict)
        ]
        graph._ensure_observation_indices()
        return graph

    def observe_candidates(
        self,
        *,
        program_slug: str,
        candidates: Iterable[Any],
        downstream_report: dict[str, Any] | None,
        selected: Iterable[Any] = (),
    ) -> None:
        candidate_list = list(candidates)
        rows = list((downstream_report or {}).get("rows") or ())
        selection_only = downstream_report is None
        if selection_only:
            for observation in self.observations:
                if observation.get("program_slug") == str(program_slug):
                    self._set_observation_selected(observation, False)
        selected_keys = {_candidate_key(item) for item in selected}
        for index, candidate in enumerate(candidate_list):
            row = (
                None
                if selection_only
                else rows[index]
                if index < len(rows) and isinstance(rows[index], dict)
                else {}
            )
            self._observe_candidate(
                program_slug=program_slug,
                candidate=candidate,
                downstream_row=row,
                selected=_candidate_key(candidate) in selected_keys,
            )

    def begin_program_run(self, program_slug: str) -> None:
        """Clear stale archive membership before a new causal observation run."""
        for item in self.observations:
            if item.get("program_slug") == str(program_slug):
                self._set_observation_selected(item, False)

    def observe_program_evaluation(
        self,
        *,
        program_slug: str,
        source: Any,
        sequence_name: str,
        principle_id: str,
        spatial: dict[str, Any],
        failed_gates: Iterable[str],
        program_hard_pass: bool | None = None,
        program_evidence: dict[str, Any] | None = None,
    ) -> None:
        """Persist pre-legal success *and failure* for the next mutation run.

        Earlier graph memory only contained candidates that had already passed
        the program gate.  Consequently the agent learned which legal-fit
        strength survived downstream, but repeatedly regenerated every bend or
        wing genotype that failed coverage/coherence.  This observation closes
        that causal gap without requiring Neo4j.
        """
        (
            authored_program,
            program,
            authored_metadata,
            metadata,
            program_hash,
            authored_book_program_hash,
            projected_program_hash,
        ) = _source_program_identities(source)
        bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
        if (
            not authored_program
            or not isinstance(bridge, dict)
            or not program_hash
            or not projected_program_hash
        ):
            return
        # Learning identity is the reusable agent-authored genotype. BOOK
        # principle/scope is a downstream mutation context and intentionally
        # has its own nodes; otherwise every principle becomes an unrelated
        # program and graph feedback can never inform the next run.
        geometry_hash = str(bridge.get("geometry_hash") or "")
        seed_family = str(bridge.get("source_seed") or str(sequence_name).split("__book_", 1)[0])
        strength = round(float(bridge.get("legal_fit_strength") or 0.0), 4)
        scope = source.metadata.get("program_book_projection_evidence") or {}
        scope = scope.get("scope") if isinstance(scope, dict) else {}
        scope_label = str((scope or {}).get("base_volume_label") or "1/1")
        failures = sorted({str(value) for value in failed_gates})
        resolved_program_hard_pass = (
            bool(program_hard_pass)
            if program_hard_pass is not None
            else not failures
        )
        massing = program_evidence if isinstance(program_evidence, dict) else {}
        if not resolved_program_hard_pass and not failures:
            failures = ["program_massing"]
        observation_key = "|".join((
            "program_gate", str(program_slug), seed_family, program_hash,
            str(strength), str(principle_id), scope_label, geometry_hash,
        ))
        observation_id = _stable_id("observation", observation_key)
        observation = {
            "id": observation_id,
            "stage": "program_gate",
            "program_slug": str(program_slug),
            "source_seed": seed_family,
            "program_hash": program_hash,
            "authored_program_hash": authored_book_program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "geometry_hash": geometry_hash,
            "geometry_family": str(
                authored_metadata.get("family")
                or metadata.get("family")
                or source.metadata.get("family")
                or "recursive_solid"
            ),
            "legal_fit_strength": strength,
            "book_principle_id": str(principle_id),
            "book_scope": scope_label,
            "program_hard_pass": resolved_program_hard_pass,
            "failed_program_gates": failures,
            "program_massing_metrics": {
                key: massing.get(key)
                for key in (
                    "volume_count", "floor_count", "volume_fit", "floor_fit",
                    "family_fit", "coherence_fit", "spatial_fit", "program_fit_score",
                )
            },
            "program_metrics": {
                key: round(float(spatial.get(key) or 0.0), 4)
                for key in (
                    "role_coverage_score", "dominant_component_ratio",
                    "dominant_ratio_score", "site_coverage_ratio",
                    "site_coverage_score", "hierarchy_score",
                    "coverage_numerator_m2", "coverage_denominator_m2",
                )
            },
            "coverage_measurement_mode": str(
                spatial.get("coverage_measurement_mode") or ""
            ),
            "selected": False,
            "vlm_critic_score": authored_metadata.get("vlm_critic_score"),
            "vlm_revision_generation": authored_metadata.get("vlm_revision_generation"),
            "vlm_geometry_critic_active": bool(authored_metadata.get("vlm_geometry_critic_active")),
        }
        self._upsert_observation(observation)

        program_node = self._upsert_node("geometry_program", program_hash, {
            "family": observation["geometry_family"],
            "name": str(authored_program.get("name") or ""),
            "base_seed": str(authored_metadata.get("base_seed") or ""),
            "operator_path": list(authored_metadata.get("operator_path") or bridge.get("operator_path") or ()),
            "intent_tags": list(authored_metadata.get("intent_tags") or ()),
            **_compact_reference_author_evidence(authored_metadata),
        })
        authored_node = self._upsert_node(
            "authored_geometry_program",
            authored_book_program_hash,
            {
                "typed_ast": _compact_typed_program_ast(
                    authored_program
                ),
                "pre_book_program_hash": program_hash,
                "typed_ast_is_authored_post_book_program": True,
            },
        )
        projected_node = self._upsert_node(
            "projected_geometry_program",
            projected_program_hash,
            {
                "geometry_hash": geometry_hash,
                "typed_ast": _compact_typed_program_ast(program),
                "typed_ast_is_final_projected_program": True,
            },
        )
        seed_node = self._upsert_node("program_seed", seed_family, {"program_slug": str(program_slug)})
        genotype_node = self._upsert_node(
            "geometry_genotype",
            f"{seed_family}|{program_hash}|{strength}",
            {"program_hash": program_hash, "source_seed": seed_family, "legal_fit_strength": strength},
        )
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        book_node = self._upsert_node("book_principle", str(principle_id), {})
        scope_node = self._upsert_node("book_scope", scope_label, {})
        self._upsert_edge(seed_node, genotype_node, "mutates_with")
        self._upsert_edge(program_node, genotype_node, "parameterizes")
        self._upsert_edge(program_node, authored_node, "book_projected_to")
        self._upsert_edge(authored_node, projected_node, "legal_projected_to")
        self._upsert_edge(genotype_node, outcome_node, "yielded")
        self._upsert_edge(book_node, outcome_node, "applied_to")
        self._upsert_edge(scope_node, outcome_node, "scoped")

    def observe_geometry_gate_failure(
        self,
        *,
        program_slug: str,
        source_seed: str,
        program: Any,
        principle_id: str,
        book_scope: str,
        stage: str,
        failure_reasons: Iterable[str],
        source: Any | None = None,
        terminal_certificate_evidence: dict[str, Any] | None = None,
        legal_floor_field_hash: str = "",
    ) -> None:
        """Persist failures that occur before the program gate.

        Clean/compiler/materialization failures used to disappear before the
        graph observation point. The next run therefore repeated the exact
        genotype × BOOK projection that had produced disconnected shells.
        This record contains only typed-program identity and measured gate
        evidence; it never stores parcel coordinates or a completed mesh.
        """
        if source is not None:
            (
                program_payload,
                projected_payload,
                metadata,
                _projected_metadata,
                program_hash,
                authored_book_program_hash,
                projected_program_hash,
            ) = _source_program_identities(source)
        else:
            program_payload = (
                program.to_dict() if hasattr(program, "to_dict") else {}
            )
            projected_payload = program_payload
            metadata = (
                program_payload.get("metadata")
                if isinstance(program_payload.get("metadata"), dict)
                else {}
            )
            program_hash = str(
                metadata.get("pre_book_program_hash")
                or (
                    program.program_hash()
                    if hasattr(program, "program_hash")
                    else ""
                )
            )
            authored_book_program_hash = program_hash
            projected_program_hash = ""
        bridge = (
            source.metadata.get("geometry_program_bridge_evidence")
            if source is not None and isinstance(getattr(source, "metadata", None), dict)
            else {}
        )
        bridge = bridge if isinstance(bridge, dict) else {}
        if not program_hash:
            return
        failures = sorted({str(value) for value in failure_reasons if str(value)})
        if not failures:
            return
        observation_key = "|".join((
            "geometry_gate", str(program_slug), str(source_seed), program_hash,
            str(principle_id), str(book_scope), str(stage), "|".join(failures),
        ))
        observation_id = _stable_id("observation", observation_key)
        observation = {
            "id": observation_id,
            "stage": "geometry_gate",
            "geometry_gate_stage": str(stage),
            "program_slug": str(program_slug),
            "source_seed": str(source_seed),
            "program_hash": program_hash,
            "authored_program_hash": authored_book_program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "geometry_hash": str(bridge.get("geometry_hash") or ""),
            "geometry_family": str(metadata.get("family") or "recursive_solid"),
            "book_principle_id": str(principle_id),
            "book_scope": str(book_scope),
            "legal_floor_field_hash": str(legal_floor_field_hash)[:160],
            "program_hard_pass": False,
            "geometry_failure_reasons": failures,
            "selected": False,
        }
        if isinstance(terminal_certificate_evidence, dict):
            observation["terminal_certificate_evidence"] = {
                str(key): deepcopy(value)
                for key, value in terminal_certificate_evidence.items()
                if str(key) in {
                    "schema_version",
                    "structural_failure",
                    "structural_subreason",
                    "repair_reason",
                    "failure_reason",
                    "failure_reasons",
                    "certificate_causes",
                    "certificate_modes",
                    "hard_fail_closed",
                    "visual_authority",
                    "legal_floor_loft_or_prism_replay_allowed",
                    "program_hash",
                    "geometry_family",
                    "book_scope",
                    "legal_floor_field_hash",
                    "source_seed",
                }
            }
        self._upsert_observation(observation)
        program_node = self._upsert_node("geometry_program", program_hash, {
            "family": observation["geometry_family"],
            "name": str(program_payload.get("name") or ""),
            "base_seed": str(metadata.get("base_seed") or ""),
            "operator_path": list(metadata.get("operator_path") or bridge.get("operator_path") or ()),
            "intent_tags": list(metadata.get("intent_tags") or ()),
            **_compact_reference_author_evidence(metadata),
        })
        book_node = self._upsert_node("book_principle", str(principle_id), {})
        scope_node = self._upsert_node("book_scope", str(book_scope), {})
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        self._upsert_edge(program_node, outcome_node, "failed_geometry_gate")
        self._upsert_edge(book_node, outcome_node, "applied_to")
        self._upsert_edge(scope_node, outcome_node, "scoped")

    def _observe_candidate(
        self,
        *,
        program_slug: str,
        candidate: Any,
        downstream_row: dict[str, Any] | None,
        selected: bool,
    ) -> None:
        source = candidate.source
        (
            authored_program,
            program,
            authored_metadata,
            metadata,
            program_hash,
            authored_book_program_hash,
            projected_program_hash,
        ) = _source_program_identities(source)
        bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
        if (
            not authored_program
            or not isinstance(bridge, dict)
            or not program_hash
            or not projected_program_hash
        ):
            return
        geometry_hash = str(bridge.get("geometry_hash") or "")
        seed_family = str(bridge.get("source_seed") or _seed_family(candidate))
        strength = round(float(bridge.get("legal_fit_strength") or 0.0), 4)
        family = str(
            authored_metadata.get("family")
            or metadata.get("family")
            or source.metadata.get("family")
            or "recursive_solid"
        )
        scope = source.metadata.get("program_book_projection_evidence") or {}
        scope = scope.get("scope") if isinstance(scope, dict) else {}
        scope_label = str((scope or {}).get("base_volume_label") or "1/1")
        observation_key = "|".join((
            str(program_slug), seed_family, program_hash, str(strength),
            str(candidate.principle_id), scope_label, geometry_hash,
        ))
        observation_id = _stable_id("observation", observation_key)
        if downstream_row is None:
            self._ensure_observation_indices()
            existing = self._observation_index.get(observation_id)
            if existing is not None:
                self._set_observation_selected(existing, selected)
            return
        legal = downstream_row.get("legal_projection") if isinstance(downstream_row.get("legal_projection"), dict) else {}
        parking = downstream_row.get("parking_hard_gate") if isinstance(downstream_row.get("parking_hard_gate"), dict) else {}
        observation = {
            "id": observation_id,
            "program_slug": str(program_slug),
            "source_seed": seed_family,
            "program_hash": program_hash,
            "authored_program_hash": authored_book_program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "geometry_hash": geometry_hash,
            "geometry_family": family,
            "legal_fit_strength": strength,
            "book_principle_id": str(candidate.principle_id),
            "book_scope": scope_label,
            "program_hard_pass": True,
            "legal_hard_pass": bool(legal.get("hard_pass")),
            "legal_component_evidence": deepcopy(
                legal.get("component_evidence") or {}
            ),
            "legal_component_failure_reasons": {
                str(component): list(
                    (evidence or {}).get("failure_reasons") or ()
                )
                for component, evidence in (
                    legal.get("component_evidence") or {}
                ).items()
                if isinstance(evidence, dict)
            },
            "geometry_retention_pass": bool(legal.get("geometry_retention_pass")),
            "volume_retention": round(float(legal.get("volume_retention") or 0.0), 4),
            "parking_hard_pass": bool(parking.get("hard_pass")),
            "combined_hard_pass": bool(downstream_row.get("combined_hard_pass")),
            "capacity_diagnostic": deepcopy(
                downstream_row.get("capacity_hard_gate") or {}
            ),
            "shared_floor_diagnostic": deepcopy(
                (legal.get("diagnostic_evidence") or {}).get(
                    "shared_floor"
                ) or {}
            ),
            "semantic_program_diagnostic": deepcopy(
                downstream_row.get("semantic_projection_hard_gate") or {}
            ),
            "release_component_evidence": deepcopy(
                downstream_row.get("release_component_evidence") or {}
            ),
            "selected": bool(selected),
            "geometry_failure_reasons": sorted(str(value) for value in legal.get("geometry_failure_reasons") or ()),
            "vlm_critic_score": authored_metadata.get("vlm_critic_score"),
            "vlm_revision_generation": authored_metadata.get("vlm_revision_generation"),
            "vlm_geometry_critic_active": bool(authored_metadata.get("vlm_geometry_critic_active")),
            "final_book_vlm_hard_pass": bool(
                (source.metadata.get("final_book_vlm_audit") or {}).get("hard_pass")
            ),
            "final_book_vlm_actions": list(
                (source.metadata.get("final_book_vlm_audit") or {}).get("critic_actions") or ()
            ),
            "final_book_vlm_response_id": str(
                (source.metadata.get("final_book_vlm_audit") or {}).get("response_id") or ""
            ),
        }
        self._upsert_observation(observation)

        program_node = self._upsert_node("geometry_program", program_hash, {
            "family": family,
            "name": str(authored_program.get("name") or ""),
            "base_seed": str(authored_metadata.get("base_seed") or ""),
            "operator_path": list(authored_metadata.get("operator_path") or bridge.get("operator_path") or ()),
            "intent_tags": list(authored_metadata.get("intent_tags") or ()),
            **_compact_reference_author_evidence(authored_metadata),
        })
        authored_node = self._upsert_node(
            "authored_geometry_program",
            authored_book_program_hash,
            {
                "typed_ast": _compact_typed_program_ast(
                    authored_program
                ),
                "pre_book_program_hash": program_hash,
                "typed_ast_is_authored_post_book_program": True,
            },
        )
        projected_node = self._upsert_node(
            "projected_geometry_program",
            projected_program_hash,
            {
                "geometry_hash": geometry_hash,
                "typed_ast": _compact_typed_program_ast(program),
                "typed_ast_is_final_projected_program": True,
            },
        )
        seed_node = self._upsert_node("program_seed", seed_family, {"program_slug": str(program_slug)})
        genotype_node = self._upsert_node(
            "geometry_genotype",
            f"{seed_family}|{program_hash}|{strength}",
            {"program_hash": program_hash, "source_seed": seed_family, "legal_fit_strength": strength},
        )
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        book_node = self._upsert_node("book_principle", str(candidate.principle_id), {})
        scope_node = self._upsert_node("book_scope", scope_label, {})
        self._upsert_edge(seed_node, genotype_node, "mutates_with")
        self._upsert_edge(program_node, genotype_node, "parameterizes")
        self._upsert_edge(program_node, authored_node, "book_projected_to")
        self._upsert_edge(authored_node, projected_node, "legal_projected_to")
        self._upsert_edge(genotype_node, outcome_node, "yielded")
        self._upsert_edge(book_node, outcome_node, "applied_to")
        self._upsert_edge(scope_node, outcome_node, "scoped")

    def observe_final_book_vlm_audit(
        self,
        *,
        program_slug: str,
        candidate: Any,
        audit: dict[str, Any],
    ) -> None:
        """Persist a critic verdict for the exact post-BOOK solid.

        Proposed edits remain critic evidence until the typed-edit validator
        compiles a distinct child program and proves a valid geometry delta.
        """
        source = candidate.source
        (
            authored_program,
            program,
            authored_metadata,
            metadata,
            program_hash,
            authored_book_program_hash,
            projected_program_hash,
        ) = _source_program_identities(source)
        bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
        if (
            not authored_program
            or not isinstance(bridge, dict)
            or not program_hash
            or not projected_program_hash
        ):
            return
        geometry_hash = str(bridge.get("geometry_hash") or "")
        source_seed = str(bridge.get("source_seed") or _seed_family(candidate))
        scope = source.metadata.get("program_book_projection_evidence") or {}
        scope = scope.get("scope") if isinstance(scope, dict) else {}
        scope_label = str((scope or {}).get("base_volume_label") or "1/1")
        response_id = str(audit.get("response_id") or "")
        observation_key = "|".join((
            "final_book_vlm", str(program_slug), source_seed, program_hash,
            projected_program_hash, geometry_hash, str(candidate.principle_id),
            scope_label, response_id,
        ))
        observation_id = _stable_id("observation", observation_key)
        observation = {
            "id": observation_id,
            "stage": "final_book_vlm",
            "program_slug": str(program_slug),
            "source_seed": source_seed,
            "program_hash": program_hash,
            "authored_program_hash": authored_book_program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "geometry_hash": geometry_hash,
            "geometry_family": str(
                authored_metadata.get("family")
                or metadata.get("family")
                or source.metadata.get("family")
                or "recursive_solid"
            ),
            "book_principle_id": str(candidate.principle_id),
            "book_scope": scope_label,
            "critic_model": str(audit.get("model") or ""),
            "critic_response_id": response_id,
            "critic_actions": [str(item) for item in audit.get("critic_actions") or ()],
            "geometry_edits": deepcopy(audit.get("geometry_edits") or []),
            "concept_scores": deepcopy(audit.get("concept_scores") or {}),
            "final_book_vlm_hard_pass": bool(audit.get("hard_pass")),
            "failed_final_book_vlm_gates": [str(item) for item in audit.get("failures") or ()],
            "reviewed_exact_post_book_geometry": bool(audit.get("reviewed_exact_post_book_geometry")),
            "reference_ids": [str(item) for item in audit.get("reference_ids") or () if item],
            "reference_massing_gate": deepcopy(audit.get("reference_massing_gate") or {}),
            "selected": False,
        }
        self._upsert_observation(observation)
        program_node = self._upsert_node("geometry_program", program_hash, {
            "family": observation["geometry_family"],
            "name": str(authored_program.get("name") or ""),
            "operator_path": list(authored_metadata.get("operator_path") or bridge.get("operator_path") or ()),
            **_compact_reference_author_evidence(authored_metadata),
        })
        authored_node = self._upsert_node(
            "authored_geometry_program",
            authored_book_program_hash,
            {
                "typed_ast": _compact_typed_program_ast(
                    authored_program
                ),
                "pre_book_program_hash": program_hash,
                "typed_ast_is_authored_post_book_program": True,
            },
        )
        projected_node = self._upsert_node("projected_geometry_program", projected_program_hash, {
            "geometry_hash": geometry_hash,
            "book_principle_id": str(candidate.principle_id),
            "book_scope": scope_label,
            "typed_ast": _compact_typed_program_ast(program),
            "typed_ast_is_exact_post_book_program": True,
            "typed_ast_edit_source_only": True,
        })
        critic_identity = response_id or observation_id
        critic_node = self._upsert_node("vlm_critic", critic_identity, {
            "review_stage": "exact_post_book_geometry",
            "model": observation["critic_model"],
            "hard_pass": observation["final_book_vlm_hard_pass"],
            "failures": observation["failed_final_book_vlm_gates"],
            "actions": observation["critic_actions"],
            "geometry_edits": observation["geometry_edits"],
            "concept_scores": observation["concept_scores"],
            "reference_massing_gate": observation["reference_massing_gate"],
        })
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        book_node = self._upsert_node("book_principle", str(candidate.principle_id), {})
        scope_node = self._upsert_node("book_scope", scope_label, {})
        self._upsert_edge(program_node, authored_node, "book_projected_to")
        self._upsert_edge(authored_node, projected_node, "legal_projected_to")
        self._upsert_edge(book_node, projected_node, "applied_to")
        self._upsert_edge(scope_node, projected_node, "scoped")
        self._upsert_edge(projected_node, critic_node, "reviewed_by")
        self._upsert_edge(critic_node, outcome_node, "judged")
        for record in audit.get("reference_records") or ():
            if not isinstance(record, dict):
                continue
            identity = str(record.get("source_id") or record.get("title") or "")
            if not identity:
                continue
            reference_node = self._upsert_node("reference", identity, {
                "source": str(record.get("source") or ""),
                "title": str(record.get("title") or ""),
                "selection_role": str(record.get("selection_role") or ""),
                "program_id": str(record.get("program_id") or ""),
                "program_match_tier": str(record.get("program_match_tier") or ""),
                "matched_tags": list(record.get("matched_tags") or ()),
            })
            self._upsert_edge(reference_node, critic_node, "informed")

    def failed_final_book_geometry_hashes(self, program_slug: str) -> set[str]:
        """Return exact final solids already rejected by the image critic.

        A paid retry may explore another hard-pass candidate, but must not
        spend another request on the same geometry identity. A typed repair
        has a new geometry hash and therefore remains eligible.
        """

        slug = str(program_slug)
        return {
            str(item.get("geometry_hash") or "")
            for item in self.observations
            if item.get("stage") == "final_book_vlm"
            and str(item.get("program_slug") or "") == slug
            and item.get("reviewed_exact_post_book_geometry") is True
            and item.get("final_book_vlm_hard_pass") is not True
            and str(item.get("geometry_hash") or "")
        }

    def observe_portfolio_render(
        self,
        *,
        program_slug: str,
        candidates: Iterable[Any],
        board_path: str | Path,
        render_evidence: Iterable[dict[str, Any]],
        render_features: Iterable[dict[str, Any]] | None = None,
    ) -> None:
        """Bind exact selected geometry identities to their MASS PNG cards.

        The PNG is observation evidence for a human or image VLM.  It never
        replaces the typed AST or geometry hash as mutation authority.
        """

        board = str(Path(board_path))
        candidate_records = tuple(candidates)
        evidence_records = tuple(render_evidence)
        if len(candidate_records) != len(evidence_records):
            raise ValueError("render observation cardinality mismatch")
        explicit_render_features = render_features is not None
        if explicit_render_features:
            feature_records = tuple(render_features or ())
            if len(candidate_records) != len(feature_records):
                raise ValueError("render observation cardinality mismatch")
            if any(
                not isinstance(feature, dict)
                for feature in feature_records
            ):
                raise ValueError("invalid rendered feature")
            render_records = zip(
                candidate_records,
                evidence_records,
                feature_records,
            )
        else:
            render_records = zip(
                candidate_records,
                evidence_records,
                (None,) * len(candidate_records),
            )
        for candidate, raw_evidence, rendered_feature in render_records:
            evidence = raw_evidence if isinstance(raw_evidence, dict) else {}
            source = candidate.source
            (
                authored_program,
                program,
                authored_metadata,
                metadata,
                program_hash,
                authored_book_program_hash,
                projected_program_hash,
            ) = _source_program_identities(source)
            bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
            if (
                not authored_program
                or not program
                or not isinstance(bridge, dict)
            ):
                continue
            capacity_geometry_hash = str(bridge.get("geometry_hash") or "")
            certificate = source.metadata.get("floorwise_visual_projection") or {}
            if not isinstance(certificate, dict):
                certificate = {}
            feature = (
                rendered_feature
                if explicit_render_features
                else candidate.feature
                if isinstance(
                    getattr(candidate, "feature", None),
                    dict,
                )
                else {}
            )
            feature_props = (
                feature.get("properties")
                if isinstance(feature.get("properties"), dict)
                else {}
            )
            geometry_artifact = (
                feature_props.get("geometry_artifact")
                if isinstance(
                    feature_props.get("geometry_artifact"),
                    dict,
                )
                else {}
            )
            artifact_certificate = (
                geometry_artifact.get("projectedVisualCertificate")
                if isinstance(
                    geometry_artifact.get("projectedVisualCertificate"),
                    dict,
                )
                else {}
            )
            final_visual_authority = (
                artifact_certificate.get("certification_mode")
                == FINAL_AUTHORITY_CERTIFICATION_MODE
            )
            rendered_visual_hash = str(
                evidence.get("projected_visual_geometry_hash") or ""
            )
            if final_visual_authority:
                semantic_anchor = evidence.get("final_semantic_anchor")
                semantic_audit = evidence.get("semantic_projection_audit")
                if (
                    not isinstance(semantic_anchor, dict)
                    or not semantic_anchor
                    or not isinstance(semantic_audit, dict)
                    or not semantic_audit
                ):
                    raise PortfolioRenderAuthorityError({
                        "reason": "render_authority_context_missing",
                        "candidate_id": str(
                            feature_props.get("variant_id") or ""
                        ),
                    })
                feature_anchor = feature_props.get("final_semantic_anchor")
                artifact_audit = geometry_artifact.get(
                    "semanticProjectionAudit"
                )
                if (
                    not isinstance(feature_anchor, dict)
                    or feature_anchor != semantic_anchor
                    or not isinstance(artifact_audit, dict)
                    or artifact_audit != semantic_audit
                ):
                    raise PortfolioRenderAuthorityError({
                        "reason": "render_authority_context_mismatch",
                        "candidate_id": str(
                            feature_props.get("variant_id") or ""
                        ),
                    })
                if semantic_audit.get("hard_pass") is not True:
                    raise PortfolioRenderAuthorityError({
                        "reason": "render_semantic_projection_hard_gate_failed",
                        "candidate_id": str(
                            feature_props.get("variant_id") or ""
                        ),
                        "failures": list(
                            semantic_audit.get("failures") or ()
                        ),
                    })
                try:
                    certified_artifact = CertifiedMassArtifact.load(
                        geometry_artifact,
                        authority_context=semantic_anchor,
                    )
                except ValueError as exc:
                    raise PortfolioRenderAuthorityError({
                        "reason": "render_authority_context_mismatch",
                        "candidate_id": str(
                            feature_props.get("variant_id") or ""
                        ),
                        "failure_type": type(exc).__name__,
                        "failure_detail": str(exc),
                    }) from exc
                validated_visual = certified_artifact.validated_visual
                certified_visual_hash = str(
                    validated_visual.visual_hash
                    if validated_visual is not None
                    else ""
                )
                final_legal_geometry_hash = str(
                    geometry_artifact.get("finalLegalGeometryHash") or ""
                )
                rendered_final_legal_hash = str(
                    evidence.get("final_legal_geometry_hash") or ""
                )
                if (
                    not certified_visual_hash
                    or rendered_visual_hash != certified_visual_hash
                ):
                    raise ValueError(
                        "projected visual render hash mismatch: "
                        f"certified={certified_visual_hash or 'missing'} "
                        f"rendered={rendered_visual_hash or 'missing'}"
                    )
                if (
                    not final_legal_geometry_hash
                    or rendered_final_legal_hash
                    != final_legal_geometry_hash
                    or capacity_geometry_hash != final_legal_geometry_hash
                ):
                    raise ValueError(
                        "final legal render hash mismatch: "
                        f"certified={final_legal_geometry_hash or 'missing'} "
                        f"rendered={rendered_final_legal_hash or 'missing'} "
                        f"source={capacity_geometry_hash or 'missing'}"
                    )
            else:
                certified_visual_hash = str(
                    certificate.get("visual_hash") or ""
                )
                final_legal_geometry_hash = ""
                if (
                    certificate.get("schema_version")
                    != "arr.maas.floorwise_visual_projection.v1"
                    or certificate.get("status") != "certified"
                    or certificate.get("hard_pass") is not True
                    or not certified_visual_hash
                    or rendered_visual_hash != certified_visual_hash
                ):
                    raise ValueError(
                        "projected visual render hash mismatch: "
                        f"certified={certified_visual_hash or 'missing'} "
                        f"rendered={rendered_visual_hash or 'missing'}"
                    )
                surfaces = tuple(source.surfaces or ())
                if (
                    not surfaces
                    or int(
                        certificate.get("projected_surface_count") or 0
                    )
                    != len(surfaces)
                    or projected_surface_visual_hash(surfaces)
                    != certified_visual_hash
                ):
                    raise ValueError(
                        "certified projected visual mesh is missing or invalid"
                    )
            geometry_hash = certified_visual_hash
            scope = source.metadata.get("program_book_projection_evidence") or {}
            scope = scope.get("scope") if isinstance(scope, dict) else {}
            scope_label = str((scope or {}).get("base_volume_label") or "1/1")
            capacity_alternative = source.metadata.get("capacity_alternative_projection") or {}
            if not isinstance(capacity_alternative, dict):
                capacity_alternative = {}
            card_index = int(evidence.get("card_index") or 0)
            artifact = {
                "schema_version": "arr.maas.mass_png_render_artifact.v1",
                "program_slug": str(program_slug),
                "board_png": board,
                "card_index": card_index,
                "crop_box": [int(value) for value in evidence.get("crop_box") or ()][:4],
                "rendered_mass_pixel_count": int(evidence.get("rendered_mass_pixel_count") or 0),
                "rendered_mass_pixel_ratio": float(evidence.get("rendered_mass_pixel_ratio") or 0.0),
                "render_hard_pass": bool(evidence.get("hard_pass")),
                "direct_png_review_required": True,
                "evidence_role": "human_and_vlm_visual_observation_not_geometry_authority",
                "geometry_authority": "certified_projected_visual_mesh",
                "projected_visual_geometry_hash": geometry_hash,
                "final_legal_geometry_hash": final_legal_geometry_hash,
                "capacity_geometry_hash": capacity_geometry_hash,
                "capacity_alternative": deepcopy(capacity_alternative),
                "capacity_alternative_id": str(
                    capacity_alternative.get("alternative_id") or ""
                ),
                "capacity_target_utilization": float(
                    capacity_alternative.get("target_utilization") or 0.0
                ),
                "capacity_achieved_utilization": float(
                    capacity_alternative.get("achieved_utilization") or 0.0
                ),
            }
            observation_id = _stable_id(
                "observation",
                "|".join(("mass_png_render", str(program_slug), geometry_hash, board, str(card_index))),
            )
            observation = {
                "id": observation_id,
                "stage": "mass_png_render",
                "program_slug": str(program_slug),
                "source_seed": str(bridge.get("source_seed") or _seed_family(candidate)),
                "program_hash": program_hash,
                "authored_program_hash": authored_book_program_hash,
                "authored_book_program_hash": authored_book_program_hash,
                "projected_program_hash": projected_program_hash,
                "geometry_hash": geometry_hash,
                "final_legal_geometry_hash": final_legal_geometry_hash,
                "capacity_geometry_hash": capacity_geometry_hash,
                "book_principle_id": str(candidate.principle_id),
                "book_scope": scope_label,
                "capacity_alternative_id": str(
                    capacity_alternative.get("alternative_id") or ""
                ),
                "capacity_target_utilization": artifact[
                    "capacity_target_utilization"
                ],
                "capacity_achieved_utilization": artifact[
                    "capacity_achieved_utilization"
                ],
                "selected": True,
                "render_artifact": artifact,
            }
            self._upsert_observation(observation)
            program_node = self._upsert_node(
                "geometry_program",
                program_hash,
                {
                    "name": str(authored_program.get("name") or ""),
                    "family": str(
                        authored_metadata.get("family")
                        or metadata.get("family")
                        or ""
                    ),
                },
            )
            authored_node = self._upsert_node(
                "authored_geometry_program",
                authored_book_program_hash,
                {
                    "typed_ast": _compact_typed_program_ast(
                        authored_program
                    ),
                    "pre_book_program_hash": program_hash,
                    "typed_ast_is_authored_post_book_program": True,
                },
            )
            geometry_node = self._upsert_node(
                "projected_geometry_program",
                projected_program_hash or geometry_hash,
                {
                    "geometry_hash": geometry_hash,
                    "capacity_geometry_hash": capacity_geometry_hash,
                    "book_principle_id": str(candidate.principle_id),
                    "book_scope": scope_label,
                    "capacity_alternative": deepcopy(capacity_alternative),
                    "typed_ast": _compact_typed_program_ast(program),
                    "typed_ast_edit_source_only": True,
                },
            )
            render_node = self._upsert_node(
                "render_artifact",
                f"{board}|{card_index}|{geometry_hash}",
                artifact,
            )
            outcome_node = self._upsert_node("outcome", observation_id, observation)
            self._upsert_edge(
                program_node,
                authored_node,
                "book_projected_to",
            )
            self._upsert_edge(
                authored_node,
                geometry_node,
                "legal_projected_to",
            )
            self._upsert_edge(geometry_node, render_node, "rendered_as")
            self._upsert_edge(render_node, outcome_node, "measured_by")

    def observe_base_book_vlm_audit(
        self,
        *,
        program_slug: str,
        candidate: Any,
        base_review_fingerprint: str,
        review_contract_fingerprint: str,
        audit: dict[str, Any],
    ) -> None:
        """Persist an exact base-parent verdict separately from final solids.

        A base approval may release descendants in later runs, but only when
        the PNU-scoped graph, program, exact rendered geometry, and complete
        visual-review contract all match.  Keeping this as a distinct stage
        prevents an intermediate parent from being mistaken for a final BOOK
        hard pass by mutation feedback.
        """
        fingerprint = str(base_review_fingerprint or "")
        contract = str(review_contract_fingerprint or "")
        if not fingerprint or not contract:
            return
        source = candidate.source
        (
            _authored_program,
            program,
            _authored_metadata,
            metadata,
            program_hash,
            authored_book_program_hash,
            projected_program_hash,
        ) = _source_program_identities(source)
        bridge = source.metadata.get("geometry_program_bridge_evidence") or {}
        program = program if isinstance(program, dict) else {}
        bridge = bridge if isinstance(bridge, dict) else {}
        geometry_hash = str(
            source.metadata.get("final_geometry_hash")
            or bridge.get("geometry_hash")
            or (source.metadata.get("geometry_program_compilation") or {}).get("geometry_hash")
            or ""
        )
        source_seed = str(bridge.get("source_seed") or _seed_family(candidate))
        scope = source.metadata.get("program_book_projection_evidence") or {}
        scope = scope.get("scope") if isinstance(scope, dict) else {}
        scope_label = str((scope or {}).get("base_volume_label") or "1/1")
        response_id = str(audit.get("response_id") or "")
        observation_key = "|".join((
            "book_base_vlm", str(program_slug), fingerprint, contract,
        ))
        observation_id = _stable_id("observation", observation_key)
        reusable_audit = {
            key: deepcopy(audit.get(key))
            for key in (
                "schema_version", "status", "hard_pass", "failures", "model",
                "prompt_contract_version", "review_contract_fingerprint",
                "response_id", "concept_scores", "critic_actions",
                "geometry_edits", "rationale", "reference_ids",
                "reviewed_exact_post_book_geometry", "review_stage",
                "gate_policy", "minimum_feasible_capacity_utilization",
                "candidate_capacity", "candidate_morphology",
                "candidate_design_concept", "reference_massing_gate",
            )
            if key in audit
        }
        observation = {
            "id": observation_id,
            "stage": "book_base_vlm",
            "program_slug": str(program_slug),
            "source_seed": source_seed,
            "program_hash": program_hash,
            "authored_program_hash": authored_book_program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "geometry_hash": geometry_hash,
            "geometry_family": str(
                metadata.get("family") or source.metadata.get("family") or "recursive_solid"
            ),
            "book_principle_id": str(candidate.principle_id),
            "book_scope": scope_label,
            "base_review_fingerprint": fingerprint,
            "review_contract_fingerprint": contract,
            "prompt_contract_version": str(audit.get("prompt_contract_version") or ""),
            "critic_model": str(audit.get("model") or ""),
            "critic_response_id": response_id,
            "base_book_vlm_hard_pass": bool(audit.get("hard_pass")),
            "failed_base_book_vlm_gates": [str(item) for item in audit.get("failures") or ()],
            "base_book_vlm_audit": reusable_audit,
            "selected": False,
        }
        self._upsert_observation(observation)

        base_node = self._upsert_node("book_base_geometry", fingerprint, {
            "geometry_hash": geometry_hash,
            "program_hash": program_hash,
            "authored_book_program_hash": authored_book_program_hash,
            "projected_program_hash": projected_program_hash,
            "book_principle_id": str(candidate.principle_id),
            "book_scope": scope_label,
            "typed_ast": _compact_typed_program_ast(program),
            "typed_ast_is_exact_base_program": True,
        })
        critic_identity = response_id or observation_id
        critic_node = self._upsert_node("vlm_critic", critic_identity, {
            "review_stage": "book_base_operative",
            "model": observation["critic_model"],
            "review_contract_fingerprint": contract,
            "hard_pass": observation["base_book_vlm_hard_pass"],
            "failures": observation["failed_base_book_vlm_gates"],
        })
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        self._upsert_edge(base_node, critic_node, "reviewed_by")
        self._upsert_edge(critic_node, outcome_node, "judged")

    def approved_base_book_vlm_audits(
        self,
        *,
        program_slug: str,
        base_review_fingerprints: Iterable[str],
        review_contract_fingerprint: str,
    ) -> dict[str, dict[str, Any]]:
        """Return only current-contract hard passes for exact base geometry."""
        requested = {
            str(value) for value in base_review_fingerprints if str(value)
        }
        contract = str(review_contract_fingerprint or "")
        if not requested or not contract:
            return {}
        latest = sorted(
            self.observations,
            key=lambda item: int(item.get("observation_sequence") or 0),
            reverse=True,
        )
        resolved: dict[str, dict[str, Any]] = {}
        seen: set[str] = set()
        for item in latest:
            if item.get("stage") != "book_base_vlm":
                continue
            if str(item.get("program_slug") or "") != str(program_slug):
                continue
            if str(item.get("review_contract_fingerprint") or "") != contract:
                continue
            fingerprint = str(item.get("base_review_fingerprint") or "")
            if fingerprint not in requested or fingerprint in seen:
                continue
            seen.add(fingerprint)
            if not bool(item.get("base_book_vlm_hard_pass")):
                continue
            audit = item.get("base_book_vlm_audit")
            if isinstance(audit, dict):
                resolved[fingerprint] = deepcopy(audit)
        return resolved

    def base_book_vlm_replenishment_feedback(
        self,
        *,
        program_slug: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return rejected exact base identities as coordinate-free edit intent."""

        def transferable_value(value: Any, depth: int = 0) -> Any:
            if depth > 3:
                return None
            if isinstance(value, (str, int, float)) and not isinstance(value, bool):
                return value if not isinstance(value, str) else value[:300]
            if isinstance(value, bool):
                return value
            if isinstance(value, (list, tuple)):
                return [
                    item for item in (
                        transferable_value(member, depth + 1)
                        for member in value[:12]
                    ) if item is not None
                ]
            if isinstance(value, dict):
                return {
                    str(key)[:80]: converted
                    for key, member in list(value.items())[:24]
                    if "id" not in str(key).lower()
                    and (converted := transferable_value(member, depth + 1))
                    is not None
                }
            return None

        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for observation in self.observations:
            if observation.get("stage") != "book_base_vlm":
                continue
            if str(observation.get("program_slug") or "") != str(program_slug):
                continue
            if observation.get("base_book_vlm_hard_pass") is True:
                continue
            fingerprint = str(
                observation.get("base_review_fingerprint") or ""
            )
            program_hash = str(observation.get("program_hash") or "")
            if not fingerprint or not program_hash:
                continue
            audit = observation.get("base_book_vlm_audit") or {}
            audit = audit if isinstance(audit, dict) else {}
            row = {
                "parent_fingerprint": fingerprint,
                "program_hash": program_hash,
                "failed_gates": [
                    str(item)[:120]
                    for item in observation.get(
                        "failed_base_book_vlm_gates"
                    ) or ()
                ][:12],
                "critic_actions": transferable_value(
                    list(audit.get("critic_actions") or ())[:8]
                ) or [],
                "geometry_edit_intents": transferable_value(
                    list(audit.get("geometry_edits") or ())[:8]
                ) or [],
                "rationale": str(audit.get("rationale") or "")[:500],
            }
            latest[(fingerprint, program_hash)] = row
        return list(latest.values())[-max(0, min(24, int(limit))):]

    def authored_visual_authority_replenishment_feedback(
        self,
        *,
        program_slug: str,
        limit: int = 12,
    ) -> list[dict[str, Any]]:
        """Return bounded coordinate-free structural repair feedback for AST revision."""

        latest: dict[tuple[str, str], dict[str, Any]] = {}
        for observation in self.observations:
            if observation.get("stage") != "geometry_gate":
                continue
            if str(observation.get("program_slug") or "") != str(program_slug):
                continue
            evidence = observation.get("terminal_certificate_evidence")
            evidence = evidence if isinstance(evidence, dict) else {}
            legacy_evidence = observation.get("terminal_materialization_evidence")
            legacy_evidence = (
                legacy_evidence if isinstance(legacy_evidence, dict) else {}
            )
            gate_stage = str(observation.get("geometry_gate_stage") or "")
            structural_failure = str(evidence.get("structural_failure") or "")
            if not structural_failure and gate_stage == "visual_projection_or_replay":
                structural_failure = "authored_visual_authority"
                evidence = {
                    "structural_failure": structural_failure,
                    "structural_subreason": "authored_visual_authority_revalidation",
                    "repair_reason": "authored_visual_projection_revalidation_failed",
                    "failure_reason": str(
                        legacy_evidence.get("failure_reason")
                        or "revalidation_floor_section_mismatch"
                    ),
                    "certificate_causes": [str(
                        legacy_evidence.get("failure_reason")
                        or "revalidation_floor_section_mismatch"
                    )],
                    "certificate_modes": [
                        "post_projection_section_revalidation"
                    ],
                    "legal_floor_field_hash": str(
                        legacy_evidence.get("legal_floor_field_hash") or ""
                    ),
                }
            if structural_failure != "authored_visual_authority":
                continue
            subreason = str(evidence.get("structural_subreason") or "")[:120]
            if not subreason:
                continue
            program_hash = str(observation.get("program_hash") or "")[:160]
            if not program_hash:
                continue
            row = {
                "structural_failure": "authored_visual_authority",
                "structural_subreason": subreason,
                "repair_reason": str(evidence.get("repair_reason") or "")[:160],
                "failure_reason": str(evidence.get("failure_reason") or "")[:160],
                "certificate_causes": [
                    str(value)[:160]
                    for value in evidence.get("certificate_causes") or ()
                    if isinstance(value, str) and value
                ][:12],
                "certificate_modes": [
                    str(value)[:160]
                    for value in evidence.get("certificate_modes") or ()
                    if isinstance(value, str) and value
                ][:12],
                "program_hash": program_hash,
                "geometry_family": str(
                    evidence.get("geometry_family")
                    or observation.get("geometry_family")
                    or ""
                )[:160],
                "book_scope": str(
                    evidence.get("book_scope")
                    or observation.get("book_scope")
                    or ""
                )[:160],
                "legal_floor_field_hash": str(
                    evidence.get("legal_floor_field_hash")
                    or observation.get("legal_floor_field_hash")
                    or ""
                )[:160],
                "hard_fail_closed": True,
                "visual_authority": "profiled_surface_payload",
                "legal_floor_loft_or_prism_replay_allowed": False,
            }
            latest[(program_hash, subreason)] = row
        return list(latest.values())[-max(0, min(24, int(limit))):]

    def migrate_legacy_base_book_vlm_observations(
        self,
        *,
        program_slug: str,
        critic_response_ids: Iterable[str],
        review_contract: dict[str, Any],
        promote_hard_passes: bool = True,
    ) -> dict[str, int]:
        """Separate historically mislabelled base reviews from final reviews.

        Before the base-stage observation type existed, the shared audit
        routine wrote intermediate base verdicts as ``final_book_vlm``.  A
        caller must provide response IDs from saved base-stage audit evidence;
        no verdict is guessed from geometry or score.  Exact hard passes are
        promoted into the current reusable base contract, while every matched
        legacy record is removed from final-stage learning semantics.
        """
        response_ids = {str(value) for value in critic_response_ids if str(value)}
        contract = str(review_contract.get("fingerprint") or "")
        if not response_ids or not contract:
            return {"matched": 0, "promoted_hard_pass": 0, "relabelled": 0}
        matched = promoted = relabelled = 0
        for item in list(self.observations):
            if item.get("stage") != "final_book_vlm":
                continue
            if str(item.get("program_slug") or "") != str(program_slug):
                continue
            response_id = str(item.get("critic_response_id") or "")
            if response_id not in response_ids:
                continue
            matched += 1
            geometry_hash = str(item.get("geometry_hash") or "")
            hard_pass = bool(item.get("final_book_vlm_hard_pass"))
            item["stage"] = "legacy_book_base_vlm"
            item["legacy_stage_migration"] = {
                "source_stage": "final_book_vlm",
                "target_stage": "book_base_vlm",
                "evidence": "saved_book_base_stage_audit_response_id",
            }
            item["legacy_base_book_vlm_hard_pass"] = hard_pass
            item["final_book_vlm_hard_pass"] = False
            item["failed_final_book_vlm_gates"] = []
            self._upsert_node("outcome", str(item.get("id") or ""), item)
            critic_node_id = _stable_id("vlm_critic", response_id or str(item.get("id") or ""))
            critic_node = self.nodes.get(critic_node_id)
            if isinstance(critic_node, dict):
                critic_node.setdefault("attributes", {})["review_stage"] = "legacy_book_base_operative"
            relabelled += 1
            if not promote_hard_passes or not hard_pass or not geometry_hash:
                continue
            fingerprint = hashlib.sha256(json.dumps(
                {"geometry_hash": geometry_hash},
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            audit = {
                "schema_version": "arr.maas.final_book_vlm_audit.v1",
                "status": "pass",
                "hard_pass": True,
                "failures": [],
                "model": str(item.get("critic_model") or review_contract.get("model") or ""),
                "prompt_contract_version": str(
                    review_contract.get("prompt_contract_version") or ""
                ),
                "review_contract_fingerprint": contract,
                "response_id": response_id,
                "concept_scores": deepcopy(item.get("concept_scores") or {}),
                "critic_actions": deepcopy(item.get("critic_actions") or []),
                "geometry_edits": deepcopy(item.get("geometry_edits") or []),
                "reference_ids": deepcopy(item.get("reference_ids") or []),
                "reference_massing_gate": deepcopy(item.get("reference_massing_gate") or {}),
                "reviewed_exact_post_book_geometry": True,
                "review_stage": "book_base_operative",
                "gate_policy": deepcopy(review_contract.get("gate_policy") or {}),
                "recovered_from_legacy_stage_label": True,
            }
            observation_key = "|".join((
                "book_base_vlm", str(program_slug), fingerprint, contract,
            ))
            observation_id = _stable_id("observation", observation_key)
            base_observation = {
                "id": observation_id,
                "stage": "book_base_vlm",
                "program_slug": str(program_slug),
                "source_seed": str(item.get("source_seed") or ""),
                "program_hash": str(item.get("program_hash") or ""),
                "projected_program_hash": str(item.get("projected_program_hash") or ""),
                "geometry_hash": geometry_hash,
                "geometry_family": str(item.get("geometry_family") or "recursive_solid"),
                "book_principle_id": str(item.get("book_principle_id") or ""),
                "book_scope": str(item.get("book_scope") or "1/1"),
                "base_review_fingerprint": fingerprint,
                "review_contract_fingerprint": contract,
                "prompt_contract_version": audit["prompt_contract_version"],
                "critic_model": audit["model"],
                "critic_response_id": response_id,
                "base_book_vlm_hard_pass": True,
                "failed_base_book_vlm_gates": [],
                "base_book_vlm_audit": audit,
                "selected": False,
            }
            self._upsert_observation(base_observation)
            base_node = self._upsert_node("book_base_geometry", fingerprint, {
                "geometry_hash": geometry_hash,
                "program_hash": base_observation["program_hash"],
                "projected_program_hash": base_observation["projected_program_hash"],
                "book_principle_id": base_observation["book_principle_id"],
                "book_scope": base_observation["book_scope"],
                "typed_ast_is_exact_base_program": True,
                "legacy_stage_migration": True,
            })
            critic_node = self._upsert_node("vlm_critic", response_id or observation_id, {
                "review_stage": "book_base_operative",
                "model": audit["model"],
                "review_contract_fingerprint": contract,
                "hard_pass": True,
                "failures": [],
            })
            outcome_node = self._upsert_node("outcome", observation_id, base_observation)
            self._upsert_edge(base_node, critic_node, "reviewed_by")
            self._upsert_edge(critic_node, outcome_node, "judged")
            promoted += 1
        self._indexed_observation_count = -1
        self._ensure_observation_indices()
        return {
            "matched": matched,
            "promoted_hard_pass": promoted,
            "relabelled": relabelled,
        }

    def observe_portfolio_vlm_audit(
        self,
        *,
        program_slug: str,
        candidate_geometry_hashes: Iterable[str],
        audit: dict[str, Any],
    ) -> None:
        """Persist the board-level sibling/diversity verdict.

        This observation has no geometry authority. It lets the next author
        query portfolio repetition evidence that an isolated-candidate critic
        cannot perceive, while exact typed AST children remain the only edits.
        """

        hashes = sorted({str(value) for value in candidate_geometry_hashes if value})
        response_id = str(audit.get("response_id") or "")
        identity = response_id or hashlib.sha256("|".join((str(program_slug), *hashes)).encode("utf-8")).hexdigest()
        observation_id = _stable_id("observation", f"portfolio_vlm|{program_slug}|{identity}")
        observation = {
            "id": observation_id,
            "stage": "portfolio_vlm",
            "program_slug": str(program_slug),
            "critic_model": str(audit.get("model") or ""),
            "critic_response_id": response_id,
            "portfolio_vlm_hard_pass": bool(audit.get("hard_pass")),
            "candidate_count": int(audit.get("candidate_count") or len(hashes)),
            "visible_family_count": int(audit.get("visible_family_count") or 0),
            "dominant_family_share": float(audit.get("dominant_family_share") or 0.0),
            "failed_portfolio_vlm_gates": [str(item) for item in audit.get("failure_reasons") or ()],
            "repeated_family_groups": deepcopy(audit.get("repeated_family_groups") or []),
            "candidate_actions": deepcopy(audit.get("candidate_actions") or []),
            "geometry_family_action_counts": deepcopy(
                audit.get("geometry_family_action_counts") or {}
            ),
            "overrepresented_geometry_families": [
                str(item) for item in audit.get("overrepresented_geometry_families") or ()
            ],
            "chassis_family_action_counts": deepcopy(
                audit.get("chassis_family_action_counts") or {}
            ),
            "overrepresented_chassis_families": [
                str(item) for item in audit.get("overrepresented_chassis_families") or ()
            ],
            "underrepresented_chassis_families": [
                str(item) for item in audit.get("underrepresented_chassis_families") or ()
            ],
            "required_next_relations": [str(item) for item in audit.get("required_next_relations") or ()],
            "required_geometry_families": [
                str(item) for item in audit.get("required_geometry_families") or ()
            ],
            "candidate_geometry_hashes": hashes,
            "selected": False,
        }
        self._upsert_observation(observation)
        portfolio_node = self._upsert_node("geometry_portfolio", f"{program_slug}|{identity}", {
            "program_slug": str(program_slug),
            "candidate_count": observation["candidate_count"],
            "geometry_hashes": hashes,
        })
        critic_node = self._upsert_node("vlm_portfolio_critic", identity, {
            "review_stage": "final_selected_board",
            "model": observation["critic_model"],
            "hard_pass": observation["portfolio_vlm_hard_pass"],
            "failures": observation["failed_portfolio_vlm_gates"],
            "repeated_family_groups": observation["repeated_family_groups"],
            "candidate_actions": observation["candidate_actions"],
            "geometry_family_action_counts": observation["geometry_family_action_counts"],
            "overrepresented_geometry_families": observation["overrepresented_geometry_families"],
            "chassis_family_action_counts": observation["chassis_family_action_counts"],
            "overrepresented_chassis_families": observation["overrepresented_chassis_families"],
            "underrepresented_chassis_families": observation["underrepresented_chassis_families"],
            "required_next_relations": observation["required_next_relations"],
            "required_geometry_families": observation["required_geometry_families"],
        })
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        self._upsert_edge(portfolio_node, critic_node, "reviewed_as_board_by")
        self._upsert_edge(critic_node, outcome_node, "judged")
        for geometry_hash in hashes:
            geometry_node = self._upsert_node("compiled_geometry", geometry_hash, {})
            self._upsert_edge(geometry_node, portfolio_node, "member_of")

    def latest_portfolio_directive(self, program_slug: str) -> dict[str, Any]:
        """Return typed next-run anchors from the latest board audit.

        Free-form critic prose remains evidence only.  Only schema-bounded
        family identifiers cross the run boundary, and they grant review and
        diversity anchoring rather than hard-pass or geometry authority.
        """
        program_records = sorted((
            item for item in self.observations
            if item.get("stage") == "portfolio_vlm"
            and str(item.get("program_slug") or "") == str(program_slug)
        ), key=lambda item: int(item.get("observation_sequence") or 0))
        record = program_records[-1] if program_records else None
        if not isinstance(record, dict):
            return {
                "schema_version": "arr.maas.portfolio_memory_directive.v1",
                "status": "no_prior_portfolio_vlm",
                "required_geometry_program_families": [],
                "required_chassis_families": [],
                "max_geometry_family_counts": {},
                "max_chassis_family_counts": {},
                "max_chassis_family_count": 0,
            }
        # A cap can suppress a repeated family so effectively that it is not
        # visible on the next board. A three-board window then forgot the
        # causal cap and immediately reintroduced the same family. Keep a
        # small bounded six-board horizon so successful suppression is not
        # mistaken for evidence that the repetition problem disappeared.
        recent_records = program_records[-6:]
        recent_family_caps: dict[str, int] = {}
        recent_chassis_caps: dict[str, int] = {}
        if not bool(record.get("portfolio_vlm_hard_pass")):
            for recent in recent_records:
                for family in recent.get("overrepresented_geometry_families") or ():
                    family = str(family)
                    if not family:
                        continue
                    keep_count = int(
                        ((recent.get("geometry_family_action_counts") or {}).get(family) or {}).get("keep")
                        or 0
                    )
                    cap = max(1, keep_count or 1)
                    recent_family_caps[family] = min(
                        cap,
                        recent_family_caps.get(family, cap),
                    )
                chassis_action_counts = recent.get("chassis_family_action_counts") or {}
                overrepresented_chassis = set(
                    str(chassis)
                    for chassis in recent.get("overrepresented_chassis_families") or ()
                    if str(chassis)
                )
                # Re-derive typed pair feedback so observations written by the
                # earlier three-member rule are upgraded without rewriting
                # the append-only outcome graph. Two candidates both marked
                # REPLACE are already decisive board-level repetition.
                for chassis, counts in chassis_action_counts.items():
                    keep_count = int((counts or {}).get("keep") or 0)
                    replace_count = int((counts or {}).get("replace") or 0)
                    if replace_count >= 2 and replace_count > keep_count:
                        overrepresented_chassis.add(str(chassis))
                for chassis in overrepresented_chassis:
                    keep_count = int(
                        (chassis_action_counts.get(str(chassis)) or {}).get("keep")
                        or 0
                    )
                    cap = max(1, keep_count or 1)
                    recent_chassis_caps[str(chassis)] = min(
                        cap,
                        recent_chassis_caps.get(str(chassis), cap),
                    )
        required_chassis = list(dict.fromkeys(
            str(item) for item in record.get("underrepresented_chassis_families") or ()
            if str(item)
        ))
        chassis_action_counts = record.get("chassis_family_action_counts") or {}
        if (
            not required_chassis
            and not bool(record.get("portfolio_vlm_hard_pass"))
            and chassis_action_counts
        ):
            # Upgrade observations produced before the missing-chassis field
            # existed. Candidate actions cover every selected board card, so
            # their normalized chassis keys are a typed, non-prose inventory.
            present_chassis = {
                str(item) for item in chassis_action_counts
                if str(item)
            }
            required_chassis = [
                f"recursive_chassis:{chassis}"
                for chassis in core_chassis_families()
                if f"recursive_chassis:{chassis}" not in present_chassis
            ]
        return {
            "schema_version": "arr.maas.portfolio_memory_directive.v1",
            "status": "materialized",
            "source_observation_id": str(record.get("id") or ""),
            "source_portfolio_hard_pass": bool(record.get("portfolio_vlm_hard_pass")),
            "required_geometry_program_families": list(dict.fromkeys(
                str(item) for item in record.get("required_geometry_families") or ()
                if str(item)
            )),
            "required_chassis_families": required_chassis,
            "max_geometry_family_counts": dict(sorted(recent_family_caps.items())),
            "max_chassis_family_counts": dict(sorted(recent_chassis_caps.items())),
            # Deprecated global form retained in the schema for old readers.
            # A board critic identifies a particular repeated chassis; it
            # must not penalize every unrelated chassis family.
            "max_chassis_family_count": 0,
            "bounded_recent_portfolio_observation_ids": [
                str(item.get("id") or "") for item in recent_records
            ],
            "failed_gates": list(record.get("failed_portfolio_vlm_gates") or ()),
            "usage_contract": "next_run_review_and_selection_anchor_only",
        }

    def preferred_strengths(
        self,
        *,
        source_seed: str,
        program_hash: str,
        fallback: Iterable[float],
        limit: int = 3,
    ) -> tuple[float, ...]:
        buckets: dict[float, list[dict[str, Any]]] = defaultdict(list)
        for item in self._observations_for_genotype(source_seed, program_hash):
            if item.get("legal_fit_strength") is None:
                # VLM critic observations carry visual feedback, not a legal
                # interpolation measurement. Treating their missing value as
                # strength zero corrupts the legal-fit learner.
                continue
            buckets[round(float(item.get("legal_fit_strength") or 0.0), 4)].append(item)
        ranked = sorted(
            buckets,
            key=lambda strength: (
                sum(bool(item.get("program_hard_pass")) for item in buckets[strength]) / len(buckets[strength]),
                sum(bool(item.get("combined_hard_pass")) for item in buckets[strength]) / len(buckets[strength]),
                # Among hard-pass genotypes preserve the authored design mesh.
                # Upper-envelope interpolation is legal adaptation, not a
                # design reward; a lower strength therefore ranks first.
                -strength,
                sum(float(item.get("volume_retention") or 0.0) for item in buckets[strength]) / len(buckets[strength]),
            ),
            reverse=True,
        )
        successful = [
            strength for strength in ranked
            if any(item.get("combined_hard_pass") for item in buckets[strength])
        ]
        if successful:
            # Exploit the least-deforming successful fit only. Multiplying a
            # known-good genotype by stronger legal interpolation recreated
            # the same pyramidal family and consumed the topology budget.
            return (successful[0],)
        if ranked:
            exploration = [ranked[0]]
            exploration.extend(
                strength for strength in dict.fromkeys(
                    max(0.0, min(1.0, round(float(value), 4))) for value in fallback
                )
                if strength not in buckets
            )
            return tuple(exploration[: max(1, int(limit))])
        return tuple(dict.fromkeys(
            max(0.0, min(1.0, round(float(value), 4))) for value in fallback
        ))[: max(1, int(limit))]

    def preferred_book_principle_ids(
        self,
        *,
        source_seed: str,
        program_hash: str,
        fallback: Iterable[str],
        limit: int = 12,
    ) -> tuple[str, ...]:
        """Retrieve a scope-balanced successful BOOK neighborhood.

        The graph never authors geometry. It only reorders typed principles
        already present in the 59-principle registry using measured prior
        program/legal outcomes for the same reusable genotype.
        """
        maximum = max(6, int(limit))
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in self._observations_for_genotype(source_seed, program_hash):
            principle_id = str(item.get("book_principle_id") or "")
            if principle_id:
                buckets[principle_id].append(item)
        ranked = sorted(
            buckets,
            key=lambda principle_id: (
                any(
                    item.get("stage") == "final_book_vlm"
                    and item.get("final_book_vlm_hard_pass")
                    for item in buckets[principle_id]
                ),
                sum(bool(item.get("combined_hard_pass")) for item in buckets[principle_id]) / len(buckets[principle_id]),
                sum(bool(item.get("program_hard_pass")) for item in buckets[principle_id]) / len(buckets[principle_id]),
                sum(float(item.get("volume_retention") or 0.0) for item in buckets[principle_id]) / len(buckets[principle_id]),
                -sum(bool(item.get("geometry_failure_reasons")) for item in buckets[principle_id]) / len(buckets[principle_id]),
                len(buckets[principle_id]),
            ),
            reverse=True,
        )
        successful = [
            principle_id for principle_id in ranked
            if any(item.get("combined_hard_pass") for item in buckets[principle_id])
        ]
        usable = successful or [
            principle_id for principle_id in ranked
            if any(item.get("program_hard_pass") for item in buckets[principle_id])
        ]
        if not usable:
            usable = [
                principle_id for principle_id in ranked
                if any(
                    item.get("stage") == "program_gate"
                    and not item.get("geometry_failure_reasons")
                    for item in buckets[principle_id]
                )
            ]
        if not usable:
            # With only failure evidence available, retain registry coverage
            # but put the least-failing measured projections first.
            usable = ranked
        chosen: list[str] = []
        # One observed success per p.3 scope is selected first.
        for scope in ("1/1", "3/8", "1/2", "1/4", "1/8", "1/16"):
            match = next((
                principle_id for principle_id in usable
                if any(str(item.get("book_scope") or "") == scope for item in buckets[principle_id])
            ), "")
            if match and match not in chosen:
                chosen.append(match)
        # Preserve BOOK base/combination/aggregation sentence kinds when they
        # have succeeded for this exact genotype.
        for token in ("book:operative:", "book:combination:", "book:aggregation:"):
            match = next((item for item in usable if token in item and item not in chosen), "")
            if match:
                chosen.append(match)
        chosen.extend(item for item in usable if item not in chosen)
        chosen.extend(str(item) for item in fallback if str(item) not in chosen)
        return tuple(chosen[:maximum])

    def agent_neighborhood(
        self,
        *,
        source_seed: str,
        program_hash: str,
        program_slug: str = "",
        program_aliases: Iterable[str] | None = None,
        limit: int = 8,
    ) -> dict[str, Any]:
        """Return compact measured memory that an LLM/VLM can safely consume."""
        descendant_hashes = self._descendant_program_hashes(program_hash, maximum_depth=2)
        rows_by_id: dict[str, dict[str, Any]] = {}
        for related_hash in (str(program_hash), *descendant_hashes):
            for item in self._observations_for_genotype(source_seed, related_hash):
                rows_by_id[str(item.get("id") or id(item))] = item
        exact_rows = list(rows_by_id.values())
        program_keys = {
            str(value) for value in (program_slug, *(program_aliases or ()))
            if str(value)
        }
        program_level_rows = [
            item for item in reversed(self.observations)
            if program_keys
            and str(item.get("program_slug") or "") in program_keys
            and str(item.get("id") or id(item)) not in rows_by_id
            and item.get("stage") in {"vlm_critic", "final_book_vlm", "portfolio_vlm"}
        ][: max(4, int(limit) * 3)]
        rows = [*exact_rows, *program_level_rows]
        ranked = sorted(
            rows,
            key=lambda item: (
                item.get("stage") == "final_book_vlm",
                bool(item.get("final_book_vlm_hard_pass")),
                bool(item.get("combined_hard_pass")),
                bool(item.get("program_hard_pass")),
                bool(item.get("geometry_changed")),
                float(item.get("volume_retention") or 0.0),
            ),
            reverse=True,
        )[: max(1, int(limit))]
        # Program/geometry failures are attributable to the authored body.
        # Exact post-BOOK critic failures are conditional on a particular BOOK
        # projection and scope, so exposing them in the same flat counter made
        # the next author treat one bad projection as a ban on the whole family.
        body_failed_gates: Counter[str] = Counter()
        projection_failure_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in rows:
            body_failed_gates.update(str(value) for value in item.get("failed_program_gates") or ())
            body_failed_gates.update(str(value) for value in item.get("geometry_failure_reasons") or ())
            for value in item.get("failed_final_book_vlm_gates") or ():
                projection_failure_rows[str(value)].append(item)
        return {
            "schema_version": "arr.maas.geometry_agent_neighborhood.v1",
            "source_seed": str(source_seed),
            "program_hash": str(program_hash),
            "descendant_program_hashes": list(descendant_hashes),
            "observation_count": len(rows),
            "exact_genotype_observation_count": len(exact_rows),
            "program_level_observation_count": len(program_level_rows),
            "successful_strengths": sorted({
                float(item.get("legal_fit_strength") or 0.0)
                for item in exact_rows if item.get("combined_hard_pass")
            }),
            "successful_book_principles": sorted({
                str(item.get("book_principle_id"))
                for item in exact_rows if item.get("combined_hard_pass") and item.get("book_principle_id")
            })[:12],
            "visually_verified_book_principles": sorted({
                str(item.get("book_principle_id"))
                for item in exact_rows
                if item.get("stage") == "final_book_vlm"
                and item.get("final_book_vlm_hard_pass")
                and item.get("book_principle_id")
            })[:12],
            "common_failed_gates": [
                {"gate": gate, "count": count}
                for gate, count in body_failed_gates.most_common(8)
            ],
            "downstream_projection_failure_patterns": [
                {
                    "gate": gate,
                    "count": len(items),
                    "distinct_book_principle_count": len({
                        str(item.get("book_principle_id") or "") for item in items
                    }),
                    "distinct_scope_count": len({
                        str(item.get("book_scope") or "") for item in items
                    }),
                    "attribution": "book_projection_context_not_global_author_failure",
                }
                for gate, items in sorted(
                    projection_failure_rows.items(),
                    key=lambda pair: len(pair[1]),
                    reverse=True,
                )[:8]
            ],
            "suggested_projection_edits": [
                {
                    "book_principle_id": str(item.get("book_principle_id") or ""),
                    "book_scope": str(item.get("book_scope") or ""),
                    "critic_actions": list(item.get("critic_actions") or ()),
                    "geometry_edits": deepcopy(item.get("geometry_edits") or []),
                    "attribution": "post_book_critic_suggestion",
                    "application_contract": "retarget_current_ast_then_validate_recompile_rerender_all_hard_gates",
                }
                for item in ranked
                if str(item.get("id") or id(item)) in rows_by_id
                if item.get("stage") == "final_book_vlm"
                and not item.get("final_book_vlm_hard_pass")
                and item.get("geometry_edits")
            ][:4],
            "program_level_relation_priors": [
                {
                    "stage": str(item.get("stage") or ""),
                    "failed_gates": list(
                        item.get("failed_final_book_vlm_gates")
                        or item.get("failed_portfolio_vlm_gates")
                        or ()
                    )[:8],
                    "critic_actions": list(item.get("critic_actions") or ())[:8],
                    "required_next_relations": list(item.get("required_next_relations") or ())[:8],
                    "edit_intents": [
                        {
                            key: deepcopy(edit.get(key))
                            for key in (
                                "operation", "node_kind", "operator", "parameter_name",
                                "numeric_value", "string_value", "vector_value", "semantic_role",
                            )
                            if edit.get(key) not in (None, "", [], 0.0)
                        }
                        for edit in item.get("geometry_edits") or ()
                        if isinstance(edit, dict)
                    ][:4],
                    "node_ids_removed": True,
                    "usage_contract": (
                        "relation prior only; retarget to current graph snapshot and revalidate"
                    ),
                }
                for item in program_level_rows[: max(1, int(limit))]
            ],
            "recent_measured_outcomes": [
                {
                    key: item.get(key)
                    for key in (
                        "stage", "program_hard_pass", "combined_hard_pass",
                        "legal_fit_strength", "book_principle_id", "book_scope",
                        "volume_retention", "critic_score", "critic_actions",
                        "geometry_changed", "mutation_status",
                        "final_book_vlm_hard_pass", "failed_final_book_vlm_gates",
                        "reviewed_exact_post_book_geometry", "concept_scores",
                        "projected_program_hash",
                    )
                    if item.get(key) is not None
                }
                for item in ranked
            ],
        }

    def author_context(
        self,
        *,
        source_seed: str,
        program_slug: str,
        program_aliases: Iterable[str] | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        """Return source-level measured priors for a new LLM graph author.

        A new program has no program hash yet, so ``agent_neighborhood`` cannot
        address it.  This view summarizes successful reusable genotypes and
        separates authored-body failures from conditional BOOK-projection
        failures.  It contains no parcel coordinates or finished mesh.
        """
        program_keys = {
            str(value) for value in (program_slug, *(program_aliases or ()))
            if str(value)
        }
        rows = [
            item for item in self.observations
            if str(item.get("source_seed") or "") == str(source_seed)
            and str(item.get("program_slug") or "") in program_keys
        ]
        portfolio_rows = sorted([
            item for item in self.observations
            if item.get("stage") == "portfolio_vlm"
            and str(item.get("program_slug") or "") in program_keys
        ], key=lambda item: int(item.get("observation_sequence") or 0))
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in rows:
            program_hash = str(item.get("program_hash") or "")
            if program_hash:
                grouped[program_hash].append(item)
        program_nodes = {
            str(node.get("identity") or ""): (
                node.get("attributes")
                if isinstance(node.get("attributes"), dict)
                else node
            )
            for node in self.nodes.values()
            if node.get("kind") == "geometry_program" and node.get("identity")
        }
        ranked_hashes = sorted(
            grouped,
            key=lambda program_hash: (
                any(item.get("final_book_vlm_hard_pass") for item in grouped[program_hash]),
                any(item.get("combined_hard_pass") for item in grouped[program_hash]),
                sum(bool(item.get("program_hard_pass")) for item in grouped[program_hash]),
                -sum(bool(item.get("failed_program_gates")) for item in grouped[program_hash]),
            ),
            reverse=True,
        )
        body_failures: Counter[str] = Counter()
        projection_failures: Counter[str] = Counter()
        for item in rows:
            body_failures.update(str(value) for value in item.get("failed_program_gates") or ())
            body_failures.update(str(value) for value in item.get("geometry_failure_reasons") or ())
            projection_failures.update(str(value) for value in item.get("failed_final_book_vlm_gates") or ())
        transferable_repairs: list[dict[str, Any]] = []
        seen_repairs: set[str] = set()
        reference_relation_priors: list[dict[str, Any]] = []
        seen_reference_priors: set[tuple[str, str]] = set()
        for item in reversed(rows):
            for assessment in item.get("reference_assessments") or ():
                if not isinstance(assessment, dict):
                    continue
                principle = str(assessment.get("transferable_principle") or "").strip()
                source_id = str(assessment.get("source_id") or "").strip()
                try:
                    relevance = float(assessment.get("program_relevance") or 0.0)
                except (TypeError, ValueError):
                    relevance = 0.0
                identity = (source_id, principle.lower())
                if not principle or relevance < 0.55 or identity in seen_reference_priors:
                    continue
                seen_reference_priors.add(identity)
                reference_relation_priors.append({
                    "source_id": source_id,
                    "program_relevance": round(min(1.0, relevance), 3),
                    "transferable_principle": principle[:300],
                    "provenance": "image_grounded_reference_vlm_assessment",
                    "usage_contract": "transfer relation only; never copy coordinates or completed form",
                })
                if len(reference_relation_priors) >= 8:
                    break
            if len(reference_relation_priors) >= 8:
                break
        for item in reversed(rows):
            if item.get("stage") != "final_book_vlm" or item.get("final_book_vlm_hard_pass"):
                continue
            edit_intents = []
            for edit in item.get("geometry_edits") or ():
                if not isinstance(edit, dict):
                    continue
                intent = {
                    key: deepcopy(edit.get(key))
                    for key in (
                        "operation", "node_kind", "operator", "parameter_name",
                        "numeric_value", "string_value", "vector_value", "semantic_role",
                    )
                    if edit.get(key) not in (None, "", [], 0.0)
                }
                if intent:
                    edit_intents.append(intent)
            if not edit_intents:
                continue
            repair = {
                "book_principle_id": str(item.get("book_principle_id") or ""),
                "book_scope": str(item.get("book_scope") or ""),
                "critic_actions": list(item.get("critic_actions") or ()),
                "edit_intents": edit_intents[:6],
                "node_ids_removed": True,
                "application_contract": (
                    "retarget relation and parameter intent to a new AST; validate, compile, render, "
                    "and re-run every hard gate"
                ),
            }
            fingerprint = json.dumps(repair, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            if fingerprint in seen_repairs:
                continue
            seen_repairs.add(fingerprint)
            transferable_repairs.append(repair)
            if len(transferable_repairs) >= 8:
                break
        return {
            "schema_version": "arr.maas.geometry_author_context.v1",
            "source_seed": str(source_seed),
            "program_slug": str(program_slug),
            "program_aliases": sorted(program_keys),
            "observation_count": len(rows),
            "successful_genotype_priors": [
                {
                    "program_hash": program_hash,
                    "base_seed": str((program_nodes.get(program_hash) or {}).get("base_seed") or ""),
                    "operator_path": list((program_nodes.get(program_hash) or {}).get("operator_path") or ()),
                    "intent_tags": list((program_nodes.get(program_hash) or {}).get("intent_tags") or ()),
                    "program_hard_pass_count": sum(
                        bool(item.get("program_hard_pass")) for item in grouped[program_hash]
                    ),
                    "combined_hard_pass_count": sum(
                        bool(item.get("combined_hard_pass")) for item in grouped[program_hash]
                    ),
                    "visually_verified_projection_count": sum(
                        bool(item.get("final_book_vlm_hard_pass")) for item in grouped[program_hash]
                    ),
                }
                for program_hash in ranked_hashes[: max(1, int(limit))]
            ],
            "common_authored_body_failures": [
                {"gate": gate, "count": count}
                for gate, count in body_failures.most_common(8)
            ],
            "conditional_book_projection_failures": [
                {
                    "gate": gate,
                    "count": count,
                    "attribution": "book_projection_context_not_global_author_failure",
                }
                for gate, count in projection_failures.most_common(8)
            ],
            "reference_relation_priors": reference_relation_priors,
            "transferable_projection_repair_priors": transferable_repairs,
            "portfolio_visual_feedback": [
                {
                    "portfolio_vlm_hard_pass": bool(item.get("portfolio_vlm_hard_pass")),
                    "candidate_count": int(item.get("candidate_count") or 0),
                    "visible_family_count": int(item.get("visible_family_count") or 0),
                    "dominant_family_share": float(item.get("dominant_family_share") or 0.0),
                    "failed_gates": list(item.get("failed_portfolio_vlm_gates") or ()),
                    "repeated_family_groups": deepcopy(item.get("repeated_family_groups") or []),
                    "required_next_relations": list(item.get("required_next_relations") or ()),
                    "required_geometry_families": list(item.get("required_geometry_families") or ()),
                    "attribution": "final_sibling_board_not_individual_candidate",
                }
                for item in portfolio_rows[-3:]
            ],
            "usage_contract": (
                "author a new bounded typed AST; reuse successful relations as priors, "
                "never copy a completed form and never bypass current hard gates"
            ),
        }

    def _descendant_program_hashes(
        self,
        program_hash: str,
        *,
        maximum_depth: int,
    ) -> tuple[str, ...]:
        """Follow validated VLM revision edges for bounded causal memory."""
        frontier = [(_stable_id("geometry_program", str(program_hash)), 0)]
        seen_nodes = {frontier[0][0]}
        descendants: list[str] = []
        while frontier:
            node_id, depth = frontier.pop(0)
            if depth >= max(0, int(maximum_depth)):
                continue
            for edge in self.edges.values():
                if edge.get("source") != node_id or edge.get("kind") != "vlm_revised_to":
                    continue
                target_id = str(edge.get("target") or "")
                if not target_id or target_id in seen_nodes:
                    continue
                seen_nodes.add(target_id)
                target = self.nodes.get(target_id) or {}
                if target.get("kind") != "geometry_program":
                    continue
                identity = str(target.get("identity") or "")
                if identity:
                    descendants.append(identity)
                frontier.append((target_id, depth + 1))
        return tuple(descendants)

    def observe_vlm_loop(
        self,
        *,
        program_slug: str,
        source_seed: str,
        trace: dict[str, Any],
    ) -> None:
        """Persist VLM reviews, typed edits, references, and revision proof."""
        for generation in trace.get("generations") or ():
            if not isinstance(generation, dict):
                continue
            for record in generation.get("records") or ():
                if not isinstance(record, dict) or record.get("status") not in {
                    "critic_reviewed", "critic_program_fit_rejected",
                }:
                    continue
                program_hash = str(record.get("program_hash") or "")
                geometry_hash = str(record.get("geometry_hash") or "")
                response_id = str(record.get("critic_response_id") or "")
                proof = record.get("revision_proof") if isinstance(record.get("revision_proof"), dict) else {}
                causal = record.get("vlm_causal_context") if isinstance(record.get("vlm_causal_context"), dict) else {}
                references = causal.get("reference_matches") if isinstance(causal.get("reference_matches"), list) else []
                reference_assessments = (
                    record.get("reference_assessments")
                    if isinstance(record.get("reference_assessments"), list)
                    else causal.get("reference_assessments")
                    if isinstance(causal.get("reference_assessments"), list)
                    else []
                )
                assessments_by_source = {
                    str(item.get("source_id") or ""): item
                    for item in reference_assessments
                    if isinstance(item, dict) and item.get("source_id")
                }
                program_context = causal.get("program_context") if isinstance(causal.get("program_context"), dict) else {}
                memory = causal.get("outcome_memory") if isinstance(causal.get("outcome_memory"), dict) else {}
                observation_key = "|".join((
                    "vlm_critic", str(program_slug), str(source_seed), program_hash,
                    geometry_hash, response_id, str(record.get("generation") or 0),
                ))
                observation_id = _stable_id("observation", observation_key)
                observation = {
                    "id": observation_id,
                    "stage": "vlm_critic",
                    "program_slug": str(program_slug),
                    "source_seed": str(source_seed),
                    "program_hash": program_hash,
                    "geometry_hash": geometry_hash,
                    "critic_model": str(record.get("critic_model") or ""),
                    "critic_response_id": response_id,
                    "critic_score": float(record.get("critic_score") or 0.0),
                    "program_fit_hard_pass": bool(record.get("program_fit_hard_pass", True)),
                    "program_appropriateness": float(record.get("program_appropriateness") or 0.0),
                    "section_program_fit": float(record.get("section_program_fit") or 0.0),
                    "critic_actions": [str(item) for item in record.get("critic_actions") or ()],
                    "geometry_edits": deepcopy(record.get("geometry_edits") or []),
                    "mutation_status": str(record.get("mutation_status") or ""),
                    "geometry_changed": bool(proof.get("geometry_changed")),
                    "child_program_hash": str(proof.get("child_program_hash") or ""),
                    "child_geometry_hash": str(proof.get("child_geometry_hash") or ""),
                    "reference_ids": [
                        str(item.get("source_id") or item.get("title") or "")
                        for item in references if isinstance(item, dict)
                    ],
                    "memory_observation_count": int(memory.get("observation_count") or 0),
                    "program_context": deepcopy(program_context),
                    "reference_assessments": deepcopy(reference_assessments),
                }
                self._upsert_observation(observation)
                program_node = self._upsert_node("geometry_program", program_hash, {
                    "name": str(record.get("program") or ""),
                })
                critic_identity = response_id or observation_id
                critic_node = self._upsert_node("vlm_critic", critic_identity, {
                    "model": observation["critic_model"],
                    "score": observation["critic_score"],
                    "actions": observation["critic_actions"],
                    "program_fit_hard_pass": observation["program_fit_hard_pass"],
                    "program_appropriateness": observation["program_appropriateness"],
                    "section_program_fit": observation["section_program_fit"],
                })
                program_identity = str(program_context.get("program_id") or program_slug)
                program_node_context = self._upsert_node("program_contract", program_identity, {
                    "design_intent": str(program_context.get("design_intent") or ""),
                    "semantic_invariants": deepcopy(program_context.get("semantic_invariants") or []),
                })
                outcome_node = self._upsert_node("outcome", observation_id, observation)
                self._upsert_edge(program_node, critic_node, "reviewed_by")
                self._upsert_edge(program_node_context, critic_node, "constrains_review")
                self._upsert_edge(critic_node, outcome_node, "proposed_typed_edit")
                if observation["child_program_hash"]:
                    child_node = self._upsert_node("geometry_program", observation["child_program_hash"], {
                        "geometry_hash": observation["child_geometry_hash"],
                    })
                    self._upsert_edge(program_node, child_node, "vlm_revised_to")
                for item in references:
                    if not isinstance(item, dict):
                        continue
                    identity = str(item.get("source_id") or item.get("title") or "")
                    if not identity:
                        continue
                    reference_node = self._upsert_node("reference", identity, {
                        "source": str(item.get("source") or ""),
                        "title": str(item.get("title") or ""),
                        "selection_role": str(item.get("selection_role") or ""),
                        "matched_tags": list(item.get("matched_tags") or ()),
                        "program_id": str(item.get("program_id") or ""),
                        "program_match_tier": str(item.get("program_match_tier") or ""),
                        "program_matched_terms": list(item.get("program_matched_terms") or ()),
                        "reference_collection": str(item.get("reference_collection") or ""),
                        "program_relevance_score": float(item.get("program_relevance_score") or 0.0),
                        "vlm_assessment": deepcopy(assessments_by_source.get(identity) or {}),
                    })
                    self._upsert_edge(reference_node, critic_node, "informed")
                    self._upsert_edge(reference_node, program_node_context, "evidence_for_program")

    def observe_executed_mass_vlm_audit(
        self,
        *,
        program_slug: str,
        source_seed: str,
        program_hash: str,
        geometry_hash: str,
        preview_path: str,
        audit: dict[str, Any],
    ) -> None:
        """Record a post-run critic of one materialized MASS and its exact images.

        Retrieval alone never creates a visual-reference edge. Only images listed
        in ``vlm_image_inputs`` are attached, so the graph cannot imply that the
        critic saw an ArchDaily image that was merely retrieved.
        """

        response_id = str(audit.get("response_id") or "")
        identity = response_id or hashlib.sha256(
            "|".join((str(program_slug), str(program_hash), str(geometry_hash))).encode("utf-8")
        ).hexdigest()
        observation_id = _stable_id("observation", f"executed_mass_vlm|{identity}")
        image_inputs = audit.get("vlm_image_inputs")
        image_inputs = image_inputs if isinstance(image_inputs, dict) else {}
        candidate_input = image_inputs.get("candidate")
        candidate_input = candidate_input if isinstance(candidate_input, dict) else {}
        reference_inputs = [
            item for item in image_inputs.get("references") or ()
            if isinstance(item, dict) and item.get("used_by_vlm")
        ]
        scores = audit.get("concept_scores")
        scores = deepcopy(scores) if isinstance(scores, dict) else {}
        score_values = [
            float(value) for value in scores.values()
            if isinstance(value, (int, float))
        ]
        critic_score = float(audit.get("critic_score") or (
            sum(score_values) / len(score_values) if score_values else 0.0
        ))
        critic_hard_pass = bool(
            audit.get("hard_pass")
            if "hard_pass" in audit
            else audit.get("program_fit_hard_pass", True)
        )
        observation = {
            "id": observation_id,
            "stage": "executed_mass_vlm",
            "program_slug": str(program_slug),
            "source_seed": str(source_seed),
            "program_hash": str(program_hash),
            "geometry_hash": str(geometry_hash),
            "critic_model": str(audit.get("model") or ""),
            "critic_response_id": response_id,
            "critic_score": round(critic_score, 4),
            "hard_pass": critic_hard_pass,
            "program_fit_hard_pass": bool(audit.get("program_fit_hard_pass", True)),
            "critic_actions": [str(item) for item in audit.get("critic_actions") or ()],
            "concept_scores": scores,
            "candidate_image_sha256": str(candidate_input.get("sha256") or ""),
            "reference_ids": [
                str(item.get("source_id") or item.get("input_id") or "")
                for item in reference_inputs
            ],
            "reference_count": len(reference_inputs),
            "selected": False,
        }
        self._upsert_observation(observation)
        program_node = self._upsert_node("geometry_program", str(program_hash), {
            "source_seed": str(source_seed),
        })
        geometry_node = self._upsert_node("compiled_geometry", str(geometry_hash), {})
        render_identity = str(candidate_input.get("sha256") or preview_path or geometry_hash)
        render_node = self._upsert_node("render_artifact", render_identity, {
            "local_path": str(preview_path),
            "sha256": str(candidate_input.get("sha256") or ""),
            "used_by_vlm": bool(candidate_input.get("used_by_vlm")),
        })
        critic_node = self._upsert_node("vlm_critic", identity, {
            "review_stage": "post_run_individual_mass",
            "model": observation["critic_model"],
            "response_id": response_id,
            "hard_pass": observation["hard_pass"],
            "program_fit_hard_pass": observation["program_fit_hard_pass"],
            "critic_score": observation["critic_score"],
            "critic_actions": observation["critic_actions"],
            "concept_scores": scores,
        })
        outcome_node = self._upsert_node("outcome", observation_id, observation)
        self._upsert_edge(program_node, geometry_node, "compiled_to")
        self._upsert_edge(geometry_node, render_node, "rendered_as")
        self._upsert_edge(render_node, critic_node, "visual_input_to")
        self._upsert_edge(critic_node, outcome_node, "judged")
        for item in reference_inputs:
            reference_identity = str(item.get("source_id") or item.get("input_id") or "")
            if not reference_identity:
                continue
            reference_node = self._upsert_node("reference", reference_identity, {
                "title": str(item.get("title") or ""),
                "local_path": str(item.get("local_path") or ""),
                "preview_url": str(item.get("preview_url") or ""),
                "sha256": str(item.get("sha256") or ""),
                "input_order": int(item.get("input_order") or 0),
                "used_by_vlm": True,
            })
            self._upsert_edge(reference_node, critic_node, "visual_input_to")

    def observe_design_memory_events(
        self,
        events: Iterable[dict[str, Any]],
    ) -> None:
        """Persist portable event facts while leaving referenced image bytes on disk."""

        from backend.app.modules.design.generation.maas.design_memory.reference_events import mutable_event

        for immutable_event in events:
            event = mutable_event(immutable_event)
            event_type = str(event.get("event_type") or "")
            event_id = str(event.get("event_id") or "")
            if not event_type or not event_id:
                raise ValueError("design-memory event requires type and stable ID")
            event_node = self._upsert_node(
                "design_memory_event",
                event_id,
                event,
            )
            program_hash = str(event.get("program_hash") or "")
            geometry_hash = str(event.get("geometry_hash") or "")
            if program_hash:
                program_node = self._upsert_node(
                    "geometry_program",
                    program_hash,
                    {},
                )
                self._upsert_edge(program_node, event_node, "recorded_in")
            if geometry_hash:
                geometry_node = self._upsert_node(
                    "compiled_geometry",
                    geometry_hash,
                    {},
                )
                self._upsert_edge(geometry_node, event_node, "recorded_in")
            if event_type in {
                "reference_retrieved",
                "reference_submitted_to_vlm",
            }:
                source_id = str(event.get("source_id") or "")
                if not source_id:
                    continue
                reference_node = self._upsert_node("reference", source_id, {
                    key: deepcopy(event.get(key))
                    for key in (
                        "title",
                        "local_path",
                        "image_uri",
                        "sha256",
                        "source_url",
                        "reference_collection",
                        "rights",
                        "provenance",
                    )
                })
                relation = (
                    "submitted_to_vlm"
                    if event_type == "reference_submitted_to_vlm"
                    else "retrieved_as_reference"
                )
                self._upsert_edge(reference_node, event_node, relation)
            elif event_type == "human_pairwise_choice":
                for role in ("preferred", "rejected"):
                    candidate_id = str(
                        event.get(f"{role}_candidate_id") or ""
                    )
                    geometry_identity = str(
                        event.get(f"{role}_geometry_hash") or ""
                    )
                    if not candidate_id:
                        continue
                    candidate_node = self._upsert_node(
                        "creative_mass_candidate",
                        candidate_id,
                        {"geometry_hash": geometry_identity},
                    )
                    self._upsert_edge(
                        candidate_node,
                        event_node,
                        f"{role}_in_choice",
                    )

    def save(self) -> dict[str, Any]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = self.to_dict()
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        return payload

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "pnu": self.pnu,
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "observation_count": len(self.observations),
            "nodes": sorted(self.nodes.values(), key=lambda item: item["id"]),
            "edges": sorted(self.edges.values(), key=lambda item: item["id"]),
            "observations": sorted(self.observations, key=lambda item: item["id"]),
            "interactive_contract": {
                "node_identity": "stable id",
                "editable_node_kinds": ["geometry_program", "geometry_genotype"],
                "typed_edit_source_node_kinds": ["geometry_program", "projected_geometry_program"],
                "projected_program_ast_path": "node.attributes.typed_ast",
                "mutation_is_append_only": True,
                "outcome_is_observation_only": True,
                "agent_query": "retrieve successful genotype neighborhood before proposing bounded mutations",
                "causal_read_order": "reference -> program_contract -> vlm_critic -> typed_edit -> child_geometry_program -> hard_gate_outcome",
                "context_nodes_are_not_geometry_edit_targets": True,
                "render_artifact_role": "human_or_vlm_observation_only",
                "render_artifact_binding": "projected_program_hash + geometry_hash + board_png + crop_box",
            },
        }

    def mirror_to_neo4j(self) -> dict[str, Any]:
        from backend.app.modules.design.generation.maas.design_memory.neo4j_adapter import DesignMemoryNeo4jAdapter

        return DesignMemoryNeo4jAdapter().mirror(self)

    def _upsert_node(self, kind: str, identity: str, attributes: dict[str, Any]) -> str:
        node_id = _stable_id(kind, identity)
        record = self.nodes.setdefault(node_id, {"id": node_id, "kind": kind, "identity": identity, "attributes": {}})
        record["attributes"].update(deepcopy(attributes))
        return node_id

    def _ensure_observation_indices(self) -> None:
        if self._indexed_observation_count == len(self.observations):
            return
        self._observation_index = {
            str(item.get("id") or ""): item
            for item in self.observations
            if item.get("id")
        }
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        for item in self.observations:
            grouped[(str(item.get("source_seed") or ""), str(item.get("program_hash") or ""))].append(item)
        self._genotype_index = dict(grouped)
        self._indexed_observation_count = len(self.observations)
        self._observation_sequence_max = max(
            (int(item.get("observation_sequence") or 0) for item in self.observations),
            default=0,
        )

    def _upsert_observation(self, observation: dict[str, Any]) -> None:
        self._ensure_observation_indices()
        self._observation_sequence_max += 1
        observation = {
            **observation,
            "observation_sequence": self._observation_sequence_max,
        }
        observation_id = str(observation["id"])
        existing = self._observation_index.get(observation_id)
        if existing is not None:
            existing.update(observation)
            return
        self.observations.append(observation)
        self._observation_index[observation_id] = observation
        key = (str(observation.get("source_seed") or ""), str(observation.get("program_hash") or ""))
        self._genotype_index.setdefault(key, []).append(observation)
        self._indexed_observation_count = len(self.observations)

    def _set_observation_selected(
        self,
        observation: dict[str, Any],
        selected: bool,
    ) -> None:
        observation["selected"] = bool(selected)
        outcome_node = self.nodes.get(
            _stable_id("outcome", str(observation.get("id") or ""))
        )
        if outcome_node is not None:
            outcome_node.setdefault("attributes", {})["selected"] = bool(selected)

    def _observations_for_genotype(self, source_seed: str, program_hash: str) -> list[dict[str, Any]]:
        self._ensure_observation_indices()
        return self._genotype_index.get((str(source_seed), str(program_hash)), [])

    def _upsert_edge(self, source: str, target: str, kind: str) -> str:
        edge_id = _stable_id("edge", f"{source}|{kind}|{target}")
        self.edges[edge_id] = {"id": edge_id, "source": source, "target": target, "kind": kind}
        return edge_id


def _seed_family(candidate: Any) -> str:
    return str(candidate.sequence.name).split("__book_", 1)[0].split("__search_", 1)[0]


def _candidate_key(candidate: Any) -> tuple[str, str, str]:
    bridge = candidate.source.metadata.get("geometry_program_bridge_evidence") or {}
    return (
        str(candidate.sequence.name),
        str(candidate.principle_id),
        str(bridge.get("geometry_hash") or ""),
    )


__all__ = ["GeometryOutcomeGraph", "SCHEMA_VERSION"]
