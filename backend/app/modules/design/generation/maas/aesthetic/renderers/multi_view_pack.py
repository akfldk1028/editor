"""Deterministic multi-view reference sheet renderer for locked MAAS geometry."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from backend.app.modules.design.generation.maas.aesthetic.contracts import RenderedReference
from backend.app.modules.design.generation.maas.aesthetic.projection_mesh import build_projection_manifest


VIEWS = ("front", "right", "back", "left", "axon", "top")


class MultiViewReferencePackRenderer:
    """Render a 2x3 multi-view sheet from MAAS floor plates / volumes.

    The output is intentionally diagrammatic, not photoreal. It gives image
    providers multiple locked views, floor guides, and scene-graph metadata so
    they have less freedom to invent a different building.
    """

    def __init__(self, output_dir: str | Path, *, size: int = 1536) -> None:
        self.output_dir = Path(output_dir)
        self.size = size

    def render(self, job: dict[str, Any]) -> RenderedReference:
        locked = job.get("locked_geometry") or {}
        mass_geojson = locked.get("mass_geojson") or {}
        volumes = _extract_volumes(locked)
        if not volumes:
            raise ValueError("Cannot render MAAS multi-view pack without Polygon/MultiPolygon geometry.")

        scene_graph = _build_scene_graph(job, volumes)
        digest = hashlib.sha256(
            json.dumps(
                {
                    "source_bundle_id": job.get("source_bundle_id"),
                    "candidate_id": job.get("candidate_id"),
                    "mass_geojson": mass_geojson,
                    "volumes": volumes,
                    "metrics": locked.get("geometry_metrics") or {},
                    "renderer": "MultiViewReferencePackRenderer",
                },
                sort_keys=True,
                ensure_ascii=True,
            ).encode("utf-8")
        ).hexdigest()[:16]

        asset_id = f"asset:maas-reference-multiview:{digest}"
        filename = f"{digest}.multi-view.png"
        self.output_dir.mkdir(parents=True, exist_ok=True)
        output_path = self.output_dir / filename

        image = Image.new("RGB", (self.size, self.size), "#f8fafc")
        draw = ImageDraw.Draw(image)
        cols = 3
        rows = 2
        gap = max(18, self.size // 80)
        panel_w = (self.size - gap * (cols + 1)) // cols
        panel_h = (self.size - gap * (rows + 1)) // rows
        bounds = _local_bounds(volumes)

        for index, view in enumerate(VIEWS):
            col = index % cols
            row = index // cols
            box = (
                gap + col * (panel_w + gap),
                gap + row * (panel_h + gap),
                gap + col * (panel_w + gap) + panel_w,
                gap + row * (panel_h + gap) + panel_h,
            )
            _draw_panel(draw, box, view, volumes, bounds, locked)

        image.save(output_path)
        pack = _write_condition_pack(
            root=self.output_dir / digest,
            digest=digest,
            job=job,
            volumes=volumes,
            bounds=bounds,
            locked=locked,
            scene_graph=scene_graph,
        )
        return RenderedReference(
            asset_id=asset_id,
            uri=str(output_path),
            media_type="image/png",
            metadata={
                "renderer": "MultiViewReferencePackRenderer",
                "reference_type": "multi_view_pack",
                "source_bundle_id": job.get("source_bundle_id"),
                "candidate_id": job.get("candidate_id"),
                "width": self.size,
                "height": self.size,
                "views": list(VIEWS),
                "sha256": _file_sha256(output_path),
                "geometry_lock": job.get("reference_render", {}).get("geometry_lock", {}),
                "scene_graph": scene_graph,
                "condition_pack": pack,
            },
        )


def _extract_volumes(locked: dict[str, Any]) -> list[dict[str, Any]]:
    mass_geojson = locked.get("mass_geojson") or {}
    props = mass_geojson.get("properties") or {}
    raw = (
        locked.get("mass_volumes")
        or props.get("mass_volumes")
        or (props.get("maas_model") or {}).get("volumes")
        or locked.get("floor_groups")
        or props.get("floor_groups")
        or locked.get("floor_plates")
        or props.get("floor_plates")
        or []
    )
    volumes: list[dict[str, Any]] = []
    if isinstance(raw, list):
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            geom = item.get("geometry")
            ring = _ring_from_geometry(geom)
            if not ring:
                continue
            bottom = _number(item.get("bottom_height"), _number(item.get("bottom_height_m"), 0.0))
            top = _number(
                item.get("top_height"),
                _number(item.get("top_height_m"), _number(item.get("height_m"), _number(props.get("height"), 15.0))),
            )
            if top <= bottom:
                top = bottom + max(2.8, _number(props.get("floor_height"), 3.0))
            volumes.append({
                "id": item.get("id") or item.get("name") or item.get("role") or f"volume_{index + 1}",
                "role": item.get("role") or item.get("name") or "mass_volume",
                "ring": ring,
                "bottom": bottom,
                "top": top,
                "floor": item.get("floor"),
                "start_floor": item.get("start_floor"),
                "end_floor": item.get("end_floor"),
            })

    if volumes:
        return volumes

    ring = _ring_from_geometry(mass_geojson.get("geometry"))
    if not ring:
        return []
    metrics = locked.get("geometry_metrics") or {}
    height = _number(metrics.get("height_m"), _number(props.get("height"), 15.0))
    return [{"id": "body", "role": "fallback_body", "ring": ring, "bottom": 0.0, "top": height}]


def _ring_from_geometry(geometry: Any) -> list[list[float]] | None:
    if not isinstance(geometry, dict):
        return None
    if geometry.get("type") == "Polygon":
        coords = geometry.get("coordinates") or []
        return _clean_ring(coords[0] if coords else [])
    if geometry.get("type") == "MultiPolygon":
        coords = geometry.get("coordinates") or []
        return _clean_ring(coords[0][0] if coords and coords[0] else [])
    return None


def _clean_ring(ring: Any) -> list[list[float]] | None:
    if not isinstance(ring, list) or len(ring) < 3:
        return None
    points = [[float(p[0]), float(p[1])] for p in ring if isinstance(p, list | tuple) and len(p) >= 2]
    if len(points) > 1 and points[0] == points[-1]:
        points = points[:-1]
    return points if len(points) >= 3 else None


def _number(value: Any, default: float) -> float:
    try:
        n = float(value)
        return n if n == n else default
    except Exception:
        return default


def _local_bounds(volumes: list[dict[str, Any]]) -> dict[str, float]:
    origin = volumes[0]["ring"][0]
    xs: list[float] = []
    ys: list[float] = []
    zs = [0.0]
    for volume in volumes:
        for point in volume["ring"]:
            x, y = _to_local(point, origin)
            xs.append(x)
            ys.append(y)
        zs.extend([volume["bottom"], volume["top"]])
    return {
        "origin_lng": origin[0],
        "origin_lat": origin[1],
        "min_x": min(xs),
        "max_x": max(xs),
        "min_y": min(ys),
        "max_y": max(ys),
        "min_z": min(zs),
        "max_z": max(zs),
    }


def _to_local(point: list[float], origin: list[float]) -> tuple[float, float]:
    lat = origin[1]
    meters_per_lng = max(1.0, 111_320.0 * __import__("math").cos(lat * __import__("math").pi / 180.0))
    return (point[0] - origin[0]) * meters_per_lng, (point[1] - origin[1]) * 110_540.0


def _draw_panel(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    view: str,
    volumes: list[dict[str, Any]],
    bounds: dict[str, float],
    locked: dict[str, Any],
) -> None:
    x0, y0, x1, y1 = box
    draw.rounded_rectangle(box, radius=10, fill="#ffffff", outline="#cbd5e1", width=2)
    font = ImageFont.load_default()
    draw.text((x0 + 12, y0 + 10), view.upper(), fill="#0f172a", font=font)

    inner = (x0 + 24, y0 + 36, x1 - 24, y1 - 24)
    if view == "top":
        _draw_top(draw, inner, volumes, bounds)
    elif view == "axon":
        _draw_axon(draw, inner, volumes, bounds)
    else:
        _draw_elevation(draw, inner, view, volumes, bounds, locked)


def _draw_top(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], volumes: list[dict[str, Any]], bounds: dict[str, float]) -> None:
    x0, y0, x1, y1 = box
    scale = _scale(bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"], x1 - x0, y1 - y0)
    for idx, volume in enumerate(sorted(volumes, key=lambda v: v["top"])):
        pts = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            px = x0 + (lx - bounds["min_x"]) * scale + ((x1 - x0) - (bounds["max_x"] - bounds["min_x"]) * scale) / 2
            py = y1 - ((ly - bounds["min_y"]) * scale + ((y1 - y0) - (bounds["max_y"] - bounds["min_y"]) * scale) / 2)
            pts.append((px, py))
        draw.polygon(pts, fill=_fill(idx, 0.34), outline="#0f172a")


def _draw_elevation(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    view: str,
    volumes: list[dict[str, Any]],
    bounds: dict[str, float],
    locked: dict[str, Any],
) -> None:
    x0, y0, x1, y1 = box
    horizontal_key = "x" if view in {"front", "back"} else "y"
    if horizontal_key == "x":
        min_h, max_h = bounds["min_x"], bounds["max_x"]
    else:
        min_h, max_h = bounds["min_y"], bounds["max_y"]
    scale_x = (x1 - x0) * 0.82 / max(max_h - min_h, 1e-9)
    scale_z = (y1 - y0) * 0.82 / max(bounds["max_z"] - bounds["min_z"], 1e-9)
    used_x = (max_h - min_h) * scale_x
    used_z = (bounds["max_z"] - bounds["min_z"]) * scale_z
    offset_x = ((x1 - x0) - used_x) / 2
    offset_z = ((y1 - y0) - used_z) / 2
    for idx, volume in enumerate(sorted(volumes, key=lambda v: (v["bottom"], v["top"]))):
        vals = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            vals.append(lx if horizontal_key == "x" else ly)
        left = x0 + offset_x + (min(vals) - min_h) * scale_x
        right = x0 + offset_x + (max(vals) - min_h) * scale_x
        top = y1 - offset_z - (volume["top"] - bounds["min_z"]) * scale_z
        bottom = y1 - offset_z - (volume["bottom"] - bounds["min_z"]) * scale_z
        draw.rectangle((left, top, right, bottom), fill=_fill(idx, 0.46), outline="#0f172a", width=2)
    floors = int((locked.get("geometry_metrics") or {}).get("num_floors") or 0)
    if floors > 1:
        for i in range(1, min(floors, 24)):
            yy = y1 - offset_z - (bounds["max_z"] - bounds["min_z"]) * scale_z * i / floors
            draw.line((x0, yy, x1, yy), fill="#cbd5e1", width=1)


def _draw_axon(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], volumes: list[dict[str, Any]], bounds: dict[str, float]) -> None:
    x0, y0, x1, y1 = box
    sx = bounds["max_x"] - bounds["min_x"]
    sy = bounds["max_y"] - bounds["min_y"]
    sz = bounds["max_z"] - bounds["min_z"]
    scale = _scale(sx + sy * 0.45, sz + sy * 0.32, x1 - x0, y1 - y0)
    for idx, volume in enumerate(sorted(volumes, key=lambda v: v["bottom"])):
        top_pts = []
        bottom_pts = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            for z, target in ((volume["top"], top_pts), (volume["bottom"], bottom_pts)):
                px = x0 + (lx - bounds["min_x"] + (ly - bounds["min_y"]) * 0.45) * scale + 18
                py = y1 - ((z - bounds["min_z"]) + (ly - bounds["min_y"]) * 0.32) * scale - 12
                target.append((px, py))
        for i in range(len(top_pts)):
            j = (i + 1) % len(top_pts)
            draw.polygon([bottom_pts[i], bottom_pts[j], top_pts[j], top_pts[i]], fill=_fill(idx, 0.22), outline="#64748b")
        draw.polygon(top_pts, fill=_fill(idx, 0.42), outline="#0f172a")


def _scale(span_x: float, span_y: float, width: float, height: float) -> float:
    return max(0.1, min(width / max(span_x, 1e-9), height / max(span_y, 1e-9)) * 0.82)


def _fill(index: int, alpha: float) -> str:
    colors = ["#f59e0b", "#f97316", "#fb923c", "#fbbf24", "#d97706", "#fde68a"]
    return colors[index % len(colors)]


def _build_scene_graph(job: dict[str, Any], volumes: list[dict[str, Any]]) -> dict[str, Any]:
    nodes = [
        {"id": "site", "type": "Site"},
        {"id": "legal_envelope", "type": "LegalEnvelope"},
        {"id": "mass", "type": "BuildingMass", "candidate_id": job.get("candidate_id")},
    ]
    edges = [
        {"source": "mass", "target": "site", "relation": "sits_on"},
        {"source": "mass", "target": "legal_envelope", "relation": "constrained_by"},
    ]
    for idx, volume in enumerate(volumes):
        vid = f"volume_{idx + 1}"
        nodes.append({
            "id": vid,
            "type": "MassVolume",
            "role": volume.get("role"),
            "bottom_height": volume["bottom"],
            "top_height": volume["top"],
        })
        edges.append({"source": vid, "target": "mass", "relation": "part_of"})
        if idx > 0:
            edges.append({"source": vid, "target": f"volume_{idx}", "relation": "stacked_after"})
    for facade in ("front", "right", "back", "left"):
        nodes.append({"id": f"facade_{facade}", "type": "Facade", "view": facade})
        edges.append({"source": f"facade_{facade}", "target": "mass", "relation": "bounds"})
    return {"schema_version": "arr.maas.scene_graph.v0", "nodes": nodes, "edges": edges}


def _write_condition_pack(
    *,
    root: Path,
    digest: str,
    job: dict[str, Any],
    volumes: list[dict[str, Any]],
    bounds: dict[str, float],
    locked: dict[str, Any],
    scene_graph: dict[str, Any],
) -> dict[str, Any]:
    root.mkdir(parents=True, exist_ok=True)
    (root / "silhouette").mkdir(exist_ok=True)
    (root / "depth").mkdir(exist_ok=True)
    (root / "floor_guides").mkdir(exist_ok=True)

    camera_poses = _camera_poses(bounds)
    facade_planes = _facade_planes(volumes, bounds)
    projection_manifest = build_projection_manifest(volumes, bounds)
    _write_json(root / "scene_graph.json", scene_graph)
    _write_json(root / "camera_poses.json", camera_poses)
    _write_json(root / "facade_planes.json", facade_planes)
    _write_json(root / "projection_manifest.json", projection_manifest)

    views: dict[str, Any] = {}
    for view in VIEWS:
        views[view] = {}
        for layer in ("silhouette", "depth", "floor_guides"):
            path = root / layer / f"{view}.png"
            _render_condition_layer(path, layer, view, volumes, bounds, locked)
            views[view][layer] = {
                "uri": str(path),
                "media_type": "image/png",
                "sha256": _file_sha256(path),
            }

    return {
        "schema_version": "arr.maas.condition_pack.v0",
        "pack_id": f"maas-condition-pack:{digest}",
        "root_uri": str(root),
        "scene_graph": {"uri": str(root / "scene_graph.json"), "media_type": "application/json"},
        "camera_poses": {"uri": str(root / "camera_poses.json"), "media_type": "application/json"},
        "facade_planes": {"uri": str(root / "facade_planes.json"), "media_type": "application/json"},
        "projection_manifest": {"uri": str(root / "projection_manifest.json"), "media_type": "application/json"},
        "views": views,
        "notes": [
            "Deterministic MAAS geometry condition pack for image/texturing workers.",
            "Depth and floor guide layers are diagrammatic first-pass conditions, not photogrammetric render outputs.",
        ],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")


def _camera_poses(bounds: dict[str, float]) -> dict[str, Any]:
    cx = (bounds["min_x"] + bounds["max_x"]) / 2
    cy = (bounds["min_y"] + bounds["max_y"]) / 2
    cz = (bounds["min_z"] + bounds["max_z"]) / 2
    span = max(bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"], bounds["max_z"] - bounds["min_z"], 1.0)
    poses = {
        "front": {"position_m": [cx, bounds["min_y"] - span * 2, cz], "target_m": [cx, cy, cz], "projection": "orthographic"},
        "right": {"position_m": [bounds["max_x"] + span * 2, cy, cz], "target_m": [cx, cy, cz], "projection": "orthographic"},
        "back": {"position_m": [cx, bounds["max_y"] + span * 2, cz], "target_m": [cx, cy, cz], "projection": "orthographic"},
        "left": {"position_m": [bounds["min_x"] - span * 2, cy, cz], "target_m": [cx, cy, cz], "projection": "orthographic"},
        "axon": {"position_m": [bounds["max_x"] + span * 1.8, bounds["min_y"] - span * 1.8, bounds["max_z"] + span * 1.4], "target_m": [cx, cy, cz], "projection": "orthographic"},
        "top": {"position_m": [cx, cy, bounds["max_z"] + span * 3], "target_m": [cx, cy, cz], "projection": "orthographic"},
    }
    return {
        "schema_version": "arr.maas.camera_poses.v0",
        "coordinate_space": "local_meter_from_first_mass_point",
        "origin": {"lng": bounds["origin_lng"], "lat": bounds["origin_lat"]},
        "views": poses,
    }


def _facade_planes(volumes: list[dict[str, Any]], bounds: dict[str, float]) -> dict[str, Any]:
    min_z = min(v["bottom"] for v in volumes)
    max_z = max(v["top"] for v in volumes)
    planes = [
        {"id": "facade_front", "view": "front", "normal_m": [0, -1, 0], "extent_m": [bounds["min_x"], bounds["max_x"], min_z, max_z]},
        {"id": "facade_right", "view": "right", "normal_m": [1, 0, 0], "extent_m": [bounds["min_y"], bounds["max_y"], min_z, max_z]},
        {"id": "facade_back", "view": "back", "normal_m": [0, 1, 0], "extent_m": [bounds["min_x"], bounds["max_x"], min_z, max_z]},
        {"id": "facade_left", "view": "left", "normal_m": [-1, 0, 0], "extent_m": [bounds["min_y"], bounds["max_y"], min_z, max_z]},
    ]
    return {
        "schema_version": "arr.maas.facade_planes.v0",
        "coordinate_space": "local_meter_from_first_mass_point",
        "origin": {"lng": bounds["origin_lng"], "lat": bounds["origin_lat"]},
        "planes": planes,
    }


def _render_condition_layer(
    path: Path,
    layer: str,
    view: str,
    volumes: list[dict[str, Any]],
    bounds: dict[str, float],
    locked: dict[str, Any],
    *,
    size: int = 512,
) -> None:
    mode = "L"
    bg = 0 if layer == "silhouette" else 255
    image = Image.new(mode, (size, size), bg)
    draw = ImageDraw.Draw(image)
    box = (36, 36, size - 36, size - 36)
    if view == "top":
        _draw_top_condition(draw, box, volumes, bounds, layer)
    elif view == "axon":
        _draw_axon_condition(draw, box, volumes, bounds, layer)
    else:
        _draw_elevation_condition(draw, box, view, volumes, bounds, locked, layer)
    image.save(path)


def _condition_value(layer: str, idx: int, volumes: list[dict[str, Any]], volume: dict[str, Any]) -> int:
    if layer == "silhouette":
        return 255
    if layer == "depth":
        denominator = max(1.0, max(v["top"] for v in volumes))
        return int(230 - min(180, (volume["top"] / denominator) * 170))
    return 255


def _draw_top_condition(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], volumes: list[dict[str, Any]], bounds: dict[str, float], layer: str) -> None:
    x0, y0, x1, y1 = box
    scale = _scale(bounds["max_x"] - bounds["min_x"], bounds["max_y"] - bounds["min_y"], x1 - x0, y1 - y0)
    for idx, volume in enumerate(sorted(volumes, key=lambda v: v["top"])):
        pts = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            px = x0 + (lx - bounds["min_x"]) * scale + ((x1 - x0) - (bounds["max_x"] - bounds["min_x"]) * scale) / 2
            py = y1 - ((ly - bounds["min_y"]) * scale + ((y1 - y0) - (bounds["max_y"] - bounds["min_y"]) * scale) / 2)
            pts.append((px, py))
        draw.polygon(pts, fill=_condition_value(layer, idx, volumes, volume), outline=255 if layer == "floor_guides" else None)


def _draw_elevation_condition(
    draw: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    view: str,
    volumes: list[dict[str, Any]],
    bounds: dict[str, float],
    locked: dict[str, Any],
    layer: str,
) -> None:
    x0, y0, x1, y1 = box
    horizontal_key = "x" if view in {"front", "back"} else "y"
    min_h, max_h = (bounds["min_x"], bounds["max_x"]) if horizontal_key == "x" else (bounds["min_y"], bounds["max_y"])
    scale_x = (x1 - x0) * 0.82 / max(max_h - min_h, 1e-9)
    scale_z = (y1 - y0) * 0.82 / max(bounds["max_z"] - bounds["min_z"], 1e-9)
    used_x = (max_h - min_h) * scale_x
    used_z = (bounds["max_z"] - bounds["min_z"]) * scale_z
    offset_x = ((x1 - x0) - used_x) / 2
    offset_z = ((y1 - y0) - used_z) / 2
    for idx, volume in enumerate(sorted(volumes, key=lambda v: (v["bottom"], v["top"]))):
        vals = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            vals.append(lx if horizontal_key == "x" else ly)
        left = x0 + offset_x + (min(vals) - min_h) * scale_x
        right = x0 + offset_x + (max(vals) - min_h) * scale_x
        top = y1 - offset_z - (volume["top"] - bounds["min_z"]) * scale_z
        bottom = y1 - offset_z - (volume["bottom"] - bounds["min_z"]) * scale_z
        draw.rectangle((left, top, right, bottom), fill=_condition_value(layer, idx, volumes, volume), outline=255 if layer == "floor_guides" else None)
    if layer == "floor_guides":
        floors = int((locked.get("geometry_metrics") or {}).get("num_floors") or 0)
        if floors > 1:
            for i in range(1, min(floors, 32)):
                yy = y1 - offset_z - (bounds["max_z"] - bounds["min_z"]) * scale_z * i / floors
                draw.line((x0, yy, x1, yy), fill=0, width=2)


def _draw_axon_condition(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], volumes: list[dict[str, Any]], bounds: dict[str, float], layer: str) -> None:
    x0, y0, x1, y1 = box
    sx = bounds["max_x"] - bounds["min_x"]
    sy = bounds["max_y"] - bounds["min_y"]
    sz = bounds["max_z"] - bounds["min_z"]
    scale = _scale(sx + sy * 0.45, sz + sy * 0.32, x1 - x0, y1 - y0)
    for idx, volume in enumerate(sorted(volumes, key=lambda v: v["bottom"])):
        top_pts = []
        for point in volume["ring"]:
            lx, ly = _to_local(point, [bounds["origin_lng"], bounds["origin_lat"]])
            px = x0 + (lx - bounds["min_x"] + (ly - bounds["min_y"]) * 0.45) * scale + 12
            py = y1 - ((volume["top"] - bounds["min_z"]) + (ly - bounds["min_y"]) * 0.32) * scale - 8
            top_pts.append((px, py))
        draw.polygon(top_pts, fill=_condition_value(layer, idx, volumes, volume), outline=255 if layer == "floor_guides" else None)


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


__all__ = ["MultiViewReferencePackRenderer", "VIEWS"]
