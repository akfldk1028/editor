"""Bounded four-view creative facade generation for one immutable MASS."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping
import uuid

from PIL import Image, ImageDraw

from backend.app.modules.design.generation.maas.aesthetic.contracts import AestheticProvider, RenderedReference
from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_consistency import evaluate_multi_view_consistency
from backend.app.modules.design.generation.maas.agents.elevation_agent.multi_view_contract import FACADE_VIEWS, MultiViewCritic, proposal_identity

PIPELINE_VERSION = "arr.elevation_agent.multi_view_pipeline.v3"


def generate_multi_view_elevation_proposal(
    bundle: Mapping[str, Any],
    *,
    adapter: AestheticProvider,
    critic: MultiViewCritic,
    strategy: Mapping[str, Any],
) -> dict[str, Any]:
    """Generate, gate, and optionally repair four facade views within 10 calls."""

    if str(bundle.get("status") or "") != "generated":
        raise ValueError("multi-view proposal requires a generated elevation bundle")
    identity = proposal_identity(bundle)
    source_views = {
        str(row.get("view") or ""): dict(row)
        for row in bundle.get("views") or ()
        if isinstance(row, Mapping)
        and str(row.get("view") or "") in FACADE_VIEWS
    }
    if tuple(view for view in FACADE_VIEWS if view in source_views) != FACADE_VIEWS:
        raise ValueError("multi-view proposal requires front, right, back, and left sources")
    source_hashes = {
        view: str(source_views[view].get("sha256") or "")
        for view in FACADE_VIEWS
    }
    strategy_payload = dict(strategy)
    strategy_sha256 = _json_sha256(strategy_payload)
    elevation_root = Path(str(bundle.get("output_directory") or "")).resolve()
    proposal_root = elevation_root / "proposals" / "multi-view-alt-01"
    proposal_root.mkdir(parents=True, exist_ok=True)
    manifest_path = proposal_root / "proposal.json"
    existing = _matching_accepted_manifest(
        manifest_path,
        identity=identity,
        source_hashes=source_hashes,
        strategy_sha256=strategy_sha256,
    )
    if existing is not None:
        return {**existing, "skipped_existing": True}
    if manifest_path.is_file():
        _archive_existing_proposal(proposal_root, manifest_path)

    artifacts: dict[str, dict[str, Any]] = {}
    repair_count = {view: 0 for view in FACADE_VIEWS}
    image_paid_attempts = 0
    critic_paid_attempts = 0
    total_retries = 0
    for view in FACADE_VIEWS:
        artifact, paid_attempts, retry_count = _generate_view(
            view,
            bundle=bundle,
            identity=identity,
            source=source_views[view],
            proposal_root=proposal_root,
            adapter=adapter,
            strategy=strategy_payload,
            attempt=0,
            repair_instruction="",
        )
        artifacts[view] = artifact
        image_paid_attempts += paid_attempts
        total_retries += retry_count

    initial_gate = evaluate_multi_view_consistency(bundle, artifacts)
    montage_path = proposal_root / "critic-montage.png"
    critic_path = proposal_root / "critic.json"
    critic_evidence: dict[str, Any] = {
        "schema_version": "arr.elevation_agent.multi_view_critic.v1",
        "status": "not_evaluated",
        "failed_views": [],
        "issues": [],
        "request_count": 0,
        "paid_request_attempt_count": 0,
        "retry_count": 0,
    }
    failed_views = list(initial_gate.get("failed_views") or ())
    if initial_gate["status"] == "passed":
        _write_montage(artifacts, montage_path)
        critic_evidence = critic.evaluate(
            identity=identity,
            strategy=strategy_payload,
            artifacts=artifacts,
            montage_path=montage_path,
        )
        critic_paid_attempts += int(
            critic_evidence.get("paid_request_attempt_count") or 0
        )
        total_retries += int(critic_evidence.get("retry_count") or 0)
        _write_json_atomic(critic_path, critic_evidence)
        failed_views = list(critic_evidence.get("failed_views") or ())
        if critic_evidence.get("status") == "passed" and not failed_views:
            return _persist_proposal(
                manifest_path,
                identity=identity,
                strategy=strategy_payload,
                strategy_sha256=strategy_sha256,
                source_hashes=source_hashes,
                artifacts=artifacts,
                initial_gate=initial_gate,
                final_gate=initial_gate,
                critic_evidence=critic_evidence,
                repair_count=repair_count,
                image_paid_attempts=image_paid_attempts,
                critic_paid_attempts=critic_paid_attempts,
                total_retries=total_retries,
                montage_path=montage_path,
                status="accepted",
            )

    repair_instructions = _repair_instructions(critic_evidence)
    for view in FACADE_VIEWS:
        if view not in failed_views:
            continue
        artifact, paid_attempts, retry_count = _generate_view(
            view,
            bundle=bundle,
            identity=identity,
            source=source_views[view],
            proposal_root=proposal_root,
            adapter=adapter,
            strategy=strategy_payload,
            attempt=1,
            repair_instruction=repair_instructions.get(view, ""),
        )
        artifacts[view] = artifact
        repair_count[view] = 1
        image_paid_attempts += paid_attempts
        total_retries += retry_count

    final_gate = evaluate_multi_view_consistency(bundle, artifacts)
    if final_gate["status"] == "passed":
        _write_montage(artifacts, montage_path)
        critic_evidence = critic.evaluate(
            identity=identity,
            strategy=strategy_payload,
            artifacts=artifacts,
            montage_path=montage_path,
        )
        critic_paid_attempts += int(
            critic_evidence.get("paid_request_attempt_count") or 0
        )
        total_retries += int(critic_evidence.get("retry_count") or 0)
        _write_json_atomic(critic_path, critic_evidence)
    status = (
        "accepted"
        if final_gate["status"] == "passed"
        and critic_evidence.get("status") == "passed"
        and not critic_evidence.get("failed_views")
        else "failed"
    )
    return _persist_proposal(
        manifest_path,
        identity=identity,
        strategy=strategy_payload,
        strategy_sha256=strategy_sha256,
        source_hashes=source_hashes,
        artifacts=artifacts,
        initial_gate=initial_gate,
        final_gate=final_gate,
        critic_evidence=critic_evidence,
        repair_count=repair_count,
        image_paid_attempts=image_paid_attempts,
        critic_paid_attempts=critic_paid_attempts,
        total_retries=total_retries,
        montage_path=montage_path,
        status=status,
    )


def _generate_view(
    view: str,
    *,
    bundle: Mapping[str, Any],
    identity: Mapping[str, str],
    source: Mapping[str, Any],
    proposal_root: Path,
    adapter: AestheticProvider,
    strategy: Mapping[str, Any],
    attempt: int,
    repair_instruction: str,
) -> tuple[dict[str, Any], int, int]:
    source_path = Path(str(source.get("path") or "")).resolve()
    reference = RenderedReference(
        asset_id=f"asset:maas:{identity['execution_id']}:locked-elevation:{view}",
        uri=str(source_path),
        metadata={
            "reference_type": "locked_elevation_view",
            "view": view,
            "identity": {**identity, "view": view},
            "sha256": str(source.get("sha256") or ""),
            "geometry_mutation_allowed": False,
        },
    )
    job = {
        "schema_version": "arr.elevation_agent.multi_view_image_job.v1",
        "source_bundle_id": identity["execution_id"],
        "candidate_id": identity["geometry_hash"],
        "identity": dict(identity),
        "view": view,
        "attempt": attempt,
        "strategy": dict(strategy),
        "prompt": {
            "prompt": (
                f"Facade system: {strategy.get('primary_system')}. "
                f"Rhythm: {strategy.get('rhythm')}. "
                f"Opening logic: {strategy.get('opening_logic')}. "
                f"{_height_profile_instruction(strategy)} "
                f"Apply the same shared facade system to the locked {view} elevation. "
                f"{repair_instruction}"
            ).strip(),
            "negative_prompt": (
                "changed silhouette, changed mass, changed camera, extra volume, "
                "removed volume, changed roofline, changed height, changed floor count"
            ),
        },
    }
    result = adapter.generate(job, reference)
    provider_metadata = dict(result.metadata or {})
    retry_count = int(provider_metadata.get("retry_count") or 0)
    paid_attempts = 0 if result.status == "not_configured" else 1
    artifact_record: dict[str, Any] = {
        "view": view,
        "identity": {**identity, "view": view},
        "attempt": attempt,
        "status": str(result.status or "failed"),
        "source": {
            "path": str(source_path),
            "sha256": str(source.get("sha256") or ""),
        },
        "artifact": {},
        "provider": str(result.provider or getattr(adapter, "name", "")),
        "provider_metadata": provider_metadata,
        "issues": list(result.issues or ()),
        "request_count": 1,
        "paid_request_attempt_count": paid_attempts,
        "retry_count": retry_count,
    }
    asset = next(
        (row for row in result.assets or () if isinstance(row, dict)),
        None,
    )
    if result.status == "complete" and asset:
        provider_path = Path(str(asset.get("uri") or "")).resolve()
        if provider_path.is_file():
            artifact_path = proposal_root / f"{view}.png"
            if provider_path != artifact_path:
                shutil.copy2(provider_path, artifact_path)
            artifact_record["artifact"] = {
                "asset_id": str(asset.get("asset_id") or ""),
                "path": str(artifact_path),
                "sha256": _sha256(artifact_path),
                "media_type": str(asset.get("media_type") or "image/png"),
                "preview_url": (
                    "/design/maas/single-executions/"
                    f"{identity['execution_id']}/elevation-proposals/"
                    f"multi-view-alt-01/{view}/"
                ),
            }
    return artifact_record, paid_attempts, retry_count


def _height_profile_instruction(strategy: Mapping[str, Any]) -> str:
    measured = strategy.get("measured_features")
    measured = measured if isinstance(measured, Mapping) else {}
    height_profile = str(measured.get("height_profile") or "")
    if height_profile == "single_storey_low":
        return (
            "The locked MASS is exactly one storey. Use one uninterrupted facade "
            "height with no intermediate floor slab, floor band, stacked window "
            "row, mezzanine line, or second-storey reading."
        )
    return f"Preserve the locked height profile ({height_profile or 'unknown'})."


def _persist_proposal(
    manifest_path: Path,
    *,
    identity: Mapping[str, str],
    strategy: Mapping[str, Any],
    strategy_sha256: str,
    source_hashes: Mapping[str, str],
    artifacts: Mapping[str, Mapping[str, Any]],
    initial_gate: Mapping[str, Any],
    final_gate: Mapping[str, Any],
    critic_evidence: Mapping[str, Any],
    repair_count: Mapping[str, int],
    image_paid_attempts: int,
    critic_paid_attempts: int,
    total_retries: int,
    montage_path: Path,
    status: str,
) -> dict[str, Any]:
    paid_attempts = image_paid_attempts + critic_paid_attempts
    if paid_attempts > 10:
        raise RuntimeError("multi-view paid request ceiling exceeded")
    payload = {
        "schema_version": "arr.elevation_agent.multi_view_proposal.v1",
        "pipeline_version": PIPELINE_VERSION,
        "status": status,
        "identity": dict(identity),
        "strategy": dict(strategy),
        "strategy_sha256": strategy_sha256,
        "source_view_sha256": dict(source_hashes),
        "required_views": list(FACADE_VIEWS),
        "artifacts": {
            view: dict(artifacts[view])
            for view in FACADE_VIEWS
            if view in artifacts
        },
        "initial_deterministic_gate": dict(initial_gate),
        "deterministic_gate": dict(final_gate),
        "critic": dict(critic_evidence),
        "repair_count_by_view": dict(repair_count),
        "image_paid_request_attempt_count": image_paid_attempts,
        "critic_paid_request_attempt_count": critic_paid_attempts,
        "paid_request_attempt_count": paid_attempts,
        "retry_count": total_retries,
        "manifest_path": str(manifest_path),
        "critic_manifest_path": str(manifest_path.parent / "critic.json"),
        "montage": {
            "path": str(montage_path) if montage_path.is_file() else "",
            "sha256": _sha256(montage_path) if montage_path.is_file() else "",
            "preview_url": (
                "/design/maas/single-executions/"
                f"{identity['execution_id']}/elevation-proposals/"
                "multi-view-alt-01/critic-montage/"
            ),
        },
        "skipped_existing": False,
    }
    _write_json_atomic(manifest_path, payload)
    return payload


def _matching_accepted_manifest(
    path: Path,
    *,
    identity: Mapping[str, str],
    source_hashes: Mapping[str, str],
    strategy_sha256: str,
) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    if (
        payload.get("status") == "accepted"
        and payload.get("pipeline_version") == PIPELINE_VERSION
        and payload.get("identity") == dict(identity)
        and payload.get("source_view_sha256") == dict(source_hashes)
        and payload.get("strategy_sha256") == strategy_sha256
    ):
        return payload
    return None


def _archive_existing_proposal(
    proposal_root: Path,
    manifest_path: Path,
) -> None:
    manifest_sha = _sha256(manifest_path)
    archive_root = proposal_root / "history" / manifest_sha[:16]
    archive_root.mkdir(parents=True, exist_ok=True)
    for name in (
        "proposal.json",
        "critic.json",
        "critic-montage.png",
        *(f"{view}.png" for view in FACADE_VIEWS),
    ):
        source = proposal_root / name
        target = archive_root / name
        if source.is_file() and not target.exists():
            shutil.copy2(source, target)


def _repair_instructions(critic: Mapping[str, Any]) -> dict[str, str]:
    result: dict[str, list[str]] = {view: [] for view in FACADE_VIEWS}
    for issue in critic.get("issues") or ():
        if not isinstance(issue, Mapping):
            continue
        instruction = str(issue.get("repair_instruction") or "").strip()
        if not instruction:
            continue
        for view in issue.get("views") or ():
            if view in result:
                result[str(view)].append(instruction)
    return {
        view: " ".join(dict.fromkeys(instructions))
        for view, instructions in result.items()
    }


def _write_montage(
    artifacts: Mapping[str, Mapping[str, Any]],
    output_path: Path,
) -> None:
    images: dict[str, Image.Image] = {}
    for view in FACADE_VIEWS:
        output = artifacts[view].get("artifact")
        output = output if isinstance(output, Mapping) else {}
        with Image.open(Path(str(output.get("path") or "")).resolve()) as image:
            images[view] = image.convert("RGB").copy()
    cell_width = max(image.width for image in images.values())
    cell_height = max(image.height for image in images.values())
    canvas = Image.new("RGB", (cell_width * 2, cell_height * 2), "white")
    draw = ImageDraw.Draw(canvas)
    for index, view in enumerate(FACADE_VIEWS):
        image = images[view]
        x = (index % 2) * cell_width
        y = (index // 2) * cell_height
        canvas.paste(image, (x, y))
        draw.rectangle((x, y, x + 92, y + 22), fill=(0, 0, 0))
        draw.text((x + 6, y + 5), view.upper(), fill=(255, 255, 255))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="PNG", optimize=True)


def _json_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        dict(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(
        json.dumps(
            dict(payload),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


__all__ = ["generate_multi_view_elevation_proposal"]
