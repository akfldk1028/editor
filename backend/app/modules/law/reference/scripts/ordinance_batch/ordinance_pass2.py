"""Second pass for jurisdictions the editor's fetcher could not do.

Run with the SiteContext venv (it has the HWP reader):
- ordinance name variants (계획 조례, 도시계획조례, 군계획조례 ...),
- article titles the fetcher's regex misses (용도구역·지역·지구안에서의 건폐율, a combined
  건폐율·용적률 article),
- caps that live in a 별표 HWP attachment ("별표 24에 따른다"): the attachment is downloaded
  from law.go.kr, its text read, and each zone's first one or two percentages taken.
Writes the same ordinance_overrides/<code>.json shape, with the 별표 URL and sha256.
"""
import hashlib
import json
import re
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, 'D:/Data/25_ACE/agents/SiteContextAgent')
from sitecontextagent.district_documents import hwp_text  # noqa: E402

OC = 'hanvit4303'
OUT = Path('D:/Data/25_ACE/editor/backend/app/modules/land/reference/data/ordinance_overrides')
LOG1 = Path(__file__).with_name('ordinance_batch.json')
LOG2 = Path(__file__).with_name('ordinance_pass2.json')
ZONES = ["제1종전용주거지역", "제2종전용주거지역", "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역",
         "준주거지역", "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역",
         "전용공업지역", "일반공업지역", "준공업지역", "보전녹지지역", "생산녹지지역", "자연녹지지역",
         "보전관리지역", "생산관리지역", "계획관리지역", "농림지역", "자연환경보전지역"]
WHERE = r"용도\s*(?:구역\s*[·ㆍ,‧]?\s*)?지역(?:\s*[·ㆍ,‧]?\s*지구\s*(?:등)?)?\s*(?:안|내)?\s*(?:에서의?|의|별)"
BCR = re.compile(WHERE + r"\s*(?:건축물의\s*)?건폐율")
FAR = re.compile(WHERE + r"\s*(?:건축물의\s*)?용적률")
BOTH = re.compile(WHERE + r"\s*(?:건축물의\s*)?건폐율\s*[·ㆍ‧및,&#;0-9\s]*용적률")


def api(url):
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode('utf-8'))


def search(name):
    d = api(f"https://www.law.go.kr/DRF/lawSearch.do?OC={OC}&target=ordin&type=JSON&query={urllib.parse.quote(name)}&display=100")
    items = d.get('OrdinSearch', {}).get('law', [])
    return [items] if isinstance(items, dict) else items


def find(local, sido_names):
    variants = [f'{local} 도시계획 조례', f'{local} 도시계획조례', f'{local} 군계획 조례', f'{local} 군계획조례',
                f'{local} 계획 조례', f'{local} 도시·군계획 조례', f'{local} 도시ㆍ군계획 조례', f'{local} 관리계획 조례']
    for name in variants:
        for item in search(name):
            if item.get('자치법규명') == name and (not sido_names or any(s in (item.get('지자체기관명') or '') for s in sido_names)):
                return item
    # Some publish under other spellings ('구례군 도시·군계획 조례', '거창군계획조례'): one broad query.
    pattern = re.compile(rf"^{re.escape(local)}\s*(?:도시\s*[·ㆍ]?\s*)?(?:군|관리)?\s*계획\s*조례(?:\s*\[[^\]]*\])?$")
    for item in search(local + ' 계획'):
        if pattern.match(item.get('자치법규명') or '') and (not sido_names or any(s in (item.get('지자체기관명') or '') for s in sido_names)):
            return item
    return None


def units_of(law):
    jo = law.get('조문') or {}
    units = jo.get('조') if isinstance(jo, dict) else jo
    return [units] if isinstance(units, dict) else (units or [])


def annexes_of(law):
    b = law.get('별표') or {}
    units = b.get('별표단위') if isinstance(b, dict) else b
    return [units] if isinstance(units, dict) else (units or [])


def article_no(u):
    raw = u.get('조문번호')
    raw = (raw[0] if isinstance(raw, list) else str(raw or '')).strip()
    if raw.isdigit() and len(raw) == 6:
        main, branch = int(raw[:4]), int(raw[4:])
        return f'제{main}조' + (f'의{branch}' if branch else '')
    return f'제{raw}조'


def body_of(u):
    parts = [str(u.get('조내용') or '')]

    def walk(x):
        if isinstance(x, dict):
            for k, v in x.items():
                if k in ('항내용', '호내용', '목내용'):
                    parts.append(str(v))
                else:
                    walk(v)
        elif isinstance(x, list):
            for y in x:
                walk(y)
    walk(u.get('항'))
    return ' '.join(parts).replace('\n', ' ')


def zone_pattern(zone):
    # Tables split names ('제1종 전용주거지역'): allow whitespace between every character.
    return r"\s*".join(map(re.escape, zone))


def pct_after(text, zone, count, table=False):
    m = re.search(zone_pattern(zone), text)
    if not m:
        return None
    window = text[m.end():m.end() + 160]
    others = [re.search(zone_pattern(z), window) for z in ZONES if z != zone]
    cut = min((o.start() for o in others if o), default=len(window))
    window = window[:cut]
    if table:  # a 별표 row: the first numbers after the zone name, no '퍼센트'
        values = [int(v.replace(',', '')) for v in re.findall(r'(?<![\d,])(\d{1,2},\d{3}|\d{1,4})(?![\d,])', window)]
    else:
        values = [int(v.replace(',', '')) for v in re.findall(r'([\d,]{2,5})\s*(?:퍼센트|%)', window)]
    return values[:count] if len(values) >= count else None


def annex_text(law, number):
    unit = next((a for a in annexes_of(law) if str(a.get('별표번호', '')).lstrip('0') == str(number)
                 and str(a.get('별표가지번호', '00')).strip('0') == ''), None)
    if unit is None or not unit.get('별표첨부파일명'):
        return None, None
    url = unit['별표첨부파일명']
    data = urllib.request.urlopen(url, timeout=120).read()
    folder = Path(__file__).with_name('annexes')
    folder.mkdir(exist_ok=True)
    path = folder / (hashlib.sha256(data).hexdigest()[:16] + '.' + (unit.get('별표첨부파일구분') or 'hwp'))
    path.write_bytes(data)
    text = hwp_text(path) if path.suffix in ('.hwp', '.hwpx') else ''
    return text, {'title': unit.get('별표제목'), 'url': url, 'sha256': hashlib.sha256(data).hexdigest(), 'bytes': len(data)}


def caps(law):
    """{zone: (bcr, far, bcr_article, far_article)}, annex provenance or None."""
    bcr_u = far_u = both_u = None
    for u in units_of(law):
        title = str(u.get('조제목') or '')
        if BOTH.search(title) and both_u is None:
            both_u = u
        elif BCR.search(title) and bcr_u is None:
            bcr_u = u
        elif FAR.search(title) and far_u is None:
            far_u = u
    out, annex = {}, None
    plans = [(both_u, 2)] if both_u and not (bcr_u and far_u) else [(bcr_u, 1), (far_u, 1)]
    for index, (unit, count) in enumerate(plans):
        if unit is None:
            continue
        body = body_of(unit)
        text, where, table = body, article_no(unit), False
        if not any(pct_after(body, z, 1) for z in ZONES):
            ref = re.search(r'별표\s*(\d+)', body)
            if ref:
                text, annex = annex_text(law, ref.group(1))
                where, table = f'별표 {ref.group(1)} ({article_no(unit)})', True
                if not text:
                    continue
        for zone in ZONES:
            got = pct_after(text, zone, count, table)
            if not got:
                continue
            row = out.setdefault(zone, {})
            if count == 2:
                row.update(bcr=got[0], far=got[1], bcr_article=where, far_article=where)
            elif index == 0:
                row.update(bcr=got[0], bcr_article=where)
            else:
                row.update(far=got[0], far_article=where)
    return out, annex


def main():
    done = json.loads(LOG1.read_text(encoding='utf-8'))
    previous = json.loads(LOG2.read_text(encoding='utf-8')) if LOG2.exists() else {}
    todo = sorted(k for k, v in done.items() if v['status'] != 'written'
                  and previous.get(k, {}).get('status') != 'written')
    table = sorted(Path('D:/Data/25_ACE/data/legal-dong-codes').glob('bjd_codes_*.txt'))[-1]
    names = {}
    for line in open(table, encoding='utf-8'):
        parts = line.rstrip('\r\n').split('\t')
        if len(parts) >= 3 and parts[2].strip() == '존재':
            names[parts[0]] = parts[1]
    report = {k: v for k, v in previous.items() if v.get('status') == 'written'}
    for code in todo:
        full = names.get(code.ljust(10, '0'))
        if not full:
            report[code] = {'status': 'failed', 'reason': 'no current name'}
            continue
        parts = full.split()
        local = parts[-1] if len(code) == 5 else parts[0]
        sido = {'전남광주통합특별시': ['전남광주통합특별시', '(구)전라남도'], '강원특별자치도': ['강원'], '전북특별자치도': ['전북', '전라북도']}.get(parts[0], [parts[0]])
        try:
            hit = find(local if len(code) == 5 else full, sido if len(code) == 5 else [])
            if not hit:
                report[code] = {'status': 'failed', 'reason': 'ordinance not found under any name variant'}
                continue
            law = api(f"https://www.law.go.kr/DRF/lawService.do?OC={OC}&target=ordin&type=JSON&ID={hit['자치법규ID']}")
            law = law.get('LawService') or law
            rows, annex = caps(law)
            if not any('bcr' in r for r in rows.values()) or not any('far' in r for r in rows.values()):
                report[code] = {'status': 'failed', 'name': hit['자치법규명'], 'reason': f'caps not parsed ({len(rows)} zones)'}
                continue
        except Exception as exc:
            report[code] = {'status': 'failed', 'reason': f'{type(exc).__name__}: {exc}'}
            continue
        name = hit['자치법규명']
        overrides = {}
        for zone, r in rows.items():
            row = {}
            if 'bcr' in r:
                row.update(bcr_default=r['bcr'], bcr_article=f"{name} {r['bcr_article']}")
            if 'far' in r:
                row.update(far_default=r['far'], far_article=f"{name} {r['far_article']}")
            overrides[zone] = row
        info = law.get('자치법규기본정보') or {}
        doc = {'__comment': f'{name} 용도지역별 건폐율·용적률 (law.go.kr 자치법규 API에서 생성, 2nd pass: name variant / 별표 HWP)',
               'code': code, 'level': 'sido' if len(code) == 2 else 'sigungu', 'sigungu_code': code,
               'sigungu_name': full,
               'ordinance': {'name': name, 'id': str(hit['자치법규ID']), 'effective': info.get('시행일자') or hit.get('시행일자'),
                             'edition_id': hit.get('자치법규일련번호'), 'issuer': hit.get('지자체기관명'),
                             'url': f"https://www.law.go.kr/LSW/ordinInfoP.do?ordinSeq={hit.get('자치법규일련번호')}",
                             'promulgated': info.get('공포일자'), 'no': info.get('공포번호'),
                             **({'annex': annex} if annex else {})},
               'fetched_at': datetime.now(timezone.utc).isoformat(timespec='seconds'),
               'overrides': overrides, 'common': {}}
        (OUT / f'{code}.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        report[code] = {'status': 'written', 'name': name, 'zones': len(overrides), 'annex': bool(annex)}
        print(code, 'written', name, len(overrides), 'zones', 'annex' if annex else '', flush=True)
    LOG2.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding='utf-8')
    print('pass2', len(todo), 'written', sum(1 for v in report.values() if v['status'] == 'written'))


if __name__ == '__main__':
    main()
