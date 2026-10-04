"""Local zone-only analysis while provider-dependent branches are migrated."""
import logging
import sqlite3
from time import perf_counter

from backend.app.modules.regulations import calculator, extended, overlays, zoning_limits
from .analysis_request import normalize_program_request
from .analysis_response import build_restrictions, format_regulations

logger = logging.getLogger(__name__)


def analyze_zones(body, repository=None):
    started = perf_counter()
    names = body['zones']
    program = normalize_program_request(body)
    reg = calculator.calculate_all(names, None, use_llm_extraction=False, **program)
    schedule = program['program_uses']
    if schedule is None and program['building_type']:
        schedule = [{'id': 'single_use', 'building_type': program['building_type'],
                     'floor_area_m2': program['floor_area_m2']}]
    reg_ext = extended.calculate_extended(
        names, None, building_type=program['building_type'], program_uses=schedule,
        assessment_date=program['assessment_date'])
    overlay = overlays.resolve_overlays(names)
    zone_info = zoning_limits.resolve_limits(names)
    zone_info['zones'] = [zone['zone_name'] for zone in zone_info['zones']]
    zone_info['bcr_limit'] = reg.get('bcr_pct', zone_info.get('bcr_limit'))
    zone_info['far_limit'] = reg.get('far_pct', zone_info.get('far_limit'))
    result = {
        'pnu': None, 'regulations': format_regulations(reg, reg_ext=reg_ext),
        'zone_info': zone_info, 'land_info': None, 'law_articles': None,
        'restrictions': build_restrictions(reg, names, reg_ext, overlays=overlay,
            overlay_all_matched=overlays.get_all_matched_zones(names)),
        'overlay_regulations': overlay or [], 'setback_lines': None, 'program': program,
        'assessment': {'status': 'needs_evidence', 'permit_compliance_verified': False,
            'scope': 'regulation_lookup_and_partial_calculation',
            'municipal_coverage': reg.get('municipal_coverage'),
            'use_permission': reg_ext.get('building_use_restriction'),
            'missing_evidence': ['complete_design_applicability_and_permit_checks']},
    }
    # Calculation remains useful on storage failure, but never claims durability.
    try:
        if repository is None:
            raise OSError('Analysis storage is not configured')
        analysis_id = repository.save(body, result, (perf_counter() - started) * 1000)
        result['storage'] = {'saved': True, 'analysis_id': analysis_id}
    except (OSError, ValueError, sqlite3.Error) as exc:
        logger.warning('Land analysis not saved (%s)', type(exc).__name__)
        result['storage'] = {'saved': False, 'error': 'Analysis storage unavailable'}
    return result
