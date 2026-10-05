"""
Floor Graph2Plan — GNN-based floor plan generation.

Wraps the Graph2Plan model (SIGGRAPH 2020, Hu et al.) for inference.
Converts room adjacency graph + boundary → room bounding boxes → GeoJSON.

Model source: clone/Graph2Plan/Interface/model/
Requires: torch, opencv-python, scipy

Unlike grid-based algorithms (GA/Subdivision/MCTS/Packing), this produces
continuous bounding boxes — rooms can be non-grid-aligned polygons.
"""

from backend.app.modules.design.generation import paths as _design_paths

import logging
import os
import subprocess
from pathlib import Path

import numpy as np

from shapely.geometry import Polygon, box as shapely_box, mapping

logger = logging.getLogger(__name__)

# Graph2Plan model directory
from backend.app.modules.design.generation.services.graph2plan_runtime import model_directory

_G2P_ROOT = model_directory()
_MODEL_PATH = _G2P_ROOT / "model" / "model.pth"

# Room type mapping: our room names → Graph2Plan room indices
# Graph2Plan vocab: 0=LivingRoom, 1=MasterRoom, 2=Kitchen, 3=Bathroom,
# 4=DiningRoom, 5=ChildRoom, 6=StudyRoom, 7=SecondRoom, 8=GuestRoom,
# 9=Balcony, 10=Entrance, 11=Storage, 12=Wall-in
_ROOM_NAME_TO_IDX = {
    "거실": 0, "livingroom": 0, "living": 0,
    "안방": 1, "masterroom": 1, "master": 1, "주침실": 1,
    "주방": 2, "kitchen": 2,
    "화장실": 3, "bathroom": 3, "욕실": 3,
    "식당": 4, "diningroom": 4, "dining": 4,
    "아이방": 5, "childroom": 5, "child": 5,
    "서재": 6, "studyroom": 6, "study": 6,
    "침실2": 7, "secondroom": 7, "bedroom": 7,
    "침실3": 8, "guestroom": 8, "guest": 8,
    "발코니": 9, "balcony": 9,
    "현관": 10, "entrance": 10,
    "창고": 11, "storage": 11,
    "드레스룸": 12, "walkin": 12, "closet": 12,
}

_IDX_TO_ROOM_NAME = {
    0: "거실", 1: "안방", 2: "주방", 3: "화장실",
    4: "식당", 5: "아이방", 6: "서재", 7: "침실2",
    8: "침실3", 9: "발코니", 10: "현관", 11: "창고", 12: "드레스룸",
}

_ROOM_COLORS = {
    0: "#dcd5cd", 1: "#8a715b", 2: "#f4f5f7", 3: "#e0e1e3",
    4: "#c8c1b9", 5: "#c6ad97", 6: "#b29983", 7: "#9e856f",
    8: "#bdac92", 9: "#f4ede0", 10: "#eeeee6", 11: "#e2dcce",
    12: "#e2dcce",
}

# Adjacency relation indices (from Graph2Plan vocab)
_PRED_ADJACENT = 1  # "adjacent" predicate index


def _check_torch():
    """Lazy-check torch availability."""
    try:
        import torch
        return torch
    except ImportError:
        return None


_model_cache = None


def _load_model():
    """Load pretrained Graph2Plan model (cached singleton)."""
    global _model_cache
    if _model_cache is not None:
        return _model_cache

    torch = _check_torch()
    if torch is None:
        raise RuntimeError("PyTorch not installed. Install with: pip install torch")

    if not _MODEL_PATH.exists():
        raise FileNotFoundError(f"Graph2Plan model not found at {_MODEL_PATH}")

    from model.model import Model
    model = Model()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    state = torch.load(str(_MODEL_PATH), map_location=device, weights_only=True)
    model.load_state_dict(state)
    model.to(device)
    model.eval()

    _model_cache = (model, device)
    logger.info(f"Graph2Plan model loaded on {device}")
    return _model_cache


def _rooms_to_graph(rooms_def):
    """
    Convert our room definitions to Graph2Plan graph format.

    Args:
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]

    Returns:
        (rooms_tensor, triples_tensor, attrs) for model input
    """
    torch = _check_torch()

    room_indices = []
    name_to_idx_map = {}

    for i, r in enumerate(rooms_def):
        name = r["name"].lower().strip()
        g2p_idx = _ROOM_NAME_TO_IDX.get(name, 7)  # default to SecondRoom
        room_indices.append(g2p_idx)
        name_to_idx_map[r["name"]] = i

    # Build triples: [subject_idx, predicate, object_idx]
    triples = []
    seen = set()
    for i, r in enumerate(rooms_def):
        for adj_name in r.get("adjacency", []):
            j = name_to_idx_map.get(adj_name)
            if j is not None and (i, j) not in seen:
                triples.append([i, _PRED_ADJACENT, j])
                seen.add((i, j))
                seen.add((j, i))

    if not triples:
        # Fallback: connect all rooms linearly
        for i in range(len(rooms_def) - 1):
            triples.append([i, _PRED_ADJACENT, i + 1])

    if torch is None:
        # Utility tests and offline fallback should not require PyTorch. The
        # full Graph2Plan inference path checks torch before calling this.
        return np.array(room_indices, dtype=np.int64), np.array(triples, dtype=np.int64).reshape(-1, 3)

    rooms_t = torch.tensor(room_indices, dtype=torch.long)
    triples_t = torch.tensor(triples, dtype=torch.long).reshape(-1, 3)

    return rooms_t, triples_t


def _boundary_to_image(footprint_coords, image_size=128):
    """
    Convert footprint boundary to Graph2Plan's 3-channel input image.

    Channel 0: inside mask
    Channel 1: boundary outline
    Channel 2: front door (first two vertices = door)
    """
    try:
        import cv2
    except ImportError:
        raise RuntimeError("OpenCV not installed. Install with: pip install opencv-python")

    torch = _check_torch()

    # Normalize coordinates to 0-255 range (Graph2Plan expects 256x256 boundary)
    coords = np.array(footprint_coords)
    min_c = coords.min(axis=0)
    max_c = coords.max(axis=0)
    span = max_c - min_c
    span[span < 1e-6] = 1.0

    # Scale to 10-245 range (leaving margin)
    scaled = ((coords - min_c) / span * 235 + 10).astype(np.int32)

    boundary_img = np.zeros((image_size, image_size), dtype=np.float32)
    inside_img = np.zeros((image_size, image_size), dtype=np.float32)
    front_img = np.zeros((image_size, image_size), dtype=np.float32)

    # Scale to half for 128x128
    pts = (scaled // 2).reshape(1, -1, 2)

    cv2.fillPoly(inside_img, pts, 1.0)
    cv2.polylines(boundary_img, pts, True, 1.0, 3)

    # First two points = front door
    door_pts = (scaled[:2] // 2).reshape(1, -1, 2)
    cv2.polylines(front_img, door_pts, True, 1.0, 3)

    input_image = np.stack([inside_img, boundary_img, front_img], axis=0)
    return torch.tensor(input_image).float()


def _boxes_to_geojson(boxes_np, room_indices, footprint, rooms_def):
    """
    Convert predicted bounding boxes to GeoJSON FeatureCollection.

    boxes_np: (N, 4) in normalized [x0, y0, x1, y1] format
    """
    coords = list(footprint.exterior.coords)
    min_x = min(c[0] for c in coords)
    min_y = min(c[1] for c in coords)
    max_x = max(c[0] for c in coords)
    max_y = max(c[1] for c in coords)

    span_x = max_x - min_x
    span_y = max_y - min_y

    features = []
    for i, (bx, room_idx) in enumerate(zip(boxes_np, room_indices)):
        # Convert normalized box to real coordinates
        x0 = min_x + bx[0] * span_x
        y0 = min_y + bx[1] * span_y
        x1 = min_x + bx[2] * span_x
        y1 = min_y + bx[3] * span_y

        room_poly = shapely_box(x0, y0, x1, y1)
        # Clip to footprint
        clipped = room_poly.intersection(footprint)
        if clipped.is_empty:
            continue

        room_name = _IDX_TO_ROOM_NAME.get(room_idx, f"Room{i}")
        color = _ROOM_COLORS.get(room_idx, "#cccccc")

        # Match with input room def for area info
        area_target = 0
        if i < len(rooms_def):
            area_target = rooms_def[i].get("area", 0)
            room_name = rooms_def[i].get("name", room_name)

        features.append({
            "type": "Feature",
            "properties": {
                "room_code": int(room_idx),
                "room_name": room_name,
                "color": color,
                "area_m2": round(float(clipped.area), 2),
                "area_target_m2": float(area_target),
            },
            "geometry": mapping(clipped),
        })

    return {
        "type": "FeatureCollection",
        "features": features,
    }


def generate_graph2plan(footprint, rooms_def, options=None):
    """
    Generate floor plan using Graph2Plan GNN model.

    Args:
        footprint: Shapely Polygon (site boundary in real coords)
        rooms_def: [{"name": str, "area": float, "adjacency": [str]}]
        options: {"num_variants": int} (default 1 — GNN is deterministic)

    Returns:
        dict compatible with FloorPlanResult TS interface
    """
    options = options or {}
    num_variants = options.get("num_variants", 1)

    if os.environ.get("EDITOR_GRAPH2PLAN_WORKER") != "1":
        from backend.app.modules.design.generation.services.graph2plan_runtime import infer
        try:
            return infer(footprint, rooms_def, options)
        except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
            return _fallback_result(footprint, rooms_def, str(exc))

    torch = _check_torch()
    if torch is None:
        return _fallback_result(footprint, rooms_def, "PyTorch not available")

    try:
        model, device = _load_model()
    except (FileNotFoundError, RuntimeError, ImportError) as e:
        return _fallback_result(footprint, rooms_def, str(e))

    # Prepare inputs
    coords = list(footprint.exterior.coords[:-1])  # drop closing point
    rooms_t, triples_t = _rooms_to_graph(rooms_def)
    boundary_img = _boundary_to_image(coords)

    # Compute inside box (bounding box in normalized form)
    inside_box = torch.tensor([[0.0, 0.0, 1.0, 1.0]])

    # Prepare attributes (simplified — position encoding)
    num_rooms = len(rooms_def)
    attrs = torch.zeros(num_rooms, 35)  # 35-dim attribute vector

    results = []

    with torch.no_grad():
        # Move to device
        boundary_img = boundary_img.unsqueeze(0).to(device)
        inside_box = inside_box.to(device)
        rooms_t = rooms_t.to(device)
        triples_t = triples_t.to(device)
        attrs = attrs.to(device)

        for variant in range(num_variants):
            try:
                model_out = model(
                    rooms_t, triples_t, boundary_img,
                    obj_to_img=None,
                    attributes=attrs,
                    boxes_gt=None,
                    generate=True,
                    refine=True,
                    relative=True,
                    inside_box=inside_box,
                )
                boxes_pred, gene_layout, boxes_refine = model_out

                # Use refined boxes
                boxes = boxes_refine.detach().cpu().numpy().squeeze()

                # Convert from center format to extent format
                if boxes.ndim == 1:
                    boxes = boxes.reshape(1, -1)
                # boxes are [cx, cy, w, h] → [x0, y0, x1, y1]
                x0 = boxes[:, 0] - boxes[:, 2] / 2
                y0 = boxes[:, 1] - boxes[:, 3] / 2
                x1 = boxes[:, 0] + boxes[:, 2] / 2
                y1 = boxes[:, 1] + boxes[:, 3] / 2
                boxes_extent = np.stack([x0, y0, x1, y1], axis=1)

                # Clip to [0, 1]
                boxes_extent = np.clip(boxes_extent, 0, 1)

                room_indices = rooms_t.cpu().numpy().tolist()
                floor_plan = _boxes_to_geojson(
                    boxes_extent, room_indices, footprint, rooms_def,
                )

                # Compute metrics
                adj_score = _compute_adjacency_score(
                    boxes_extent, rooms_def, footprint,
                )
                area_error = _compute_area_error(
                    boxes_extent, rooms_def, footprint,
                )

                results.append({
                    "design_id": variant,
                    "metrics": {
                        "adjacency_score": round(float(adj_score), 3),
                        "area_error": round(float(area_error), 3),
                        "compactness": 0.8,
                    },
                    "floor_plan": floor_plan,
                })

            except Exception as e:
                logger.warning(f"Graph2Plan variant {variant} failed: {e}")
                continue

    if not results:
        return _fallback_result(footprint, rooms_def, "Model inference failed")

    return {
        "algorithm": "graph2plan",
        "grid_info": {
            "rows": 0, "cols": 0, "cell_size": 0,
            "active_cells": 0,
        },
        "rooms": rooms_def,
        "num_results": len(results),
        "results": results,
    }


def _compute_adjacency_score(boxes, rooms_def, footprint):
    """Check how many adjacency requirements are met (boxes touch)."""
    if not rooms_def:
        return 1.0

    coords = list(footprint.exterior.coords)
    min_x = min(c[0] for c in coords)
    min_y = min(c[1] for c in coords)
    span_x = max(c[0] for c in coords) - min_x
    span_y = max(c[1] for c in coords) - min_y

    name_to_idx = {r["name"]: i for i, r in enumerate(rooms_def)}

    total_adj = 0
    met_adj = 0

    for i, r in enumerate(rooms_def):
        for adj_name in r.get("adjacency", []):
            j = name_to_idx.get(adj_name)
            if j is None or j <= i:
                continue
            total_adj += 1

            if i < len(boxes) and j < len(boxes):
                # Check if boxes overlap or touch (expanded by 2% tolerance)
                bi = boxes[i]
                bj = boxes[j]
                tol = 0.02
                if (bi[0] - tol <= bj[2] and bi[2] + tol >= bj[0] and
                    bi[1] - tol <= bj[3] and bi[3] + tol >= bj[1]):
                    met_adj += 1

    return met_adj / total_adj if total_adj > 0 else 1.0


def _compute_area_error(boxes, rooms_def, footprint):
    """Mean absolute area error vs targets."""
    if not rooms_def:
        return 0.0

    fp_area = footprint.area
    errors = []
    for i, r in enumerate(rooms_def):
        target = r.get("area", 0)
        if target <= 0 or i >= len(boxes):
            continue
        bx = boxes[i]
        # Box area as fraction of footprint
        box_w = (bx[2] - bx[0])
        box_h = (bx[3] - bx[1])
        actual = box_w * box_h * fp_area
        errors.append(abs(actual - target) / target)

    return sum(errors) / len(errors) if errors else 0.0


def _fallback_result(footprint, rooms_def, error_msg):
    """Return empty result with error when model unavailable."""
    logger.warning(f"Graph2Plan fallback: {error_msg}")
    return {
        "algorithm": "graph2plan",
        "grid_info": {"rows": 0, "cols": 0, "cell_size": 0, "active_cells": 0},
        "rooms": rooms_def,
        "num_results": 0,
        "results": [],
        "error": error_msg,
    }
