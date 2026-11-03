"""Live regression for the site search: 42 typed queries through ``POST /api/v1/land/search``.

    .venv/Scripts/python.exe -X utf8 backend/scripts/address_search_regression.py [--base http://127.0.0.1:18449]

Each case says what a correct answer is; ``before`` is the PNU the old ``/resolve`` path (getCoord, then
``/reverse`` at the point) gave on 2026-11-03 (None = no parcel). A case is correct now when:
- ``unique``    status unique and the top PNU is the expected one;
- ``choose``    not unique (never a silent single answer), the expected PNU in the list when one is named;
- ``place`` / ``area``  candidates listed and the top one is the expected lot / district;
- ``none``      nothing selected (status none, or a list with no exact match).
Before was correct only for ``unique`` with the same PNU, ``none`` with no PNU, and ``place`` with the right lot.
Needs the backend running with its VWorld key; calls the provider about 2-4 times per case.
"""
import argparse
import json
import sys
import urllib.request

SANGOK = '4115011300106840001'
CITY_HALL = '1114010300100310000'
CASES = [
    # query, expectation, expected PNU (or label fragment for area), PNU the old path gave
    ('4115011300106840001', 'unique', SANGOK, SANGOK),
    ('4115011300206840001', 'none', None, None),
    ('1111010100100010000', 'unique', '1111010100100010000', '1111010100100010000'),
    ('41150-11300-1-0684-0001', 'unique', SANGOK, None),
    ('경기도 의정부시 산곡동 684-1', 'unique', SANGOK, SANGOK),
    ('의정부시 산곡동 684-1', 'unique', SANGOK, SANGOK),
    ('산곡동 684-1', 'unique', SANGOK, SANGOK),
    ('의정부 산곡동 684-1', 'unique', SANGOK, SANGOK),
    ('경기 의정부시 산곡동 684-1', 'unique', SANGOK, SANGOK),
    ('산곡동684-1', 'unique', SANGOK, SANGOK),
    ('산곡동 684번지 1', 'unique', SANGOK, SANGOK),
    ('서울특별시 중구 세종대로 110', 'unique', CITY_HALL, CITY_HALL),
    ('세종대로 110', 'unique', CITY_HALL, CITY_HALL),
    ('서울 중구 세종대로110', 'unique', CITY_HALL, CITY_HALL),
    ('서울 중구 세종로 110', 'none', None, None),
    ('서울 강남구 테헤란로 152', 'unique', '1168010100107370000', '1168010100107370000'),
    ('테헤란로152', 'unique', '1168010100107370000', '1168010100107370000'),
    ('서울 중구 을지로1가 1', 'choose', None, '1114010500100010001'),
    ('서울 중구 을지로1가', 'area', '서울특별시 중구 을지로1가', '1114010400100100003'),
    ('서울특별시 종로구 청운동 산 1', 'choose', '1111010100200010001', '1111010100200010001'),
    ('강원특별자치도 평창군 대관령면 횡계리 1', 'unique', '5176038024100010000', '5176038024100010000'),
    ('강원도 평창군 대관령면 횡계리 1', 'unique', '5176038024100010000', '5176038024100010000'),
    ('제주특별자치도 제주시 첨단로 242', 'unique', '5011013600121810000', '5011013600121810000'),
    ('부산 해운대구 우동 1408', 'unique', '2635010500114080000', '2635010500114080000'),
    ('세종특별자치시 한누리대로 2130', 'unique', '3611010300107180000', '3611010300107180000'),
    ('전북특별자치도 전주시 완산구 효자동2가 1', 'choose', '5211114100100010001', '5211114100100010001'),
    ('서울시청', 'place', CITY_HALL, None),
    ('강남역', 'place', '1168010100108580000', '1168010100108230007'),
    ('롯데월드타워', 'place', '1171010200100290000', None),
    ('의정부시청', 'place', '4115010100103260002', '4115010100103260002'),
    ('판교역로 235', 'unique', '4113510900106810000', '4113510900106810000'),
    ('경기도 성남시 분당구 판교역로 235', 'unique', '4113510900106810000', '4113510900106810000'),
    ('대구 수성구 범어동', 'area', '대구광역시 수성구 범어동', '2726010100100010000'),
    ('광주광역시 서구 내방로 111', 'unique', '1224012000112000000', '1224012000112000000'),
    ('신촌동 1', 'choose', '4148012000100010000', '4113110900100010001'),
    ('중앙동 1', 'choose', None, '5113010100100010001'),
    ('산곡동 100', 'choose', '2823710300101000000', '2823710300101000000'),
    ('산곡동 684-1 인천', 'choose', SANGOK, SANGOK),
    ('중앙로 1', 'choose', '5111010100100150000', '5213011800100010001'),
    ('서울 중구 세종대로 11O', 'choose', None, None),
    ('서울 중구 세종대로 1100', 'none', None, None),
    ('강남대로 396', 'unique', '1168010100108580000', None),
]


def search(base: str, query: str) -> dict:
    request = urllib.request.Request(base.rstrip('/') + '/api/v1/land/search', method='POST',
                                     data=json.dumps({'query': query}).encode(), headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def correct_now(expect: str, target, reply: dict) -> bool:
    status, rows = reply.get('status'), reply.get('candidates') or []
    top = rows[0] if rows else {}
    pnus = [row.get('pnu') for row in rows]
    if expect == 'unique':
        return status == 'unique' and top.get('pnu') == target
    if expect == 'choose':
        return status == 'ambiguous' and (target is None or target in pnus)
    if expect == 'place':
        return status == 'ambiguous' and top.get('kind') == 'place' and top.get('pnu') == target
    if expect == 'area':
        return status == 'ambiguous' and top.get('kind') == 'area' and top.get('label') == target
    return status == 'none' or (status == 'ambiguous' and not any(row.get('exact') for row in rows))


def correct_before(expect: str, target, before) -> bool:
    if expect == 'unique':
        return before == target
    if expect == 'none':
        return before is None
    if expect == 'place':
        return before == target
    return False  # choose / area: the old path always answered one lot without saying so


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--base', default='http://127.0.0.1:18449')
    args = parser.parse_args()
    now = before = 0
    print(f"{'query':<34} {'expect':<7} {'status':<10} {'top candidate':<44} before now")
    for query, expect, target, old in CASES:
        try:
            reply = search(args.base, query)
        except Exception as error:  # a live script: a failed call is a wrong case, shown as such
            reply = {'status': f'error {type(error).__name__}', 'candidates': []}
        top = (reply.get('candidates') or [{}])[0]
        flag = ('S ' if top.get('substituted') else '') + (top.get('label') or '-')
        ok_now, ok_before = correct_now(expect, target, reply), correct_before(expect, target, old)
        now += ok_now
        before += ok_before
        print(f"{query:<34} {expect:<7} {reply.get('status', '?'):<10} {flag[:44]:<44} {'ok' if ok_before else 'NO':<6} {'ok' if ok_now else 'NO'}")
    print(f'\nbefore {before}/{len(CASES)} correct, now {now}/{len(CASES)} correct')
    return 0 if now == len(CASES) else 1


if __name__ == '__main__':
    sys.exit(main())
