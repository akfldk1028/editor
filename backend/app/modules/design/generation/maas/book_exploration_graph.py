"""BOOK-faithful exploration graph used by agents and the frontend.

The graph is deliberately not a Cartesian product.  Every execution edge is
an explicit transition supported by the BOOK corpus or by a named downstream
contract.  Source pages and implementation helpers are represented as
evidence/detail edges, so they can never silently become design actions.
"""

from __future__ import annotations

from hashlib import sha256
from typing import Any, Iterable

from backend.app.modules.design.generation.maas.book_language.base_volume_contract import BOOK_BASE_VOLUME_SPECS
from backend.app.modules.design.generation.maas.book_language.capacity_alternatives import capacity_alternative_catalog
from backend.app.modules.design.generation.maas.book_language.catalog import load_book_language_catalog
from backend.app.modules.design.generation.maas.book_language.source_bundle import load_book_source_bundle
from backend.app.modules.design.generation.maas.book_language.registry import build_book_language_registry
from backend.app.modules.design.generation.maas.geometry_language.base_seeds import BASE_SEED_SPECS
from backend.app.modules.design.generation.maas.geometry_language.affine_matrix import identity_matrix4, matrix4_to_lists, scale_matrix4
from backend.app.modules.design.generation.maas.geometry_language.typology_priors import TYPOLOGY_PRIORS
from backend.app.modules.design.generation.maas.program_massing.profiles import load_program_profiles


SCHEMA_VERSION = "arr.maas.book_exploration_graph.v1"

EXECUTION_STAGE_ORDER = (
    "base_model",
    "derived_volume",
    "orientation",
    "operation_family",
    "cardinality",
    "operation",
    "variation",
    "book_extension",
    "program",
    "capacity",
    "hard_gate",
    "render",
    "vlm",
    "portfolio_memory",
)

_ORIENTATIONS = (
    ("long_axis", "Long axis"),
    ("short_axis", "Short axis"),
    ("vertical", "Vertical"),
)

_HARD_GATES = (
    ("connected_solid", "Connected solid"),
    ("program_fit", "Program fit"),
    ("capacity_target", "FAR alternative target"),
    ("legal", "Legal envelope"),
    ("geometry_retention", "Geometry retention"),
    ("parking", "Parking"),
)


def _node(
    node_id: str,
    kind: str,
    stage: str,
    label: str,
    *,
    authority: str,
    evidence_ids: Iterable[str] = (),
    visible: bool = True,
    **attributes: Any,
) -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": kind,
        "stage": stage,
        "label": label,
        "authority": authority,
        "evidence_ids": list(evidence_ids),
        "visible": bool(visible),
        "attributes": attributes,
    }


def _edge(
    source: str,
    target: str,
    kind: str,
    *,
    scope: str = "execution",
    authority: str = "book",
) -> dict[str, Any]:
    raw = f"{scope}:{kind}:{source}:{target}"
    return {
        "id": f"edge:{sha256(raw.encode('utf-8')).hexdigest()[:20]}",
        "source": source,
        "target": target,
        "kind": kind,
        "scope": scope,
        "authority": authority,
    }


def _source_documents() -> list[dict[str, Any]]:
    bundle = load_book_source_bundle()
    return [{
        "id": f"book:document:{item['sha256'][:16]}",
        "label": item["filename"],
        "path": item["path"],
        "sha256": item["sha256"],
        "role": item["role"],
        "purpose": item["purpose"],
        "line_count": item["line_count"],
    } for item in bundle["documents"]]


def _program_label(profile: dict[str, Any]) -> str:
    aliases = [str(value) for value in profile.get("aliases") or ()]
    korean = next((value for value in aliases if any("가" <= char <= "힣" for char in value)), "")
    return korean or str(profile.get("id") or "generic").replace("_", " ").title()


def build_book_exploration_graph() -> dict[str, Any]:
    registry = build_book_language_registry()
    catalog = load_book_language_catalog()
    catalog_by_english = {
        str(item["english"]).casefold(): item for item in catalog["entries"]
    }
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    documents = _source_documents()
    document_ids = [item["id"] for item in documents]
    for item in documents:
        nodes.append(_node(
            item["id"], "source_document", "evidence", item["label"],
            authority="book", visible=False, path=item["path"], sha256=item["sha256"],
            source_role=item["role"], purpose=item["purpose"], line_count=item["line_count"],
        ))

    # Interpretive and diagram vocabulary belongs to the BOOK map, but it is
    # not silently promoted to an executable mass operation.
    for entry in catalog["entries"]:
        if entry["layer"] not in {"process", "diagram", "aggregation", "implementation"}:
            continue
        node_id = str(entry["catalog_id"])
        stage = {
            "process": "book_process_language",
            "diagram": "book_geometry_language",
            "aggregation": "aggregation_method",
            "implementation": "implementation_language",
        }[str(entry["layer"])]
        page_ids = [f"book:page:{int(page):02d}" for page in entry["scan_pages"]]
        nodes.append(_node(
            node_id,
            f"book_{str(entry['layer']).replace('-', '_')}",
            stage,
            str(entry["english"]),
            authority="book",
            evidence_ids=page_ids,
            visible=False,
            catalog_entry_id=str(entry["id"]),
            catalog_layer=str(entry["layer"]),
            catalog_stage=stage,
            korean=str(entry["korean"]),
            category=str(entry["category"]),
            scope_label=str(entry["scope"]),
            scan=str(entry["scan"]),
            book_pages=str(entry["book_pages"]),
            meaning=str(entry["meaning"]),
        ))

    for page in registry["pages"]:
        page_number = int(page["page"])
        page_id = f"book:page:{page_number:02d}"
        nodes.append(_node(
            page_id, "source_page", "evidence", f"BOOK scan {page_number:02d}",
            authority="book", visible=False, evidence_ids=document_ids,
            source_path=page.get("source_path"), sha256=page.get("sha256"),
            section=page.get("section"), ocr_status=page.get("ocr_status"),
            vlm_audit={"status": "not_run", "cache_policy": "image_hash_and_prompt_version"},
        ))
        for document_id in document_ids:
            edges.append(_edge(document_id, page_id, "contains", scope="evidence"))

    unit_spec = next(spec for spec in BOOK_BASE_VOLUME_SPECS if spec.label == "1/1")
    unit_box_id = "book:base-model:1-1"
    base_model_ids = [unit_box_id]
    nodes.append(_node(
        unit_box_id, "base_model", "base_model", "1/1 UnitBox",
        authority="book", evidence_ids=["book:page:03"], fraction=unit_spec.fraction,
        topology=unit_spec.topology,
        cells=[{"minimum": list(cell.minimum), "maximum": list(cell.maximum)} for cell in unit_spec.cells],
        matrix4=matrix4_to_lists(identity_matrix4()),
        canonical_base_authority=True,
        is_exploration_root=True,
        catalog_layer="diagram", catalog_stage="base_model",
    ))
    edges.append(_edge("book:page:03", unit_box_id, "documents", scope="evidence"))

    derived_volume_ids: list[str] = []
    scope_node_ids = [unit_box_id]
    for spec in BOOK_BASE_VOLUME_SPECS:
        if spec.label == "1/1":
            continue
        derived_id = f"book:derived-volume:{spec.label.replace('/', '-')}"
        derived_volume_ids.append(derived_id)
        scope_node_ids.append(derived_id)
        nodes.append(_node(
            derived_id, "derived_volume", "derived_volume", f"{spec.label} Derived Volume",
            authority="book", evidence_ids=["book:page:03"], fraction=spec.fraction,
            topology=spec.topology,
            cells=[{"minimum": list(cell.minimum), "maximum": list(cell.maximum)} for cell in spec.cells],
            derivation_operator="book_base_volume",
            canonical_parent_id=unit_box_id,
            is_exploration_root=False,
            catalog_layer="diagram", catalog_stage="derived_volume",
        ))
        edges.append(_edge(unit_box_id, derived_id, "derives_volume"))
        edges.append(_edge("book:page:03", derived_id, "documents", scope="evidence"))

    orientation_ids = []
    for value, label in _ORIENTATIONS:
        node_id = f"book:orientation:{value}"
        orientation_ids.append(node_id)
        nodes.append(_node(node_id, "orientation", "orientation", label, authority="book"))
    for scope_id in scope_node_ids:
        for orientation_id in orientation_ids:
            edges.append(_edge(scope_id, orientation_id, "orients_as"))

    cardinality_ids: dict[tuple[str, str], str] = {}
    for family in ("add", "displace", "subtract"):
        family_id = f"book:operation-family:{family}"
        nodes.append(_node(
            family_id, "operation_family", "operation_family", family.title(), authority="book",
        ))
        for orientation_id in orientation_ids:
            edges.append(_edge(orientation_id, family_id, "selects_family"))
        for cardinality in ("single", "multiple"):
            cardinality_id = f"book:cardinality:{family}:{cardinality}"
            cardinality_ids[(family, cardinality)] = cardinality_id
            nodes.append(_node(
                cardinality_id, "cardinality", "cardinality",
                f"{family.title()} / {cardinality.title()}", authority="book",
            ))
            edges.append(_edge(family_id, cardinality_id, "selects_cardinality"))

    operation_ids: list[str] = []
    variation_ids: list[str] = []
    for principle in registry["principles"]:
        if principle["kind"] != "base_operative":
            continue
        operation_id = str(principle["principle_id"])
        operation_ids.append(operation_id)
        page_ids = [f"book:page:{int(page):02d}" for page in principle.get("page_refs") or ()]
        nodes.append(_node(
            operation_id, "operation", "operation", str(principle["label"]).title(),
            authority="book", evidence_ids=page_ids,
            transformation=principle["transformation"], cardinality=principle["cardinality"],
            execution_verbs=principle["execution_verbs"], semantics=principle.get("semantics") or {},
            catalog_entry_id=str((catalog_by_english.get(str(principle["label"]).casefold()) or {}).get("id") or ""),
            catalog_layer="operation", catalog_stage="operation",
        ))
        edges.append(_edge(
            cardinality_ids[(principle["transformation"], principle["cardinality"])],
            operation_id, "permits_operation",
        ))
        for page_id in page_ids:
            edges.append(_edge(page_id, operation_id, "documents", scope="evidence"))

        variation_id = f"book:variation-field:{principle['label']}"
        variation_ids.append(variation_id)
        nodes.append(_node(
            variation_id, "variation_field", "variation",
            f"{str(principle['label']).title()} variations", authority="book",
            evidence_ids=page_ids, parameter_contract=principle.get("source_diagram_contract") or {},
            executable_mapping_authority="engineered",
        ))
        edges.append(_edge(operation_id, variation_id, "varies_as"))

    extension_ids: list[str] = []
    for principle in registry["principles"]:
        kind = str(principle["kind"])
        if kind not in {"combination", "aggregation"}:
            continue
        node_id = str(principle["principle_id"])
        extension_ids.append(node_id)
        page_ids = [f"book:page:{int(page):02d}" for page in principle.get("page_refs") or ()]
        nodes.append(_node(
            node_id, kind, "book_extension", str(principle["label"]),
            authority="book", evidence_ids=page_ids,
            execution_verbs=principle.get("execution_verbs") or (),
            aggregation_methods=principle.get("aggregation_methods") or (),
            catalog_entry_id=str((catalog_by_english.get(str(principle["label"]).casefold()) or {}).get("id") or ""),
            catalog_layer="combination" if kind == "combination" else "aggregation-expression",
            catalog_stage="combination" if kind == "combination" else "aggregation_expression",
        ))
        first_verb = str((principle.get("execution_verbs") or [""])[0])
        parent_id = f"book:variation-field:{first_verb}"
        if parent_id in variation_ids:
            edges.append(_edge(parent_id, node_id, "extends_with"))
        for page_id in page_ids:
            edges.append(_edge(page_id, node_id, "documents", scope="evidence"))

    for case in registry["case_studies"]:
        case_id = str(case["principle_id"])
        page_ids = [f"book:page:{int(page):02d}" for page in case.get("page_refs") or ()]
        nodes.append(_node(
            case_id, "case_study", "evidence", str(case["label"]), authority="book",
            evidence_ids=page_ids, visible=False, project=case.get("project"),
            implementation_elements=case.get("implementation_elements") or (),
        ))
        for verb in case.get("verbs") or ():
            operation_id = f"book:operative:{verb}"
            if operation_id in operation_ids:
                edges.append(_edge(case_id, operation_id, "demonstrates", scope="evidence"))
        for page_id in page_ids:
            edges.append(_edge(page_id, case_id, "documents", scope="evidence"))

        for element in case.get("implementation_elements") or ():
            entry = next((
                item for item in catalog["entries"]
                if str(item["english"]).casefold() == str(element).casefold()
                and str(item["category"]) == str(case.get("project") or "")
            ), None)
            if not entry:
                continue
            implementation_id = str(entry["catalog_id"])
            edges.append(_edge(case_id, implementation_id, "describes", scope="evidence"))
            for verb in case.get("verbs") or ():
                operation_id = f"book:operative:{verb}"
                if operation_id in operation_ids:
                    edges.append(_edge(operation_id, implementation_id, "implemented_as", scope="evidence"))

    # Reify the relationships explicitly printed by BOOK. This makes Taper,
    # for example, connect to Taper+Taper, Embed+Taper, Taper+Bend,
    # Array|Taper and Tapered Volumes without inventing a relation.
    aggregation_method_ids = {
        str(item["english"]).casefold(): str(item["catalog_id"])
        for item in catalog["entries"] if item["layer"] == "aggregation"
    }
    for principle in registry["principles"]:
        if principle["kind"] not in {"combination", "aggregation"}:
            continue
        target_id = str(principle["principle_id"])
        for verb in principle.get("execution_verbs") or ():
            operation_id = f"book:operative:{verb}"
            if operation_id in operation_ids:
                edges.append(_edge(operation_id, target_id, "participates_in", scope="evidence"))
            method_id = aggregation_method_ids.get(str(verb).casefold())
            if method_id:
                edges.append(_edge(method_id, target_id, "organizes", scope="evidence"))

    # Existing seed/chassis machinery remains available, but only as an
    # expandable implementation detail below a selected BOOK Base Model.
    for seed in BASE_SEED_SPECS:
        seed_id = f"engineered:host-proportion:{seed.seed_id}"
        nodes.append(_node(
            seed_id, "host_proportion", "implementation_detail", seed.label,
            authority="engineered", visible=False,
            normalized_scale=list(seed.normalized_scale),
            matrix4=matrix4_to_lists(scale_matrix4(seed.normalized_scale)),
            architectural_use=seed.architectural_use,
        ))
        edges.append(_edge(unit_box_id, seed_id, "derives_host_proportion", scope="detail", authority="engineered"))
    for chassis in TYPOLOGY_PRIORS:
        chassis_id = f"engineered:relation-scaffold:{chassis.typology_id}"
        nodes.append(_node(
            chassis_id, "relation_scaffold", "implementation_detail", chassis.label,
            authority="engineered", visible=False,
            relation_class=chassis.relation_class, primary_operator=chassis.primary_operator,
        ))
        for seed_id in chassis.preferred_base_seeds:
            edges.append(_edge(
                f"engineered:host-proportion:{seed_id}", chassis_id,
                "scaffolded_by", scope="detail", authority="engineered",
            ))

    program_ids = []
    for profile in load_program_profiles():
        raw_id = str(profile.get("id") or "generic")
        node_id = f"program:{raw_id}"
        program_ids.append(node_id)
        nodes.append(_node(
            node_id, "program_projection", "program", _program_label(profile),
            authority="engineered", design_intent=str(profile.get("design_intent") or ""),
        ))
    form_result_ids = [*variation_ids, *extension_ids]
    for result_id in form_result_ids:
        for program_id in program_ids:
            edges.append(_edge(
                result_id, program_id, "projects_program",
                authority="engineered",
            ))

    experimental_id = "experimental:typed-extension"
    nodes.append(_node(
        experimental_id, "experimental_gateway", "book_extension", "Typed experimental extension",
        authority="experimental", allowed_source="validated_book_result",
        allowed_action="supported verbs and relations only",
    ))
    for extension_id in extension_ids:
        edges.append(_edge(
            extension_id, experimental_id, "may_extend_to",
            authority="experimental",
        ))
    for program_id in program_ids:
        edges.append(_edge(
            experimental_id, program_id, "projects_program",
            authority="experimental",
        ))

    capacity_ids = []
    for item in capacity_alternative_catalog():
        raw_id = str(item.get("id") or item.get("slug") or item.get("label") or "capacity")
        node_id = f"capacity:{raw_id}"
        capacity_ids.append(node_id)
        nodes.append(_node(
            node_id, "capacity_alternative", "capacity", str(item.get("label") or raw_id),
            authority="engineered", **{key: value for key, value in item.items() if key not in {"id", "label"}},
        ))
    for program_id in program_ids:
        for capacity_id in capacity_ids:
            edges.append(_edge(program_id, capacity_id, "fits_capacity", authority="engineered"))

    gate_ids = []
    for gate, label in _HARD_GATES:
        gate_id = f"gate:{gate}"
        gate_ids.append(gate_id)
        nodes.append(_node(gate_id, "hard_gate", "hard_gate", label, authority="engineered"))
    for capacity_id in capacity_ids:
        edges.append(_edge(capacity_id, gate_ids[0], "evaluated_by", authority="engineered"))
    for source, target in zip(gate_ids, gate_ids[1:]):
        edges.append(_edge(source, target, "then_evaluated_by", authority="engineered"))

    tail_nodes = (
        ("render:mass-png", "render_artifact", "render", "MASS PNG", "rendered_as"),
        ("vlm:geometry-critic", "vlm_review", "vlm", "Geometry critic", "reviewed_by"),
        ("vlm:typed-revision", "typed_revision", "vlm", "Typed repair", "revises_to"),
        ("vlm:portfolio-critic", "vlm_review", "vlm", "Portfolio critic", "reviewed_by"),
        ("memory:selected-portfolio", "portfolio_memory", "portfolio_memory", "Selected portfolio + memory", "selected_as"),
    )
    previous = gate_ids[-1]
    for node_id, kind, stage, label, edge_kind in tail_nodes:
        nodes.append(_node(node_id, kind, stage, label, authority="observed"))
        edges.append(_edge(previous, node_id, edge_kind, authority="observed"))
        previous = node_id
    for variation_id in variation_ids:
        edges.append(_edge(
            "vlm:typed-revision", variation_id, "requests_typed_repair",
            scope="feedback", authority="observed",
        ))

    execution_edges = [item for item in edges if item["scope"] in {"execution", "feedback"}]
    return {
        "schema_version": SCHEMA_VERSION,
        "graph_id": "maas_book_exploration",
        "root_node_ids": base_model_ids,
        "stage_order": list(EXECUTION_STAGE_ORDER),
        "catalog_stage_order": [
            "book_process_language", "base_model", "book_geometry_language",
            "operation", "combination", "aggregation_method",
            "aggregation_expression", "implementation_language",
        ],
        "authority_order": ["book", "engineered", "experimental", "observed"],
        "source_documents": documents,
        "nodes": nodes,
        "edges": edges,
        "counts": {
            "node_count": len(nodes),
            "edge_count": len(edges),
            "execution_edge_count": len(execution_edges),
            "base_model_count": len(base_model_ids),
            "derived_volume_count": len(derived_volume_ids),
            "operation_count": len(operation_ids),
            "combination_count": sum(item["kind"] == "combination" for item in nodes),
            "aggregation_count": sum(item["kind"] == "aggregation" for item in nodes),
            "case_study_evidence_count": sum(item["kind"] == "case_study" for item in nodes),
            "book_page_evidence_count": 69,
            "catalog_language_count": catalog["entry_count"],
            "catalog_layer_counts": catalog["layer_counts"],
        },
        "contracts": {
            "exploration_starts_at_base_model": True,
            "canonical_base_model_is_unitbox_1_1": True,
            "book_ratios_are_derived_states": True,
            "source_and_case_edges_are_not_actions": True,
            "program_is_after_book_form": True,
            "base_seed_and_chassis_are_detail_only": True,
            "frontend_must_not_synthesize_edges": True,
            "vlm_may_request_typed_repairs_only": True,
            "book_core_and_experimental_lineage_are_separate": True,
            "complete_134_entry_catalog_is_addressable": True,
            "all_four_extracted_source_documents_are_required": True,
        },
    }


__all__ = ["EXECUTION_STAGE_ORDER", "SCHEMA_VERSION", "build_book_exploration_graph"]
