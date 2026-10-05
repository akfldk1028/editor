"""Evidence-backed parcel overrides and one conservative storey gate.

Storey limits never become statutory metre limits. Without an actual floor
schedule, height/storey is a conservative concept proxy, not certified floors.
"""
from copy import deepcopy
from functools import lru_cache
from math import ceil, isfinite


_POLICIES = {'4115011300106840001': {'policy_id': 'gosan-public1-molit-2026-334',
                         'parcel_label': '경기도 의정부시 산곡동 684-1 / 공공1',
                         'max_storeys': 5,
                         'max_bcr_pct': 60.0,
                         'max_far_pct': 250.0,
                         'statutory_max_height_m': None,
                         'default_building_type': '업무시설',
                         'building_subtype': '공공업무시설',
                         'sources': [{'title': '의정부고산 토지이용계획도 등 관련도면: 가구 및 획지, 건축물 등에 관한 결정도',
                                      'date': '2026-06-29',
                                      'download_url': 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=67554543',
                                      'listing_url': 'https://apply.lh.or.kr/lhapply/apply/wt/wrtanc/selectWrtancInfo.do?aisTpCd=01&ccrCnntSysDsCd=01&panId=BN-0007713&uppAisTpCd=01',
                                      'relevant_pdf_pages_1_based': [6],
                                      'sha256': '0225c991a7c2c8ca7dc497c8576eaa1d29668f57b5d78ebd43727e22349bb3cd',
                                      'bytes': 16093893,
                                      'pdf_page_count': 6,
                                      'retrieved_on': '2026-09-06',
                                      'local_evidence': 'agents/MassAgent/docs/reports/legal-sources/gosan-15-drawings.pdf'},
                                     {'title': '국토교통부고시 제2022-374호 지구계획 변경(9차)',
                                      'date': '2022-06-29',
                                      'download_url': 'https://www.ui4u.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000174255&fileSn=0',
                                      'listing_url': 'https://www.ui4u.go.kr/portal/bbs/view.do?bIdx=251846&mId=0114050000&ptIdx=27',
                                      'relevant_pdf_pages_1_based': [13, 22],
                                      'sha256': '7b60ffbf4ad20fca7d0b48fe37488c2ec913faf714dd4b7314f29ef2bbb584ca',
                                      'bytes': 446211,
                                      'pdf_page_count': 32,
                                      'retrieved_on': '2026-09-06',
                                      'local_evidence': 'agents/MassAgent/docs/reports/legal-sources/gosan-9-notice.pdf'},
                                     {'title': '의정부고산 9차 지구단위계획 시행지침',
                                      'date': '2022-06-29',
                                      'download_url': 'https://www.ui4u.go.kr/cmm/fms/FileDown.do?atchFileId=FILE_000000000174255&fileSn=3',
                                      'listing_url': 'https://www.ui4u.go.kr/portal/bbs/view.do?bIdx=251846&mId=0114050000&ptIdx=27',
                                      'relevant_pdf_pages_1_based': [47, 48, 49, 50, 56],
                                      'sha256': '5708c6bc0854cdba547e0664b05999f23553bf123bee0cb8e392ba356dc1e78e',
                                      'bytes': 5813648,
                                      'pdf_page_count': 79,
                                      'retrieved_on': '2026-09-06',
                                      'local_evidence': 'agents/MassAgent/docs/reports/legal-sources/gosan-9-guidelines-full.pdf'},
                                     {'title': '건축법 시행령 별표1, 현행 법령 페이지 시행일2026-07-28',
                                      'date': '2026-07-28',
                                      'download_url': 'https://www.law.go.kr/LSW/flDownload.do?gubun=&flSeq=168351463&bylClsCd=110201',
                                      'listing_url': 'https://www.law.go.kr/LSW/lsInfoP.do?ancYnChk=0&chrClsCd=010202&efYd=20260728&lsiSeq=288339&urlMode=lsInfoP',
                                      'relevant_pdf_pages_1_based': [3, 7],
                                      'sha256': '150e9bafcf6544fdcbd43ab5d3d67691ab56b03193260a24c8ace25882e560fc',
                                      'bytes': 137824,
                                      'pdf_page_count': 12,
                                      'retrieved_on': '2026-09-06',
                                      'local_evidence': 'agents/MassAgent/docs/reports/legal-sources/building-decree-annex1-20260728.pdf'}],
                         'unverified': ['measured_terrain_datum',
                                        'exact_building_line_geometry',
                                        'detailed_floor_schedule',
                                        'access_and_egress'],
                         'numeric_status': 'direct_revision15_drawing_confirmed; '
                                           'latest_official_revision_obtained',
                         'allowed_use_status': 'historical_revision9_text_confirmed; '
                                               'current_detailed_change_chain_incomplete',
                         'use_classification_status': 'current_national_rule_confirmed; '
                                                      'actual_program_schedule_unverified',
                         'building_line_status': '2m_line_graphically_observed_on_specific_frontages; '
                                                 'local_geometry_unregistered',
                         'vehicle_access_status': 'prohibited_intervals_graphically_observed; '
                                                  'local_geometry_unregistered',
                         'datum_measured': False}}


# Source-native registration is owned here; reports are evidence, not runtime
# configuration. Metre rules use the written dimension, not PDF ink thickness.
_POLICIES['4115011300106840001']['frontage_registration'] = {
    'registration_id': 'gosan-public1-decision15-frontages-20260906',
    'evidence_grade': 'official_plan_registered',
    'survey_verified': False,
    'permit_compliance_verified': False,
    'source_pdf_sha256': '0225c991a7c2c8ca7dc497c8576eaa1d29668f57b5d78ebd43727e22349bb3cd',
    'source_pdf_page_1_based': 6,
    'source_pdf_url': 'https://apply.lh.or.kr/lhapply/lhFile.do?fileid=67554543',
    'diagnostic_file': 'agents/MassAgent/docs/reports/public1-coordinate-registration.json',
    'diagnostic_sha256': 'f38717b39191f42601bf0db6b14236763dc1e4f8fa6261e5382eec3b1e08039e',
    'coordinate_frame': 'parcel UTM translated by its minimum x,y; metres',
    'reference_parcel_ring_local_m': [
        [0.0, 32.85654268087819], [11.59371943201404, 39.50109809124842],
        [29.64010443945881, 50.43758501717821], [46.434598230640404, 61.34179168846458],
        [76.16706880752463, 44.32430054806173], [78.23247281974182, 36.59896623622626],
        [57.298764832085, 0.0], [33.13071452913573, 13.857184919528663]],
    'native_boundary_path_indices': [169709, 169802, 169859, 169736],
    'similarity_rmse_m': 0.0422624523558319,
    'similarity_max_residual_m': 0.06730724482142661,
    'pdf_to_local_matrix': [[1.7632335297180013, -0.03870232491089445],
                            [-0.03870232491089446, -1.7632335297180015]],
    'pdf_to_local_translation': [-1128.226518104534, 2717.6559174955923],
    'building_limit': {
        'edge_indices_0_based': [3, 4, 5], 'setback_m': 2.0,
        'basis': 'written 2m dimension on registered connected frontages; no blanket parcel buffer',
        'native_line_path_indices': list(range(153873, 153898)),
        'native_dimension_path_indices': [153087, 153088, 153089, 153090],
        'observed_centerline_local_m': [[44.56676010658284, 60.12905534841926],
            [74.48117894171324, 42.985759756271534], [76.07149158052712, 36.87602862980489],
            [55.52816026433155, 1.0152078718458881]]},
    'road_frontage': {
        # An explicit observation of this parcel's official drawing. Reuse
        # the already registered edge geometry; a setback is not generally
        # evidence of a road, and other policies do not inherit this meaning.
        'registered_edge_group': 'building_limit',
        'basis': 'decision15 page6: roads adjoin these registered NE, corner and SE edges',
        'purpose': 'pedestrian_address_orientation; vehicle_prohibition_is_separate'},
    'vehicle_access_prohibited': {
        'full_edge_indices_0_based': [3, 4], 'partial_edge_index_0_based': 5,
        'partial_edge_end_chainage_m': 9.272546192997954,
        'end_local_m': [73.62868408060275, 28.550038223959213],
        'native_path_indices': [152682, 152776, 152778],
        'native_end_tick_midpoint': [714.7499694824219, 1509.4100341796875],
        'endpoint_reading_spread_m': 0.04481685651251688,
        'basis': 'registered red symbol endpoints; cartographic estimate, not survey tolerance'},
}
_POLICIES['4115011300106840001'].update({
    'building_line_status': 'official_plan_registered; survey_geometry_unverified',
    'vehicle_access_status': 'official_plan_prohibited_intervals_registered; actual_access_design_unverified',
})

# Floating-point geometry equality only. This is not a map/survey allowance.
_COORDINATE_EPSILON_M = 1e-6
_AREA_EPSILON_M2 = 1e-6


def policy_for(pnu):
    return deepcopy(_POLICIES.get(str(pnu)))


def default_building_type(pnu, requested=None):
    if requested:
        return str(requested)
    return (_POLICIES.get(str(pnu)) or {}).get('default_building_type', '제1종근린생활시설')


@lru_cache(maxsize=16)
def _frontage_shapes(pnu):
    reg = (_POLICIES.get(str(pnu)) or {}).get('frontage_registration')
    return frontage_shapes_from_registration(reg) if reg is not None else None


def frontage_shapes_from_registration(reg):
    """Pure owner interpretation of a supplied official-plan registration.

    A2A consumers can use the exact received snapshot rather than re-querying
    a process-local policy. Parcel identity/frame binding remains the caller's.
    """
    from shapely.geometry import LineString, Polygon
    from shapely.ops import unary_union
    ring = reg['reference_parcel_ring_local_m']
    reference = Polygon(ring)
    allowed = reference
    reach = reference.length * 2
    for index in reg['building_limit']['edge_indices_0_based']:
        a, b = ring[index], ring[(index+1) % len(ring)]
        dx, dy = b[0]-a[0], b[1]-a[1]
        length = (dx*dx+dy*dy)**.5
        tx, ty = dx/length, dy/length
        nx, ny = (ty, -tx) if not reference.exterior.is_ccw else (-ty, tx)
        offset = reg['building_limit']['setback_m']
        x, y = a[0]+nx*offset, a[1]+ny*offset
        halfplane = Polygon([(x-tx*reach,y-ty*reach), (x+tx*reach,y+ty*reach),
                             (x+tx*reach+nx*reach,y+ty*reach+ny*reach),
                             (x-tx*reach+nx*reach,y-ty*reach+ny*reach)])
        allowed = allowed.intersection(halfplane)
    access = reg['vehicle_access_prohibited']
    lines = [LineString([ring[i],ring[(i+1) % len(ring)]])
             for i in access['full_edge_indices_0_based']]
    lines.append(LineString([ring[access['partial_edge_index_0_based']],access['end_local_m']]))
    return reference, allowed, unary_union(lines)


def _registered_frontage(site):
    pnu = str(getattr(site, 'pnu', None))
    shapes = _frontage_shapes(pnu)
    if shapes is None:
        return None
    parcel = getattr(site, 'site_local_utm', None)
    reference = shapes[0]
    if (parcel is None or parcel.is_empty or not parcel.is_valid
            or parcel.hausdorff_distance(reference) > _COORDINATE_EPSILON_M
            or parcel.symmetric_difference(reference).area > _AREA_EPSILON_M2):
        raise ValueError('parcel registration coordinate frame mismatch; re-register official plan')
    return _POLICIES[pnu]['frontage_registration'], shapes


def registered_buildable(site):
    """Written setback on registered frontages; unrelated parcels are unchanged."""
    registration = _registered_frontage(site)
    return registration[1][1] if registration else None


def registered_road_frontage_evidence(site):
    """Explicitly documented road edges in the verified parcel-local frame."""
    registration = _registered_frontage(site)
    if registration is None:
        return None
    reg, shapes = registration
    road = reg.get('road_frontage')
    if road is None:
        return None
    indices = reg[road['registered_edge_group']]['edge_indices_0_based']
    ring = reg['reference_parcel_ring_local_m']
    return {
        'registration_id': reg['registration_id'],
        'basis': road['basis'], 'purpose': road['purpose'],
        'coordinate_frame': reg['coordinate_frame'],
        'edge_indices_0_based': list(indices),
        'segments_local_m': [[list(ring[i]), list(ring[(i + 1) % len(ring)])]
                             for i in indices],
        'reference_ring_is_ccw': shapes[0].exterior.is_ccw,
        'source_pdf_sha256': reg['source_pdf_sha256'],
        'source_pdf_page_1_based': reg['source_pdf_page_1_based'],
        'source_pdf_url': reg['source_pdf_url'],
        'evidence_grade': reg['evidence_grade'],
        'survey_verified': False, 'vehicle_access_permission': None,
        'vehicle_access_status': 'not_assessed_by_pedestrian_orientation',
    }


def frontage_evidence(site):
    registration = _registered_frontage(site)
    if registration is None:
        return None
    reg, shapes = registration
    return {**deepcopy(reg), 'coordinate_frame_matches': True,
            'building_line_geometry_registered': True,
            'registered_buildable_area_m2': float(shapes[1].area),
            'vehicle_access_design': vehicle_access_evidence(site)}


def registered_vehicle_approach(site):
    """Registered road frontage minus prohibited intervals; no entrance approval."""
    from shapely.geometry import LineString, mapping
    from shapely.ops import unary_union
    road = registered_road_frontage_evidence(site)
    registration = _registered_frontage(site)
    if road is None or registration is None:
        return {'status': 'unregistered', 'geometry': mapping(LineString()),
                'prohibited_geometry': mapping(LineString()), 'vehicle_access_verified': False}
    prohibited = registration[1][2]
    frontage = unary_union([LineString(points) for points in road['segments_local_m']])
    return {**road, 'status': 'registered_road_minus_vehicle_prohibition',
            'geometry': mapping(frontage.difference(prohibited)),
            'prohibited_geometry': mapping(prohibited), 'vehicle_access_verified': False}


def source_plan_projection(source):
    """Public access to the same full-source projection used by parcel gates."""
    return _projection_for_gate(source)


def vehicle_access_evidence(site, *, boundary_crossings=None):
    """Check supplied boundary crossing points/segments against prohibition only.

    Missing entrance geometry stays unverified. A nonprohibited frontage is not
    evidence of an available road, parking, fire access, or an approved entrance.
    """
    registration = _registered_frontage(site)
    result = {'scope': 'registered_vehicle_prohibition_only', 'satisfied': None,
              'access_and_egress_verified': False, 'reasons': []}
    if registration is None:
        return {**result, 'status': 'no_registered_vehicle_prohibition'}
    reg, (parcel, _allowed, prohibited) = registration
    result.update(evidence_grade=reg['evidence_grade'], survey_verified=False,
                  prohibited_intervals=deepcopy(reg['vehicle_access_prohibited']))
    if not boundary_crossings:
        return {**result, 'status': 'actual_access_design_unverified'}
    for crossing in boundary_crossings:
        if (crossing is None or crossing.is_empty
                or not parcel.boundary.buffer(_COORDINATE_EPSILON_M).covers(crossing)):
            result['reasons'].append('vehicle_access_not_on_parcel_boundary')
        elif prohibited.distance(crossing) <= _COORDINATE_EPSILON_M:
            result['reasons'].append('vehicle_access_crosses_prohibited_interval')
    return {**result, 'status': 'prohibition_checked', 'satisfied': not result['reasons']}


def _projection_for_gate(source):
    """Use the complete BOOK export mesh; ordinary IR uses its plan volumes.

    BOOK bridge vertices are centroid-relative XY metres, normalized Z. The
    bridge marker owns that frame. Other surface types cannot be translated
    under this assumption. Never repair a missing BOOK mesh with slice proxies.
    """
    from shapely.geometry import Polygon
    from shapely.ops import unary_union
    metadata = getattr(source, 'metadata', None) or {}
    bridge = metadata.get('geometry_program_bridge_evidence') or {}
    if bridge.get('surface_coordinate_frame') == 'source_footprint_centroid_local':
        from backend.app.modules.design.generation.maas.massv2.render_mesh import physical_triangles
        triangles = []
        for points in physical_triangles(source):
            triangle = Polygon([(x, y) for x, y, _z in points])
            if triangle.area > 0:
                triangles.append(triangle)
        projection = unary_union(triangles)
        if projection.is_empty:
            raise ValueError('BOOK export has no horizontal projection')
        return projection, 'complete_export_surface_xy_projection'
    if metadata.get('book_height_certificate'):
        raise ValueError('BOOK export surface coordinate frame required')
    return unary_union([v.footprint for v in source.volumes]), 'source_volume_plan_projection'


def _building_line_evidence(projection, site):
    try:
        allowed = registered_buildable(site)
    except ValueError as error:
        return {'satisfied': False, 'status': 'registration_frame_mismatch', 'reason': str(error),
                'evidence_grade': 'official_plan_registered', 'survey_verified': False}
    if allowed is None:
        return None
    outside = float(projection.difference(allowed).area)
    return {'satisfied': outside <= _AREA_EPSILON_M2, 'outside_area_m2': outside,
            'evidence_grade': 'official_plan_registered', 'survey_verified': False,
            'registration_id': _POLICIES[str(site.pnu)]['frontage_registration']['registration_id']}


def area_limit_evidence(source, site, gross_m2):
    """Compare actual source projection and the supplied floor-area certificate."""
    ground_cap = getattr(site, 'ground_capacity_m2', None)
    far_cap = getattr(site, 'far_capacity_m2', None)
    try:
        projection, projection_basis = _projection_for_gate(source)
    except ValueError as error:
        return {'ground_m2': None, 'gross_m2': float(gross_m2),
                'ground_capacity_m2': ground_cap, 'far_capacity_m2': far_cap,
                'projection_basis': 'unavailable', 'projection_error': str(error),
                'satisfied': False, 'reasons': ['source_projection_unavailable']}
    ground = float(projection.area)
    reasons = []
    if ground_cap is not None and ground > ground_cap + 1e-6:
        reasons.append('projected_area_exceeds_capacity')
    if far_cap is not None and float(gross_m2) > far_cap + 1e-6:
        reasons.append('floor_area_exceeds_capacity')
    building_line = _building_line_evidence(projection, site)
    if building_line is not None and not building_line['satisfied']:
        reasons.append('registered_building_line_exceeded' if 'outside_area_m2' in building_line
                       else 'parcel_registration_frame_mismatch')
    return {'ground_m2': ground, 'gross_m2': float(gross_m2),
            'ground_capacity_m2': ground_cap, 'far_capacity_m2': far_cap,
            'projection_basis': projection_basis,
            'building_line': building_line,
            'satisfied': not reasons, 'reasons': reasons}


def storey_limit_evidence(source, site, *, storey_m=None, declared_storeys=None,
                         book_floor_count=None, source_kind='authored'):
    policy = policy_for(getattr(site, 'pnu', None))
    limit = (policy or {}).get('max_storeys')
    meta = source.metadata or {}
    declared = declared_storeys if declared_storeys is not None else meta.get('declared_storeys')
    declared = float(declared) if declared is not None else None
    # BOOK must supply its own retained ruler. A missing record cannot be
    # repaired by silently borrowing the parcel's default storey height.
    if source_kind != 'book':
        storey_m = storey_m or meta.get('authored_floor_height_m') or getattr(site, 'floor_height_m', None)
    valid_storey = storey_m is not None and isfinite(float(storey_m)) and float(storey_m) > 0
    height = float(meta.get('authored_height_m') or 0)
    datum = float(meta.get('datum_m') or 0)
    structural = set(meta.get('structural_bands') or ())
    tops = []
    for index, volume in enumerate(source.volumes):
        if index in structural:
            continue
        low, high = volume.bottom_fraction * height, volume.top_fraction * height
        if volume.section_kind() == 'flat':
            tops.append(high)
        else:
            tops.extend(low + (high-low)*point[3]
                        for triangle in volume.surface_mesh for point in triangle)
    occupied = max(0., max(tops, default=datum)-datum)
    proxy = max(0, ceil(occupied / float(storey_m)-1e-6)) if valid_storey else None
    book_count = int(book_floor_count) if book_floor_count is not None else None
    reasons = []
    if limit is not None:
        if not valid_storey or proxy is None:
            reasons.append('missing_candidate_storey_ruler')
        if source_kind == 'book' and (book_count is None or book_count < 1):
            reasons.append('missing_book_floor_count')
        if proxy is not None and proxy > limit:
            reasons.append('conceptual_storey_proxy_exceeds_limit')
        if declared is not None and declared > limit:
            reasons.append('declared_storeys_exceed_limit')
        if book_count is not None and book_count > limit:
            reasons.append('book_floor_count_exceeds_limit')
    return {'policy_id': (policy or {}).get('policy_id'), 'max_storeys': limit,
            'statutory_max_height_m': (policy or {}).get('statutory_max_height_m'),
            'declared_storeys': declared, 'book_floor_count': book_count,
            'candidate_storey_height_m': float(storey_m) if valid_storey else None,
            'occupied_height_above_datum_m': occupied, 'conceptual_storey_proxy': proxy,
            'count_basis': 'conservative occupied-height / candidate-storey proxy; not verified design floors',
            'actual_design_floor_count_verified': False,
            'satisfied': not reasons, 'reasons': reasons, 'policy_evidence': policy}
