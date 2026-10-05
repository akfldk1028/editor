"""Export top MAAS candidates as compact proposal packages."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


PROPOSAL_PACKAGE_SCHEMA_VERSION = "arr.maas.competition_proposal_package.v1"


def export_top_proposal_packages(
    payload: dict[str, Any],
    *,
    output_dir: Path,
    top_n: int = 3,
) -> dict[str, Any]:
    response = payload.get("response") if isinstance(payload.get("response"), dict) else payload
    features = ((response.get("feature_collection") or {}).get("features") or []) if isinstance(response, dict) else []
    features = [feature for feature in features if isinstance(feature, dict)][: max(1, int(top_n))]
    output_dir.mkdir(parents=True, exist_ok=True)
    packages = []
    for index, feature in enumerate(features, 1):
        package = _proposal(feature, index)
        json_path = output_dir / f"proposal_{index:02d}.json"
        png_path = output_dir / f"proposal_{index:02d}.png"
        json_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        image_uri = package.get("image_uri")
        if image_uri and Path(str(image_uri)).exists():
            shutil.copyfile(str(image_uri), png_path)
            package["proposal_png"] = str(png_path)
            json_path.write_text(json.dumps(package, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        packages.append({
            "rank": index,
            "variant_id": package["variant_id"],
            "json": str(json_path),
            "png": str(png_path) if png_path.exists() else "",
        })
    manifest = {
        "schema_version": PROPOSAL_PACKAGE_SCHEMA_VERSION,
        "output_dir": str(output_dir),
        "count": len(packages),
        "packages": packages,
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def _proposal(feature: dict[str, Any], rank: int) -> dict[str, Any]:
    props = feature.get("properties") if isinstance(feature.get("properties"), dict) else {}
    pref = props.get("preference_distillation") if isinstance(props.get("preference_distillation"), dict) else {}
    source = props.get("source_signature") if isinstance(props.get("source_signature"), dict) else {}
    ambition = props.get("architectural_ambition_evidence") if isinstance(props.get("architectural_ambition_evidence"), dict) else {}
    parking = props.get("parking_precheck") if isinstance(props.get("parking_precheck"), dict) else {}
    layout = parking.get("layout_candidate") if isinstance(parking.get("layout_candidate"), dict) else {}
    return {
        "schema_version": PROPOSAL_PACKAGE_SCHEMA_VERSION,
        "rank": rank,
        "variant_id": props.get("variant_id"),
        "mass_shape": props.get("mass_shape"),
        "image_uri": pref.get("image_uri") or "",
        "massing_concept": {
            "family": source.get("family") or props.get("operator_family"),
            "primary_language": source.get("primary_language"),
            "secondary_language": source.get("secondary_language"),
            "formal_principle": ambition.get("formal_principle") or source.get("formal_principle"),
            "dominant_gesture": ambition.get("dominant_gesture") or source.get("dominant_gesture"),
        },
        "metrics": {
            "far": props.get("far"),
            "bcr": props.get("bcr"),
            "height": props.get("height"),
            "preference_score": pref.get("distilled_preference_score"),
            "vlm_status": pref.get("vlm_status"),
        },
        "hard_gates": pref.get("hard_gates") or {},
        "parking_mass_stage": {
            "status": layout.get("status"),
            "provided_spaces": layout.get("provided_spaces"),
            "required_spaces": layout.get("required_spaces"),
            "permit_final": False,
        },
        "vlm_summary": {
            "concept_scores": pref.get("concept_scores") or {},
            "rationale": (pref.get("vlm_result") or {}).get("rationale", ""),
            "warnings": (pref.get("vlm_result") or {}).get("warnings", []),
        },
        "reference_matches": pref.get("reference_matches") or [],
        "remaining_risks": [
            "parking permit-final driveway/mechanical review remains downstream",
            "VLM preference is ranking evidence, not legal authority",
        ],
    }


__all__ = ["PROPOSAL_PACKAGE_SCHEMA_VERSION", "export_top_proposal_packages"]
