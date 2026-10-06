"""Pure parking arithmetic of `calculator._resolve_parking` (split out of calculator.py).

The reference loaders (`_parking_national`, `_accessible_applicability`) and their
caches stay in calculator/__init__.py, where tests monkeypatch them.
"""

import math
from decimal import Decimal, ROUND_HALF_UP

from ..legal_use import classify_building_use


# 별표 1 umbrellas whose statutory carve-out is a structural cross-reference, not a
# declarable use label, so the umbrella itself can never be resolved:
#   제1종 근린생활시설[건축법 시행령 별표1 제3호 바목·사목 … 은 제외한다]
#   방송통신시설 중 방송국 (the row covers one subtype, not the umbrella)
# 의료시설/운동시설/문화 및 집회시설/공장 stay here as a deliberate conservatism:
# their carve-outs are declarable, but nothing in this pipeline needs the umbrella.
_PARKING_AMBIGUOUS_UMBRELLA = {'방송통신시설', '제1종 근린생활시설', '의료시설',
                               '운동시설', '문화 및 집회시설', '공장'}

# Uses named in a 별표 1 parenthetical carve-out. Such a use never inherits its
# category's row; it matches only a row that lists it explicitly.
#   문화 및 집회시설(관람장은 제외한다)
#   의료시설(정신병원·요양병원 및 격리병원은 제외한다)
#   운동시설(골프장·골프연습장 및 옥외수영장은 제외한다)
#   업무시설(외국공관 및 오피스텔은 제외한다)
_PARKING_CARVE_OUT = {'관람장', '정신병원', '요양병원', '격리병원',
                      '골프장', '골프연습장', '옥외수영장', '외국공관', '오피스텔'}


def _parking_row(rows: list[dict], building_type: str) -> tuple[dict | None, str | None]:
    """Resolve a use to its 별표 1 row. Returns (row, precision).

    Exact legal identity wins. A use that is not itself listed may inherit its
    statutory category's row ("category"), because 별표 1 writes those rows at
    umbrella level - but never when the use is a named carve-out of that row.
    Never broadens an excluded subtype and never falls back to 그 밖의 건축물.
    """
    classification = classify_building_use(building_type)
    canonical = classification['canonical_use']
    if canonical is None or canonical in _PARKING_AMBIGUOUS_UMBRELLA:
        return None, None
    if canonical in {'아파트', '연립주택', '다세대주택'}:
        canonical = '공동주택'
    for row in rows:
        if any(canonical == classify_building_use(use)['canonical_use']
               for use in row.get('uses', [])):
            return row, 'exact'
    category = classification['category']
    if (category is None or category == canonical or canonical in _PARKING_CARVE_OUT
            or category in _PARKING_AMBIGUOUS_UMBRELLA):
        return None, None
    for row in rows:
        if any(category == classify_building_use(use)['canonical_use']
               for use in row.get('uses', [])):
            return row, 'category'
    return None, None


def _parking_detached_house(area: float, tier: dict) -> float:
    """별표 1 제4호 단독주택(다가구주택 제외): 50㎡ 초과 first_max 이하 1대, 초과분은
    step㎡당 1대 (시행령 150/100; 의정부 별표 3은 134/85). 50㎡ 이하는 표에 값이 없고
    비고 4 단서가 면적을 100㎡로 나눈 대수로 정한다 (서울 별표 2 비고 4도 100㎡,
    의정부 별표 3 비고 1은 85㎡) - the divisor is read from the ordinance snapshot."""
    first_max = float(tier.get('first_max_m2', 150))
    step = float(tier.get('step_m2', 100))
    if area <= 50:
        return area / float(tier.get('under_50_divisor_m2', 100))
    if area <= first_max:
        return 1.0
    return 1 + (area - first_max) / step


def _parking_first_decimal(cars: float) -> float:
    """별표 1 비고 4's "소수점 이하 첫째자리까지의 주차대수".

    별표 1 states the precision, not how to reach it; neither the 시행령, 서울 별표 2
    비고 4 (same sentence), 의정부 별표 3 비고 1 (restates it with an 85㎡ divisor for
    단독주택 50㎡ 이하) nor 법제처 법령해석 15-0777 says 반올림 or 절사. Round-half-up
    is used, consistent with 비고 6's own treatment of 0.5, and the exact quotient
    is preserved alongside so an ordinance that decides otherwise can override.
    """
    return float(Decimal(repr(cars)).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP))


def _parking_round_note6(subtotal: float) -> int:
    """별표 1 비고 6: 0.5 이상은 1로, 총주차대수 1대 미만은 0대. 반올림이지 올림이 아니다."""
    if subtotal < 1:
        return 0
    whole = math.floor(subtotal)
    return whole + (1 if Decimal(repr(subtotal)) - whole >= Decimal('0.5') else 0)


def _parking_finalize(out: dict, evaluated: list) -> None:
    """별표 1 비고 6 단수처리 -> the binding 부설주차장 주차대수.

    "소수점 이하의 수…가 0.5 이상인 경우에는 이를 1로 본다. 다만, 해당 시설물
    전체에 대하여 설치기준을 적용하여 산정한 총주차대수가 1대 미만인 경우에는
    주차대수를 0으로 본다." 서울 조례 별표 2 비고 6 and 별표 3 비고 7 repeat this
    verbatim; 의정부 별표 3 carries no rounding note of its own, so the 시행령 sentence
    governs there too. An ordinance may tighten the ratio (비고 11) without changing
    this step. 법제처 법령해석 15-0777 (2015-12-31): the 단서's "해당 시설물 전체" is
    the whole mixed-use building, so the 1대 미만 test runs on the summed total.

    The number is emitted only when it binds: an ordinance snapshot is present
    (시행령 별표 1 is the national floor, the ordinance is what binds the parcel),
    every declared use resolved, and no unresolved 주차장설치제한지역 candidate -
    there the 별표 3 cap is lower than the requirement, so an uncapped number
    would overstate parking.
    """
    distinct = {(item.get('classification') or {}).get('canonical_use') for item in evaluated}
    # 별표 1 비고 4 governs "용도가 다른 시설물이 복합된 시설물" only. A single use -
    # or several entries of the same use - is summed at full precision, so a
    # 0.95-car facility stays below 비고 6's 1대 threshold instead of being lifted
    # to 1.0 by a rounding step the statute does not apply to it.
    mixed_use = len(distinct - {None}) > 1
    calculation = {
        'notes_applied': (['별표1 비고4'] if mixed_use else []) + ['별표1 비고6'],
        'mixed_use': mixed_use,
        'rounding_policy': 'first_decimal_round_half_up' if mixed_use else 'exact_quotient',
        'final_rule': '소수점 이하 0.5 이상은 1로 본다; 총주차대수 1대 미만은 0대',
        'basis': out.get('parking_basis'),
        'subtotal_first_decimal': None,
        'uses': [{k: item.get(k) for k in
                  ('id', 'building_type', 'ratio_m2_per_car', 'rule', 'use_precision',
                   'calculated_intermediate', 'cars_first_decimal', 'status')}
                 for item in evaluated],
        # 비고 1 lists uses that need no 부설주차장 (변전소·수도원·동물 및 식물 관련
        # 시설·송수신 중계시설·도시철도 역사·전통한옥 등). None of them is a
        # declarable label in legal_use, so no exemption is evaluated here.
        'note1_exemptions_evaluated': False,
    }
    out['parking_calculation'] = calculation
    if not evaluated or any(item['cars_first_decimal'] is None for item in evaluated):
        for item in evaluated:
            for reason in item.get('missing_evidence', []):
                if reason not in out['parking_missing_evidence']:
                    out['parking_missing_evidence'].append(reason)
        return
    key = 'cars_first_decimal' if mixed_use else 'calculated_intermediate'
    subtotal = float(sum(Decimal(repr(item[key])) for item in evaluated))
    calculation['subtotal'] = subtotal
    calculation['subtotal_first_decimal'] = subtotal if mixed_use else None
    if out['parking_basis'] != 'municipal_snapshot':
        # The national table is a floor; the ordinance is the binding number.
        calculation['national_floor_cars'] = _parking_round_note6(subtotal)
        return
    if out['parking_restricted_candidate']:
        return
    out['parking_required'] = _parking_round_note6(subtotal)
    out['parking_status'] = 'calculated'


def _accessible_row(rows: list[dict], classification: dict) -> dict | None:
    canonical = classification.get('canonical_use')
    if canonical is None:
        return None
    for row in rows:
        if canonical in row.get('uses', []):
            return row
    category = classification.get('category')
    for row in rows:
        if category in row.get('uses', []):
            return row
    return None


def _accessible_use_status(row: dict | None, area) -> tuple[str, str]:
    """One use against 별표 1: applies / not_applicable / needs_evidence, with its clause."""
    if row is None:
        return 'needs_evidence', 'accessibility_act_applicability_unknown_use'
    if row.get('status'):
        return row['status'], row.get('reason') or row.get('clause', '')
    condition = row.get('applies_when') or {}
    if condition.get('always'):
        return 'applies', row.get('clause', '')
    minimum = condition.get('min_floor_area_m2')
    if minimum is not None:
        if not (isinstance(area, (int, float)) and not isinstance(area, bool) and math.isfinite(area)):
            return 'needs_evidence', 'floor_area_for_accessibility_threshold'
        if area >= minimum:
            return 'applies', row.get('clause', '')
        return row.get('below', 'needs_evidence'), f"{row.get('clause', '')} 문턱 {minimum}㎡ 미달"
    return 'needs_evidence', row.get('clause', '')
