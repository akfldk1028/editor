import json
import re
import struct
import subprocess
import sys
import zlib
from dataclasses import replace
from pathlib import Path
from xml.etree import ElementTree

import pytest

import backend.app.modules.visual_review.service as visual_review_service
from backend.app.modules.generation_loop.operators import layout_fingerprint
from backend.app.modules.generation_loop.service import (
    run_building_generation,
    run_generation_loop,
)
from backend.app.modules.visual_review.service import (
    create_building_visual_review_artifacts,
    create_visual_review_artifacts,
    run_visual_review_loop,
)
from backend.app.schemas.layout import OpeningSegment, RoomPolygon
from backend.app.schemas.loop import CandidateRecord, IterationRecord, LoopResult
from backend.app.schemas.mass import MassInput
from backend.app.schemas.metrics import ValidationViolation


def _sample_result():
    mass = MassInput(
        project_id="visual",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )
    return run_generation_loop(mass, floor_index=1, use_type="neighborhood_commercial"), mass.footprint_polygon


def _strict_building_floor():
    mass = MassInput(
        project_id="strict-visual",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"office": 1.0},
    )
    building = run_building_generation(mass)
    return building.floor_results[0], mass.footprint_polygon


def _l_shaped_result(project_id: str = "visual"):
    result, boundary = _sample_result()
    room = replace(
        result.layout.rooms[0],
        space_type="shop_unit",
        polygon=[(0, 0), (20, 0), (20, 4), (8, 4), (8, 10), (0, 10)],
    )
    layout = replace(result.layout, rooms=[room])
    return replace(result, mass=replace(result.mass, project_id=project_id), layout=layout), boundary


def _png_pixel(data: bytes, x: int, y: int) -> tuple[int, int, int]:
    offset = 8
    compressed = b""
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IDAT":
            compressed += payload
    raw = zlib.decompress(compressed)
    width = struct.unpack(">I", data[16:20])[0]
    row_stride = width * 3 + 1
    pixel = y * row_stride + 1 + x * 3
    return tuple(raw[pixel : pixel + 3])


def _png_colors(data: bytes) -> set[tuple[int, int, int]]:
    offset = 8
    compressed = b""
    while offset < len(data):
        length = struct.unpack(">I", data[offset : offset + 4])[0]
        kind = data[offset + 4 : offset + 8]
        payload = data[offset + 8 : offset + 8 + length]
        offset += 12 + length
        if kind == b"IDAT":
            compressed += payload
    raw = zlib.decompress(compressed)
    width, height = struct.unpack(">II", data[16:24])
    row_stride = width * 3 + 1
    return {
        tuple(raw[row * row_stride + 1 + column * 3 : row * row_stride + 4 + column * 3])
        for row in range(height)
        for column in range(width)
    }


def test_create_visual_review_artifacts_writes_svg_png_and_report(tmp_path):
    result, boundary = _sample_result()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)

    assert review.svg_path.exists()
    assert review.png_path.exists()
    assert review.html_path.exists()
    assert review.report_path.exists()
    assert "<svg" in review.svg_path.read_text(encoding="utf-8")
    assert "visual review" in review.html_path.read_text(encoding="utf-8").lower()
    assert review.png_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["project_id"] == "visual"
    assert report["needs_iteration"] is True
    assert report["checks"]["boundary"] == "pass"
    assert report["checks"]["openings"] == "not_checked"
    assert report["checks"]["corridor_width"] == "not_checked"
    assert report["checks"]["basic_design"] == "not_checked"


def test_strict_review_renders_complete_basic_design_evidence_in_fixed_layer_order(
    tmp_path,
):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    expected_layers = [
        "grid",
        "rooms",
        "circulation",
        "core",
        "structure",
        "envelope",
        "door-openings",
        "furniture",
        "fixtures",
        "egress",
        "dimensions",
        "text-labels",
    ]
    group_layers = re.findall(r'<g data-layer="([^"]+)">', svg)
    assert group_layers[: len(expected_layers)] == expected_layers
    assert report["checks"]["basic_design"] == "pass"
    assert report["validation"]["basic_design"] is not None
    assert report["render_evidence"]["modeled"] == report["render_evidence"]["svg"]
    assert report["render_evidence"]["modeled"] == report["render_evidence"]["png"]
    assert report["render_evidence"]["missing"] == {"png": {}, "svg": {}}
    assert report["render_evidence"]["skipped"] == {"png": [], "svg": []}
    for layer, kinds in report["render_evidence"]["modeled"].items():
        for kind, identifiers in kinds.items():
            for identifier in identifiers:
                metadata = (
                    f'data-id="{identifier}" data-kind="{kind}" '
                    f'data-layer="{layer}"'
                )
                assert metadata in svg
    for layer in expected_layers:
        completeness = report["layer_completeness"][layer]
        assert completeness["modeled"] == completeness["svg"]
        assert completeness["modeled"] == completeness["png"]


def test_svg_escapes_all_feature_metadata_attributes(tmp_path):
    result, boundary = _strict_building_floor()
    assert result.layout.basic_design is not None
    unsafe_id = 'unsafe" onload="alert(1)'
    unsafe_kind = 'grid" onclick="alert(2)'
    changed_line = replace(
        result.layout.basic_design.lines[0],
        line_id=unsafe_id,
        kind=unsafe_kind,
    )
    basic_design = replace(
        result.layout.basic_design,
        lines=(changed_line, *result.layout.basic_design.lines[1:]),
    )
    result = replace(
        result,
        layout=replace(result.layout, basic_design=basic_design),
        validation=replace(result.validation, accepted=False, is_valid=False),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    assert f'data-id="{unsafe_id}"' not in svg
    assert f'data-kind="{unsafe_kind}"' not in svg
    assert 'data-id="unsafe&quot; onload=&quot;alert(1)"' in svg
    assert 'data-kind="grid&quot; onclick=&quot;alert(2)"' in svg


def test_svg_keeps_exit_and_bottom_annotations_inside_separate_readable_lanes(
    tmp_path,
):
    mass = MassInput(
        project_id="annotation-lanes",
        floors=1,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )
    result = run_building_generation(mass).floor_results[0]
    boundary = mass.footprint_polygon

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    root = ElementTree.fromstring(review.svg_path.read_text(encoding="utf-8"))
    namespace = "{http://www.w3.org/2000/svg}"
    texts = root.findall(f".//{namespace}text")
    assert sum(text.attrib.get("data-kind") == "circulation" for text in texts) == 1
    boundary_polygon = root.find(
        f".//{namespace}polygon[@data-kind='boundary']"
    )
    assert boundary_polygon is not None
    max_boundary_x = max(
        float(point.split(",")[0])
        for point in boundary_polygon.attrib["points"].split()
    )
    groups = root.findall(f".//{namespace}g")
    annotated = {
        group.attrib["data-kind"]: group.find(f"{namespace}text")
        for group in groups
        if group.attrib.get("data-kind")
        in {
            "protected_exit",
            "overall_width",
            "street",
            "entrance",
            "scale_line",
        }
    }
    exits = [
        group.find(f"{namespace}text")
        for group in groups
        if group.attrib.get("data-kind") == "protected_exit"
    ]
    assert len(exits) == 2
    assert all(text is not None for text in exits)
    for text in exits:
        assert text is not None and text.text is not None
        assert float(text.attrib["x"]) + len(text.text) * 3 <= max_boundary_x
    bottom_kinds = ("overall_width", "street", "entrance", "scale_line")
    assert all(annotated[kind] is not None for kind in bottom_kinds)
    positions = {
        kind: (
            float(annotated[kind].attrib["x"]),
            float(annotated[kind].attrib["y"]),
            annotated[kind].text or "",
        )
        for kind in bottom_kinds
    }
    for index, first_kind in enumerate(bottom_kinds):
        first_x, first_y, first_text = positions[first_kind]
        for second_kind in bottom_kinds[index + 1 :]:
            second_x, second_y, second_text = positions[second_kind]
            same_lane = abs(first_y - second_y) < 10
            overlaps = abs(first_x - second_x) < (
                len(first_text) + len(second_text)
            ) * 3
            assert not (same_lane and overlaps)


def test_strict_review_fails_basic_design_check_when_modeled_feature_is_not_renderable(
    tmp_path,
):
    result, boundary = _strict_building_floor()
    assert result.layout.basic_design is not None
    malformed = result.layout.basic_design.lines[0]
    object.__setattr__(malformed, "points", ((float("nan"), 0.0), (0.0, 0.0)))

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["accepted"] is False
    assert report["needs_iteration"] is True
    assert report["checks"]["basic_design"] == "fail"
    assert report["render_evidence"]["missing"]["svg"]
    assert report["render_evidence"]["missing"]["png"]
    assert report["render_evidence"]["skipped"]["svg"][0]["reason"] == (
        "non_finite_geometry"
    )


@pytest.mark.parametrize(
    ("points", "reason"),
    [
        (((0.0, 0.0), (0.0, 0.0)), "degenerate_geometry"),
        (((1000.0, 1000.0), (1000.0, 1005.0)), "off_canvas"),
    ],
)
def test_strict_review_rejects_finite_basic_design_features_with_no_visible_output(
    tmp_path,
    points,
    reason,
):
    result, boundary = _strict_building_floor()
    assert result.layout.basic_design is not None
    grid = next(
        line for line in result.layout.basic_design.lines if line.kind == "grid"
    )
    malformed = replace(grid, points=points, label="")
    features = replace(
        result.layout.basic_design,
        lines=tuple(
            malformed if line.line_id == grid.line_id else line
            for line in result.layout.basic_design.lines
        ),
    )
    result = replace(
        result,
        layout=replace(result.layout, basic_design=features),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["accepted"] is False
    assert report["needs_iteration"] is True
    assert report["checks"]["basic_design"] == "fail"
    for output in ("svg", "png"):
        skipped = next(
            item
            for item in report["render_evidence"]["skipped"][output]
            if item["id"] == grid.line_id
        )
        assert skipped["reason"] == reason
        assert grid.line_id in report["render_evidence"]["missing"][output]["grid"][
            "grid"
        ]


def test_unchecked_review_does_not_fabricate_basic_design_layers_and_disables_controls(
    tmp_path,
):
    result, boundary = _sample_result()
    assert result.layout.basic_design is None
    assert result.validation.basic_design_checked is False

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    page = review.html_path.read_text(encoding="utf-8")
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["basic_design"] == "not_checked"
    for layer in (
        "grid",
        "core",
        "structure",
        "envelope",
        "furniture",
        "fixtures",
        "egress",
        "dimensions",
    ):
        assert f'<g data-layer="{layer}">' not in svg
        assert re.search(
            rf'<button[^>]+data-layer="{layer}"[^>]+disabled',
            page,
        )
        assert layer not in report["layer_completeness"]


def test_building_review_writes_navigable_artifacts_for_every_floor(tmp_path):
    mass = MassInput(
        project_id="five-floor-review",
        floors=5,
        footprint_polygon=[(0, 0), (30, 0), (30, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.2, "office": 0.8},
    )
    result = run_building_generation(mass)

    artifacts = create_building_visual_review_artifacts(
        result,
        boundary=mass.footprint_polygon,
        output_dir=tmp_path,
    )

    assert artifacts.index_html_path.is_file()
    assert artifacts.report_path.is_file()
    assert len(artifacts.floor_artifacts) == 5
    assert all(review.png_path.is_file() for review in artifacts.floor_artifacts)
    assert all(review.svg_path.is_file() for review in artifacts.floor_artifacts)
    index = artifacts.index_html_path.read_text(encoding="utf-8")
    assert '<link rel="icon" href="data:,"' in index
    assert "F1 | neighborhood_commercial" in index
    assert "F5 | office" in index
    report = json.loads(artifacts.report_path.read_text(encoding="utf-8"))
    assert report["accepted"] is True
    assert report["vertical_core_aligned"] is True
    assert report["vertical_basic_design_aligned"] is True
    assert report["vertical_structure_aligned"] is True
    assert report["planner_provenance"]["provider"] == "deterministic"
    assert report["planner_provenance"]["validated_assignments"] == [
        {"floor_index": 1, "use_type": "neighborhood_commercial"},
        {"floor_index": 2, "use_type": "office"},
        {"floor_index": 3, "use_type": "office"},
        {"floor_index": 4, "use_type": "office"},
        {"floor_index": 5, "use_type": "office"},
    ]
    assert [floor["floor_index"] for floor in report["floors"]] == [1, 2, 3, 4, 5]


def test_png_artifact_has_requested_pixel_size(tmp_path):
    result, boundary = _sample_result()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=640,
        height=320,
    )

    data = review.png_path.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    assert (width, height) == (640, 320)


def test_polygon_artifacts_render_an_l_shape_without_filling_its_missing_corner(tmp_path):
    result, boundary = _l_shaped_result()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path, width=200, height=100)

    png = review.png_path.read_bytes()
    assert _png_pixel(png, 50, 26) == (217, 234, 211)
    assert _png_pixel(png, 141, 26) == (255, 255, 255)
    svg = review.svg_path.read_text(encoding="utf-8")
    assert '18.0,91.0 182.0,91.0 182.0,58.2 83.6,58.2 83.6,9.0 18.0,9.0' in svg


def test_artifacts_render_circulation_in_svg_and_png(tmp_path):
    result, boundary = _sample_result()
    corridor = RoomPolygon(
        room_id="corridor",
        space_type="circulation",
        polygon=[(9, 0), (11, 0), (11, 10), (9, 10)],
    )
    result = replace(
        result,
        layout=replace(result.layout, circulation=[corridor]),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=200,
        height=100,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    assert 'data-kind="circulation"' in svg
    assert 'fill="#d9d9d9" stroke="#38761d"' in svg
    assert ">circulation</text>" in svg
    assert _png_pixel(review.png_path.read_bytes(), 100, 50) == (217, 217, 217)


def test_svg_renders_door_width_and_room_identity_area_labels(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=300,
        height=100,
    )

    svg = review.svg_path.read_text(encoding="utf-8")
    assert svg.count('data-kind="door-opening"') == len(result.layout.openings)
    assert svg.count('data-kind="door-width"') == len(result.layout.openings)
    assert 'aria-label="open_work door clear width 0.9 m"' in svg
    assert ">0.9 m</text>" in svg
    assert 'data-kind="room-label"' in svg
    assert "open_work" in svg
    assert "133.38 m2" in svg


def test_png_renders_high_contrast_door_segment_pixels(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
        width=300,
        height=100,
    )

    png = review.png_path.read_bytes()
    assert visual_review_service.PNG_DOOR_STROKE in _png_colors(png)


def test_png_contains_distinct_pixels_for_basic_design_layers_and_bitmap_labels(
    tmp_path,
):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    colors = _png_colors(review.png_path.read_bytes())
    assert {
        (247, 214, 208),  # core stair
        (66, 75, 84),  # structure
        (11, 110, 153),  # envelope
        (242, 226, 184),  # furniture
        (191, 227, 223),  # fixtures
        (46, 125, 50),  # egress
        (163, 72, 19),  # dimensions and site
        (25, 30, 35),  # bitmap text
    } <= colors


def test_review_report_exposes_validated_opening_and_corridor_measurements(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "pass"
    assert report["checks"]["corridor_width"] == "pass"
    assert report["measurements"]["door_count"] == len(result.layout.openings)
    assert report["measurements"]["min_door_width"] == 0.9
    assert report["measurements"]["min_corridor_width"] == pytest.approx(1.2)
    assert report["measurements"]["failed_room_ids"] == []


def test_review_exposes_validator_room_form_measurements_and_layer_controls(tmp_path):
    result, boundary = _strict_building_floor()
    result = replace(
        result,
        validation=replace(
            result.validation,
            violations=[
                *result.validation.violations,
                ValidationViolation(
                    code="room_min_width", subject="open_work", message="too narrow"
                ),
                ValidationViolation(
                    code="room_aspect_ratio", subject="meeting", message="too long"
                ),
            ],
        ),
    )

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    page = review.html_path.read_text(encoding="utf-8")
    svg = review.svg_path.read_text(encoding="utf-8")

    assert report["checks"]["room_form"] == "fail"
    assert report["measurements"]["min_room_width"] == pytest.approx(1.961505)
    assert report["measurements"]["max_room_aspect_ratio"] == pytest.approx(2.0)
    assert report["measurements"]["failed_room_ids"] == ["meeting", "open_work"]
    assert 'data-layer="rooms"' in svg
    assert 'data-layer="circulation"' in svg
    assert 'data-layer="door-openings"' in svg
    assert 'data-layer="text-labels"' in svg
    assert 'id="working-layer-controls"' in page
    assert 'aria-pressed="true"' in page
    assert "Room Program and Form" in page


def test_room_form_table_joins_validator_area_metric_by_room_id(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)
    page = review.html_path.read_text(encoding="utf-8")
    open_work_area = next(
        metric.actual_area for metric in result.validation.room_areas if metric.room_id == "open_work"
    )

    assert '<th scope="col">Area m2</th>' in page
    assert f"<td>{open_work_area:g}</td>" in page


def test_layer_control_script_resynchronizes_after_iframe_load(tmp_path):
    result, boundary = _strict_building_floor()

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)
    page = review.html_path.read_text(encoding="utf-8")

    assert "function synchronizeLayers()" in page
    assert 'frame.addEventListener("load", synchronizeLayers)' in page


def test_use_specific_room_palette_has_svg_and_png_entries_for_each_role():
    room_types = {
        "open_work", "meeting", "reception", "focus", "pantry", "restroom", "core", "it_storage",
        "sales", "checkout", "stock", "staff", "utility",
    }

    assert room_types <= visual_review_service.PALETTE.keys()
    assert room_types <= visual_review_service.PNG_PALETTE.keys()
    assert len({visual_review_service.PALETTE[room_type] for room_type in room_types}) == len(room_types)


@pytest.mark.parametrize(
    ("invalid_x", "clear_width"),
    [
        (float("nan"), 0.9),
        ("not-a-coordinate", 0.9),
        (21.06, "0.9"),
    ],
)
def test_invalid_opening_coordinate_is_skipped_without_blocking_review_artifacts(
    tmp_path,
    invalid_x,
    clear_width,
):
    result, boundary = _strict_building_floor()
    invalid = OpeningSegment(
        opening_id="invalid-door",
        kind="door",
        connects=("office_area", "corridor"),
        start=(invalid_x, 4.0),
        end=(21.06, 4.9),
        clear_width=clear_width,
    )
    validation = replace(
        result.validation,
        accepted=False,
        is_valid=False,
        hard_violation_count=1,
        violations=[
            *result.validation.violations,
            ValidationViolation(
                code="door_geometry",
                subject=invalid.opening_id,
                message="door coordinates must be finite",
            ),
        ],
    )
    result = replace(
        result,
        layout=replace(result.layout, openings=[*result.layout.openings, invalid]),
        validation=validation,
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    assert all(
        path.is_file()
        for path in (
            review.svg_path,
            review.png_path,
            review.html_path,
            review.report_path,
        )
    )
    svg = review.svg_path.read_text(encoding="utf-8")
    assert "invalid-door" not in svg
    assert "nan" not in svg.lower()
    assert svg.count('data-kind="door-opening"') == len(result.layout.openings) - 1
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "fail"
    assert report["measurements"]["door_count"] == len(result.layout.openings)


def test_present_but_unchecked_openings_are_not_reported_as_pass(tmp_path):
    result, boundary = _strict_building_floor()
    result = replace(
        result,
        validation=replace(
            result.validation,
            openings_checked=False,
            corridor_width_checked=False,
        ),
    )

    review = create_visual_review_artifacts(
        result,
        boundary=boundary,
        output_dir=tmp_path,
    )

    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    assert report["checks"]["openings"] == "not_checked"
    assert report["checks"]["corridor_width"] == "not_checked"


def test_artifacts_escape_text_use_safe_stems_and_keep_links_under_output_root(tmp_path):
    result, boundary = _l_shaped_result(project_id='../../Project <script>alert(1)</script>')
    room = replace(result.layout.rooms[0], space_type='<svg onload="alert(1)">')
    result = replace(result, layout=replace(result.layout, rooms=[room]))

    review = create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path)

    for path in (review.svg_path, review.png_path, review.html_path, review.report_path):
        assert path.resolve().is_relative_to(tmp_path.resolve())
        assert "/" not in path.name
        assert "<" not in path.name
    assert review.svg_path.stem.startswith("project-script-alert-1-script-")
    assert review.svg_path.stem.endswith("-f1")
    assert '<svg onload="alert(1)">' not in review.svg_path.read_text(encoding="utf-8")
    assert "&lt;svg onload=&quot;alert(1)&quot;&gt;" in review.svg_path.read_text(encoding="utf-8")
    html = review.html_path.read_text(encoding="utf-8")
    assert "Project &lt;script&gt;alert(1)&lt;/script&gt;" in html
    report = json.loads(review.report_path.read_text(encoding="utf-8"))
    for artifact in report["artifacts"].values():
        assert not Path(artifact).is_absolute()
        assert ".." not in Path(artifact).parts


@pytest.mark.parametrize(
    ("first_project_id", "second_project_id"),
    [
        ("!!!", "@@@"),
        ("a" * 80 + "-first", "a" * 80 + "-second"),
    ],
)
def test_distinct_project_ids_have_distinct_deterministic_artifact_stems(
    tmp_path, first_project_id, second_project_id
):
    first_result, boundary = _l_shaped_result(project_id=first_project_id)
    second_result, _ = _l_shaped_result(project_id=second_project_id)

    first_review = create_visual_review_artifacts(first_result, boundary=boundary, output_dir=tmp_path)
    repeated_review = create_visual_review_artifacts(first_result, boundary=boundary, output_dir=tmp_path)
    second_review = create_visual_review_artifacts(second_result, boundary=boundary, output_dir=tmp_path)

    assert first_review.svg_path == repeated_review.svg_path
    assert first_review.svg_path != second_review.svg_path
    assert len(first_review.svg_path.stem) <= 96
    assert len(second_review.svg_path.stem) <= 96


@pytest.mark.parametrize(("width", "height"), [(0, 100), (100, 0), (-1, 100), (100, -1)])
def test_artifact_viewport_dimensions_must_be_positive(tmp_path, width, height):
    result, boundary = _sample_result()

    with pytest.raises(ValueError, match="viewport width and height must be positive"):
        create_visual_review_artifacts(result, boundary=boundary, output_dir=tmp_path, width=width, height=height)


def test_cli_review_generates_visual_artifacts(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "review"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-review",
                "floors": 2,
                "footprint_polygon": [[0, 0], [20, 0], [20, 10], [0, 10]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
            "--output-dir",
            str(output_dir),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["needs_iteration"] is True
    for key in ("svg_path", "png_path", "html_path", "report_path"):
        artifact_path = Path(payload[key])
        assert artifact_path.exists()
        assert artifact_path.is_relative_to(output_dir)


def test_run_visual_review_loop_writes_search_history_and_canonical_index(tmp_path):
    mass = MassInput(
        project_id="loop-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )

    result = run_visual_review_loop(
        mass,
        floor_index=1,
        use_type="neighborhood_commercial",
        output_dir=tmp_path,
        max_iterations=5,
        review_level="zoning",
    )

    assert result.iterations_run == 2
    assert result.final_needs_iteration is True
    assert result.accepted is False
    assert result.termination_reason == "search_exhausted"
    assert result.evaluation_count > result.iterations_run
    assert result.index_json_path == tmp_path / "review.index.json"
    assert result.index_html_path == tmp_path / "index.html"

    reports = [
        json.loads(artifact.report_path.read_text(encoding="utf-8"))
        for artifact in result.artifacts
    ]
    assert [artifact.report_path.parent.name for artifact in result.artifacts] == [
        "iteration_001",
        "iteration_002",
    ]
    assert reports[0]["fingerprint"] != reports[1]["fingerprint"]
    assert reports[0]["accepted"] is False
    assert reports[0]["needs_iteration"] is True
    assert "circulation_missing" in {
        violation["code"] for violation in reports[0]["violations"]
    }
    assert reports[1]["accepted"] is False
    assert reports[1]["needs_iteration"] is True
    assert reports[1]["checks"] == {
        "area": "pass",
        "basic_design": "not_checked",
        "boundary": "pass",
        "circulation_access": "pass",
            "corridor_width": "not_checked",
            "openings": "not_checked",
            "overlap": "pass",
            "room_form": "fail",
    }
    assert reports[1]["scores"]["area_score"] < 1
    assert all(
        reports[1]["checks"][name] == "pass"
        for name in ("area", "boundary", "circulation_access", "overlap")
    )
    accepted_html = result.artifacts[1].html_path.read_text(encoding="utf-8")
    assert "needs iteration" in accepted_html
    assert "Hard Validation Checks" in accepted_html
    assert "Advisory Scores" in accepted_html
    assert "<td>fail</td>" in accepted_html
    assert reports[1]["parent_id"] is not None
    assert reports[1]["operator"] == "corridor-horizontal"
    assert reports[1]["operator_params"]
    assert reports[0]["total_score_delta"] is None
    assert reports[0]["hard_failure_count_delta"] is None
    assert reports[1]["total_score_delta"] == pytest.approx(
        reports[1]["scores"]["total_score"] - reports[0]["scores"]["total_score"]
    )
    assert reports[1]["hard_failure_count_delta"] == (
        reports[1]["hard_failure_count"] - reports[0]["hard_failure_count"]
    )

    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))
    assert index["schema_version"] == 1
    assert index["project_id"] == "loop-review"
    assert index["floor_index"] == 1
    assert index["use_type"] == "neighborhood_commercial"
    assert index["accepted"] is False
    assert index["review_level"] == "zoning"
    assert set(index["unchecked_checks"]) == {
        "basic_design",
        "corridor_width",
        "openings",
    }
    assert index["termination_reason"] == "search_exhausted"
    assert index["evaluation_count"] == result.evaluation_count
    assert [entry["iteration"] for entry in index["iterations"]] == [1, 2]
    assert index["score_trend"] == [
        report["scores"]["total_score"] for report in reports
    ]
    assert index["lineage"] == [
        {
            "candidate_id": report["candidate_id"],
            "parent_id": report["parent_id"],
            "operator": report["operator"],
            "operator_params": report["operator_params"],
        }
        for report in reports
    ]
    assert [
        entry["fingerprint"] for entry in index["iterations"]
    ] == [report["fingerprint"] for report in reports]
    assert str(tmp_path.resolve()) not in json.dumps(index)
    for entry in index["iterations"]:
        for relative_path in entry["artifacts"].values():
            assert not Path(relative_path).is_absolute()
            assert (tmp_path / relative_path).exists()

    index_html = result.index_html_path.read_text(encoding="utf-8")
    assert "<h1>" in index_html
    assert "<th" in index_html
    assert "<script" not in index_html.lower()
    for entry in index["iterations"]:
        assert entry["artifacts"]["html"] in index_html


def test_default_review_loop_runs_one_strict_concept_basic_evaluation(tmp_path):
    mass = MassInput(
        project_id="strict-loop-review",
        floors=2,
        footprint_polygon=[(0, 0), (30, 0), (30, 12), (0, 12)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 0.5, "office": 0.5},
    )

    result = run_visual_review_loop(
        mass,
        floor_index=2,
        use_type="office",
        output_dir=tmp_path,
        max_iterations=9,
    )
    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))
    report = json.loads(result.artifacts[0].report_path.read_text(encoding="utf-8"))

    assert result.review_level == "concept-basic"
    assert result.iterations_run == 1
    assert result.evaluation_count == 1
    assert result.accepted is True
    assert result.final_needs_iteration is False
    assert result.termination_reason == "accepted"
    assert result.unchecked_checks == ()
    assert index["review_level"] == "concept-basic"
    assert index["unchecked_checks"] == []
    assert index["planner_provenance"]["provider"] == "deterministic"
    assert index["planner_provenance"]["planner_mode"] == "deterministic"
    assert index["iterations"][0]["checks"]["openings"] == "pass"
    assert index["iterations"][0]["checks"]["corridor_width"] == "pass"
    assert index["iterations"][0]["checks"]["basic_design"] == "pass"
    assert report["floor_index"] == 2
    assert report["use_type"] == "office"
    assert report["validation"]["basic_design_checked"] is True
    for layer in (
        "grid",
        "core",
        "structure",
        "envelope",
        "furniture",
        "fixtures",
        "egress",
        "dimensions",
    ):
        counts = report["layer_completeness"][layer]
        assert counts["modeled"] == counts["svg"] == counts["png"]


def test_review_index_is_identical_across_output_roots(tmp_path):
    mass = MassInput(
        project_id="deterministic-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    first = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path / "first",
        max_iterations=5, review_level="zoning",
    )
    second = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path / "second",
        max_iterations=5, review_level="zoning",
    )

    first_index = json.loads(first.index_json_path.read_text(encoding="utf-8"))
    second_index = json.loads(second.index_json_path.read_text(encoding="utf-8"))
    assert first_index == second_index


def test_review_loop_iteration_budget_exhaustion_is_not_accepted(tmp_path):
    mass = MassInput(
        project_id="budget-review",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path,
        max_iterations=1, review_level="zoning",
    )
    index = json.loads((tmp_path / "review.index.json").read_text(encoding="utf-8"))

    assert result.accepted is False
    assert result.final_needs_iteration is True
    assert result.termination_reason == "iteration_budget_exhausted"
    assert index["accepted"] is False
    assert index["needs_iteration"] is True
    assert index["termination_reason"] == "iteration_budget_exhausted"


def test_failed_review_loop_preserves_search_diagnostic(tmp_path, monkeypatch):
    generated, _ = _sample_result()
    search = LoopResult(
        mass=generated.mass,
        program=generated.program,
        best=None,
        iterations=[],
        history=[],
        termination_reason="failed",
        evaluation_count=0,
        error="RuntimeError: evaluator failed",
    )
    monkeypatch.setattr(
        visual_review_service,
        "run_candidate_search",
        lambda *args, **kwargs: search,
    )
    mass = MassInput(
        project_id="failed-review",
        floors=1,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[],
        access_candidates=[],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass,
        1,
        "neighborhood_commercial",
        tmp_path,
        review_level="zoning",
    )
    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))

    assert result.error == "RuntimeError: evaluator failed"
    assert index["error"] == "RuntimeError: evaluator failed"


def test_review_report_uses_search_iteration_when_best_candidate_is_unchanged(
    tmp_path, monkeypatch
):
    generated, _ = _sample_result()
    candidate = CandidateRecord(
        iteration=1,
        layout=generated.layout,
        validation=generated.validation,
        fingerprint=layout_fingerprint(generated.layout),
        parent_id=None,
        operator="baseline",
        operator_params={"output": Path("relative-artifact")},
    )
    search = LoopResult(
        mass=generated.mass,
        program=generated.program,
        best=candidate,
        iterations=[
            IterationRecord(1, [candidate], candidate, candidate),
            IterationRecord(2, [candidate], candidate, candidate),
        ],
        history=[candidate],
        termination_reason="stagnated",
        evaluation_count=2,
    )
    monkeypatch.setattr(
        visual_review_service, "run_candidate_search", lambda *args, **kwargs: search
    )
    mass = MassInput(
        project_id="visual",
        floors=2,
        footprint_polygon=[(0, 0), (20, 0), (20, 10), (0, 10)],
        site_edges=[{"edge_index": 0, "kind": "street"}],
        access_candidates=[{"edge_index": 0, "position": 0.5}],
        use_mix={"neighborhood_commercial": 1.0},
    )

    result = run_visual_review_loop(
        mass, 1, "neighborhood_commercial", tmp_path,
        max_iterations=2, review_level="zoning",
    )
    reports = [
        json.loads(artifact.report_path.read_text(encoding="utf-8"))
        for artifact in result.artifacts
    ]

    assert [report["iteration"] for report in reports] == [1, 2]
    assert reports[1]["fingerprint"] == reports[0]["fingerprint"]
    assert reports[1]["total_score_delta"] == 0
    assert reports[1]["hard_failure_count_delta"] == 0
    assert reports[0]["operator_params"] == {"output": "relative-artifact"}
    index = json.loads(result.index_json_path.read_text(encoding="utf-8"))
    assert index["iterations"][0]["operator_params"] == {
        "output": "relative-artifact"
    }
    assert index["lineage"][0]["operator_params"] == {
        "output": "relative-artifact"
    }
    assert "relative-artifact" in result.index_html_path.read_text(encoding="utf-8")


def test_cli_loop_review_runs_iterations_and_prints_final_state(tmp_path):
    input_path = tmp_path / "mass.json"
    output_dir = tmp_path / "loop"
    input_path.write_text(
        json.dumps(
            {
                "project_id": "cli-loop",
                "floors": 2,
                "footprint_polygon": [[0, 0], [30, 0], [30, 12], [0, 12]],
                "site_edges": [{"edge_index": 0, "kind": "street"}],
                "access_candidates": [{"edge_index": 0, "position": 0.5}],
                "use_mix": {"neighborhood_commercial": 0.5, "office": 0.5},
            }
        ),
        encoding="utf-8",
    )

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "backend.app.cli",
            "loop-review",
            "--input",
            str(input_path),
            "--floor",
            "1",
            "--use-type",
            "neighborhood_commercial",
            "--output-dir",
            str(output_dir),
            "--max-iterations",
            "3",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    payload = json.loads(completed.stdout)
    assert payload["review_level"] == "concept-basic"
    assert payload["iterations_run"] == 1
    assert payload["evaluation_count"] == 1
    assert payload["final_needs_iteration"] is False
    assert payload["accepted"] is True
    assert payload["termination_reason"] == "accepted"
    assert payload["unchecked_checks"] == []
    assert Path(payload["index_json_path"]).exists()
    assert Path(payload["index_html_path"]).exists()
    assert all(Path(artifact["html_path"]).exists() for artifact in payload["artifacts"])
