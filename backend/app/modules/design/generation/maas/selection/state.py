"""Mutable state container for MAAS review selection."""

from __future__ import annotations

from typing import Callable

from backend.app.modules.design.generation.maas.selection.constraints import final_shape
from backend.app.modules.design.generation.maas.selection.types import Feature, FeatureBool, FeatureText


class SelectionState:
    """Mutable review selection state shared by extraction steps."""

    def __init__(self, *, source_family: FeatureText) -> None:
        self.result: list[Feature] = []
        self.seen_ids: set[int] = set()
        self.seen_shapes: set[str] = set()
        self.seen_source_families: dict[str, int] = {}
        self._source_family = source_family

    def rebuild(self) -> None:
        self.seen_ids.clear()
        self.seen_shapes.clear()
        self.seen_source_families.clear()
        for item in self.result:
            self.seen_ids.add(id(item))
            shape = final_shape(item)
            if shape:
                self.seen_shapes.add(shape)
            source_family = self._source_family(item)
            if source_family:
                self.seen_source_families[source_family] = self.seen_source_families.get(source_family, 0) + 1

    def append_seen(self, feature: Feature, *, source_family: str | None = None) -> None:
        self.result.append(feature)
        self.seen_ids.add(id(feature))
        shape = final_shape(feature)
        if shape:
            self.seen_shapes.add(shape)
        family = source_family if source_family is not None else self._source_family(feature)
        if family:
            self.seen_source_families[family] = self.seen_source_families.get(family, 0) + 1

    def replace_if_valid(
        self,
        index: int,
        candidate: Feature,
        *,
        constraints_ok: Callable[[list[Feature]], bool],
    ) -> bool:
        if candidate in self.result:
            return False
        previous = self.result[index]
        self.result[index] = candidate
        if not constraints_ok(self.result):
            self.result[index] = previous
            self.rebuild()
            return False
        self.rebuild()
        return True

    def replace_relaxed(
        self,
        index: int,
        candidate: Feature,
        *,
        mass_stage_parking_pass: FeatureBool,
        review_geometry_ok: FeatureBool | None = None,
        enforce_unique_shape: bool = True,
    ) -> bool:
        if candidate in self.result:
            return False
        if not mass_stage_parking_pass(candidate):
            return False
        if review_geometry_ok is not None and not review_geometry_ok(candidate):
            return False
        shape = final_shape(candidate)
        if shape and enforce_unique_shape and any(
            i != index and final_shape(item) == shape
            for i, item in enumerate(self.result)
        ):
            return False
        self.result[index] = candidate
        self.rebuild()
        return True

    def replace_unchecked(self, index: int, candidate: Feature) -> None:
        self.result[index] = candidate
        self.rebuild()
