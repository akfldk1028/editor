"""CLI harness for MAAS second-stage preference distillation."""

from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import argparse
import json
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.preference.candidate_crops import crop_candidate_images, crop_path_for_feature
from backend.app.modules.design.generation.maas.preference.concept_schema import build_preference_distillation
from backend.app.modules.design.generation.maas.preference.generation_feedback import build_vlm_generation_feedback, write_vlm_generation_feedback
from backend.app.modules.design.generation.maas.preference.pairwise_store import load_pairwise_labels, pairwise_win_counts
from backend.app.modules.design.generation.maas.preference.paper_sources import paper_source_summary
from backend.app.modules.design.generation.maas.preference.quality_audit import audit_preference_output
from backend.app.modules.design.generation.maas.preference.proposal_package import export_top_proposal_packages
from backend.app.modules.design.generation.maas.preference.reference_corpus import archdaily_api_collection_dir, archdaily_seed_collection_dir, collect_archdaily_from_api, collect_archdaily_from_search, collect_archdaily_metadata, default_reference_root, download_reference_images, ensure_reference_seed_files, load_reference_items, load_reference_tree, match_reference_context, write_reference_manifest, refresh_archdaily_db_manifest, write_reference_items
from backend.app.modules.design.generation.maas.preference.reranker import rerank_candidates
from backend.app.modules.design.generation.maas.preference.vlm_scorer import VlmScoringError, score_candidate_with_openai_vlm


def run_preference_harness(
    *,
    input_json: Path,
    output_json: Path,
    image_path: Path | None = None,
    reference_root: Path | None = None,
    pairwise_jsonl: Path | None = None,
    use_vlm: bool = False,
    vlm_model: str | None = None,
    candidate_crop_dir: Path | None = None,
    feedback_json: Path | None = None,
    next_generation_context_json: Path | None = None,
    proposal_dir: Path | None = None,
    require_vlm_feedback: bool = False,
) -> dict[str, Any]:
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    collection = response.get("feature_collection") if isinstance(response.get("feature_collection"), dict) else {}
    features = collection.get("features") if isinstance(collection.get("features"), list) else []
    root = _resolve_reference_root(reference_root)
    seed_paths = ensure_reference_seed_files(root)
    references = _load_all_references(root)
    labels = load_pairwise_labels(pairwise_jsonl) if pairwise_jsonl else []
    wins = pairwise_win_counts(labels)
    crop_manifest: dict[str, Any] = {}
    if use_vlm and image_path is not None and candidate_crop_dir is not None:
        crop_manifest = crop_candidate_images(
            sheet_path=image_path,
            output_dir=candidate_crop_dir,
            features=features,
        )
    for index, feature in enumerate(features):
        props = feature.setdefault("properties", {})
        if not isinstance(props.get("paper_alignment_evidence"), dict):
            props["paper_alignment_evidence"] = _fallback_paper_alignment(feature)
        matches = match_reference_context(feature, references, limit=5)
        vlm_result: dict[str, Any] | None = None
        vlm_error = ""
        candidate_image_path = crop_path_for_feature(crop_manifest, feature, index) or image_path
        if use_vlm and candidate_image_path is not None:
            try:
                vlm_result = score_candidate_with_openai_vlm(
                    feature=feature,
                    image_path=candidate_image_path,
                    reference_matches=matches,
                    model=vlm_model,
                )
            except (VlmScoringError, Exception) as exc:
                vlm_error = str(exc)
        props["preference_distillation"] = build_preference_distillation(
            feature,
            image_uri=str(candidate_image_path or ""),
            vlm_model=(vlm_result or {}).get("model") if vlm_result else None,
            vlm_scores=(vlm_result or {}).get("concept_scores") if vlm_result else None,
            reference_matches=matches,
            human_pairwise_wins=wins.get(str(props.get("variant_id") or ""), 0),
            vlm_status="scored" if vlm_result else ("failed" if vlm_error else "not_requested"),
            vlm_error=vlm_error,
        )
        props["preference_distillation"]["vlm_result"] = vlm_result or {}
        model = props.get("maas_model")
        if isinstance(model, dict):
            model["preference_distillation"] = props["preference_distillation"]
    ranked = rerank_candidates(features, pairwise_wins=wins)
    collection["features"] = ranked
    response["feature_collection"] = collection
    feedback: dict[str, Any] = {}
    if feedback_json is not None or next_generation_context_json is not None or require_vlm_feedback:
        if require_vlm_feedback:
            scored = sum(
                1
                for feature in ranked
                if ((feature.get("properties") or {}).get("preference_distillation") or {}).get("vlm_status") == "scored"
            )
            if scored != len(ranked):
                raise RuntimeError(f"VLM feedback requires all candidates scored, got {scored}/{len(ranked)}")
        feedback = build_vlm_generation_feedback(response)
        response["vlm_generation_feedback"] = feedback
        if feedback_json is not None:
            write_vlm_generation_feedback(feedback_json, feedback)
        if next_generation_context_json is not None:
            write_vlm_generation_feedback(next_generation_context_json, {
                "schema_version": "arr.maas.next_generation_context.v1",
                "input_json": str(input_json),
                "source_preference_json": str(output_json),
                "generation_feedback": feedback,
            })
    proposal_manifest: dict[str, Any] = {}
    if proposal_dir is not None:
        proposal_manifest = export_top_proposal_packages(response, output_dir=proposal_dir)
    response["preference_harness"] = {
        "schema_version": "arr.maas.preference_harness.v1",
        "input_json": str(input_json),
        "output_json": str(output_json),
        "image_path": str(image_path or ""),
        "reference_seed_paths": seed_paths,
        "reference_count": len(references),
        "pairwise_label_count": len(labels),
        "use_vlm": use_vlm,
        "vlm_model": vlm_model or "",
        "candidate_crop_manifest": crop_manifest,
        "feedback_json": str(feedback_json or ""),
        "next_generation_context_json": str(next_generation_context_json or ""),
        "proposal_manifest": proposal_manifest,
        "paper_sources": paper_source_summary(),
    }
    response["preference_quality_audit"] = audit_preference_output(response)
    if "response" in payload:
        payload["response"] = response
    else:
        payload = response
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return response["preference_harness"]


def _fallback_paper_alignment(feature: dict[str, Any]) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    repair = props.get("repair_delta") if isinstance(props.get("repair_delta"), dict) else {}
    order = props.get("orderliness_evidence") if isinstance(props.get("orderliness_evidence"), dict) else {}
    return {
        "schema_version": "arr.maas.paper_alignment.v1",
        "method_status": "paper_inspired_arr_native",
        "typology_generator": "llm_massdsl" if str(props.get("mass_shape") or "").startswith("llm_") else "grammar_or_seed_massdsl",
        "source_family": source.get("family") or props.get("operator_family") or "",
        "generator_mode": ((source.get("rule_evidence") or {}).get("generator_mode") if isinstance(source.get("rule_evidence"), dict) else "") or "",
        "source_geometry_lineage": {
            "mass_shape": props.get("mass_shape"),
            "massdsl_source": (props.get("massdsl_proposal") or {}).get("proposal_source") if isinstance(props.get("massdsl_proposal"), dict) else "",
            "parameter_source": ((props.get("massdsl_proposal") or {}).get("design_parameters") or {}).get("parameter_source")
            if isinstance(props.get("massdsl_proposal"), dict)
            and isinstance((props.get("massdsl_proposal") or {}).get("design_parameters"), dict)
            else "",
            "geometry_resolution": (props.get("geometry_resolution") or {}).get("status") if isinstance(props.get("geometry_resolution"), dict) else "",
        },
        "formal_variation_stage": {
            "formal_principle": ambition.get("formal_principle") or source.get("formal_principle") or "",
            "dominant_gesture": ambition.get("dominant_gesture") or source.get("dominant_gesture") or "",
            "volume_based_variation": bool(ambition.get("formal_principle") or source.get("formal_principle")),
            "boundary_based_variation": bool(source.get("rule_evidence")),
        },
        "objective_vector": {
            "far_utilization": float(props.get("far_utilization") or 0.0),
            "bcr_utilization": float(props.get("bcr_utilization") or 0.0),
            "diversity_score": float(props.get("diversity_score") or 0.0),
            "orderliness_score": float(order.get("orderliness_score") or 0.0),
        },
        "legal_repair_delta": {
            "schema_version": repair.get("schema_version") or "",
            "area_retention": repair.get("area_retention"),
            "scope": repair.get("scope") or "",
        },
        "selection_reason": "preference_harness_backfilled_from_existing_candidate_evidence",
        "limitations": ["Backfilled by second-stage harness for an existing JSON artifact."],
    }


def _resolve_reference_root(reference_root: Path | None = None) -> Path:
    raw = reference_root or default_reference_root()
    if raw.is_absolute():
        return raw
    candidates = [
        _design_paths.workspace_root() / raw,
        _design_paths.workspace_root() / raw,
        Path.cwd() / raw,
    ]
    for candidate in candidates:
        if (candidate / "archdaily" / "DB_MANIFEST.json").exists() or any(candidate.rglob("metadata.jsonl")):
            return candidate
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def collect_archdaily_seed_urls(
    *,
    reference_root: Path | None = None,
    collection_name: str = "manual_seed",
    download_images: bool = False,
) -> Path:
    root = reference_root or Path("docs/ai-session-memory/reference-corpus")
    paths = ensure_reference_seed_files(root)
    seed_path = Path(paths["archdaily_seed"])
    urls = [
        line.strip()
        for line in seed_path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    items = collect_archdaily_metadata(urls)
    collection_dir = archdaily_seed_collection_dir(root, collection_name=collection_name)
    if download_images:
        items = download_reference_images(items, image_dir=collection_dir / "images")
    output = collection_dir / "metadata.jsonl"
    write_reference_items(output, items)
    write_reference_manifest(collection_dir / "manifest.json", {
        "schema_version": "arr.maas.archdaily_seed_collection.v1",
        "source": "archdaily_seed",
        "seed_urls": str(seed_path),
        "collection_name": collection_name,
        "download_images": download_images,
        "item_count": len(items),
        "image_count": sum(1 for item in items if item.local_path),
        "metadata_jsonl": str(output),
        "images_dir": str(collection_dir / "images"),
    })
    refresh_archdaily_db_manifest(root)
    return output


def crawl_archdaily_search(
    *,
    reference_root: Path | None = None,
    start_url: str = "https://www.archdaily.com/search/projects",
    pages: int = 1,
    limit: int = 40,
    download_images: bool = False,
) -> Path:
    root = reference_root or Path("docs/ai-session-memory/reference-corpus")
    ensure_reference_seed_files(root)
    archdaily_dir = root / "archdaily"
    items = collect_archdaily_from_search(
        start_url=start_url,
        pages=pages,
        limit=limit,
        download_images=download_images,
        image_dir=archdaily_dir / "images",
    )
    output = archdaily_dir / "metadata.jsonl"
    write_reference_items(output, items)
    return output


def crawl_archdaily_api(
    *,
    reference_root: Path | None = None,
    start_path: str = "/projects",
    site: str = "us",
    query: str = "",
    pages: int = 1,
    limit: int = 40,
    download_images: bool = False,
    collection_name: str = "",
) -> Path:
    root = reference_root or Path("docs/ai-session-memory/reference-corpus")
    ensure_reference_seed_files(root)
    collection_dir = archdaily_api_collection_dir(
        root,
        start_path=start_path,
        site=site,
        query=query,
        collection_name=collection_name,
    )
    items = collect_archdaily_from_api(
        start_path=start_path,
        site=site,
        query=query,
        pages=pages,
        limit=limit,
        download_images=download_images,
        image_dir=collection_dir / "images",
    )
    output = collection_dir / "metadata.jsonl"
    write_reference_items(output, items)
    write_reference_manifest(collection_dir / "manifest.json", {
        "schema_version": "arr.maas.archdaily_api_collection.v1",
        "source": "archdaily_api",
        "site": site,
        "start_path": start_path,
        "query": query,
        "pages": pages,
        "limit": limit,
        "download_images": download_images,
        "item_count": len(items),
        "image_count": sum(1 for item in items if item.local_path),
        "metadata_jsonl": str(output),
        "images_dir": str(collection_dir / "images"),
    })
    refresh_archdaily_db_manifest(root)
    return output


def _load_all_references(root: Path) -> list[Any]:
    references = load_reference_tree(root)
    if references:
        return references
    return load_reference_items(root / "huggingface" / "metadata.jsonl")


def export_generation_feedback(
    *,
    input_json: Path,
    feedback_json: Path | None = None,
    next_generation_context_json: Path | None = None,
    proposal_dir: Path | None = None,
    require_vlm_feedback: bool = False,
) -> dict[str, Any]:
    payload = json.loads(input_json.read_text(encoding="utf-8"))
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    collection = response.get("feature_collection") if isinstance(response.get("feature_collection"), dict) else {}
    features = collection.get("features") if isinstance(collection.get("features"), list) else []
    if require_vlm_feedback:
        scored = sum(
            1
            for feature in features
            if ((feature.get("properties") or {}).get("preference_distillation") or {}).get("vlm_status") == "scored"
        )
        if scored != len(features):
            raise RuntimeError(f"VLM feedback requires all candidates scored, got {scored}/{len(features)}")
    feedback = build_vlm_generation_feedback(response)
    if feedback_json is not None:
        write_vlm_generation_feedback(feedback_json, feedback)
    if next_generation_context_json is not None:
        write_vlm_generation_feedback(next_generation_context_json, {
            "schema_version": "arr.maas.next_generation_context.v1",
            "input_json": str(input_json),
            "generation_feedback": feedback,
        })
    if proposal_dir is not None:
        feedback["proposal_manifest"] = export_top_proposal_packages(response, output_dir=proposal_dir)
    return feedback


def main() -> None:
    parser = argparse.ArgumentParser(description="Run MAAS second-stage preference distillation.")
    parser.add_argument("--input-json", default="docs/playwright/design-route-live-verify/maas-20-alt-latest.json")
    parser.add_argument("--output-json", default="docs/playwright/design-route-live-verify/maas-20-alt-preference-latest.json")
    parser.add_argument("--image-path", default="docs/playwright/design-route-live-verify/maas-20-alt-latest.png")
    parser.add_argument("--reference-root", default="docs/ai-session-memory/reference-corpus")
    parser.add_argument("--pairwise-jsonl", default="")
    parser.add_argument("--use-vlm", action="store_true")
    parser.add_argument("--vlm-model", default="")
    parser.add_argument("--candidate-crop-dir", default="")
    parser.add_argument("--feedback-json", default="")
    parser.add_argument("--next-generation-context-json", default="")
    parser.add_argument("--proposal-dir", default="")
    parser.add_argument("--require-vlm-feedback", action="store_true")
    parser.add_argument("--feedback-only", action="store_true")
    parser.add_argument("--collect-archdaily", action="store_true")
    parser.add_argument("--crawl-archdaily", action="store_true")
    parser.add_argument("--crawl-archdaily-api", action="store_true")
    parser.add_argument("--crawl-only", action="store_true")
    parser.add_argument("--archdaily-start-url", default="https://www.archdaily.com/search/projects")
    parser.add_argument("--archdaily-api-path", default="/projects")
    parser.add_argument("--archdaily-site", default="us")
    parser.add_argument("--archdaily-query", default="")
    parser.add_argument("--archdaily-collection", default="")
    parser.add_argument("--archdaily-pages", type=int, default=1)
    parser.add_argument("--archdaily-limit", type=int, default=40)
    parser.add_argument("--download-archdaily-images", action="store_true")
    args = parser.parse_args()
    reference_root = _resolve_reference_root(Path(args.reference_root))
    if args.collect_archdaily:
        collect_archdaily_seed_urls(
            reference_root=reference_root,
            collection_name=args.archdaily_collection or "manual_seed",
            download_images=args.download_archdaily_images,
        )
    if args.crawl_archdaily:
        crawl_archdaily_search(
            reference_root=reference_root,
            start_url=args.archdaily_start_url,
            pages=args.archdaily_pages,
            limit=args.archdaily_limit,
            download_images=args.download_archdaily_images,
        )
    if args.crawl_archdaily_api:
        crawl_archdaily_api(
            reference_root=reference_root,
            start_path=args.archdaily_api_path,
            site=args.archdaily_site,
            query=args.archdaily_query,
            pages=args.archdaily_pages,
            limit=args.archdaily_limit,
            download_images=args.download_archdaily_images,
            collection_name=args.archdaily_collection,
        )
    if args.crawl_only:
        print(json.dumps({
            "schema_version": "arr.maas.preference_harness.crawl_only.v1",
            "reference_root": str(reference_root),
            "crawl_archdaily": bool(args.crawl_archdaily),
            "crawl_archdaily_api": bool(args.crawl_archdaily_api),
        }, ensure_ascii=False, indent=2))
        return
    if args.feedback_only:
        feedback = export_generation_feedback(
            input_json=Path(args.input_json),
            feedback_json=Path(args.feedback_json) if args.feedback_json else None,
            next_generation_context_json=Path(args.next_generation_context_json) if args.next_generation_context_json else None,
            proposal_dir=Path(args.proposal_dir) if args.proposal_dir else None,
            require_vlm_feedback=bool(args.require_vlm_feedback),
        )
        print(json.dumps(feedback, ensure_ascii=False, indent=2))
        return
    result = run_preference_harness(
        input_json=Path(args.input_json),
        output_json=Path(args.output_json),
        image_path=Path(args.image_path) if args.image_path else None,
        reference_root=reference_root,
        pairwise_jsonl=Path(args.pairwise_jsonl) if args.pairwise_jsonl else None,
        use_vlm=bool(args.use_vlm),
        vlm_model=args.vlm_model or None,
        candidate_crop_dir=Path(args.candidate_crop_dir) if args.candidate_crop_dir else None,
        feedback_json=Path(args.feedback_json) if args.feedback_json else None,
        next_generation_context_json=Path(args.next_generation_context_json) if args.next_generation_context_json else None,
        proposal_dir=Path(args.proposal_dir) if args.proposal_dir else None,
        require_vlm_feedback=bool(args.require_vlm_feedback),
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
