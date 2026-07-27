from __future__ import annotations

import math
import struct
import zlib


Color = tuple[int, int, int]


class SimplePngCanvas:
    def __init__(self, width: int, height: int, background: Color = (255, 255, 255)):
        if width <= 0 or height <= 0:
            raise ValueError("png canvas width and height must be positive")
        self.width = width
        self.height = height
        self.pixels = bytearray(background * width * height)

    def fill_rect(self, x0: int, y0: int, x1: int, y1: int, color: Color) -> None:
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
        self.fill_rect(x0, y0, x1, y0 + thickness, color)
        self.fill_rect(x0, y1 - thickness, x1, y1, color)
        self.fill_rect(x0, y0, x0 + thickness, y1, color)
        self.fill_rect(x1 - thickness, y0, x1, y1, color)

    def fill_polygon(self, points: list[tuple[int | float, int | float]], color: Color) -> None:
        if len(points) < 3:
            raise ValueError("polygon requires at least three points")

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
        if thickness < 1:
            raise ValueError("polygon stroke thickness must be positive")
        for (x1, y1), (x2, y2) in zip(points, points[1:] + points[:1]):
            self._draw_line(round(x1), round(y1), round(x2), round(y2), color, thickness)

    def stroke_line(
        self,
        start: tuple[int | float, int | float],
        end: tuple[int | float, int | float],
        color: Color,
        thickness: int = 1,
    ) -> None:
        if thickness < 1:
            raise ValueError("line stroke thickness must be positive")
        self._draw_line(
            round(start[0]),
            round(start[1]),
            round(end[0]),
            round(end[1]),
            color,
            thickness,
        )

    def _set_pixel(self, x: int, y: int, color: Color) -> None:
        if 0 <= x < self.width and 0 <= y < self.height:
            offset = (y * self.width + x) * 3
            self.pixels[offset : offset + 3] = bytes(color)

    def _draw_line(self, x1: int, y1: int, x2: int, y2: int, color: Color, thickness: int) -> None:
        delta_x = abs(x2 - x1)
        delta_y = -abs(y2 - y1)
        step_x = 1 if x1 < x2 else -1
        step_y = 1 if y1 < y2 else -1
        error = delta_x + delta_y
        start = -(thickness // 2)
        while True:
            for offset_y in range(start, start + thickness):
                for offset_x in range(start, start + thickness):
                    self._set_pixel(x1 + offset_x, y1 + offset_y, color)
            if x1 == x2 and y1 == y2:
                return
            double_error = 2 * error
            if double_error >= delta_y:
                error += delta_y
                x1 += step_x
            if double_error <= delta_x:
                error += delta_x
                y1 += step_y

    def to_bytes(self) -> bytes:
        rows = []
        stride = self.width * 3
        for y in range(self.height):
            rows.append(b"\x00" + bytes(self.pixels[y * stride : (y + 1) * stride]))
        raw = b"".join(rows)
        return b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", _ihdr(self.width, self.height)) + _chunk(
            b"IDAT", zlib.compress(raw)
        ) + _chunk(b"IEND", b"")


def _ihdr(width: int, height: int) -> bytes:
    return struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)


def _chunk(kind: bytes, data: bytes) -> bytes:
    checksum = zlib.crc32(kind + data) & 0xFFFFFFFF
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", checksum)
