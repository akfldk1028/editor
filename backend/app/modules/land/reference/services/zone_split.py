"""How a parcel is divided between its 용도지역 — the one rule both `zone_geometry` copies apply.

용도지역 are mutually exclusive by definition (국토계획법 제36조: one of the four kinds per piece of
ground), yet the Vworld 용도지역 layer (LT_C_UQ111) is drawn feature by feature at different times and
scales, so two zone polygons can overlap each other by a hair and a zone boundary can sit a metre
off the cadastral line. Measured on the verified parcels: a 54.6 m × 0.09 m strip of 자연녹지지역
lying entirely inside the 제2종일반주거지역 polygon on 4115011300106840001, a 0.05 m strip on its
neighbour, 0.005 m strips on two Seoul parcels. Treating such a strip as a part of the parcel that
carries its own building limits turned a 60 % cap into 59.92 % through the 제84조 weighted average.

This module partitions the parcel exclusively and separates boundary tolerance from a real split:

1. Zones are walked from the one covering most of the parcel downwards; ground two zones both claim
   goes to the earlier (larger) one. Overlaps are recorded, never counted twice.
2. A remaining exclusive part that is under BOUNDARY_TOLERANCE_MAX_SHARE of the parcel, narrower
   than BOUNDARY_TOLERANCE_MAX_WIDTH_M and no larger than the 시행령 제94조 small-part size is a
   drawing artefact, not a 제84조 part: it is folded into the largest zone and disclosed.
3. Ground no zone polygon covers is reported as `uncovered_m2` and never redistributed.

Basis for the tolerance: 용도지역 are decided on 1:5,000 지형도면 (국토계획법 제32조), where a
0.1–0.2 mm line is 0.5–1.0 m of ground; the measured offset between LT_C_UQ111 and the cadastral
layer on the verified parcels is 1.2–1.8 m; a 제94조 split (330 m² / 660 m² parts) is tens of
metres wide. The statute itself sets no measurement tolerance — the thresholds are this module's,
named here, and every exclusion is carried into the result so the Law Agent and the user can read
it against the 토지이용계획확인서, which lists the same artefact zone.

Pure: shapely in, dataclasses out. No provider I/O, no rounding of what callers compute with.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Sequence

from shapely.geometry import GeometryCollection, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union
from shapely.validation import make_valid

SPLIT_VERSION = 'zone_split.v1'            # stored with cached splits; bump on any change of rule
METHOD = 'exclusive_partition+boundary_tolerance'
BOUNDARY_TOLERANCE_MAX_SHARE = 0.01        # a part under 1 % of the parcel ...
BOUNDARY_TOLERANCE_MAX_WIDTH_M = 1.0       # ... and narrower than one map line (see module docstring)
AREA_EPSILON_M2 = 1e-6                     # below this a geometry has no area (shared edges, collapsed rings)
TOLERANCE_BASIS = ('1:5,000 지형도면(국토계획법 제32조) 선 굵기 0.1~0.2 mm = 지상 0.5~1.0 m; 용도지역 레이어와 지적 경계의 '
                   '실측 오프셋 1.2~1.8 m; 시행령 제94조의 분할 부분(330/660㎡)은 수십 m 폭')

ZONE_OVERLAP = 'zone_overlap'
BOUNDARY_TOLERANCE = 'boundary_tolerance'


@dataclass(frozen=True)
class ExcludedSliver:
    """A piece of the parcel a zone polygon claims but the split does not give it."""
    zone: str
    area_m2: float
    width_m: float          # 2·area / perimeter of the excluded geometry: the strip's mean width
    share: float            # area / parcel area
    reason: str             # ZONE_OVERLAP (another zone already covers it) | BOUNDARY_TOLERANCE
    folded_into: str        # the zone whose area carries it

    def note(self) -> str:
        cause = '용도지역 폴리곤끼리 겹친 부분' if self.reason == ZONE_OVERLAP else '도면 경계 허용오차 폭의 띠'
        return (f'{self.zone}: 토지이용계획 속성에는 표시되나 측정 폭 {self.width_m:.2f} m, {self.area_m2:.2f}㎡({self.share:.2%})의 '
                f'{cause}으로 제84조 분할에서 제외, {self.folded_into}에 귀속')


@dataclass(frozen=True)
class ZoneSplit:
    """The parcel's exclusive division between its 용도지역, with what was excluded and why."""
    parcel_area_m2: float
    areas: dict[str, float]                      # exclusive, after folding; sum == parcel_area − uncovered_m2
    excluded_slivers: tuple[ExcludedSliver, ...]
    uncovered_m2: float                          # ground no zone polygon covers; reported, never redistributed
    method: str = METHOD
    version: str = SPLIT_VERSION

    @property
    def zones(self) -> list[str]:
        """Zone names that keep ground, largest first."""
        return [name for name, _ in sorted(self.areas.items(), key=lambda item: (-item[1], item[0])) if _ > AREA_EPSILON_M2]

    def notes(self) -> list[str]:
        lines = [sliver.note() for sliver in self.excluded_slivers]
        if self.uncovered_m2 > 0.01:
            lines.append(f'용도지역 미피복 {self.uncovered_m2:.2f}㎡ (어느 용도지역에도 배분하지 않음)')
        return lines

    def to_dict(self) -> dict:
        return {
            'version': self.version, 'method': self.method,
            'parcel_area_m2': round(self.parcel_area_m2, 4),
            'areas_m2': {name: round(area, 4) for name, area in self.areas.items()},
            'excluded_slivers': [{'zone': s.zone, 'area_m2': round(s.area_m2, 3), 'width_m': round(s.width_m, 3),
                                  'share': round(s.share, 6), 'reason': s.reason, 'folded_into': s.folded_into}
                                 for s in self.excluded_slivers],
            'uncovered_m2': round(self.uncovered_m2, 4),
            'thresholds': {'max_share': BOUNDARY_TOLERANCE_MAX_SHARE, 'max_width_m': BOUNDARY_TOLERANCE_MAX_WIDTH_M,
                           'basis': TOLERANCE_BASIS},
            'notes': self.notes(),
        }


def polygonal(geometry: BaseGeometry | None) -> BaseGeometry:
    """Only the areal parts of a geometry: a Polygon/MultiPolygon, or an empty Polygon when there are none."""
    if geometry is None or geometry.is_empty:
        return Polygon()
    if isinstance(geometry, (Polygon, MultiPolygon)):
        return geometry
    if isinstance(geometry, GeometryCollection):
        parts = [part for part in geometry.geoms if isinstance(part, (Polygon, MultiPolygon)) and not part.is_empty]
        return polygonal(unary_union(parts)) if parts else Polygon()
    return Polygon()


def _width(geometry: BaseGeometry) -> float:
    """The mean width of a strip-shaped geometry: 2·area / perimeter (a 0.1 m × 50 m strip → 0.1 m)."""
    length = float(geometry.length)
    return 2.0 * float(geometry.area) / length if length > 0.0 else 0.0


def split_parcel(parcel_utm: Polygon, pieces_by_zone: Mapping[str, Sequence[BaseGeometry]], *,
                 small_part_m2: float | None = None) -> ZoneSplit:
    """Divide `parcel_utm` (metres) between zones from their parcel-clipped pieces.

    `pieces_by_zone`: per zone name, the UTM geometries of that zone's features already intersected with
    the parcel (one per WFS feature; the same zone comes back as several features). `small_part_m2` is the
    시행령 제94조 small-part size (330 m²); a strip larger than it is never treated as tolerance, whatever
    its width, so this rule can never swallow a part the statute would split on."""
    parcel_area = float(parcel_utm.area)
    if parcel_area <= AREA_EPSILON_M2:
        return ZoneSplit(parcel_area_m2=max(parcel_area, 0.0), areas={}, excluded_slivers=(), uncovered_m2=0.0)

    merged: dict[str, BaseGeometry] = {}
    for name, parts in pieces_by_zone.items():
        geometry = polygonal(unary_union([part for part in parts if part is not None and not part.is_empty]) if parts else None)
        if not geometry.is_empty and not geometry.is_valid:
            geometry = polygonal(make_valid(geometry))
        if float(geometry.area) > AREA_EPSILON_M2:
            merged[name] = geometry

    order = sorted(merged, key=lambda name: (-float(merged[name].area), name))
    exclusive: dict[str, BaseGeometry] = {}
    slivers: list[ExcludedSliver] = []
    covered: BaseGeometry = Polygon()
    for name in order:
        piece = merged[name]
        overlap = polygonal(piece.intersection(covered)) if not covered.is_empty else Polygon()
        if float(overlap.area) > AREA_EPSILON_M2:
            owner = max((earlier for earlier in exclusive if merged[earlier].intersects(overlap)),
                        key=lambda earlier: float(merged[earlier].intersection(overlap).area), default=order[0])
            slivers.append(ExcludedSliver(zone=name, area_m2=float(overlap.area), width_m=_width(overlap),
                                          share=float(overlap.area) / parcel_area, reason=ZONE_OVERLAP, folded_into=owner))
        part = polygonal(piece.difference(covered)) if not covered.is_empty else piece
        if float(part.area) > AREA_EPSILON_M2:
            exclusive[name] = part
        covered = unary_union([covered, piece]) if not covered.is_empty else piece
    uncovered = max(0.0, parcel_area - float(polygonal(covered).area))

    areas = {name: float(part.area) for name, part in exclusive.items()}
    if areas:
        largest = max(areas, key=lambda name: (areas[name], name))
        for name in sorted(exclusive):
            if name == largest:
                continue
            part = exclusive[name]
            area, width = float(part.area), _width(part)
            share = area / parcel_area
            if (share < BOUNDARY_TOLERANCE_MAX_SHARE and width < BOUNDARY_TOLERANCE_MAX_WIDTH_M
                    and (small_part_m2 is None or area <= small_part_m2)):
                slivers.append(ExcludedSliver(zone=name, area_m2=area, width_m=width, share=share,
                                              reason=BOUNDARY_TOLERANCE, folded_into=largest))
                areas[largest] += area
                del areas[name]
    return ZoneSplit(parcel_area_m2=parcel_area, areas=areas, excluded_slivers=tuple(slivers), uncovered_m2=uncovered)


def exclusive_zone_names(areas: Mapping[str, float] | None, names: Iterable[str],
                         is_use_zone: Callable[[str], bool]) -> tuple[list[str], list[str]]:
    """(kept, removed): a 용도지역 name (`is_use_zone`) with no ground left in `areas` is removed; 지구·구역 and
    unknown names pass through. With no split (`areas` None) nothing is removed."""
    names = list(names)
    if areas is None:
        return names, []
    kept, removed = [], []
    for name in names:
        if is_use_zone(name) and float(areas.get(name, 0.0)) <= AREA_EPSILON_M2:
            removed.append(name)
        else:
            kept.append(name)
    return kept, removed


def with_removed(payload: Mapping, removed: Sequence[str]) -> dict:
    """The split's dict plus `removed_zones` — the official 용도지역 names the split left no ground to — with a
    note for every removed zone the slivers do not already explain (a zone the layer never brings inside the
    parcel at all leaves no sliver, but the 토지이용계획 attribute still lists it, so it must be said)."""
    explained = {sliver.get('zone') for sliver in payload.get('excluded_slivers') or [] if isinstance(sliver, dict)}
    notes = list(payload.get('notes') or [])
    notes.extend(f'{zone}: 토지이용계획 속성에는 표시되나 용도지역 레이어에서 필지와 겹치는 면적이 없어 제84조 분할에서 제외'
                 for zone in removed if zone not in explained)
    return {**payload, 'removed_zones': list(removed), 'notes': notes}


__all__ = ['AREA_EPSILON_M2', 'BOUNDARY_TOLERANCE', 'BOUNDARY_TOLERANCE_MAX_SHARE', 'BOUNDARY_TOLERANCE_MAX_WIDTH_M',
           'ExcludedSliver', 'METHOD', 'SPLIT_VERSION', 'ZONE_OVERLAP', 'ZoneSplit', 'exclusive_zone_names',
           'polygonal', 'split_parcel', 'with_removed']
