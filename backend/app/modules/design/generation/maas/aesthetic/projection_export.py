"""Export baked MAAS facade projection as textured mesh assets."""

from __future__ import annotations

import base64
import json
import struct
from pathlib import Path
from typing import Any

from backend.app.modules.design.generation.maas.aesthetic.contracts import ProviderResult


def attach_textured_mesh_assets(provider_result: ProviderResult) -> ProviderResult:
    """Attach renderer-neutral mesh and glTF assets from the baked atlas.

    The exporter is deliberately deterministic: it only combines locked MAAS
    facade surfaces with the already-baked texture atlas. It does not alter or
    repair geometry.
    """

    bake_asset = _first_asset(provider_result, "texture_bake_manifest")
    atlas_asset = _first_asset(provider_result, "baked_texture_atlas")
    if not bake_asset or not atlas_asset:
        return provider_result

    bake_path = _local_path(bake_asset.get("uri"))
    atlas_path = _local_path(atlas_asset.get("uri"))
    if not bake_path or not atlas_path or not bake_path.exists() or not atlas_path.exists():
        return provider_result

    try:
        bake = json.loads(bake_path.read_text(encoding="utf-8"))
        projection_path = Path(str(bake["source_projection_manifest"]))
        projection = json.loads(projection_path.read_text(encoding="utf-8"))
    except Exception:
        return provider_result

    surfaces = projection.get("surfaces") or []
    mesh = _build_mesh(surfaces)
    if not mesh["indices"]:
        return provider_result

    out_dir = bake_path.parent
    manifest_path = out_dir / "textured_mesh_manifest.json"
    gltf_path = out_dir / "textured_mesh.gltf"
    source_asset_id = _source_asset_id(provider_result)

    mesh_manifest = {
        "schema_version": "arr.maas.textured_mesh.v0",
        "mode": "baked_texture_mesh",
        "coordinate_space": projection.get("coordinate_space") or "local_meter_from_first_mass_point",
        "origin": projection.get("origin"),
        "source_projection_manifest": str(projection_path),
        "source_bake_manifest": str(bake_path),
        "texture_atlas_uri": str(atlas_path),
        "mesh": mesh,
        "surface_count": len(mesh["surface_ranges"]),
        "legal_status_effect": "none",
    }
    manifest_path.write_text(json.dumps(mesh_manifest, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")

    gltf = _build_gltf(mesh, atlas_path.name)
    gltf_path.write_text(json.dumps(gltf, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    assets = list(provider_result.assets)
    assets.extend([
        {
            "asset_id": f"{source_asset_id}:mesh:manifest",
            "uri": str(manifest_path),
            "media_type": "application/json",
            "source_bundle_id": _first_asset_value(provider_result, "source_bundle_id"),
            "candidate_id": _first_asset_value(provider_result, "candidate_id"),
            "legal_status_effect": "none",
            "role": "textured_mesh_manifest",
            "metadata": {
                "mode": "baked_texture_mesh",
                "texture_atlas_uri": str(atlas_path),
                "gltf_uri": str(gltf_path),
                "surface_count": len(mesh["surface_ranges"]),
            },
        },
        {
            "asset_id": f"{source_asset_id}:mesh:gltf",
            "uri": str(gltf_path),
            "media_type": "model/gltf+json",
            "source_bundle_id": _first_asset_value(provider_result, "source_bundle_id"),
            "candidate_id": _first_asset_value(provider_result, "candidate_id"),
            "legal_status_effect": "none",
            "role": "textured_gltf",
            "metadata": {
                "mode": "baked_texture_mesh",
                "texture_atlas_uri": str(atlas_path),
                "mesh_manifest_uri": str(manifest_path),
                "surface_count": len(mesh["surface_ranges"]),
            },
        },
    ])

    metadata = dict(provider_result.metadata or {})
    metadata["textured_mesh"] = {
        "mode": "baked_texture_mesh",
        "mesh_manifest_asset_id": f"{source_asset_id}:mesh:manifest",
        "gltf_asset_id": f"{source_asset_id}:mesh:gltf",
        "texture_atlas_asset_id": atlas_asset.get("asset_id"),
        "surface_count": len(mesh["surface_ranges"]),
    }
    return ProviderResult(
        provider=provider_result.provider,
        status=provider_result.status,
        assets=assets,
        metadata=metadata,
        issues=list(provider_result.issues or []),
    )


def _build_mesh(surfaces: list[dict[str, Any]]) -> dict[str, Any]:
    positions: list[list[float]] = []
    uvs: list[list[float]] = []
    indices: list[int] = []
    surface_ranges: list[dict[str, Any]] = []

    for surface in surfaces:
        vertices = surface.get("vertices_m")
        surface_uv = surface.get("uv")
        triangles = surface.get("triangles")
        if not _valid_vertices(vertices) or not _valid_uv(surface_uv) or not _valid_triangles(triangles):
            continue

        vertex_offset = len(positions)
        index_start = len(indices)
        positions.extend([[float(v[0]), float(v[1]), float(v[2])] for v in vertices])
        uvs.extend([[float(uv[0]), float(uv[1])] for uv in surface_uv])
        for triangle in triangles:
            indices.extend([vertex_offset + int(triangle[0]), vertex_offset + int(triangle[1]), vertex_offset + int(triangle[2])])

        surface_ranges.append({
            "surface_id": surface.get("id"),
            "volume_id": surface.get("volume_id"),
            "view": surface.get("view"),
            "index_start": index_start,
            "index_count": len(indices) - index_start,
        })

    return {
        "positions_m": positions,
        "uv": uvs,
        "indices": indices,
        "surface_ranges": surface_ranges,
    }


def _build_gltf(mesh: dict[str, Any], atlas_filename: str) -> dict[str, Any]:
    positions = mesh["positions_m"]
    uvs = mesh["uv"]
    indices = mesh["indices"]

    position_bytes = _pack_f32(value for position in positions for value in position)
    uv_bytes = _pack_f32(value for uv in uvs for value in uv)
    index_bytes = _pack_u32(indices)

    chunks: list[bytes] = []
    buffer_views: list[dict[str, Any]] = []
    offset = 0
    for data, target in ((position_bytes, 34962), (uv_bytes, 34962), (index_bytes, 34963)):
        offset = _append_aligned(chunks, offset)
        buffer_views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data), "target": target})
        chunks.append(data)
        offset += len(data)
    offset = _append_aligned(chunks, offset)
    buffer = b"".join(chunks)

    mins, maxs = _position_bounds(positions)
    return {
        "asset": {"version": "2.0", "generator": "ARR MAAS aesthetic projection exporter"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0, "name": "MAAS textured facade mesh"}],
        "meshes": [{
            "name": "MAAS textured facade mesh",
            "primitives": [{
                "attributes": {"POSITION": 0, "TEXCOORD_0": 1},
                "indices": 2,
                "material": 0,
                "mode": 4,
            }],
        }],
        "materials": [{
            "name": "AI facade atlas material",
            "pbrMetallicRoughness": {
                "baseColorTexture": {"index": 0},
                "metallicFactor": 0.0,
                "roughnessFactor": 0.78,
            },
            "doubleSided": True,
        }],
        "textures": [{"source": 0}],
        "images": [{"uri": atlas_filename, "mimeType": "image/png"}],
        "buffers": [{
            "uri": "data:application/octet-stream;base64," + base64.b64encode(buffer).decode("ascii"),
            "byteLength": len(buffer),
        }],
        "bufferViews": buffer_views,
        "accessors": [
            {
                "bufferView": 0,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(positions),
                "type": "VEC3",
                "min": mins,
                "max": maxs,
            },
            {
                "bufferView": 1,
                "byteOffset": 0,
                "componentType": 5126,
                "count": len(uvs),
                "type": "VEC2",
            },
            {
                "bufferView": 2,
                "byteOffset": 0,
                "componentType": 5125,
                "count": len(indices),
                "type": "SCALAR",
            },
        ],
    }


def _append_aligned(chunks: list[bytes], offset: int) -> int:
    pad = (-offset) % 4
    if pad:
        chunks.append(b"\x00" * pad)
        offset += pad
    return offset


def _pack_f32(values: Any) -> bytes:
    return b"".join(struct.pack("<f", float(value)) for value in values)


def _pack_u32(values: list[int]) -> bytes:
    return b"".join(struct.pack("<I", int(value)) for value in values)


def _position_bounds(positions: list[list[float]]) -> tuple[list[float], list[float]]:
    return (
        [min(position[i] for position in positions) for i in range(3)],
        [max(position[i] for position in positions) for i in range(3)],
    )


def _valid_vertices(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(v, list) and len(v) >= 3 for v in value)


def _valid_uv(value: Any) -> bool:
    return isinstance(value, list) and len(value) >= 3 and all(isinstance(v, list) and len(v) >= 2 for v in value)


def _valid_triangles(value: Any) -> bool:
    return isinstance(value, list) and all(isinstance(t, list) and len(t) == 3 for t in value)


def _first_asset(provider_result: ProviderResult, role: str) -> dict[str, Any] | None:
    for asset in provider_result.assets:
        if asset.get("role") == role:
            return asset
    return None


def _local_path(uri: Any) -> Path | None:
    if not isinstance(uri, str) or uri.startswith(("http://", "https://")):
        return None
    return Path(uri)


def _source_asset_id(provider_result: ProviderResult) -> str:
    for asset in provider_result.assets:
        if asset.get("role") == "generated_facade_image" and asset.get("asset_id"):
            return str(asset["asset_id"])
    return f"asset:maas-aesthetic-generated:{provider_result.provider}"


def _first_asset_value(provider_result: ProviderResult, key: str) -> Any:
    for asset in provider_result.assets:
        if asset.get(key) is not None:
            return asset.get(key)
    return None


__all__ = ["attach_textured_mesh_assets"]
