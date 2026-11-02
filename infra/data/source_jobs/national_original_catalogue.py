"""Resumable public NGII discovery, isolated from existing publication writers."""
import argparse
import collections
import concurrent.futures
import json
import os
from pathlib import Path
import re
import time

import httpx
import source_job_paths as sjp

BASE = 'https://map.ngii.go.kr'


def province_code(provider, municipality):
    if provider == '12':
        return '29' if municipality in {'12210', '12240', '12270', '12300', '12330'} else '46'
    return {'45': '52'}.get(provider, provider)


def select_candidates(rows, existing):
    choices = {}
    rank = {'zip': 0, 'dxf': 1, 'ngi': 2}
    for row in rows:
        if int(row.get('scale') or 999999) > 5000 or row['num'] in existing:
            continue
        if row.get('fileExt') not in rank:
            continue
        old = choices.get(row['num'])
        if old is None or rank[row['fileExt']] < rank[old['fileExt']]:
            choices[row['num']] = row
    return list(choices.values())


def write(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    temporary.replace(path)


def search_form(region, kind):
    a, b, c, d = map(float, region['geom'].split(','))
    return {'minx': a, 'miny': b, 'maxx': c, 'maxy': d,
            'sigu': region['sigunguCodePck'], 'type': kind}


def query(region):
    rows = []
    with httpx.Client(timeout=60, trust_env=False) as client:
        for kind in ('0', '3'):
            for attempt in range(3):
                try:
                    response = client.post(BASE + '/ms/map/suchiQuery.do', data=search_form(region, kind))
                    response.raise_for_status()
                    items = response.json()['items']
                    if not isinstance(items, list):
                        raise ValueError('Invalid catalogue')
                    rows.extend({**item, 'type': kind} for item in items)
                    break
                except Exception as error:
                    if attempt == 2:
                        return dict(state='request_failed', errorType=type(error).__name__, checkedAt=time.time())
                    time.sleep(attempt + 1)
    return dict(state='checked', queryVersion=2, checkedAt=time.time(), rows=rows,
                scope='Provider municipality search; not download or geometry verification proof.')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=sjp.DATA_ROOT / 'management/national-source-expansion')
    args = parser.parse_args()
    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    import msvcrt
    lock = (root / 'catalogue.lock').open('a+b')
    if not lock.tell():
        lock.write(b'0'); lock.flush()
    lock.seek(0)
    msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    with httpx.Client(timeout=60, trust_env=False) as client:
        providers = client.get(BASE + '/pd/ctlsSvc/selectSidoList.do').json()['siList']
        regions = []
        for provider in providers:
            municipalities = client.get(BASE + '/pd/ctlsSvc/selectSigunguList.do', params={'code': provider['code']}).json()['guList']
            for municipality in municipalities:
                regions.append(dict(categoryPck='9', sidoCode=provider['code'], sidoNm=provider['codenm'],
                    sigunguCodePck=municipality['code'], sigunguNmPck=municipality['codenm'],
                    geom=municipality['geom'], provinceCode=province_code(provider['code'], municipality['code'])))
    if len({r['provinceCode'] for r in regions}) != 17:
        raise ValueError('Provider mapping no longer covers exactly 17 reporting provinces')
    write(root / 'national-package-targets.json', dict(at=time.time(), providerGroups=providers,
        reportingProvinces=17, regions=regions, state='targets_discovered_not_ordered'))
    existing = set()
    for path in (sjp.NGII_ORIGINAL_ROOT / 'files').iterdir():
        if path.suffix.lower() in {'.zip', '.dxf', '.ngi'} and path.stat().st_size:
            match = re.search(r'_(\d{8,9})_\d{4}_', path.name)
            if match:
                existing.add(match[1])
    results = {}
    for region in regions:
        path = root / (region['sigunguCodePck'] + '-search.json')
        if path.exists():
            result = json.loads(path.read_text(encoding='utf-8'))
            if result['state'] == 'checked' and result.get('queryVersion') == 2:
                results[region['sigunguCodePck']] = result

    def save(state):
        candidates = select_candidates([row for result in results.values() for row in result.get('rows', [])], existing)
        provinces = []
        for code in sorted({r['provinceCode'] for r in regions}):
            selected = [r for r in regions if r['provinceCode'] == code]
            checked = [results[r['sigunguCodePck']] for r in selected if r['sigunguCodePck'] in results]
            records = [row for result in checked for row in result.get('rows', [])]
            precise = {str(r['num']) for r in records if int(r.get('scale') or 999999) <= 5000}
            provinces.append(dict(provinceCode=code, targetMunicipalities=len(selected),
                checkedMunicipalities=sum(r['state'] == 'checked' for r in checked),
                requestFailures=sum(r['state'] == 'request_failed' for r in checked),
                listedPreciseSheets=len(precise), localFilenameMatches=len(precise & existing),
                candidateSheets=len(select_candidates(records, existing))))
        write(root / 'catalogue-status.json', dict(pid=os.getpid(), at=time.time(), state=state,
            targetMunicipalities=len(regions), checkedMunicipalities=sum(r['state'] == 'checked' for r in results.values()),
            candidateSheets=len(candidates), provinces=provinces, orderedThisRun=0, downloadedThisRun=0,
            limitation='Search records are not orders, downloads, verified geometry, or complete national coverage.'))
        write(root / 'precise-download-plan.json', dict(at=time.time(), state='discovered_not_ordered',
            sheets=len(candidates), batches=[[dict(orderTp=r['type'],mapScale=r['scale'],mapNo=r['num'],
                mapName=r.get('name',''),mapHistoryNo=r.get('historyNo',''),mapKind='0') for r in candidates[i:i+100]]
                for i in range(0,len(candidates),100)]))
        write(root / 'national-catalogue.json', [dict(row, sheet=row['num']) for row in candidates])

    save('running')
    pending = [r for r in regions if r['sigunguCodePck'] not in results]
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(query, r): r for r in pending}
        for future in concurrent.futures.as_completed(futures):
            region = futures[future]
            result = future.result()
            results[region['sigunguCodePck']] = result
            write(root / (region['sigunguCodePck'] + '-search.json'), result)
            save('running')
    save('finished' if all(r['state'] == 'checked' for r in results.values()) else 'finished_with_failures')


if __name__ == '__main__':
    main()
