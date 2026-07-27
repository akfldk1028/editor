from __future__ import annotations

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
