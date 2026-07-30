from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExteriorAllocationRequest:
    floor_index: int
    room_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.floor_index, int)
            or isinstance(self.floor_index, bool)
            or self.floor_index < 1
        ):
            raise ValueError("exterior allocation floor_index must be positive")
        if (
            not isinstance(self.room_ids, tuple)
            or not self.room_ids
            or any(
                not isinstance(room_id, str) or not room_id.strip()
                for room_id in self.room_ids
            )
        ):
            raise ValueError("exterior allocation room_ids must be non-empty strings")
        if self.room_ids != tuple(sorted(set(self.room_ids))):
            raise ValueError(
                "exterior allocation room_ids must be sorted and unique"
            )
