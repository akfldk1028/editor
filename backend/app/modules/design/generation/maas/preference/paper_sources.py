"""Paper and code provenance for MAAS second-stage preference distillation."""

from __future__ import annotations

from typing import Any


PREFERENCE_PAPER_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "id": "shapeassembly_siggraph_asia_2020",
        "title": "ShapeAssembly: Learning to Generate Programs for 3D Shape Structure Synthesis",
        "paper_url": "https://arxiv.org/abs/2009.08026",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "typed parametric shape programs whose attachment and symmetry relations generate editable families",
        "limitation": "cuboid part assembly is not sufficient for architectural bends, profiles, cuts, or legal site adaptation",
        "method_layer": "recursive_parametric_assembly",
        "runtime_components": ["geometry_language.ast", "geometry_language.compiler", "geometry_language.programs"],
        "operator_families": ["attach", "bridge", "join_related", "linear_array", "mirror", "radial_array", "stack", "union"],
        "activation_policy": "operator_and_recursive_ast",
    },
    {
        "id": "szalinski_siggraph_2020",
        "title": "Synthesizing Structured CAD Models with Equality Saturation and Inverse Transformations",
        "paper_url": "https://arxiv.org/abs/1909.12252",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "canonical AST rewriting and equivalence-aware candidate collapse instead of retaining redundant CSG programs",
        "limitation": "semantic architectural program and visual quality objectives remain MAAS-specific",
        "method_layer": "canonical_program_normalization",
        "runtime_components": ["geometry_language.ast", "geometry_language.cost", "geometry_language.compiler"],
        "operator_families": [],
        "activation_policy": "compiler_and_structural_hash",
    },
    {
        "id": "cadfusion_2025",
        "title": "Text-to-CAD Generation Through Infusing Visual Feedback in Large Language Models",
        "paper_url": "https://arxiv.org/abs/2501.19054",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "alternate executable parametric-program learning with rendered visual feedback rather than scoring labels alone",
        "limitation": "CAD visual similarity does not encode architectural program, law, parking, or competition-board diversity",
        "method_layer": "rendered_visual_feedback",
        "runtime_components": ["geometry_language.render", "geometry_language.vlm_adapter", "preference.vlm_scorer"],
        "operator_families": [],
        "activation_policy": "evaluated_vlm_feedback",
    },
    {
        "id": "cadloop_cvprw_2026",
        "title": "CADLoop: An Equivariant-Aware Skill-Grounded Loop for CAD Data Curation",
        "paper_url": "https://openaccess.thecvf.com/content/CVPR2026W/NeXD/html/Zhang_CADLoop_An_Equivariant-Aware_Skill-Grounded_Loop_for_CAD_Data_Curation_CVPRW_2026_paper.html",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "VLM infers design intent while a symbolic compiler performs typed AST repair and deterministic geometry verification",
        "limitation": "near-miss CAD reconstruction repair is narrower than open-ended architectural mass generation",
        "method_layer": "neuro_symbolic_typed_repair",
        "runtime_components": ["geometry_language.vlm_adapter", "geometry_language.loop", "geometry_language.gate"],
        "operator_families": [],
        "activation_policy": "materialized_typed_edit",
    },
    {
        "id": "cadtalk_cvpr_2024",
        "title": "CADTalk: An Algorithm and Benchmark for Semantic Commenting of CAD Programs",
        "paper_url": "https://openaccess.thecvf.com/content/CVPR2024/html/Yuan_CADTalk_An_Algorithm_and_Benchmark_for_Semantic_Commenting_of_CAD_CVPR_2024_paper.html",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "pair executable graph nodes with architectural semantic roles so agents and users can understand and revise the same program",
        "limitation": "semantic comments must remain grounded in compiled geometry and cannot substitute for executable relations",
        "method_layer": "semantic_program_trace",
        "runtime_components": ["geometry_language.ast", "geometry_language.execution_activation", "geometry_language.execution_agent_context"],
        "operator_families": [],
        "activation_policy": "recursive_ast_with_semantic_roles",
    },
    {
        "id": "evomass_foar_2024",
        "title": "Optimization-based Design Exploration of Building Massing Typologies—EvoMass",
        "paper_url": "https://doi.org/10.1016/j.foar.2024.06.001",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "typology-oriented candidate populations with explicit capacity, site, legal, parking and diversity feedback before portfolio selection",
        "limitation": "MAAS uses a typed geometry compiler and hard gates rather than reproducing the Rhino-Grasshopper EvoMass implementation",
        "method_layer": "performance_bounded_typology_exploration",
        "runtime_components": ["book_language.candidate_generation", "book_language.capacity_alternatives", "book_language.portfolio_selection", "book_language.downstream_hard_gate"],
        "operator_families": [],
        "activation_policy": "capacity_and_selector_passed",
    },
    {
        "id": "ppd_cvpr_2025",
        "title": "Personalized Preference Fine-tuning of Diffusion Models",
        "paper_url": "https://arxiv.org/abs/2501.06655",
        "code_url": "https://github.com/Asap7772/Personalized-Text-To-Image-Diffusion",
        "local_code_path": "clone/Personalized-Text-To-Image-Diffusion",
        "local_commit": "fe3835f",
        "maas_adaptation": "few-shot pairwise preference examples and VLM preference profile extraction",
        "limitation": "public code includes only the VLM component, not diffusion fine-tuning",
    },
    {
        "id": "visionreward_2024",
        "title": "VisionReward: Fine-Grained Multi-Dimensional Human Preference Learning for Image and Video Generation",
        "paper_url": "https://arxiv.org/abs/2412.21059",
        "code_url": "https://github.com/zai-org/VisionReward",
        "local_code_path": "clone/VisionReward",
        "local_commit": "511960d",
        "maas_adaptation": "architecture-specific VLM QA checklist with weighted concept scoring",
        "limitation": "generic image reward questions must be replaced by architecture-massing questions",
    },
    {
        "id": "aesthetiq_cvpr_2025",
        "title": "AesthetiQ: Enhancing Graphic Layout Design via Aesthetic-Aware Preference Alignment",
        "paper_url": "https://arxiv.org/abs/2503.00591",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "filter candidates before preference alignment; use pairwise VLM preference after quality gates",
        "limitation": "official code repository not found during 2026-07-08 audit",
    },
    {
        "id": "designpref_2025",
        "title": "DesignPref: Capturing Personal Preferences in Visual Design Generation",
        "paper_url": "https://arxiv.org/abs/2511.20513",
        "code_url": "",
        "local_code_path": "",
        "local_commit": "",
        "maas_adaptation": "designer preference is subjective, so professor/user pairwise calibration is required",
        "limitation": "official code repository not found during 2026-07-08 audit",
    },
)


def paper_source_summary() -> list[dict[str, Any]]:
    return [dict(item) for item in PREFERENCE_PAPER_SOURCES]


def executable_paper_method_context(
    *,
    operators: list[str] | tuple[str, ...],
    stage_status: dict[str, str],
    structural_hash: str = "",
    typed_geometry_edit_count: int = 0,
    semantic_role_count: int = 0,
) -> dict[str, Any]:
    """Report which paper adaptations were actually active for one MASS.

    This is provenance, not a claim that MAAS reproduces the referenced paper.
    A paper can be registered while its runtime method remains inactive (for
    example CADFusion when no VLM visual-feedback pass was executed).
    """

    operator_set = {str(value) for value in operators if str(value)}
    executed = {"passed", "evaluated", "compiled"}
    rows: list[dict[str, Any]] = []
    for source in PREFERENCE_PAPER_SOURCES:
        policy = str(source.get("activation_policy") or "")
        if not policy:
            continue
        required_operators = set(source.get("operator_families") or ())
        evidence: dict[str, Any] = {}
        active = False
        if policy == "operator_and_recursive_ast":
            matched = sorted(operator_set & required_operators)
            evidence = {"matched_operators": matched, "recursive_geometry": stage_status.get("recursive_geometry")}
            active = bool(matched) and stage_status.get("recursive_geometry") in executed
        elif policy == "compiler_and_structural_hash":
            evidence = {"compiler": stage_status.get("compiler"), "structural_hash_present": bool(structural_hash)}
            active = stage_status.get("compiler") in executed and bool(structural_hash)
        elif policy == "evaluated_vlm_feedback":
            evidence = {"render": stage_status.get("render"), "vlm": stage_status.get("vlm")}
            active = stage_status.get("render") in executed and stage_status.get("vlm") in executed
        elif policy == "materialized_typed_edit":
            evidence = {"vlm": stage_status.get("vlm"), "typed_geometry_edit_count": int(typed_geometry_edit_count)}
            active = stage_status.get("vlm") in executed and typed_geometry_edit_count > 0
        elif policy == "recursive_ast_with_semantic_roles":
            evidence = {"recursive_geometry": stage_status.get("recursive_geometry"), "semantic_role_count": int(semantic_role_count)}
            active = stage_status.get("recursive_geometry") in executed and semantic_role_count > 0
        elif policy == "capacity_and_selector_passed":
            evidence = {"capacity": stage_status.get("capacity"), "selector": stage_status.get("selector")}
            active = stage_status.get("capacity") in executed and stage_status.get("selector") in executed
        rows.append({
            "source_id": source["id"],
            "title": source["title"],
            "paper_url": source["paper_url"],
            "method_layer": source["method_layer"],
            "runtime_status": "adaptation_active" if active else "registered_not_active_for_this_mass",
            "runtime_components": list(source.get("runtime_components") or ()),
            "maas_adaptation": source["maas_adaptation"],
            "limitation": source["limitation"],
            "evidence": evidence,
        })
    return {
        "schema_version": "arr.maas.executable_paper_method_context.v1",
        "claim_policy": "method_adaptation_provenance_not_paper_reimplementation",
        "source_count": len(rows),
        "active_source_count": sum(row["runtime_status"] == "adaptation_active" for row in rows),
        "sources": rows,
    }


__all__ = ["PREFERENCE_PAPER_SOURCES", "executable_paper_method_context", "paper_source_summary"]
