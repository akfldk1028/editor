"""Normative area sizing for program spaces.

Room areas used to be a flat fraction of the floor plate, so a restroom grew
with the building instead of with its occupancy: the same office program
produced 24.9 m2 of restroom on a 707 m2 plate and 70.4 m2 on a 763 m2 plate.

Every space here is sized from the quantity that actually drives it -- fixture
counts for restrooms, headcount for meeting and focus space, a fixed module for
service rooms -- and carries the citation and evidence level behind that number.
Anything we assumed rather than sourced is surfaced through ``unresolved_facts``
so it reaches the delivery manifest as ``not_checked`` instead of passing for a
regulatory fact.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields as dataclass_fields
import json
import math
from pathlib import Path
from typing import Literal


EvidenceLevel = Literal["statutory", "practice", "assumed"]
SizingBasis = Literal["fixture", "occupancy", "fixed", "ratio", "residual"]


# 「업무시설 적정 공간면적 설계기준 개발 연구」(국토교통부) proposes 8.5 m2 per
# person as the optimum net workplace area, measured as
# (total - core - primary circulation) / headcount.
WORKPLACE_AREA_PER_PERSON_M2 = 8.5
_WORKPLACE_CITATION = "업무시설 적정 공간면적 설계기준 개발 연구 (국토교통부)"



@dataclass(frozen=True)
class FixtureModule:
    """A plumbing fixture and the floor area its module occupies."""

    name: str
    width_m: float
    depth_m: float
    citation: str
    evidence_level: EvidenceLevel

    def __post_init__(self) -> None:
        for label in ("width_m", "depth_m"):
            value = getattr(self, label)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{self.name} {label} must be finite and positive")

    @property
    def area_m2(self) -> float:
        return self.width_m * self.depth_m


# 「장애인·노인·임산부 등의 편의증진 보장에 관한 법률 시행규칙」 별표 1 requires a
# 1.6 m x 2.0 m clear floor area for an accessible stall in new construction.
ACCESSIBLE_STALL = FixtureModule(
    name="accessible_water_closet",
    width_m=1.6,
    depth_m=2.0,
    citation="장애인등편의법 시행규칙 별표1 (신축 유효바닥면적 1.6m x 2.0m)",
    evidence_level="statutory",
)

# Standard stall and fixture modules.  Korean law fixes the accessible stall but
# not the ordinary one, so these are conventional design dimensions.
STANDARD_STALL = FixtureModule(
    name="water_closet",
    width_m=0.9,
    depth_m=1.4,
    citation="관행 설계치수 (법정 기준 없음)",
    evidence_level="practice",
)
URINAL = FixtureModule(
    name="urinal",
    width_m=0.75,
    depth_m=1.2,
    citation="관행 설계치수 (법정 기준 없음)",
    evidence_level="practice",
)
LAVATORY = FixtureModule(
    name="lavatory",
    width_m=0.6,
    depth_m=1.2,
    citation="관행 설계치수 (법정 기준 없음)",
    evidence_level="practice",
)

# Lobby, cross-circulation between fixture runs and wall thickness, as a
# multiplier on net fixture area.
_RESTROOM_CIRCULATION_FACTOR = 1.55

_MALE_SHARE = 0.5


@dataclass(frozen=True)
class RestroomSchedule:
    """Fixture counts and the resulting restroom area for one floor."""

    occupants: int
    male_water_closets: int
    female_water_closets: int
    urinals: int
    lavatories: int
    accessible_stalls: int
    fixture_area_m2: float
    circulation_factor: float
    total_area_m2: float
    unresolved_facts: tuple[str, ...]


def occupant_load(workplace_area_m2: float) -> int:
    """Headcount a net workplace area supports, rounded up to a whole person."""
    if not math.isfinite(workplace_area_m2) or workplace_area_m2 < 0:
        raise ValueError("workplace_area_m2 must be finite and non-negative")
    return math.ceil(workplace_area_m2 / WORKPLACE_AREA_PER_PERSON_M2)


def _water_closets_ibc_business(occupants: int) -> int:
    """IBC Table 2902.1, Group B: 1 per 25 for the first 50, then 1 per 50."""
    if occupants <= 0:
        return 0
    if occupants <= 50:
        return math.ceil(occupants / 25)
    return 2 + math.ceil((occupants - 50) / 50)


def restroom_schedule(
    *,
    occupants: int,
    jurisdiction: str | None = None,
) -> RestroomSchedule:
    """Size a restroom from its fixture schedule rather than from floor area."""
    if occupants < 0:
        raise ValueError("occupants must be non-negative")

    unresolved: list[str] = [
        "restroom fixture count assumes a 50/50 gender split; actual tenant "
        "gender ratio not_checked",
        "IBC Table 2902.1 Group B used for water closet counts; the Korean "
        "equivalent for 업무시설 is not_checked",
    ]

    male_occupants = math.ceil(occupants * _MALE_SHARE)
    female_occupants = occupants - male_occupants

    male_wc = _water_closets_ibc_business(male_occupants)
    female_wc = _water_closets_ibc_business(female_occupants)
    urinals = male_wc

    if jurisdiction and jurisdiction.upper().startswith("KR"):
        # 공중화장실 등에 관한 법률 시행령 별표: the number of female water closets
        # must be at least 1.5x the male water closets plus urinals.  That statute
        # governs 공중화장실; applying it to an office floor is a conservative
        # design choice, so it is recorded rather than claimed as compliance.
        female_wc = max(female_wc, math.ceil((male_wc + urinals) * 1.5))
        unresolved.append(
            "공중화장실법 여성 대변기 1.5배 규칙을 업무시설에 적용함; 해당 법의 "
            "업무시설 적용 여부 not_checked"
        )

    # One accessible stall per gender is the conventional provision; the statute
    # fixes the stall size, not how many floors must have one.
    accessible = 2 if occupants > 0 else 0
    unresolved.append(
        "accessible stall count assumed at one per gender per floor; "
        "장애인등편의법 의무 설치 대상 여부 not_checked"
    )

    lavatories = male_wc + female_wc  # IBC Group B: 1 lavatory per water closet

    fixture_area = (
        (male_wc + female_wc) * STANDARD_STALL.area_m2
        + urinals * URINAL.area_m2
        + lavatories * LAVATORY.area_m2
        + accessible * ACCESSIBLE_STALL.area_m2
    )
    total = fixture_area * _RESTROOM_CIRCULATION_FACTOR

    return RestroomSchedule(
        occupants=occupants,
        male_water_closets=male_wc,
        female_water_closets=female_wc,
        urinals=urinals,
        lavatories=lavatories,
        accessible_stalls=accessible,
        fixture_area_m2=round(fixture_area, 3),
        circulation_factor=_RESTROOM_CIRCULATION_FACTOR,
        total_area_m2=round(total, 3),
        unresolved_facts=tuple(unresolved),
    )


@dataclass(frozen=True)
class SizingContext:
    """What a floor knows about itself before its program is sized."""

    net_area_m2: float
    jurisdiction: str | None = None

    def __post_init__(self) -> None:
        if not math.isfinite(self.net_area_m2) or self.net_area_m2 <= 0:
            raise ValueError("net_area_m2 must be finite and positive")

    def workplace_area_m2(self, core_share: float = 0.0) -> float:
        """Net workplace area the headcount standard is measured on.

        The 국토부 basis takes (total - core - primary circulation);
        ``net_area_m2`` already excludes the corridor and the corners no room
        can take, so only the core's share comes off here.
        """
        if not 0.0 <= core_share < 1.0:
            raise ValueError("core_share must be in [0, 1)")
        return self.net_area_m2 * (1.0 - core_share)

    def occupants(self, core_share: float = 0.0) -> int:
        return occupant_load(self.workplace_area_m2(core_share))


@dataclass(frozen=True)
class SizingRule:
    """How one space type derives its area."""

    basis: SizingBasis
    citation: str
    evidence_level: EvidenceLevel
    # occupancy basis: area = base_m2 + per_occupant_m2 * occupants
    base_m2: float = 0.0
    per_occupant_m2: float = 0.0
    minimum_m2: float = 0.0
    # ratio basis: area = plate_ratio * net_area_m2
    plate_ratio: float = 0.0


# ---------------------------------------------------------------- use profiles as data
# Each use type is a JSON file in ``profiles/``: its spaces, relationships and
# (optionally) sizing rules, every rule with its citation and evidence level.
# A new use type is a new file; nothing here changes.
_PROFILE_DIR = Path(__file__).resolve().parent / "profiles"


def _fields(cls, item: dict) -> dict:
    names = {f.name for f in dataclass_fields(cls)}
    return {key: value for key, value in item.items() if key in names}


def load_sizing_rules(use_type: str) -> dict[str, SizingRule] | None:
    data = _read_profile(use_type)
    rules = data.get("sizing_rules")
    if rules is None:
        return None
    return {name: SizingRule(**_fields(SizingRule, item)) for name, item in rules.items()}


def _read_profile(use_type: str) -> dict:
    path = _PROFILE_DIR / f"{use_type}.json"
    if not path.is_file():
        raise ValueError(f"unsupported use_type: {use_type}")
    return json.loads(path.read_text(encoding="utf-8"))


@dataclass(frozen=True)
class SizedSpace:
    space_type: str
    area_m2: float
    basis: SizingBasis
    citation: str
    evidence_level: EvidenceLevel
    unresolved_facts: tuple[str, ...] = field(default_factory=tuple)


_ASSUMED = "내부 설계 가정치 (출처 미확인)"

OFFICE_SIZING: dict[str, SizingRule] = load_sizing_rules("office")  # profiles/office.json


def size_space(
    space_type: str,
    context: SizingContext,
    rules: dict[str, SizingRule],
) -> SizedSpace:
    """Derive one space's target area from its own driver."""
    rule = rules.get(space_type)
    if rule is None:
        raise KeyError(f"no sizing rule for space type: {space_type}")

    if rule.basis == "fixture":
        core_rule = rules.get("core")
        core_share = (
            core_rule.plate_ratio
            if core_rule is not None and core_rule.basis == "ratio"
            else 0.0
        )
        schedule = restroom_schedule(
            occupants=context.occupants(core_share),
            jurisdiction=context.jurisdiction,
        )
        return SizedSpace(
            space_type=space_type,
            area_m2=max(schedule.total_area_m2, rule.minimum_m2),
            basis=rule.basis,
            citation=rule.citation,
            evidence_level=rule.evidence_level,
            unresolved_facts=schedule.unresolved_facts,
        )

    if rule.basis == "residual":
        assigned = sum(
            size_space(other, context, rules).area_m2
            for other in rules
            if other != space_type
        )
        residual = context.net_area_m2 - assigned
        if residual < rule.minimum_m2:
            raise ValueError(
                f"plate leaves {residual:.1f} m2 residual for '{space_type}', "
                f"below its {rule.minimum_m2:.1f} m2 minimum"
            )
        return SizedSpace(
            space_type=space_type,
            # Deliberately unrounded: this is what makes the program sum to the
            # plate exactly.  Rounding here leaves a float residue behind.
            area_m2=residual,
            basis=rule.basis,
            citation=rule.citation,
            evidence_level=rule.evidence_level,
        )

    if rule.basis == "ratio":
        area = rule.plate_ratio * context.net_area_m2
        return SizedSpace(
            space_type=space_type,
            area_m2=round(max(area, rule.minimum_m2), 3),
            basis=rule.basis,
            citation=rule.citation,
            evidence_level=rule.evidence_level,
            unresolved_facts=(
                f"{space_type} 면적이 플레이트 비례 자리확보값; 확정 면적 not_checked",
            ),
        )

    occupants = context.occupants if rule.basis == "occupancy" else 0
    area = rule.base_m2 + rule.per_occupant_m2 * occupants
    return SizedSpace(
        space_type=space_type,
        area_m2=round(max(area, rule.minimum_m2), 3),
        basis=rule.basis,
        citation=rule.citation,
        evidence_level=rule.evidence_level,
        unresolved_facts=(
            (f"{space_type} 면적 계수가 {_ASSUMED}; not_checked",)
            if rule.evidence_level == "assumed"
            else ()
        ),
    )
