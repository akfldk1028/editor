"""What kind of designation a 토지이용계획 name is, and what follows for the caps.

`getLandUseAttr` lists everything that binds a parcel in one flat list: 용도지역 (제2종일반주거지역), 용도지구·구역·권역
(지구단위계획구역, 과밀억제권역, 가축사육제한구역) and district-plan land uses or facilities (공공청사, 주차장, 공원).
Only a 용도지역 decides 건폐율·용적률 under the ordinance table (국토계획법 제36조·제77조·제78조); a 지구·구역 adds its
own restrictions on top (제37조·제38조…); a 용지·시설 is a 지구단위계획 or 공공주택지구 decision about what the land is
for, not a zoning category at all. The calculators used to call every name they did not recognise "unresolved
zoning" and withhold the caps — which turned a plain 제2종일반주거지역 parcel into "상한 미확정" because its district
plan marks it 공공청사. Pure.
"""
from __future__ import annotations

import re
from typing import Iterable

USE_ZONE = 'use_zone'          # a 국토계획법 제36조 용도지역: decides the caps; unknown → the caps are genuinely unresolved
OVERLAY = 'overlay'            # …지구·구역·권역·지대 and other …지역 designations: restrictions on top; unknown → reported, caps stand
FACILITY = 'facility'          # anything else (공공청사, 공원, 주차장 …): a land-use decision; reported, caps stand

# 국토계획법 제36조: the 용도지역 families. A name ending in 지역 outside them (역사문화환경보존지역, 소음대책지역 …)
# is a designation under another law, not a zoning category, and must not withhold the caps.
_USE_ZONE_FAMILIES = ('주거지역', '상업지역', '공업지역', '녹지지역', '관리지역', '농림지역', '자연환경보전지역')
_OVERLAY_SUFFIXES = ('지구', '구역', '권역', '지대', '구간', '지역')
# 시행령 제86조제1항 단서: the 정북 일조 setback does not bind (1호) a parcel inside 지구단위계획구역·경관지구(자연·시가지·특화…)·
# 중점경관관리구역·특별가로구역 (or a 허가권자-designated area) when it fronts a road 20 m or wider, (2호) a parcel inside a
# 건축협정구역 building against another in it, (3호) when the 정북 neighbour is not an 전용·일반주거지역. 1호 needs the road
# width and 3호 the neighbour's zone — Site facts — so the rule is conditional where these designations appear.
_SUNLIGHT_ROAD_EXEMPTION_AREAS = ('지구단위계획구역', '경관지구', '중점경관관리구역', '특별가로구역')
_SUNLIGHT_AGREEMENT_AREA = '건축협정구역'
_PARENTHETICAL = re.compile(r'\s*\([^)]*\)\s*$')


def kind(name: str) -> str:
    # "제2종일반주거지역(7층이하)": the qualifier in brackets is not part of the designation's kind.
    name = _PARENTHETICAL.sub('', (name or '').strip())
    if name.endswith(_USE_ZONE_FAMILIES):
        return USE_ZONE
    if name.endswith(_OVERLAY_SUFFIXES):
        return OVERLAY
    return FACILITY


def unresolved_evidence(names: Iterable[str], known_zones: set[str], recognized_overlays: set[str]) -> tuple[list[str], list[str]]:
    """(blocking, codes) for the names neither the zone catalog nor the overlay table knows: a code per name
    (`unresolved_zoning:` for a 용도지역, `unlisted_designation:` otherwise) and which of them block the caps."""
    blocking, codes = [], []
    for name in names:
        if name in known_zones or name in recognized_overlays:
            continue
        if kind(name) == USE_ZONE:
            blocking.append(name)
            codes.append('unresolved_zoning:' + name)
        else:
            codes.append('unlisted_designation:' + name)
    return blocking, codes


def sunlight_exemption_areas(names: Iterable[str]) -> list[str]:
    """The parcel's designations under which 시행령 제86조①1 (road ≥ 20 m) or 2 (건축협정구역) can lift the 정북 setback."""
    return [name for name in names if name.endswith(_SUNLIGHT_ROAD_EXEMPTION_AREAS) or name == _SUNLIGHT_AGREEMENT_AREA]


_SUNLIGHT_BOUND_NEIGHBOUR = ('전용주거지역', '일반주거지역')


def sunlight_exemption_note(names: Iterable[str], north_neighbour_zone: str | None = None) -> str | None:
    """The one-line 단서 for the parcel's designations (and, when known, its 정북 neighbour's zone), or None."""
    found = sunlight_exemption_areas(names)
    road = [name for name in found if name != _SUNLIGHT_AGREEMENT_AREA]
    parts = []
    if north_neighbour_zone and not north_neighbour_zone.endswith(_SUNLIGHT_BOUND_NEIGHBOUR):
        # 시행령 제86조①3: the 정북 neighbour is not an 전용·일반주거지역 — the setback does not apply (zone layer reading).
        parts.append(f'정북방향 인접 대지가 {north_neighbour_zone}(전용·일반주거지역 아님)이라 적용 제외(시행령 §86①3) — 용도지역 레이어로 읽은 값, 지적·현황 확인')
    if road:
        parts.append(f"{'·'.join(road)} 안 대지가 너비 20m 이상 도로에 접하면 적용 제외(시행령 §86①1), 접도 폭 확인")
    if _SUNLIGHT_AGREEMENT_AREA in found:
        parts.append('건축협정구역 안 대지 상호간 건축이면 적용 제외(시행령 §86①2)')
    return '; '.join(parts) if parts else None


__all__ = ['FACILITY', 'OVERLAY', 'USE_ZONE', 'kind', 'sunlight_exemption_areas', 'sunlight_exemption_note', 'unresolved_evidence']
