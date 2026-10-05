"""Conditional surface-parking study on the delivered source and actual parcel.

Requirement and stall dimensions belong to the existing parking owners. This
module reserves public space, checks their actual output, and draws evidence.
It never certifies access or claims an optimum for the parcel.
"""
import hashlib
import json
from math import isfinite, sqrt
from pathlib import Path

from shapely.geometry import Polygon, mapping, shape
from shapely.ops import unary_union

from backend.app.modules.design.generation.maas.parking_layout import generate_parking_layout_candidate
from backend.app.modules.design.generation.maas.parking_requirements import resolve_candidate_parking_requirement
from backend.app.modules.design.generation.maas.massv2.parcel_policy import source_plan_projection, registered_vehicle_approach


def _hash(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
        separators=(',', ':'), allow_nan=False).encode('utf8')).hexdigest()


def parking_status_text(evidence):
    text = {
        'current_layout_capacity_shortfall':'현재 배치로는 조건부 필요 대수를 채우지 못했습니다. 다른 배치 가능성은 남아 있습니다.',
        'layout_geometry_conflict':'주차 구획 또는 차로가 건물·마당 예약·대지 경계를 침범해 배치 조정이 필요합니다.',
        'aisle_geometry_unverified':'구획 수량은 확보했으나 실제 차로 형상은 확인하지 못했습니다.',
        'requirement_unresolved':'용도 또는 주차 기준이 미확정이어서 필요 대수를 확정하지 않았습니다.',
        'count_reserved_access_unverified':'조건부 필요 수량을 배치했습니다. 진입·차량 회전·보행 연결은 미검증입니다.',
    }[evidence['status']]
    checks = evidence.get('geometry_checks') or {}
    if checks.get('satisfied') is False and evidence['status'] != 'layout_geometry_conflict':
        text += ' 구획 또는 차로의 공간 충돌도 있어 표시 수량 전체를 유효한 주차장으로 볼 수 없습니다.'
    if checks.get('satisfied') is False:
        text += (f" 차로 침범: 건물 {checks['drive_building_overlap_m2']:.2f}㎡, "
                 f"마당 예약 {checks['drive_public_overlap_m2']:.2f}㎡, 대지 밖 {checks['drive_outside_site_m2']:.2f}㎡.")
    grid = (evidence.get('layout') or {}).get('grid_solver') or {}
    if grid.get('drive_components_connected') is False:
        text += ' 차로가 서로 끊겨 있어 표시 구획 전체를 연결된 주차장으로 사용할 수 없습니다.'
    return text


def _polygons(geometry):
    if geometry.is_empty:
        return []
    if isinstance(geometry, Polygon):
        return [geometry]
    return [polygon for part in getattr(geometry, 'geoms', ()) for polygon in _polygons(part)]


def _layout_geometries(layout):
    stalls = [Polygon(row['polygon']) for row in layout.get('stalls', [])]
    drives = [Polygon(points) for points in layout.get('drive_cells', [])]
    connector = layout.get('entrance_connector_polygon')
    if connector:
        drives.append(Polygon(connector))
    if any(not g.is_valid or g.is_empty for g in stalls + drives):
        raise ValueError('parking owner returned invalid stall or drive geometry')
    return unary_union(stalls), unary_union(drives)


def _geometry_checks(layout, parcel, building, reserve):
    stalls, drives = _layout_geometries(layout)
    precision = float(layout.get('coordinate_precision_m') or 0)
    # Export rounds X and Y independently. Its own precision bounds the
    # displacement; record raw overlap too, rather than erasing slivers.
    displacement = precision * sqrt(2) / 2
    uncertainty = {name: (g.buffer(displacement).area - g.area if displacement and not g.is_empty else 0)
                   for name, g in (('stall', stalls), ('drive', drives))}
    values = {}
    for name, geometry in (('stall', stalls), ('drive', drives)):
        values[name + '_building_overlap_m2'] = geometry.intersection(building).area
        values[name + '_public_overlap_m2'] = geometry.intersection(reserve).area
        values[name + '_outside_site_m2'] = geometry.difference(parcel).area
    values['reported_count_matches_geometry'] = int(layout.get('provided_spaces') or 0) == len(layout.get('stalls', []))
    values['satisfied'] = values['reported_count_matches_geometry'] and all(
        value <= uncertainty[key.split('_')[0]] for key, value in values.items()
        if key.endswith('_m2'))
    values['export_coordinate_precision_m'] = precision
    values['rounding_area_uncertainty_m2'] = uncertainty
    values['drive_geometry_present'] = not drives.is_empty
    return values


def assess_site_parking(source, site, certificate, *, source_shape_id, public_reserve=None):
    """One parking layout chosen after evaluating every free area component.

    source_shape_id is supplied by the existing delivery identity owner; the
    core does not duplicate the tool's geometry hashing implementation.
    """
    if not source_shape_id or certificate.get('shape_id') != source_shape_id:
        raise ValueError('parking source/certificate identity mismatch')
    if certificate.get('site_pnu') is not None and str(certificate['site_pnu']) != str(site.pnu):
        raise ValueError('parking certificate parcel identity mismatch')
    gross = float(certificate['gross_m2'])
    if not isfinite(gross) or gross < 0:
        raise ValueError('parking requires finite certified mass area')
    parcel = getattr(site, 'site_local_utm', None)
    if parcel is None or parcel.is_empty or not parcel.is_valid:
        raise ValueError('parking requires the actual parcel geometry')
    occupied, projection_basis = source_plan_projection(source)
    reserve_record = public_reserve if public_reserve is not None else source.metadata.get('public_reserve')
    if reserve_record is not None:
        if (not isinstance(reserve_record, dict) or reserve_record.get('confirmed') is not True
                or reserve_record.get('source_shape_id') != source_shape_id
                or reserve_record.get('coordinate_frame') != 'parcel_local_m'):
            raise ValueError('authored public reserve requires confirmed source identity and parcel-local frame')
        reserve = shape(reserve_record['geometry'])
        if not reserve.is_valid or reserve.geom_type not in ('Polygon', 'MultiPolygon'):
            raise ValueError('authored public reserve geometry is invalid')
        reserve_basis = 'confirmed_authored_public_reserve'
    else:
        reserve = occupied.convex_hull.difference(occupied).intersection(parcel)
        reserve_basis = 'temporary_convex_hull_void_reservation'
    available = parcel.difference(unary_union([occupied, reserve]))
    components = sorted(_polygons(available), key=lambda p: (-p.area, p.normalize().wkb_hex))
    approach = registered_vehicle_approach(site)
    frontage = shape(approach['geometry'])
    road_context = {'road_frontages': [{'geometry':mapping(frontage)}]} if not frontage.is_empty else {}
    requirement = resolve_candidate_parking_requirement(pnu=str(site.pnu),
        building_type='공공업무시설', facility_area_m2=gross,
        options={'building_use_code':'appendix1_14_a', 'accessible_parking_applicable':True})
    required = requirement.get('required_spaces')
    accessible = (requirement.get('accessible') or {}).get('accessible_min')
    evaluations = []
    if requirement.get('status') == 'computed' and required is not None and accessible is not None:
        for index, polygon in enumerate(components):
            layout = generate_parking_layout_candidate(polygon, required_spaces=int(required),
                accessible_spaces=int(accessible), strategy='ground_surface',
                road_context=road_context, drive_envelope=polygon)
            checks = _geometry_checks(layout, parcel, occupied, reserve)
            evaluations.append({'component_index':index, 'area_m2':polygon.area,
                                'layout':layout, 'geometry_checks':checks})
    selected = max(evaluations, key=lambda row: (
        row['geometry_checks']['satisfied'],
        int(row['layout'].get('provided_accessible_spaces') or 0) >= int(accessible or 0),
        int(row['layout'].get('provided_spaces') or 0),
        row['geometry_checks']['drive_geometry_present'], row['area_m2']), default=None)
    layout = selected['layout'] if selected else {'provided_spaces':0, 'provided_accessible_spaces':0,
        'stalls':[], 'drive_cells':[], 'status':'not_generated'}
    checks = selected['geometry_checks'] if selected else _geometry_checks(layout, parcel, occupied, reserve)
    provided = len(layout.get('stalls', []))
    provided_accessible = sum(row.get('type') == 'accessible' for row in layout.get('stalls', []))
    count_met = required is not None and provided >= required and accessible is not None and provided_accessible >= accessible
    status = ('requirement_unresolved' if required is None or accessible is None else
              'current_layout_capacity_shortfall' if not count_met else
              'layout_geometry_conflict' if not checks['satisfied'] else
              'aisle_geometry_unverified' if required and not checks['drive_geometry_present'] else
              'count_reserved_access_unverified')
    return {'schema':'arr.maas.site_parking_study.v1', 'status':status,
        'source_name':certificate.get('name') or source.name, 'source_shape_id':source_shape_id,
        'certificate_id':certificate.get('certificate_id'), 'facility_area_assumption_m2':gross,
        'floor_area_basis':certificate.get('floor_area_basis'),
        'facility_area_basis':'certificate mass-area value used as a conditional programme scenario; statutory parking-area exclusions unverified',
        'site_pnu':str(site.pnu), 'site_geometry_sha256':hashlib.sha256(parcel.normalize().wkb).hexdigest(),
        'source_projection_sha256':hashlib.sha256(occupied.normalize().wkb).hexdigest(),
        'projection_basis':projection_basis, 'projection_area_m2':occupied.area,
        'programme_assumption':'공공업무시설 및 장애인전용주차구역 적용 대상이라는 조건부 설계 가정',
        'programme_classification_verified':False, 'requirement':requirement,
        'law_source_sha256':(requirement.get('source') or {}).get('source_sha256'),
        'law_requirement_evidence_sha256':_hash(requirement),
        'public_reserve_basis':reserve_basis, 'public_reserve_area_m2':reserve.area,
        'public_reserve_outside_site_m2':reserve.difference(parcel).area,
        'public_reserve_building_overlap_m2':reserve.intersection(occupied).area,
        'available_area_m2':available.area, 'component_count':len(components),
        'evaluated_component_count':len(evaluations),
        'component_policy':'each component evaluated; one conservative single parking area selected; counts not summed',
        'selected_component_index':selected['component_index'] if selected else None,
        'component_evaluations':evaluations, 'layout':layout, 'geometry_checks':checks,
        'provided_spaces':provided, 'provided_accessible_spaces':provided_accessible,
        'count_target_met':bool(count_met), 'vehicle_access_status':'unverified',
        'pedestrian_access_status':'unverified', 'swept_path_status':'unverified',
        'legal_approval':False, 'site_maximum_proven':False, 'road_context':road_context,
        'registered_approach':approach,
        'geometry':{'site':mapping(parcel), 'building_projection':mapping(occupied),
                    'public_reserve':mapping(reserve), 'available':mapping(available)},
        'limitations':[
            '전체 건물 투영의 볼록껍질 안 빈 공간을 마당·집 사이 길로 예약하는 임시 보수적 공간 가설이다.'
            if reserve_basis.startswith('temporary') else '확정 저작 예약 영역을 우선 적용했다.',
            '전체 상부 투영도 제외하므로 필로티 아래 주차 가능성을 포함하지 않는다.',
            '인증서의 매스 면적을 조건부 시설면적으로 사용했다. 실제 실별 면적 및 법정 주차 산정 제외 항목은 미확정이다.',
            '기준이 확정된 경우 모든 분리 영역을 개별 검토한 후 한 곳을 선택한다. 부족은 이 배치의 용량 부족이며 대지 최대해나 위법 판정이 아니다.',
            '확정 출입구·보행 연결·차량 회전 궤적·도로 폭·실별 용도는 미검증이다. 수량 충족만으로 허가 적합을 뜻하지 않는다.']}


def write_site_parking_plan(evidence, out_dir, *, stem):
    """Draw exactly the stored stall/drive/reserve polygons and save their evidence."""
    from PIL import Image, ImageDraw, ImageFont
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / (stem + '-site-parking.png')
    canvas = Image.new('RGB', (1200, 1140), '#fcfcfa')
    draw = ImageDraw.Draw(canvas)
    font_path = Path('C:/Windows/Fonts/malgun.ttf')
    font = ImageFont.truetype(str(font_path), 19) if font_path.exists() else ImageFont.load_default()
    small = ImageFont.truetype(str(font_path), 15) if font_path.exists() else font
    geometry = {key:shape(value) for key,value in evidence['geometry'].items()}
    parcel = geometry['site']
    stalls, drives = _layout_geometries(evidence['layout'])
    xmin, ymin, xmax, ymax = unary_union([parcel, geometry['building_projection'],
        geometry['public_reserve'], stalls, drives]).bounds
    scale = min(1050/max(xmax-xmin, 1), 720/max(ymax-ymin, 1))
    offset_x = (1200-(xmax-xmin)*scale)/2
    def point(x, y):
        return offset_x + (x-xmin)*scale, 880-(y-ymin)*scale
    def paint(value, color, outline=None):
        mask = Image.new('L', canvas.size)
        painter = ImageDraw.Draw(mask)
        for polygon in _polygons(value):
            painter.polygon([point(x,y) for x,y in polygon.exterior.coords], fill=255)
            for ring in polygon.interiors:
                painter.polygon([point(x,y) for x,y in ring.coords], fill=0)
        canvas.paste(color, mask=mask)
        if outline:
            for polygon in _polygons(value):
                for ring in (polygon.exterior, *polygon.interiors):
                    draw.line([point(x,y) for x,y in ring.coords], fill=outline, width=2)
    def lines(value, color):
        if value.is_empty:
            return
        if value.geom_type == 'LineString':
            draw.line([point(x,y) for x,y in value.coords], fill=color, width=6)
        else:
            for part in getattr(value,'geoms',()): lines(part,color)
    paint(parcel, '#f3f2ec', '#686f6a')
    paint(geometry['public_reserve'], '#c7dfc7', '#628065')
    paint(geometry['building_projection'], '#67747b', '#34444e')
    layout = evidence['layout']
    for cell in layout.get('drive_cells', []): paint(Polygon(cell), '#f2d59b', '#b79b61')
    if layout.get('entrance_connector_polygon'):
        paint(Polygon(layout['entrance_connector_polygon']), '#f2d59b', '#b79b61')
    for index, row in enumerate(layout.get('stalls', []), 1):
        polygon = Polygon(row['polygon'])
        paint(polygon, '#bcadd8' if row.get('type') == 'accessible' else '#a4c7e3', '#466986')
        x,y = point(polygon.centroid.x, polygon.centroid.y)
        draw.text((x-9,y-9), 'A' if row.get('type') == 'accessible' else str(index), fill='#20343d', font=small)
    conflict = unary_union([stalls, drives]).intersection(unary_union([
        geometry['building_projection'], geometry['public_reserve']]))
    conflict = unary_union([conflict, unary_union([stalls, drives]).difference(parcel)])
    if evidence['geometry_checks']['satisfied'] is False:
        paint(conflict, '#dda29b', '#a74b42')
    lines(shape(evidence['registered_approach']['prohibited_geometry']), '#ae554b')
    lines(shape(evidence['registered_approach']['geometry']), '#318b88')
    required = evidence['requirement'].get('required_spaces')
    draw.text((45,26),'마당을 남긴 지상 주차 공간 검토 · 매스 면적 기준의 조건부 주차', fill='#22343a', font=font)
    draw.text((45,62),f"조건부 필요 {required if required is not None else '미정'}대 · 현재 배치 {evidence['provided_spaces']}대 (장애인 {evidence['provided_accessible_spaces']}대)",fill='#22343a',font=font)
    legend = [('#67747b','건물 전체 투영'),('#c7dfc7','마당·길 예약'),('#a4c7e3','주차 구획'),
              ('#f2d59b','차로'),('#318b88','금지 제외 도로면'),('#ae554b','차량출입 금지')]
    for i,(color,label) in enumerate(legend):
        x=45+i*188
        draw.rectangle((x,112,x+17,129),fill=color)
        draw.text((x+23,110),label,fill='#374650',font=small)
    draw.text((45,920),'업무시설·장애인주차 적용 가정 / 주차 산정 제외 면적·차량 진입·회전·보행 접근은 미검증',fill='#374650',font=small)
    draw.text((45,950),f"분리 영역 {evidence['component_count']}곳 중 {evidence['evaluated_component_count']}곳 검토 · 단일 주차장 선택 · 마당 예약 {evidence['public_reserve_area_m2']:.1f}㎡",fill='#374650',font=small)
    draw.text((45,980),('볼록껍질 내부 빈 공간 예약은 임시 가설이며 출입구나 실제 동선 설계를 뜻하지 않습니다.'
        if evidence['public_reserve_basis'].startswith('temporary') else '확정 저작의 공공 공간 예약 영역을 우선 적용했습니다.'),fill='#374650',font=small)
    y = 1010
    line = ''
    for character in parking_status_text(evidence):
        if draw.textlength(line + character, font=small) > 1100:
            draw.text((45,y),line,fill='#374650',font=small)
            y += 23
            line = ''
        line += character
    draw.text((45,y),line,fill='#374650',font=small)
    if evidence['geometry_checks']['satisfied'] is False:
        draw.text((45,y+23),'붉은 겹침은 주차면·차로와 건물·마당 예약·대지 경계의 충돌입니다.',fill='#a74b42',font=small)
    canvas.save(target)
    record = {**evidence, 'png_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    target.with_suffix('.json').write_text(json.dumps(record,ensure_ascii=False,indent=2,allow_nan=False),encoding='utf8')
    return target
