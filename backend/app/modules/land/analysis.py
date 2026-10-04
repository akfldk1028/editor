"""Land analysis composed from local rules and explicit external providers."""
import logging
import sqlite3
from time import perf_counter
from starlette.concurrency import run_in_threadpool

from backend.app.modules.regulations import calculator, extended, overlays, zoning_limits
from .analysis_request import normalize_program_request
from .analysis_response import build_restrictions, format_regulations
from .pnu import parse_pnu
from .evidence import collect_evidence

logger = logging.getLogger(__name__)


def analyze_zones(body, repository=None):
    started = perf_counter()
    result, _ = calculate(body, body['zones'])
    return save_result(body, result, started, repository)


def calculate(body, names, pnu_info=None, land_info=None, zone_areas=None, proposals=None):
    program = normalize_program_request(body)
    jurisdiction = pnu_info['sido'] + pnu_info['sigungu'] if pnu_info else ''
    extractor = (lambda zones, kind: proposals.get(kind)) if proposals else None
    reg = calculator.calculate_all(names, land_info, sigungu_code=jurisdiction,
        zone_areas=zone_areas, use_llm_extraction=bool(extractor), extractor=extractor, **program)
    schedule = program['program_uses']
    if schedule is None and program['building_type']:
        schedule = [{'id': 'single_use', 'building_type': program['building_type'],
                     'floor_area_m2': program['floor_area_m2']}]
    reg_ext = extended.calculate_extended(
        names, land_info, building_type=program['building_type'], program_uses=schedule,
        assessment_date=program['assessment_date'])
    overlay = overlays.resolve_overlays(names)
    zone_info = zoning_limits.resolve_limits(names, zone_areas)
    zone_info['zones'] = [zone['zone_name'] for zone in zone_info['zones']]
    zone_info['bcr_limit'] = reg.get('bcr_pct', zone_info.get('bcr_limit'))
    zone_info['far_limit'] = reg.get('far_pct', zone_info.get('far_limit'))
    if zone_areas:
        zone_info['zone_areas_m2'] = {key: round(float(value), 2) for key, value in zone_areas.items()}
    result = {
        'pnu': pnu_info, 'regulations': format_regulations(reg, reg_ext=reg_ext),
        'zone_info': zone_info, 'land_info': land_info, 'law_articles': None,
        'restrictions': build_restrictions(reg, names, reg_ext, overlays=overlay,
            overlay_all_matched=overlays.get_all_matched_zones(names)),
        'overlay_regulations': overlay or [], 'setback_lines': None, 'program': program,
        'assessment': {'status': 'needs_evidence', 'permit_compliance_verified': False,
            'scope': 'regulation_lookup_and_partial_calculation',
            'municipal_coverage': reg.get('municipal_coverage'),
            'use_permission': reg_ext.get('building_use_restriction'),
            'missing_evidence': ['complete_design_applicability_and_permit_checks']},
    }
    return result, reg


def save_result(body, result, started, repository):
    # Calculation remains useful on storage failure, but never claims durability.
    try:
        if repository is None:
            raise OSError('Analysis storage is not configured')
        analysis_id = repository.save(body, result, (perf_counter() - started) * 1000,
            error='; '.join(result.get('errors', [])) or result.get('warning', ''))
        result['storage'] = {'saved': True, 'analysis_id': analysis_id}
    except (OSError, ValueError, sqlite3.Error) as exc:
        logger.warning('Land analysis not saved (%s)', type(exc).__name__)
        result['storage'] = {'saved': False, 'error': 'Analysis storage unavailable'}
    return result


async def analyze_land(body, addresses, attributes, geometry_provider, repository=None,
                       *, law_client=None, extraction_client=None):
    from backend.app.modules.regulations.setbacks import compute_setback_lines
    from .geometry_queries import GeometryQueries
    started = perf_counter()
    names = list(body['zones'])
    pnu_info = land_info = None
    geometry = body.get('geometry')
    errors = []
    if body['input_type'] == 'pnu':
        pnu_info = parse_pnu(body['input'])
    elif body['input_type'] == 'address':
        resolved = await addresses.resolve_address(body['input'])
        if resolved['success'] and resolved.get('pnu'):
            pnu_info = parse_pnu(resolved['pnu'])
        else:
            errors.append(resolved.get('error') or 'Address resolved without parcel identity')
    if pnu_info:
        land_info = await attributes.get(pnu_info['pnu'])
        errors.extend(land_info.get('errors', []))
        if land_info['success'] and not names:
            names = land_info['zones']
        if not geometry:
            boundary = await addresses.fetch_parcel_geometry(pnu_info['pnu'])
            geometry = boundary.get('geometry') if boundary.get('success') else None
            if not geometry:
                errors.append(boundary.get('error') or 'Parcel boundary unavailable')
    if not names:
        result = {'pnu': pnu_info, 'regulations': None, 'zone_info': None,
            'land_info': land_info, 'law_articles': None, 'restrictions': [],
            'warning': 'No zoning zones provided or resolved'}
    else:
        queries = GeometryQueries(geometry_provider, repository)
        zone_areas = None
        if geometry and sum(zoning_limits.lookup(name) is not None for name in names) > 1:
            zone_areas, split_errors = await queries.split(geometry)
            errors.extend(split_errors)
        law, advisory = await collect_evidence(names, include_law=body.get('include_law', True),
            law_client=law_client, extraction_client=extraction_client)
        result, reg = await run_in_threadpool(calculate, body, names, pnu_info, land_info, zone_areas,
            advisory['proposals'] if advisory else None)
        result['law_articles'] = law
        if law:
            errors.extend(law['errors'])
        if advisory is not None:
            result['advisory'] = advisory
        if geometry:
            roads, neighbors, frontage_errors = await queries.frontages(geometry)
            errors.extend(frontage_errors)
            result['setback_lines'] = await run_in_threadpool(compute_setback_lines, geometry, reg,
                compute_datum=False, road_frontages=roads or None, neighbor_parcels=neighbors or None)
    if errors:
        result['errors'] = list(dict.fromkeys(errors))
    return await run_in_threadpool(save_result, body, result, started, repository)
