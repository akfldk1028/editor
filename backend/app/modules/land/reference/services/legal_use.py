"""Conservative legal-use labels shared by applicability and parking.

Classification identifies a use; it does not establish permission or that every
exception within a broad statutory category has been excluded.
"""
import re


def _key(value):
    return re.sub(r'\s+', '', value or '').lower()


_GROUPS = {
    '교육연구시설': ['교육연구시설', '학교'],
    '공동주택': ['공동주택', '아파트', '공동주택(아파트)', '연립주택', '다세대주택', '기숙사', '학생용 기숙사'],
    '단독주택': ['단독주택', '다가구주택', '다중주택', '공관'],
    '업무시설': ['업무시설', '오피스텔', '공공업무시설', '일반업무시설', '외국공관'],
    '방송통신시설': ['방송통신시설', '방송통신시설 중 데이터센터', '방송국'],
    '의료시설': ['의료시설', '병원', '정신병원', '요양병원', '격리병원'],
    '운동시설': ['운동시설', '골프장', '골프연습장', '옥외수영장'],
    '문화 및 집회시설': ['문화 및 집회시설', '관람장'],
}
_SIMPLE = ['위락시설', '종교시설', '판매시설', '운수시설', '장례식장', '제1종 근린생활시설', '제2종 근린생활시설', '숙박시설', '수련시설', '공장', '창고시설', '발전시설', '노유자시설']
_LOOKUP = {_key(use): (use, category) for category, uses in _GROUPS.items() for use in uses}
_LOOKUP.update({_key(use): (use, use) for use in _SIMPLE})
_ALIASES = {
    '학교시설': '학교',
    '공동주택(아파트)': '아파트',
    '업무시설(오피스텔)': '오피스텔', '업무시설중오피스텔': '오피스텔', 'officetel': '오피스텔',
    '데이터센터': '방송통신시설 중 데이터센터', 'datacenter': '방송통신시설 중 데이터센터',
    'datacentre': '방송통신시설 중 데이터센터', '방송통신시설(데이터센터)': '방송통신시설 중 데이터센터',
    '방송통신시설중방송국': '방송국', '방송통신시설(방송국)': '방송국',
    '업무시설(외국공관)': '외국공관', '의료시설(요양병원)': '요양병원',
    '의료시설(정신병원)': '정신병원', '의료시설(격리병원)': '격리병원',
    '문화및집회시설(관람장)': '관람장', '운동시설(옥외수영장)': '옥외수영장',
}


def classify_building_use(value) -> dict:
    label = value if isinstance(value, str) else ''
    normalized = _key(label)
    canonical, category = _LOOKUP.get(_key(_ALIASES.get(normalized, label)), (None, None))
    return {'input': label, 'canonical_use': canonical, 'category': category,
            'subtype': canonical if canonical != category else None,
            'status': 'classified' if canonical else 'needs_evidence'}
