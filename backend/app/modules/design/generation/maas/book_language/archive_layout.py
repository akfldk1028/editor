"""Shared immutable layout contract for portfolio board cards."""

from __future__ import annotations


ARCHIVE_CARD_WIDTH = 384
ARCHIVE_CARD_HEIGHT = 322
ARCHIVE_HEADER_HEIGHT = 72
ARCHIVE_PREVIEW_HEIGHT = 260
ARCHIVE_COLUMNS = 5


def archive_card_crop_box(card_index: int) -> tuple[int, int, int, int]:
    """Return the one-based portfolio card's preview crop."""

    if int(card_index) < 1:
        raise ValueError("card_index must be one-based and positive")
    zero_based = int(card_index) - 1
    x = (zero_based % ARCHIVE_COLUMNS) * ARCHIVE_CARD_WIDTH
    y = ARCHIVE_HEADER_HEIGHT + (zero_based // ARCHIVE_COLUMNS) * ARCHIVE_CARD_HEIGHT
    return (
        x,
        y,
        x + ARCHIVE_CARD_WIDTH,
        y + ARCHIVE_PREVIEW_HEIGHT,
    )


__all__ = [
    "ARCHIVE_CARD_HEIGHT",
    "ARCHIVE_CARD_WIDTH",
    "ARCHIVE_COLUMNS",
    "ARCHIVE_HEADER_HEIGHT",
    "ARCHIVE_PREVIEW_HEIGHT",
    "archive_card_crop_box",
]
