from __future__ import annotations

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
