from __future__ import annotations

import math
import struct
import zlib


Color = tuple[int, int, int]
Point = tuple[int | float, int | float]

_FONT_FIRST_CODEPOINT = 32
_FONT_LAST_CODEPOINT = 126
_FONT_FALLBACK = "?"
_FONT_5X7 = bytes.fromhex(
    """
    00 00 00 00 00  00 00 5f 00 00  00 07 00 07 00  14 7f 14 7f 14
    24 2a 7f 2a 12  23 13 08 64 62  36 49 55 22 50  00 05 03 00 00
    00 1c 22 41 00  00 41 22 1c 00  14 08 3e 08 14  08 08 3e 08 08
    00 50 30 00 00  08 08 08 08 08  00 60 60 00 00  20 10 08 04 02
    3e 51 49 45 3e  00 42 7f 40 00  42 61 51 49 46  21 41 45 4b 31
    18 14 12 7f 10  27 45 45 45 39  3c 4a 49 49 30  01 71 09 05 03
    36 49 49 49 36  06 49 49 29 1e  00 36 36 00 00  00 56 36 00 00
    08 14 22 41 00  14 14 14 14 14  00 41 22 14 08  02 01 51 09 06
    32 49 79 41 3e  7e 11 11 11 7e  7f 49 49 49 36  3e 41 41 41 22
    7f 41 41 22 1c  7f 49 49 49 41  7f 09 09 09 01  3e 41 49 49 7a
    7f 08 08 08 7f  00 41 7f 41 00  20 40 41 3f 01  7f 08 14 22 41
    7f 40 40 40 40  7f 02 0c 02 7f  7f 04 08 10 7f  3e 41 41 41 3e
    7f 09 09 09 06  3e 41 51 21 5e  7f 09 19 29 46  46 49 49 49 31
    01 01 7f 01 01  3f 40 40 40 3f  1f 20 40 20 1f  3f 40 38 40 3f
    63 14 08 14 63  07 08 70 08 07  61 51 49 45 43  00 7f 41 41 00
    02 04 08 10 20  00 41 41 7f 00  04 02 01 02 04  40 40 40 40 40
    00 01 02 04 00  20 54 54 54 78  7f 48 44 44 38  38 44 44 44 20
    38 44 44 48 7f  38 54 54 54 18  08 7e 09 01 02  0c 52 52 52 3e
    7f 08 04 04 78  00 44 7d 40 00  20 40 44 3d 00  7f 10 28 44 00
    00 41 7f 40 00  7c 04 18 04 78  7c 08 04 04 78  38 44 44 44 38
    7c 14 14 14 08  08 14 14 18 7c  7c 08 04 04 08  48 54 54 54 20
    04 3f 44 40 20  3c 40 40 20 7c  1c 20 40 20 1c  3c 40 30 40 3c
    44 28 10 28 44  0c 50 50 50 3c  44 64 54 4c 44  00 08 36 41 00
    00 00 7f 00 00  00 41 36 08 00  08 04 08 10 08
    """
)


class SimplePngCanvas:
    def __init__(self, width: int, height: int, background: Color = (255, 255, 255)):
        if width <= 0 or height <= 0:
            raise ValueError("png canvas width and height must be positive")
        self.width = width
        self.height = height
        self.pixels = bytearray(background * width * height)

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
        _require_finite_values((x0, y0, x1, y1), "rectangle coordinates")
        left = max(0, min(self.width, min(x0, x1)))
        right = max(0, min(self.width, max(x0, x1)))
        top = max(0, min(self.height, min(y0, y1)))
        bottom = max(0, min(self.height, max(y0, y1)))
        for y in range(top, bottom):
            row = y * self.width * 3
            for x in range(left, right):
                offset = row + x * 3
                self.pixels[offset : offset + 3] = bytes(color)

    def stroke_rect(self, x0: int, y0: int, x1: int, y1: int, color: Color, thickness: int = 2) -> None:
        _require_finite_values((x0, y0, x1, y1), "rectangle coordinates")
        _require_positive_integer(thickness, "rectangle stroke thickness")
        self.fill_rect(x0, y0, x1, y0 + thickness, color)
        self.fill_rect(x0, y1 - thickness, x1, y1, color)
        self.fill_rect(x0, y0, x0 + thickness, y1, color)
        self.fill_rect(x1 - thickness, y0, x1, y1, color)

    def fill_polygon(self, points: list[tuple[int | float, int | float]], color: Color) -> None:
        if len(points) < 3:
            raise ValueError("polygon requires at least three points")
        _require_finite_points(points, "polygon points")

        min_y = max(0, math.floor(min(y for _, y in points)))
        max_y = min(self.height - 1, math.ceil(max(y for _, y in points)) - 1)
        for y in range(min_y, max_y + 1):
            scanline = y + 0.5
            intersections: list[float] = []
            for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
                if (y1 > scanline) != (y2 > scanline):
                    intersections.append(x1 + (scanline - y1) * (x2 - x1) / (y2 - y1))
            intersections.sort()
            for left, right in zip(intersections[::2], intersections[1::2]):
                start_x = max(0, math.ceil(left - 0.5))
                end_x = min(self.width - 1, math.floor(right - 0.5))
                for x in range(start_x, end_x + 1):
                    self._set_pixel(x, y, color)

    def stroke_polygon(
        self,
        points: list[tuple[int | float, int | float]],
        color: Color,
        thickness: int = 1,
    ) -> None:
        if len(points) < 2:
            raise ValueError("polygon requires at least two points")
        _require_finite_points(points, "polygon points")
        _require_positive_integer(thickness, "polygon stroke thickness")
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            self._draw_line(round(x1), round(y1), round(x2), round(y2), color, thickness)

    def stroke_line(
        self,
        start: Point,
        end: Point,
        color: Color,
        thickness: int = 1,
    ) -> None:
        _require_finite_points((start, end), "line points")
        _require_positive_integer(thickness, "line stroke thickness")
        self._draw_line(
            round(start[0]),
            round(start[1]),
            round(end[0]),
            round(end[1]),
            color,
            thickness,
        )

    def stroke_polyline(
        self,
        points: list[Point],
        color: Color,
        thickness: int = 1,
    ) -> None:
        if len(points) < 2:
            raise ValueError("polyline requires at least two points")
        _require_finite_points(points, "polyline points")
        _require_positive_integer(thickness, "polyline stroke thickness")
        for start, end in zip(points, points[1:]):
            self._draw_line(
                round(start[0]),
                round(start[1]),
                round(end[0]),
                round(end[1]),
                color,
                thickness,
            )

    def stroke_dashed_polyline(
        self,
        points: list[Point],
        color: Color,
        thickness: int = 1,
        dash_length: int | float = 6,
        gap_length: int | float = 4,
    ) -> None:
        if len(points) < 2:
            raise ValueError("dashed polyline requires at least two points")
        _require_finite_points(points, "dashed polyline points")
        _require_positive_integer(thickness, "dashed polyline stroke thickness")
        _require_finite_values((dash_length, gap_length), "dash and gap lengths")
        if dash_length <= 0 or gap_length <= 0:
            raise ValueError("dash and gap lengths must be positive")

        cycle_length = dash_length + gap_length
        phase = 0.0
        for start, end in zip(points, points[1:]):
            delta_x = end[0] - start[0]
            delta_y = end[1] - start[1]
            segment_length = math.hypot(delta_x, delta_y)
            if not math.isfinite(segment_length):
                raise ValueError("dashed polyline segment length must be finite")
            if segment_length == 0:
                continue
            self._draw_dashed_segment(
                start,
                end,
                color,
                thickness,
                dash_length,
                cycle_length,
                phase,
            )
            phase = (phase + segment_length) % cycle_length

    def draw_arrowhead(
        self,
        tip: Point,
        tail: Point,
        color: Color,
        size: int | float = 6,
        thickness: int = 1,
    ) -> None:
        _require_finite_points((tip, tail), "arrowhead points")
        _require_finite_values((size,), "arrowhead size")
        if size <= 0:
            raise ValueError("arrowhead size must be positive")
        _require_positive_integer(thickness, "arrowhead stroke thickness")
        delta_x = tail[0] - tip[0]
        delta_y = tail[1] - tip[1]
        length = math.hypot(delta_x, delta_y)
        if not math.isfinite(length):
            raise ValueError("arrowhead length must be finite")
        if length == 0:
            raise ValueError("arrowhead tip and tail must differ")

        unit_x = delta_x / length
        unit_y = delta_y / length
        angle = math.radians(30)
        for sign in (-1, 1):
            cos_angle = math.cos(sign * angle)
            sin_angle = math.sin(sign * angle)
            wing_x = unit_x * cos_angle - unit_y * sin_angle
            wing_y = unit_x * sin_angle + unit_y * cos_angle
            self.stroke_line(
                tip,
                (tip[0] + wing_x * size, tip[1] + wing_y * size),
                color,
                thickness,
            )

    def fill_circle(self, center: Point, radius: int | float, color: Color) -> None:
        _require_finite_points((center,), "circle center")
        _require_finite_values((radius,), "circle radius")
        if radius < 0:
            raise ValueError("circle radius cannot be negative")
        center_x, center_y = center
        min_x = max(0, math.floor(center_x - radius))
        max_x = min(self.width - 1, math.ceil(center_x + radius))
        min_y = max(0, math.floor(center_y - radius))
        max_y = min(self.height - 1, math.ceil(center_y + radius))
        squared_radius = radius * radius
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                if (x - center_x) ** 2 + (y - center_y) ** 2 <= squared_radius:
                    self._set_pixel(x, y, color)

    def stroke_circle(
        self,
        center: Point,
        radius: int | float,
        color: Color,
        thickness: int = 1,
    ) -> None:
        _require_finite_points((center,), "circle center")
        _require_finite_values((radius,), "circle radius")
        if radius <= 0:
            raise ValueError("circle radius must be positive")
        _require_positive_integer(thickness, "circle stroke thickness")
        center_x, center_y = center
        min_x = max(0, math.floor(center_x - radius))
        max_x = min(self.width - 1, math.ceil(center_x + radius))
        min_y = max(0, math.floor(center_y - radius))
        max_y = min(self.height - 1, math.ceil(center_y + radius))
        inner_radius = max(0.0, radius - thickness)
        squared_inner = inner_radius * inner_radius
        squared_outer = radius * radius
        for y in range(min_y, max_y + 1):
            for x in range(min_x, max_x + 1):
                squared_distance = (x - center_x) ** 2 + (y - center_y) ** 2
                if squared_inner < squared_distance <= squared_outer:
                    self._set_pixel(x, y, color)

    def draw_text(
        self,
        text: str,
        origin: Point,
        color: Color,
        scale: int = 1,
    ) -> None:
        _require_finite_points((origin,), "text origin")
        _require_finite_values((scale,), "text scale")
        if not isinstance(scale, int) or isinstance(scale, bool) or not 1 <= scale <= 8:
            raise ValueError("text scale must be an integer from 1 to 8")
        origin_x = round(origin[0])
        origin_y = round(origin[1])
        advance = 6 * scale
        for character_index, character in enumerate(text):
            codepoint = ord(character)
            if not _FONT_FIRST_CODEPOINT <= codepoint <= _FONT_LAST_CODEPOINT:
                codepoint = ord(_FONT_FALLBACK)
            glyph_offset = (codepoint - _FONT_FIRST_CODEPOINT) * 5
            glyph = _FONT_5X7[glyph_offset : glyph_offset + 5]
            glyph_x = origin_x + character_index * advance
            for column, column_bits in enumerate(glyph):
                for row in range(7):
                    if column_bits & (1 << row):
                        self.fill_rect(
                            glyph_x + column * scale,
                            origin_y + row * scale,
                            glyph_x + (column + 1) * scale,
                            origin_y + (row + 1) * scale,
                            color,
                        )

    def _set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self.pixels[offset : offset + 3] = bytes(color)

    def _draw_line(self, x1: int, y1: int, x2: int, y2: int, color: Color, thickness: int) -> None:
        clipped = self._clip_segment((x1, y1), (x2, y2), thickness)
        if clipped is None:
            return
        (clipped_start, clipped_end, _, _) = clipped
        x1, y1 = round(clipped_start[0]), round(clipped_start[1])
        x2, y2 = round(clipped_end[0]), round(clipped_end[1])
        delta_x = abs(x2 - x1)
        delta_y = -abs(y2 - y1)
        step_x = 1 if x1 < x2 else -1
        step_y = 1 if y1 < y2 else -1
        error = delta_x + delta_y
        while True:
            self._paint_stroke_pixel(x1, y1, color, thickness)
            if x1 == x2 and y1 == y2:
                return
            double_error = 2 * error
            if double_error >= delta_y:
                error += delta_y
                x1 += step_x
            if double_error <= delta_x:
                error += delta_x
                y1 += step_y

    def _draw_dashed_segment(
        self,
        start: Point,
        end: Point,
        color: Color,
        thickness: int,
        dash_length: int | float,
        cycle_length: int | float,
        phase: float,
    ) -> None:
        clipped = self._clip_segment(start, end, thickness)
        if clipped is None:
            return
        clipped_start, clipped_end, start_ratio, end_ratio = clipped
        delta_x = clipped_end[0] - clipped_start[0]
        delta_y = clipped_end[1] - clipped_start[1]
        steps = max(abs(round(delta_x)), abs(round(delta_y)))
        original_length = math.hypot(end[0] - start[0], end[1] - start[1])
        if steps == 0:
            ratios = (start_ratio,)
        else:
            ratios = (
                start_ratio + (end_ratio - start_ratio) * index / steps
                for index in range(steps + 1)
            )
        for ratio in ratios:
            cycle_position = (phase + original_length * ratio) % cycle_length
            if cycle_position <= dash_length:
                self._paint_stroke_pixel(
                    round(start[0] + (end[0] - start[0]) * ratio),
                    round(start[1] + (end[1] - start[1]) * ratio),
                    color,
                    thickness,
                )

    def _paint_stroke_pixel(
        self,
        x: int,
        y: int,
        color: Color,
        thickness: int,
    ) -> None:
        offset_start = -(thickness // 2)
        left = max(0, x + offset_start)
        right = min(self.width - 1, x + offset_start + thickness - 1)
        top = max(0, y + offset_start)
        bottom = min(self.height - 1, y + offset_start + thickness - 1)
        for pixel_y in range(top, bottom + 1):
            for pixel_x in range(left, right + 1):
                self._set_pixel(pixel_x, pixel_y, color)

    def _clip_segment(
        self,
        start: Point,
        end: Point,
        thickness: int,
    ) -> tuple[Point, Point, float, float] | None:
        delta_x = end[0] - start[0]
        delta_y = end[1] - start[1]
        if not math.isfinite(delta_x) or not math.isfinite(delta_y):
            raise ValueError("line segment delta must be finite")

        offset_start = -(thickness // 2)
        offset_end = offset_start + thickness - 1
        min_x = -offset_end
        max_x = self.width - 1 - offset_start
        min_y = -offset_end
        max_y = self.height - 1 - offset_start
        start_ratio = 0.0
        end_ratio = 1.0
        boundaries = (
            (-delta_x, start[0] - min_x),
            (delta_x, max_x - start[0]),
            (-delta_y, start[1] - min_y),
            (delta_y, max_y - start[1]),
        )
        for direction, distance in boundaries:
            if direction == 0:
                if distance < 0:
                    return None
                continue
            ratio = distance / direction
            if direction < 0:
                start_ratio = max(start_ratio, ratio)
            else:
                end_ratio = min(end_ratio, ratio)
            if start_ratio > end_ratio:
                return None
        return (
            (
                start[0] + delta_x * start_ratio,
                start[1] + delta_y * start_ratio,
            ),
            (
                start[0] + delta_x * end_ratio,
                start[1] + delta_y * end_ratio,
            ),
            start_ratio,
            end_ratio,
        )

    def to_bytes(self) -> bytes:
        rows = []
        stride = self.width * 3
        for y in range(self.height):
            rows.append(b"\x00" + bytes(self.pixels[y * stride : (y + 1) * stride]))
        raw = b"".join(rows)
        return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", _ihdr(self.width, self.height)) + _chunk(
            b"IDAT", zlib.compress(raw)
        ) + _chunk(b"IEND", b"")


def _require_finite_values(
    values: tuple[int | float, ...],
    description: str,
) -> None:
    try:
        finite = all(math.isfinite(value) for value in values)
    except TypeError as error:
        raise ValueError(f"{description} must be finite numbers") from error
    if not finite:
        raise ValueError(f"{description} must be finite")


def _require_finite_points(
    points: tuple[Point, ...] | list[Point],
    description: str,
) -> None:
    try:
        values = tuple(coordinate for point in points for coordinate in point)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{description} must contain finite coordinate pairs") from error
    if any(len(point) != 2 for point in points):
        raise ValueError(f"{description} must contain finite coordinate pairs")
    _require_finite_values(values, description)


def _require_positive_integer(value: int, description: str) -> None:
    _require_finite_values((value,), description)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{description} must be a positive integer")
    if value < 1:
        raise ValueError(f"{description} must be positive")


def _ihdr(width: int, height: int) -> bytes:
    return struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)
