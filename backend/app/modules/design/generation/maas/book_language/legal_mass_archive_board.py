"""Selection-independent board for immutable legal MASS archive records."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from math import cos, isfinite, radians, sin
from pathlib import Path
import re
from typing import Any, Mapping, Sequence

from PIL import Image, ImageDraw, ImageFont

from backend.app.modules.design.generation.maas.preference.loop import _opaque_profiled_surface_fill
from backend.app.modules.design.generation.maas.preference.mesh_rasterizer import RasterTriangle, rasterize_depth_tested_triangles
from backend.app.modules.design.generation.maas.book_language.legal_mass_archive import _final_surface_payload_hash

from backend.app.modules.design.generation.maas.book_language.archive_layout import ARCHIVE_CARD_HEIGHT, ARCHIVE_CARD_WIDTH, ARCHIVE_COLUMNS, ARCHIVE_HEADER_HEIGHT, ARCHIVE_PREVIEW_HEIGHT


def render_legal_mass_archive_board(
    *,
    output_dir: Path,
    program_slug: str,
    target_count: int,
    selected_count: int,
    archive_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Render only certified archive surfaces and return manifest-ready evidence."""

    records = [dict(record) for record in archive_records if isinstance(record, Mapping)]
    safe_program = re.sub(r"[^A-Za-z0-9_.-]+", "-", str(program_slug)).strip("-") or "program"
    output_path = Path(output_dir).resolve() / (
        f"maas-book-{safe_program}-{int(target_count)}-legal-archive.png"
    )
    row_count = max(1, (len(records) + ARCHIVE_COLUMNS - 1) // ARCHIVE_COLUMNS)
    canvas = Image.new(
        "RGB",
        (ARCHIVE_CARD_WIDTH * ARCHIVE_COLUMNS, ARCHIVE_HEADER_HEIGHT + ARCHIVE_CARD_HEIGHT * row_count),
        "#07111f",
    )
    draw = ImageDraw.Draw(canvas)
    try:
        title_font = ImageFont.truetype("C:/Windows/Fonts/malgunbd.ttf", 22)
        label_font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 12)
        note_font = ImageFont.truetype("C:/Windows/Fonts/malgun.ttf", 10)
    except OSError:
        title_font = label_font = note_font = ImageFont.load_default()
    draw.text(
        (24, 20),
        f"MAAS legal archive: {safe_program} ({len(records)} archived / {selected_count}/{int(target_count)} selected)",
        fill="#f8fafc",
        font=title_font,
    )

    cards: list[dict[str, Any]] = []
    for index, record in enumerate(records, start=1):
        surfaces = _validated_archive_surfaces(record)
        preview, visible_pixels = _render_exact_surface_preview(surfaces)
        x = (index - 1) % ARCHIVE_COLUMNS * ARCHIVE_CARD_WIDTH
        y = ARCHIVE_HEADER_HEIGHT + (index - 1) // ARCHIVE_COLUMNS * ARCHIVE_CARD_HEIGHT
        canvas.paste(preview, (x, y))
        visible_ratio = visible_pixels / float(preview.width * preview.height)
        card = _card_evidence(record, index=index, visible_pixels=visible_pixels, visible_ratio=visible_ratio)
        cards.append(card)
        draw.rectangle((x, y + ARCHIVE_PREVIEW_HEIGHT, x + ARCHIVE_CARD_WIDTH, y + ARCHIVE_CARD_HEIGHT), fill="#3f1d26")
        draw.text((x + 10, y + 264), f"{index:02d} UTIL {card['utilization']:.0%} | CAPACITY {card['capacity_status'].upper()}", fill="#f8fafc", font=label_font)
        draw.text((x + 10, y + 280), f"PARKING {card['parking_status'].upper()} | VLM {card['vlm_status'].upper()}", fill="#f8fafc", font=note_font)
        draw.text((x + 10, y + 296), f"NOT SELECTED: {card['non_selection_reason']}", fill="#fda4af", font=note_font)
        draw.text((x + 10, y + 308), f"{card['geometry_hash'][:12]} {card['program_hash'][:12]} {card['source_surface_payload_hash'][:12]}", fill="#cbd5e1", font=note_font)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path)
    png_bytes = output_path.read_bytes()
    return {
        "schema_version": "arr.maas.legal_mass_archive_board.v1",
        "selection_effect": "none_archive_only",
        "program_slug": str(program_slug),
        "target_count": int(target_count),
        "selected_count": int(selected_count),
        "card_count": len(cards),
        "visible_mass_pixel_ratio": (
            sum(card["visible_mass_pixels"] for card in cards)
            / float(sum(ARCHIVE_CARD_WIDTH * ARCHIVE_PREVIEW_HEIGHT for _ in cards) or 1)
        ),
        "png_path": str(output_path),
        "png_sha256": hashlib.sha256(png_bytes).hexdigest(),
        "archive_record_identities": [card["archive_record_identity"] for card in cards],
        "cards": cards,
    }


def _validated_archive_surfaces(
    record: Mapping[str, Any],
) -> list[dict[str, Any]]:
    surfaces = deepcopy(record.get("final_authored_surface_payload"))
    if not isinstance(surfaces, list) or not surfaces:
        raise ValueError("legal archive record has no certified final surfaces")
    expected_hash = str(record.get("final_surface_payload_hash") or "")
    try:
        actual_hash = _final_surface_payload_hash(surfaces)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"legal archive surface payload is not canonical: {exc}") from None
    if not expected_hash or actual_hash != expected_hash:
        raise ValueError("legal archive surface payload hash mismatch")
    for surface in surfaces:
        if not isinstance(surface, dict):
            raise ValueError("legal archive record has invalid certified surface")
        vertices = surface.get("vertices_m")
        if not isinstance(vertices, list) or len(vertices) != 3:
            raise ValueError("legal archive record has non-triangle certified surface")
        for vertex in vertices:
            if not isinstance(vertex, (list, tuple)) or len(vertex) != 3:
                raise ValueError("legal archive record has invalid certified surface vertices")
            coordinates = tuple(float(value) for value in vertex)
            if not all(isfinite(value) for value in coordinates):
                raise ValueError("legal archive record has non-finite certified surface vertices")
    return surfaces


def _render_exact_surface_preview(
    surfaces: Sequence[Mapping[str, Any]],
) -> tuple[Image.Image, int]:
    """Rasterize archived triangles directly, without a footprint or volume proxy."""

    width, height = ARCHIVE_CARD_WIDTH, ARCHIVE_PREVIEW_HEIGHT
    view_width, view_height = width // 2, height // 2
    image = Image.new("RGB", (width, height), "#f7f9fb")
    draw = ImageDraw.Draw(image, "RGBA")
    covered_pixels = 0
    views = (
        ("isometric", 35.0, False, 0, 0),
        ("opposite", 215.0, False, view_width, 0),
        ("front", 0.0, False, 0, view_height),
        ("top", 0.0, True, view_width, view_height),
    )
    for label, angle, top_view, origin_x, origin_y in views:
        theta = radians(angle)
        transformed: list[tuple[Mapping[str, Any], list[tuple[float, float, float]]]] = []
        all_points: list[tuple[float, float]] = []
        for surface in surfaces:
            projected_vertices = []
            for x, y, z in surface["vertices_m"]:
                rotated_x = float(x) * cos(theta) - float(y) * sin(theta)
                rotated_y = float(x) * sin(theta) + float(y) * cos(theta)
                vertical = -rotated_y if top_view else rotated_y * 0.34 - float(z)
                projected_vertices.append((rotated_x, vertical, rotated_y + float(z) * 0.12))
                all_points.append((rotated_x, vertical))
            transformed.append((surface, projected_vertices))
        min_x = min(point[0] for point in all_points)
        max_x = max(point[0] for point in all_points)
        min_y = min(point[1] for point in all_points)
        max_y = max(point[1] for point in all_points)
        scale = min(
            (view_width - 28) / max(max_x - min_x, 1e-9),
            (view_height - 28) / max(max_y - min_y, 1e-9),
        )
        center_x = (min_x + max_x) / 2.0
        center_y = (min_y + max_y) / 2.0
        triangles = []
        for surface, vertices in transformed:
            screen_points = tuple(
                (
                    origin_x + view_width / 2.0 + (x - center_x) * scale,
                    origin_y + view_height / 2.0 + (y - center_y) * scale,
                )
                for x, y, _depth in vertices
            )
            color = tuple(int(value) for value in _opaque_profiled_surface_fill(
                surface["vertices_m"]
            ))
            triangles.append(RasterTriangle(
                points=screen_points,
                depths=tuple(vertex[2] for vertex in vertices),
                color=color if len(color) == 4 else (*color, 255),
            ))
        draw.rectangle(
            (origin_x + 3, origin_y + 3, origin_x + view_width - 3, origin_y + view_height - 3),
            outline=(203, 213, 225, 255),
        )
        covered_pixels += rasterize_depth_tested_triangles(
            image,
            triangles,
            clip_box=(
                origin_x + 4,
                origin_y + 4,
                origin_x + view_width - 4,
                origin_y + view_height - 4,
            ),
        )
        draw.text((origin_x + 8, origin_y + 7), label, fill=(71, 85, 105, 255))
    return image, covered_pixels


def _card_evidence(record: Mapping[str, Any], *, index: int, visible_pixels: int, visible_ratio: float) -> dict[str, Any]:
    capacity = record.get("capacity_evidence") if isinstance(record.get("capacity_evidence"), Mapping) else {}
    status = str(capacity.get("capacity_objective_status") or "not_selected")
    return {
        "card_index": index,
        "archive_record_identity": ":".join((str(record.get("geometry_hash") or ""), str(record.get("program_hash") or ""), str(record.get("final_surface_payload_hash") or ""))),
        "geometry_hash": str(record.get("geometry_hash") or ""),
        "program_hash": str(record.get("program_hash") or ""),
        "source_surface_payload_hash": str(record.get("final_surface_payload_hash") or ""),
        "source_surface_count": len(record.get("final_authored_surface_payload") or ()),
        "utilization": float(capacity.get("feasible_capacity_utilization") or 0.0),
        "capacity_status": status,
        "parking_status": str(capacity.get("parking_status") or "not_recorded"),
        "vlm_status": str(capacity.get("vlm_status") or "not_reviewed"),
        "non_selection_reason": _recorded_non_selection_reason(record),
        "visible_mass_pixels": visible_pixels,
        "visible_mass_pixel_ratio": visible_ratio,
    }


def _recorded_non_selection_reason(record: Mapping[str, Any]) -> str:
    direct = str(record.get("non_selection_reason") or "").strip()
    if direct:
        return direct
    for evidence_key in (
        "selection_evidence",
        "vlm_evidence",
        "diversity_evidence",
    ):
        evidence = record.get(evidence_key)
        if not isinstance(evidence, Mapping):
            continue
        for reason_key in (
            "non_selection_reason",
            "selection_reason",
            "rejection_reason",
            "reason",
        ):
            reason = str(evidence.get(reason_key) or "").strip()
            if reason:
                return reason
        for reasons_key in ("failure_reasons", "reasons"):
            reasons = evidence.get(reasons_key)
            if isinstance(reasons, (list, tuple)):
                recorded = next(
                    (str(value).strip() for value in reasons if str(value).strip()),
                    "",
                )
                if recorded:
                    return recorded
    return "not recorded"


__all__ = ["render_legal_mass_archive_board"]
