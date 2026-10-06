"""Generate 도시계획 조례 cap files for every jurisdiction with the editor's own fetcher."""
import glob
import json
import subprocess
import sys
from pathlib import Path

EDITOR = Path('D:/Data/25_ACE/editor')
PY = str(EDITOR / '.venv/Scripts/python.exe')
SCRIPT = str(EDITOR / 'backend/app/modules/law/reference/scripts/fetch_ordinance_caps.py')
OUT_DIR = EDITOR / 'backend/app/modules/land/reference/data/ordinance_overrides'
LOG = Path(__file__).with_name('ordinance_batch.json')
METRO = {'11', '26', '27', '28', '30', '31', '50'}
FORMER_GWANGJU = {'12210', '12240', '12270', '12300', '12330'}

table = sorted(glob.glob('D:/Data/25_ACE/data/legal-dong-codes/bjd_codes_*.txt'))[-1]
rows = [l.rstrip('\r\n').split('\t') for l in open(table, encoding='utf-8')][1:]
live = [(r[0], r[1]) for r in rows if len(r) >= 3 and r[2].strip() == '존재']
sido = {c[:2]: n for c, n in live if c[2:] == '00000000'}

jobs = []
for code, name in ((c[:2], n) for c, n in live if c[2:] == '00000000'):
    if code in METRO:
        jobs.append((code, [f'{name} 도시계획 조례'], None))
for code, name in live:
    if code[5:] != '00000' or code[2:5] == '000':
        continue
    short, parts = code[:5], name.split()
    if short[:2] in METRO or len(parts) != 2:
        continue  # metro 자치구 use the city's ordinance; 일반구 (3 tokens) use their 시
    local = parts[1]
    if short in FORMER_GWANGJU:
        jobs.append((short, ['광주광역시 도시계획 조례'], 'former 광주광역시 ordinance applied in its former area after the merger'))
        continue
    names = [f'{local} 도시계획 조례'] if local.endswith('시') else [f'{local} 군계획 조례', f'{local} 도시·군계획 조례', f'{local} 도시계획 조례']
    jobs.append((short, names, None))

only = set(sys.argv[1:])
done = json.loads(LOG.read_text(encoding='utf-8')) if LOG.exists() else {}
for code, names, transitional in jobs:
    if only and code not in only:
        continue
    if done.get(code, {}).get('status') == 'written':
        continue
    result = {'status': 'failed', 'tried': []}
    for name in names:
        proc = subprocess.run([PY, '-X', 'utf8', SCRIPT, code, name], cwd=str(EDITOR), capture_output=True,
                              text=True, encoding='utf-8', errors='replace', timeout=600)
        result['tried'].append({'name': name, 'rc': proc.returncode,
                                'tail': (proc.stdout + proc.stderr)[-400:]})
        if proc.returncode == 0 and (OUT_DIR / f'{code}.json').is_file():
            result.update(status='written', name=name)
            if transitional:
                path = OUT_DIR / f'{code}.json'
                doc = json.loads(path.read_text(encoding='utf-8'))
                doc['ordinance']['transitional'] = transitional
                path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            break
    done[code] = result
    LOG.write_text(json.dumps(done, ensure_ascii=False, indent=1), encoding='utf-8')
    print(code, result['status'], result.get('name') or names[0], flush=True)
print('jobs', len(jobs), 'written', sum(1 for v in done.values() if v['status'] == 'written'))
