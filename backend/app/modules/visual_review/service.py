from __future__ import annotations

import json
from pathlib import Path

from backend.app.core.serialization import to_jsonable
from backend.app.schemas.result import GenerationResult
from backend.app.schemas.visual import VisualReviewArtifacts
from engine.geometry.polygon import bounds
from engine.io.png import SimplePngCanvas

PALETTE = {
    "shop_unit": "#d9ead3",
    "office_area": "#cfe2f3",
    "core": "#f4cccc",
    "restroom": "#d9d2e9",
    "storage": "#fff2cc",
    "utility": "#ead1dc",
    "pantry": "#d0e0e3",
    "ps_eps": "#fce5cd",
}

PNG_PALETTE = {
    "shop_unit": (217, 234, 211),
    "office_area": (207, 226, 243),
    "core": (244, 204, 204),
    "restroom": (217, 210, 233),
    "storage": (255, 242, 204),
    "utility": (234, 209, 220),
    "pantry": (208, 224, 227),
    "ps_eps": (252, 229, 205),
}


def create_visual_review_artifacts(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    output_dir: str | Path,
    width: int = 960,
    height: int = 540,
) -> VisualReviewArtifacts:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)

    stem = f"{result.mass.project_id}-f{result.program.floor_index}"
    svg_path = target / f"{stem}.svg"
    png_path = target / f"{stem}.png"
    html_path = target / f"{stem}.html"
    report_path = target / f"{stem}.review.json"

    svg_path.write_text(_render_svg(result, boundary, width, height), encoding="utf-8")
    png_path.write_bytes(_render_png(result, boundary, width, height))

    checks = {
        "boundary": "pass" if result.validation.boundary_score == 1 else "fail",
        "overlap": "pass" if result.validation.overlap_score == 1 else "fail",
        "area": "pass" if result.validation.area_score == 1 else "fail",
        "efficiency": "pass" if result.validation.efficiency_score >= 0.85 else "fail",
    }
    needs_iteration = any(value == "fail" for value in checks.values())
    report = {
        "project_id": result.mass.project_id,
        "floor_index": result.program.floor_index,
        "use_type": result.program.use_type,
        "needs_iteration": needs_iteration,
        "checks": checks,
        "validation": to_jsonable(result.validation),
        "artifacts": {
            "svg": str(svg_path),
            "png": str(png_path),
            "html": str(html_path),
        },
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    html_path.write_text(_render_html(result, svg_path.name, png_path.name, report_path.name, report), encoding="utf-8")

    return VisualReviewArtifacts(
        svg_path=svg_path,
        png_path=png_path,
        html_path=html_path,
        report_path=report_path,
        needs_iteration=needs_iteration,
        checks=checks,
    )


def _render_svg(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> str:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="white"/>',
    ]
    for room in result.layout.rooms:
        points = " ".join(
            f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in room.polygon
        )
        fill = PALETTE.get(room.space_type, "#eeeeee")
        parts.append(f'<polygon points="{points}" fill="{fill}" stroke="#111111" stroke-width="2"/>')
        cx, cy = _centroid(room.polygon)
        parts.append(
            f'<text x="{_sx(cx, min_x, scale, pad_x)}" y="{_sy(cy, min_y, scale, pad_y, height)}" '
            f'font-family="Arial" font-size="14" text-anchor="middle">{room.space_type}</text>'
        )
    boundary_points = " ".join(
        f"{_sx(x, min_x, scale, pad_x)},{_sy(y, min_y, scale, pad_y, height)}" for x, y in boundary
    )
    parts.append(f'<polygon points="{boundary_points}" fill="none" stroke="#000000" stroke-width="4"/>')
    parts.append("</svg>")
    return "\n".join(parts)


def _render_png(
    result: GenerationResult,
    boundary: list[tuple[float, float]],
    width: int,
    height: int,
) -> bytes:
    min_x, min_y, max_x, max_y = bounds(boundary)
    scale, pad_x, pad_y = _fit_transform(min_x, min_y, max_x, max_y, width, height)
    canvas = SimplePngCanvas(width, height)
    for room in result.layout.rooms:
        x0, y0, x1, y1 = bounds(room.polygon)
        left = int(_sx(x0, min_x, scale, pad_x))
        right = int(_sx(x1, min_x, scale, pad_x))
        top = int(_sy(y1, min_y, scale, pad_y, height))
        bottom = int(_sy(y0, min_y, scale, pad_y, height))
        color = PNG_PALETTE.get(room.space_type, (238, 238, 238))
        canvas.fill_rect(left, top, right, bottom, color)
        canvas.stroke_rect(left, top, right, bottom, (17, 17, 17), thickness=2)
    b_left = int(_sx(min_x, min_x, scale, pad_x))
    b_right = int(_sx(max_x, min_x, scale, pad_x))
    b_top = int(_sy(max_y, min_y, scale, pad_y, height))
    b_bottom = int(_sy(min_y, min_y, scale, pad_y, height))
    canvas.stroke_rect(b_left, b_top, b_right, b_bottom, (0, 0, 0), thickness=4)
    return canvas.to_bytes()


def _render_html(
    result: GenerationResult,
    svg_name: str,
    png_name: str,
    report_name: str,
    report: dict,
) -> str:
    status = "needs iteration" if report["needs_iteration"] else "passes baseline checks"
    checks = "".join(f"<tr><td>{name}</td><td>{value}</td></tr>" for name, value in report["checks"].items())
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{result.mass.project_id} floor visual review</title>
  <style>
    body {{ margin: 24px; font-family: Arial, sans-serif; background: white; color: #111; }}
    main {{ max-width: 1180px; margin: 0 auto; }}
    h1 {{ font-size: 22px; margin: 0 0 12px; }}
    .status {{ margin-bottom: 18px; font-weight: 700; }}
    .grid {{ display: grid; grid-template-columns: 2fr 1fr; gap: 20px; align-items: start; }}
    iframe {{ width: 100%; height: 620px; border: 1px solid #ccc; }}
    table {{ border-collapse: collapse; width: 100%; }}
    td {{ border-bottom: 1px solid #ddd; padding: 8px 6px; }}
    a {{ color: #0645ad; }}
  </style>
</head>
<body>
  <main>
    <h1>Visual Review: {result.mass.project_id} F{result.program.floor_index}</h1>
    <div class="status">{status}</div>
    <div class="grid">
      <iframe src="{svg_name}" title="floor plan svg"></iframe>
      <section>
        <table>{checks}</table>
        <p><a href="{png_name}">PNG</a></p>
        <p><a href="{report_name}">Review JSON</a></p>
      </section>
    </div>
  </main>
</body>
</html>
"""


def _fit_transform(
    min_x: float,
    min_y: float,
    max_x: float,
    max_y: float,
    width: int,
    height: int,
) -> tuple[float, float, float]:
    drawing_width = max_x - min_x
    drawing_height = max_y - min_y
    scale = min((width * 0.86) / drawing_width, (height * 0.82) / drawing_height)
    pad_x = (width - drawing_width * scale) / 2
    pad_y = (height - drawing_height * scale) / 2
    return scale, pad_x, pad_y


def _sx(x: float, min_x: float, scale: float, pad_x: float) -> float:
    return round((x - min_x) * scale + pad_x, 2)


def _sy(y: float, min_y: float, scale: float, pad_y: float, height: int) -> float:
    return round(height - ((y - min_y) * scale + pad_y), 2)


def _centroid(points: list[tuple[float, float]]) -> tuple[float, float]:
    return (
        sum(point[0] for point in points) / len(points),
        sum(point[1] for point in points) / len(points),
    )
