"""Prepare explicit batches from newly discovered downloadable precise sheets."""
import source_job_paths as sjp
import json,time
from pathlib import Path
ROOT=Path(str(sjp.NGII_ORIGINAL_ROOT))
audit=json.loads((ROOT/'live-source-audit.json').read_text(encoding='utf-8'))
choices={}
for result in audit['results'].values():
    for row in result.get('newPreciseSheets',[]):
        score={'zip':0,'dxf':1,'ngi':2}.get(row['fileExt'],3)
        if row['num'] not in choices or score<choices[row['num']][0]:
            choices[row['num']]=(score,row)
rows=[v[1] for v in choices.values()]
catalogue=[dict(sheet=x['num'],scale=x['scale'],projection=x['projection'],year='',
                **{k:x[k] for k in ['minx','miny','maxx','maxy']}) for x in rows]
plan=[dict(orderTp=x['type'],mapScale=x['scale'],mapNo=x['num'],mapName=x['name'],
           mapHistoryNo=x['historyNo'],mapKind='0') for x in rows]
(ROOT/'live-extra-catalogue.json').write_text(json.dumps(catalogue,ensure_ascii=False),encoding='utf-8')
(ROOT/'live-extra-download-plan.json').write_text(json.dumps(dict(at=time.time(),auditState=audit['state'],
    auditChecked=audit['regionsChecked'],sheets=len(plan),batches=[plan[i:i+100] for i in range(0,len(plan),100)]),
    ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(dict(audited=audit['regionsChecked'],preparedSheets=len(plan))))
