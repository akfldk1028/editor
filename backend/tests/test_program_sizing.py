import pytest

from backend.app.modules.program_prior.sizing import (
    OFFICE_SIZING,
    SizingContext,
    occupant_load,
    restroom_schedule,
    size_space,
)


def test_occupant_load_uses_domestic_workplace_standard():
    # 「업무시설 적정 공간면적 설계기준 개발 연구」 8.5 m2/person
    assert occupant_load(850.0) == 100


def test_occupant_load_rounds_up_partial_occupants():
    assert occupant_load(851.0) == 101
    assert occupant_load(0.0) == 0


def test_restroom_schedule_applies_ibc_business_water_closet_table():
    # 100 occupants, 50/50 split: male 50 -> 2 (1 per 25 for the first 50),
    # female 50 -> 2 (1 per 25).
    schedule = restroom_schedule(occupants=100)

    assert schedule.male_water_closets == 2
    assert schedule.female_water_closets == 2
    assert schedule.lavatories == schedule.male_water_closets + schedule.female_water_closets


def test_restroom_schedule_switches_to_one_per_fifty_above_fifty_occupants():
    # male 100 -> 2 for the first 50, then 1 per 50 for the remaining 50 -> 3
    schedule = restroom_schedule(occupants=200)

    assert schedule.male_water_closets == 3
    assert schedule.female_water_closets == 3


def test_restroom_schedule_reserves_one_accessible_stall_per_gender():
    schedule = restroom_schedule(occupants=100)

    assert schedule.accessible_stalls == 2


def test_restroom_schedule_area_is_dominated_by_fixture_geometry_not_floor_ratio():
    small = restroom_schedule(occupants=60)
    large = restroom_schedule(occupants=120)

    # Doubling occupancy must not double area the way a floor-area ratio would;
    # the accessible stalls are a fixed floor.
    assert large.total_area_m2 > small.total_area_m2
    assert large.total_area_m2 < small.total_area_m2 * 2


def test_restroom_schedule_honours_korean_female_stall_ratio_rule():
    # 공중화장실법 시행령 별표: female WC >= (male WC + urinals) * 1.5
    schedule = restroom_schedule(occupants=200, jurisdiction="KR")
    male_side = schedule.male_water_closets + schedule.urinals

    assert schedule.female_water_closets >= male_side * 1.5


def test_restroom_schedule_reports_assumed_facts_as_unresolved():
    schedule = restroom_schedule(occupants=100)

    assert any("gender" in fact for fact in schedule.unresolved_facts)


def test_restroom_schedule_rejects_negative_occupants():
    with pytest.raises(ValueError):
        restroom_schedule(occupants=-1)


def test_office_restroom_area_is_stable_across_plate_sizes():
    """The bug this module exists to fix.

    alt-01 (707 m2 plate) produced 24.9 m2 of restroom while alt-02
    (763 m2 plate) produced 70.4 m2 for the same program.  Occupancy on
    those two plates differs by under 10%, so the restroom must too.
    """
    small = size_space("restroom", SizingContext(net_area_m2=707.0), OFFICE_SIZING)
    large = size_space("restroom", SizingContext(net_area_m2=763.0), OFFICE_SIZING)

    assert large.area_m2 / small.area_m2 < 1.25


def test_open_work_absorbs_the_residual_area():
    context = SizingContext(net_area_m2=700.0)
    sized = {
        space_type: size_space(space_type, context, OFFICE_SIZING)
        for space_type in OFFICE_SIZING
    }

    assert sum(item.area_m2 for item in sized.values()) == pytest.approx(700.0)
    assert sized["open_work"].basis == "residual"


def test_size_space_carries_provenance_for_every_space_type():
    context = SizingContext(net_area_m2=700.0)

    for space_type in OFFICE_SIZING:
        sized = size_space(space_type, context, OFFICE_SIZING)
        assert sized.citation, f"{space_type} has no citation"
        assert sized.evidence_level in {"statutory", "practice", "assumed"}


def test_size_space_rejects_a_plate_too_small_for_the_normative_program():
    with pytest.raises(ValueError, match="residual"):
        size_space("open_work", SizingContext(net_area_m2=40.0), OFFICE_SIZING)
