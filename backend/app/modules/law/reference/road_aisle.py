"""Evidence-bound preliminary applicability for parking with a road aisle."""
from copy import deepcopy
from datetime import date
import hashlib
import json
import math

from . import siting_rules


def evaluate(pnu, total_spaces, structure, parking_angle, facts, assessment_date=None):
    if not isinstance(pnu, str) or len(pnu) != 19 or not pnu.isascii() or not pnu.isdecimal():
        raise ValueError('pnu must be 19 ASCII digits')
    asof = date.fromisoformat(assessment_date) if assessment_date else date.today()
    identity = deepcopy(dict(pnu=pnu, total_spaces=total_spaces, structure=structure,
                             parking_angle=parking_angle, facts=facts,
                             assessment_date=asof.isoformat()))
    data = siting_rules.catalog()
    small = data['small_attached_parking']
    narrow, wide = small['road_aisle'], small['wide_road_aisle']
    missing, denied = [], []
    evidence = facts if isinstance(facts, dict) else {}

    def fact(name, numeric=False):
        item = evidence.get(name)
        refs = item.get('source_refs') if isinstance(item, dict) else None
        value = item.get('value') if isinstance(item, dict) else None
        sourced = isinstance(refs, list) and bool(refs) and all(isinstance(ref, str) and ref.strip() for ref in refs)
        valid = (not isinstance(value, bool) and isinstance(value, (int, float))
                 and math.isfinite(value) and value > 0) if numeric else isinstance(value, bool)
        if not sourced or not valid:
            missing.append(name)
            return None
        return value

    width = fact('road_width_m', numeric=True)
    separated = fact('has_sidewalk_separation')
    centreline = fact('centreline_presence')
    connection = fact('unobstructed_connection')
    frontage = fact('legal_road_frontage')
    if connection is False:
        denied.append('obstructed_connection')
    if frontage is False:
        denied.append('no_legal_road_frontage')
    count_known = type(total_spaces) is int and total_spaces > 0
    if not count_known:
        missing.append('total_installed_spaces')
    elif total_spaces > small['max_total_spaces']:
        denied.append('exceeds_small_attached_total_spaces')
    if structure is None or structure == '':
        missing.append('structure')
    elif structure != 'surface':
        denied.append('structure_outside_surface_scope')
    if parking_angle is None or parking_angle == '':
        missing.append('parking_angle')
    elif parking_angle not in ('perpendicular', 'parallel'):
        denied.append('unsupported_parking_angle')
    if asof < date.fromisoformat(small['effective_from']):
        missing.append('applicable_legal_edition')
    # The reference was last checked against law.go.kr on verified_on. An assessment after that
    # date is not missing evidence (the edition is in force); it is a re-verification to schedule.
    verification_stale = asof > date.fromisoformat(data['verified_on'])

    policy, combined, extent = None, None, None
    maximum = small['max_total_spaces']
    if width is not None and separated is not None:
        if width < narrow['unseparated_road_width_lt_m'] and not separated:
            policy = 'small_attached_road_aisle'
            if parking_angle in ('perpendicular', 'parallel'):
                combined = narrow[f'{parking_angle}_combined_width_m']
            extent = 'centreline' if centreline else 'opposite_edge'
        elif width >= wide['separated_road_width_at_least_m'] and separated:
            policy = 'small_attached_wide_road_aisle'
            maximum = wide['max_total_spaces']
            combined = small['adjacent_aisle_widths_m'][wide['parking_angle']]
            extent = 'source_road_polygon'
            if count_known and total_spaces > maximum:
                denied.append('exceeds_wide_road_total_spaces')
            if parking_angle not in (None, '', wide['parking_angle']):
                denied.append('wide_road_requires_perpendicular')
            if fact('no_obstruction_to_parking_use') is False:
                denied.append('obstruction_to_parking_use')
        else:
            denied.append('road_width_and_separation_outside_catalog_scope')

    status = 'denied' if denied else 'needs_evidence' if missing else 'applicable_for_preliminary_design'
    return dict(schema_version='law.road_aisle_conditions.v1', pnu=pnu,
                status=status, policy_id=policy, max_total_spaces=maximum,
                required_combined_aisle_width_m=combined,
                allowed_extent=extent if status == 'applicable_for_preliminary_design' else None,
                missing_evidence=missing, denial_reasons=denied,
                input_identity=identity,
                input_hash=hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
                source_snapshot_hash=hashlib.sha256(json.dumps(
                    {'small_attached_parking': small, 'verified_on': data['verified_on']},
                    sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()).hexdigest(),
                source=deepcopy(small), verified_on=data['verified_on'], verification_stale=verification_stale,
                geometry_requirements=['actual_sourced_road_polygon', 'contiguous_frontage', 'allowed_extent_geometry', 'combined_aisle_width_measurement'],
                permit_compliance_verified=False)
