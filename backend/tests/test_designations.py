"""designations: an unknown 용지·시설 reports, an unknown 용도지역 blocks; the 정북 exemption areas are named."""
from backend.app.modules.land.analysis_response import build_restrictions
from backend.app.modules.land.reference.services import designations
from backend.app.modules.regulations import calculator


def test_kind_reads_the_suffix_only():
    for name in ('제2종일반주거지역', '준주거지역', '일반상업지역', '준공업지역', '자연녹지지역', '계획관리지역', '농림지역', '자연환경보전지역', '미확인주거지역'):
        assert designations.kind(name) == designations.USE_ZONE, name
    # A designation under another law that happens to end in 지역 is not a zoning category.
    for name in ('지구단위계획구역', '과밀억제권역', '가축사육제한구역', '시가지경관지구', '학교환경위생정화구역', '역사문화환경보존지역', '소음대책지역'):
        assert designations.kind(name) == designations.OVERLAY, name
    for name in ('공공청사', '공원', '주차장', '근린생활시설용지', ''):
        assert designations.kind(name) == designations.FACILITY, name


def test_only_an_unknown_use_zone_blocks_the_caps():
    names = ['제2종일반주거지역', '공공청사', '과밀억제권역', '지구단위계획구역', '이상한주거지역', '새로운지구', '역사문화환경보존지역']
    blocking, codes = designations.unresolved_evidence(names, {'제2종일반주거지역'}, {'과밀억제권역', '지구단위계획구역'})
    assert blocking == ['이상한주거지역']
    assert codes == ['unlisted_designation:공공청사', 'unresolved_zoning:이상한주거지역', 'unlisted_designation:새로운지구', 'unlisted_designation:역사문화환경보존지역']


def test_the_calculator_keeps_the_caps_when_only_a_facility_is_unlisted():
    result = calculator.calculate_all(['제2종일반주거지역', '공공청사', '지구단위계획구역'], None, sigungu_code='41150', use_llm_extraction=False)
    coverage = result['municipal_coverage']
    assert 'unlisted_designation:공공청사' in coverage['missing_evidence']
    assert not any(code.startswith('unresolved_zoning:') for code in coverage['missing_evidence'])
    assert result['bcr_pct'] is not None and result['far_pct'] is not None
    # A genuinely unknown 용도지역 still withholds the ordinance caps.
    unknown = calculator.calculate_all(['제2종일반주거지역', '미확인주거지역'], None, sigungu_code='41150', use_llm_extraction=False)
    assert 'unresolved_zoning:미확인주거지역' in unknown['municipal_coverage']['missing_evidence']
    assert unknown['municipal_coverage']['status'] == 'needs_evidence'


def test_restrictions_say_the_exemption_the_floor_and_the_unlisted_designation():
    reg = {'bcr_pct': 60, 'far_pct': 250, 'municipal_coverage': {'status': 'ok'}, 'sunlight_applies': True,
           'unmatched_zones': ['공공청사', '이상한주거지역']}
    ext = {'site_subdivision_limit': {'min_area_m2': 60}}
    lines = build_restrictions(reg, ['제2종일반주거지역', '지구단위계획구역', '공공청사', '이상한주거지역'], ext, overlays=[], overlay_all_matched={'지구단위계획구역'})
    assert any(line.startswith('일조사선') and '지구단위계획구역 안 대지가 너비 20m 이상 도로에 접하면 적용 제외' in line for line in lines)
    assert '대지 분할 제한: 시행령 하한 60m² 이상 범위에서 조례로 정함 — 조례 면적 확인 필요' in lines
    assert '미인식 용도지역: 이상한주거지역 (수동 확인 필요)' in lines
    assert any(line.startswith('규제표에 없는 지정: 공공청사') for line in lines)
    assert not any('상한 미확정' in line for line in lines)
    plain = build_restrictions({'sunlight_applies': True, 'unmatched_zones': []}, ['제2종일반주거지역'], None)
    assert plain == ['일조사선: 정북방향 10m 이하 1.5m · 초과 부분 H/2 이격']
