from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Iterable
import xml.etree.ElementTree as ET


SUPPORTED_SHAPES = {"circle", "line", "polygon", "polyline", "rect"}
REQUIRED_ATTRIBUTES = {
    "circle": ("cx", "cy", "r"),
    "line": ("x1", "y1", "x2", "y2"),
    "polygon": ("points",),
    "polyline": ("points",),
    "rect": ("x", "y", "width", "height"),
}


def create_dxf_handoff(
    *,
    alternative_dir: Path,
    output_path: Path,
    drawing_path: str,
) -> dict[str, Any]:
    source_root = alternative_dir.resolve()
    report_path = source_root / "building.review.json"
    report = _read_json(report_path)
    floors = report.get("floors")
    if not isinstance(floors, list) or not floors:
        raise ValueError("building review has no floors")

    entities: list[str] = []
    sources: list[dict[str, Any]] = []
    cursor_x = 0.0
    for floor in floors:
        floor_index = int(floor["floor_index"])
        boundary = _points(floor["floor_boundary"]["polygon"])
        min_x, min_y, max_x, max_y = _bounds(boundary)
        width = max_x - min_x
        svg_relative = floor["artifacts"]["svg"]
        svg_path = _contained(source_root, svg_relative)
        svg_bytes = svg_path.read_bytes()
        root = ET.fromstring(svg_bytes)
        svg_boundary = next(
            (
                element
                for element in root.iter()
                if element.get("data-id") == "floor-boundary"
                and _tag(element) == "polygon"
            ),
            None,
        )
        if svg_boundary is None:
            raise ValueError(f"floor {floor_index} SVG has no floor boundary")
        svg_min_x, svg_min_y, svg_max_x, svg_max_y = _bounds(
            _svg_points(svg_boundary.get("points", ""))
        )
        if svg_max_x == svg_min_x or svg_max_y == svg_min_y:
            raise ValueError(f"floor {floor_index} SVG boundary is degenerate")

        def transform(x: float, y: float) -> tuple[float, float]:
            model_x = min_x + (x - svg_min_x) * (max_x - min_x) / (svg_max_x - svg_min_x)
            model_y = max_y - (y - svg_min_y) * (max_y - min_y) / (svg_max_y - svg_min_y)
            return model_x + cursor_x - min_x, model_y

        entities.extend(_svg_entities(root, floor_index, transform))
        sources.append(
            {
                "floor_index": floor_index,
                "svg": svg_relative,
                "sha256": sha256(svg_bytes).hexdigest(),
            }
        )
        cursor_x += width + 5.0

    output_path.parent.mkdir(parents=True, exist_ok=True)
    dxf = _dxf_document(entities)
    _atomic_write(output_path, dxf, encoding="ascii")
    result = {
        "contract_version": "planm-cad-handoff/v1",
        "alternative_id": source_root.name,
        "drawing_path": drawing_path,
        "source_floor_count": len(floors),
        "entity_count": len(entities),
        "units": "meters",
        "dwg_validation": "not_checked",
        "sources": sources,
    }
    _atomic_write(
        output_path.with_name("manifest.json"),
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _svg_entities(root: ET.Element, floor_index: int, transform) -> list[str]:
    entities: list[str] = []

    def visit(element: ET.Element, inherited_layer: str = "geometry") -> None:
        layer = element.get("data-layer", inherited_layer)
        tag = _tag(element)
        if tag in SUPPORTED_SHAPES and all(
            element.get(attribute) for attribute in REQUIRED_ATTRIBUTES[tag]
        ):
            dxf_layer = f"F{floor_index:03d}_{_layer_name(layer)}"
            if tag in {"polygon", "polyline"}:
                points = [transform(x, y) for x, y in _svg_points(element.get("points", ""))]
                entities.extend(_line_chain(points, dxf_layer, close=tag == "polygon"))
            elif tag == "line":
                start = transform(float(element.get("x1", "")), float(element.get("y1", "")))
                end = transform(float(element.get("x2", "")), float(element.get("y2", "")))
                entities.append(_line(start, end, dxf_layer))
            elif tag == "rect":
                x = float(element.get("x", ""))
                y = float(element.get("y", ""))
                width = float(element.get("width", ""))
                height = float(element.get("height", ""))
                points = [
                    transform(x, y),
                    transform(x + width, y),
                    transform(x + width, y + height),
                    transform(x, y + height),
                ]
                entities.extend(_line_chain(points, dxf_layer, close=True))
            elif tag == "circle":
                cx = float(element.get("cx", ""))
                cy = float(element.get("cy", ""))
                center = transform(cx, cy)
                edge = transform(cx + float(element.get("r", "")), cy)
                radius = abs(edge[0] - center[0])
                entities.append(_circle(center, radius, dxf_layer))
        for child in element:
            visit(child, layer)

    visit(root)
    return entities


def _dxf_document(entities: Iterable[str]) -> str:
    return "".join(
        [
            "0\nSECTION\n2\nHEADER\n9\n$ACADVER\n1\nAC1009\n",
            "9\n$INSUNITS\n70\n6\n0\nENDSEC\n",
            "0\nSECTION\n2\nENTITIES\n",
            *entities,
            "0\nENDSEC\n0\nEOF\n",
        ]
    )


def _line(start: tuple[float, float], end: tuple[float, float], layer: str) -> str:
    return (
        f"0\nLINE\n8\n{layer}\n10\n{start[0]:.6f}\n20\n{start[1]:.6f}\n30\n0\n"
        f"11\n{end[0]:.6f}\n21\n{end[1]:.6f}\n31\n0\n"
    )


def _circle(center: tuple[float, float], radius: float, layer: str) -> str:
    return (
        f"0\nCIRCLE\n8\n{layer}\n10\n{center[0]:.6f}\n20\n{center[1]:.6f}\n"
        f"30\n0\n40\n{radius:.6f}\n"
    )


def _line_chain(
    points: list[tuple[float, float]], layer: str, *, close: bool
) -> list[str]:
    if len(points) < 2:
        return []
    pairs = list(zip(points, points[1:]))
    if close and points[-1] != points[0]:
        pairs.append((points[-1], points[0]))
    return [_line(start, end, layer) for start, end in pairs]


def _tag(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1]


def _layer_name(value: str) -> str:
    normalized = re.sub(r"[^A-Z0-9_]+", "_", value.upper()).strip("_")
    return (normalized or "GEOMETRY")[:48]


def _svg_points(value: str) -> list[tuple[float, float]]:
    numbers = [float(item) for item in re.findall(r"[-+]?(?:\d*\.\d+|\d+)(?:[eE][-+]?\d+)?", value)]
    if len(numbers) % 2:
        raise ValueError("SVG points contain an unmatched coordinate")
    return list(zip(numbers[::2], numbers[1::2]))


def _points(value: Any) -> list[tuple[float, float]]:
    if not isinstance(value, list):
        raise ValueError("floor boundary polygon is invalid")
    return [(float(point[0]), float(point[1])) for point in value]


def _bounds(points: list[tuple[float, float]]) -> tuple[float, float, float, float]:
    if not points:
        raise ValueError("geometry has no points")
    xs, ys = zip(*points)
    return min(xs), min(ys), max(xs), max(ys)


def _contained(root: Path, relative_path: str) -> Path:
    candidate = (root / relative_path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as error:
        raise ValueError("review artifact path escapes the alternative") from error
    if not candidate.is_file():
        raise ValueError(f"review artifact does not exist: {relative_path}")
    return candidate


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("building review must be a JSON object")
    return value


def _atomic_write(path: Path, value: str, *, encoding: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(value, encoding=encoding)
    temporary.replace(path)
