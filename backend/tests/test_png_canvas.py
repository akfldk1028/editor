from __future__ import annotations

import subprocess
import sys

import pytest

from engine.io.png import SimplePngCanvas


BLACK = (0, 0, 0)
WHITE = (255, 255, 255)


def _pixel(canvas: SimplePngCanvas, x: int, y: int) -> tuple[int, int, int]:
    offset = (y * canvas.width + x) * 3
    return tuple(canvas.pixels[offset : offset + 3])


def test_draw_text_renders_visible_scaled_ascii_pixels() -> None:
    canvas = SimplePngCanvas(40, 24)

    canvas.draw_text("A1", (2, 3), BLACK, scale=2)

    assert _pixel(canvas, 6, 3) == BLACK
    assert _pixel(canvas, 2, 9) == BLACK
    assert _pixel(canvas, 18, 16) == BLACK
    assert _pixel(canvas, 0, 0) == WHITE


def test_draw_text_clips_and_uses_question_mark_for_unsupported_characters() -> None:
    clipped = SimplePngCanvas(6, 6)
    clipped.draw_text("A", (-2, -2), BLACK)
    fallback = SimplePngCanvas(8, 8)
    fallback.draw_text("\N{SNOWMAN}", (0, 0), BLACK)
    question_mark = SimplePngCanvas(8, 8)
    question_mark.draw_text("?", (0, 0), BLACK)

    assert any(channel == 0 for channel in clipped.pixels)
    assert fallback.pixels == question_mark.pixels


@pytest.mark.parametrize("scale", [0, 9])
def test_draw_text_rejects_scale_outside_supported_bounds(scale: int) -> None:
    canvas = SimplePngCanvas(8, 8)

    with pytest.raises(ValueError, match="scale"):
        canvas.draw_text("A", (0, 0), BLACK, scale=scale)


def test_stroke_dashed_polyline_preserves_visible_gaps_across_segments() -> None:
    canvas = SimplePngCanvas(24, 24)

    canvas.stroke_dashed_polyline(
        [(2, 2), (18, 2), (18, 18)],
        BLACK,
        dash_length=4,
        gap_length=3,
    )

    assert _pixel(canvas, 2, 2) == BLACK
    assert _pixel(canvas, 5, 2) == BLACK
    assert _pixel(canvas, 7, 2) == WHITE
    assert _pixel(canvas, 18, 18) == BLACK


def test_polyline_arrowhead_and_circle_primitives_render_visible_pixels() -> None:
    canvas = SimplePngCanvas(32, 24)

    canvas.stroke_polyline([(2, 12), (14, 12), (14, 4)], BLACK, thickness=2)
    canvas.draw_arrowhead((14, 4), (14, 12), BLACK, size=5, thickness=1)
    canvas.fill_circle((23, 8), 3, BLACK)
    canvas.stroke_circle((23, 17), 3, BLACK, thickness=1)

    assert _pixel(canvas, 8, 12) == BLACK
    assert _pixel(canvas, 14, 4) == BLACK
    assert _pixel(canvas, 23, 8) == BLACK
    assert _pixel(canvas, 23, 17) == WHITE
    assert _pixel(canvas, 26, 17) == BLACK


def test_canvas_primitives_keep_png_bytes_deterministic() -> None:
    def render() -> bytes:
        canvas = SimplePngCanvas(48, 32)
        canvas.draw_text("PLAN", (2, 2), BLACK, scale=1)
        canvas.stroke_dashed_polyline([(2, 14), (44, 14)], BLACK)
        canvas.draw_arrowhead((44, 14), (36, 14), BLACK)
        canvas.fill_circle((10, 24), 3, BLACK)
        return canvas.to_bytes()

    assert render() == render()


def test_large_offscreen_geometry_finishes_with_a_valid_png() -> None:
    script = """
from engine.io.png import SimplePngCanvas

canvas = SimplePngCanvas(16, 16)
canvas.stroke_line((-1e9, 8), (1e9, 8), (0, 0, 0))
canvas.stroke_polyline([(-1e9, 4), (1e9, 4)], (0, 0, 0))
canvas.stroke_dashed_polyline([(-1e9, 12), (1e9, 12)], (0, 0, 0))
canvas.draw_arrowhead((1e9, 6), (-1e9, 6), (0, 0, 0))
canvas.fill_circle((0, 0), 1e9, (0, 0, 0))
canvas.stroke_circle((0, 0), 1e9, (0, 0, 0))
print(canvas.to_bytes()[:8].hex())
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=2,
    )

    assert result.stdout.strip() == "89504e470d0a1a0a"


@pytest.mark.parametrize(
    ("operation", "message"),
    [
        (lambda canvas: canvas.fill_rect(0, 0, float("nan"), 2, BLACK), "finite"),
        (
            lambda canvas: canvas.stroke_rect(0, 0, 2, float("inf"), BLACK),
            "finite",
        ),
        (
            lambda canvas: canvas.fill_polygon(
                [(0, 0), (float("nan"), 1), (1, 0)],
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_polygon(
                [(0, 0), (float("inf"), 1)],
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_line(
                (float("nan"), 0),
                (1, 1),
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_polyline(
                [(0, 0), (float("inf"), 1)],
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_dashed_polyline(
                [(0, 0), (1, 1)],
                BLACK,
                dash_length=float("nan"),
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_dashed_polyline(
                [(0, 0), (1, 1)],
                BLACK,
                gap_length=float("inf"),
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.draw_arrowhead(
                (1, 1),
                (0, 0),
                BLACK,
                size=float("nan"),
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.fill_circle(
                (0, 0),
                float("inf"),
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_circle(
                (float("nan"), 0),
                2,
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.draw_text(
                "A",
                (float("inf"), 0),
                BLACK,
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.stroke_line(
                (0, 0),
                (1, 1),
                BLACK,
                thickness=float("inf"),
            ),
            "finite",
        ),
        (
            lambda canvas: canvas.draw_text(
                "A",
                (0, 0),
                BLACK,
                scale=float("nan"),
            ),
            "finite",
        ),
    ],
)
def test_public_primitives_reject_non_finite_geometry(operation, message: str) -> None:
    canvas = SimplePngCanvas(8, 8)

    with pytest.raises(ValueError, match=message):
        operation(canvas)


@pytest.mark.parametrize(
    ("start", "end", "thickness", "visible_pixel"),
    [
        ((0, -1), (7, -1), 4, (0, 0)),
        ((0, 8), (7, 8), 3, (0, 7)),
        ((-1, 0), (-1, 7), 3, (0, 0)),
        ((8, 0), (8, 7), 2, (7, 0)),
    ],
    ids=("top-even", "bottom-odd", "left-odd", "right-even"),
)
def test_thick_line_keeps_stroke_portion_inside_each_canvas_edge(
    start: tuple[int, int],
    end: tuple[int, int],
    thickness: int,
    visible_pixel: tuple[int, int],
) -> None:
    canvas = SimplePngCanvas(8, 8)

    canvas.stroke_line(start, end, BLACK, thickness=thickness)

    assert _pixel(canvas, *visible_pixel) == BLACK


def test_thick_polyline_and_dashed_polyline_keep_edge_strokes() -> None:
    solid = SimplePngCanvas(8, 8)
    dashed = SimplePngCanvas(8, 8)

    solid.stroke_polyline([(0, -1), (7, -1)], BLACK, thickness=4)
    dashed.stroke_dashed_polyline(
        [(0, -1), (7, -1)],
        BLACK,
        thickness=4,
        dash_length=1,
        gap_length=6,
    )

    assert all(_pixel(solid, x, 0) == BLACK for x in range(8))
    assert any(_pixel(dashed, x, 0) == BLACK for x in range(8))
    assert any(_pixel(dashed, x, 0) == WHITE for x in range(8))
