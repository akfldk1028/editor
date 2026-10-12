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

from typing import Iterable

USE_ZONE = 'use_zone'          # …지역: decides the caps; unknown → the caps are genuinely unresolved
OVERLAY = 'overlay'            # …지구·구역·권역·지대: restrictions on top; unknown → reported, caps stand
FACILITY = 'facility'          # anything else (공공청사, 공원, 주차장 …): a land-use decision; reported, caps stand

_OVERLAY_SUFFIXES = ('지구', '구역', '권역', '지대', '구간')
# 시행령 제86조제1항 단서 1호·3호: in these areas a parcel on a road 20 m or wider (or inside a 건축협정구역) is not
# bound by the 정북 일조 setback — a Site fact (road width) decides, so the rule is conditional there.
SUNLIGHT_EXEMPTION_AREAS = ('지구단위계획구역', '경관지구', '중점경관관리구역', '특별가로구역', '건축협정구역')


def kind(name: str) -> str:
    name = (name or '').strip()
    if name.endswith('지역'):
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
    """The parcel's designations under which 시행령 제86조①1·3 can lift the 정북 setback (road width decides)."""
    return [name for name in names if name in SUNLIGHT_EXEMPTION_AREAS]


__all__ = ['FACILITY', 'OVERLAY', 'SUNLIGHT_EXEMPTION_AREAS', 'USE_ZONE', 'kind', 'sunlight_exemption_areas', 'unresolved_evidence']
