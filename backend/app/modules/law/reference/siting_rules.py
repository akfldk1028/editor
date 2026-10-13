"""Source-versioned siting criteria; parcel evidence is a separate verdict."""
from copy import deepcopy
from datetime import date
import json
import math
from pathlib import Path

from backend.app.modules.regulations.legal_use import classify_building_use


def catalog():
    from backend.app.modules.design.generation.maas.parking import layout as parking
    data = json.loads((Path(__file__).parent / 'data/structured/siting_design_rules.json').read_text(encoding='utf-8'))
    small = data['small_attached_parking']
    # Existing parking numeric ownership is retained; the source catalog adds
    # applicability/evidence, rather than creating another copy of the values.
    small['max_total_spaces'] = parking.SMALL_ATTACHED_PARKING_MAX_SPACES
    small['entrance_min_width_m'] = parking.ATTACHED_PARKING_ENTRANCE_WIDTH_M
    small['entrance_exception']['min_width_m'] = parking.ATTACHED_PARKING_DEAD_END_APPROVAL_ENTRANCE_WIDTH_M
    small['adjacent_aisle_widths_m'].update(perpendicular=parking.DEFAULT_AISLE_WIDTH_M,
                                         parallel=parking.DEFAULT_PARALLEL_AISLE_WIDTH_M)
    small['road_aisle'].update(unseparated_road_width_lt_m=parking.ROAD_AS_AISLE_UNDIVIDED_MAX_ROAD_WIDTH_M,
        perpendicular_combined_width_m=parking.ROAD_AS_AISLE_PERPENDICULAR_REQUIRED_WIDTH_M,
        parallel_combined_width_m=parking.ROAD_AS_AISLE_PARALLEL_REQUIRED_WIDTH_M)
    small['wide_road_aisle'].update(separated_road_width_at_least_m=parking.ROAD_AS_AISLE_UNDIVIDED_MAX_ROAD_WIDTH_M,
                                 max_total_spaces=parking.TANDEM_ALLOWED_MAX_SPACES)
    small['tandem']['max_total_spaces'] = parking.TANDEM_ALLOWED_MAX_SPACES
    return data


def siting_requirements(pnu, building_type, total_floor_area_m2, assessment_date=None):
    data = catalog()
    rule = data['road_frontage']
    asof = date.fromisoformat(assessment_date) if assessment_date else date.today()
    if not isinstance(pnu, str) or len(pnu) != 19 or not pnu.isascii() or not pnu.isdecimal():
        raise ValueError('pnu must be 19 ASCII digits')
    known_area = (not isinstance(total_floor_area_m2, bool) and isinstance(total_floor_area_m2, (int, float))
                  and math.isfinite(total_floor_area_m2) and total_floor_area_m2 > 0)
    use = classify_building_use(building_type)
    missing = []
    if not known_area:
        missing.append('total_floor_area_m2')
    if use['status'] != 'classified':
        missing.append('legal_building_use')
    if not date.fromisoformat(rule['effective_from']) <= asof <= date.fromisoformat(data['verified_on']):
        missing.append('applicable_legal_edition')
    criteria = None
    if not missing:
        large = rule['large']
        threshold = large['factory_total_floor_area_at_least_m2'] if use['category'] == '공장' else large['total_floor_area_at_least_m2']
        selected = large if total_floor_area_m2 >= threshold else rule['ordinary']
        criteria = {k: v for k, v in selected.items() if k.startswith('min_')}
    return {'schema_version': 'law.siting_requirements.v1', 'pnu': pnu,
            'requested': {'building_type': building_type, 'total_floor_area_m2': total_floor_area_m2},
            'status': 'needs_evidence' if missing else 'criteria_available',
            'criteria': criteria, 'source': deepcopy(rule), 'verified_on': data['verified_on'],
            'assessment_date': asof.isoformat(), 'missing_evidence': missing + rule['requires'],
            'exceptions_applied': False, 'permit_compliance_verified': False}
