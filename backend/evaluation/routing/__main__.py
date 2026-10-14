import argparse
import asyncio
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

from .metrics import score_routes
from .runner import run_case


async def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--cases',type=Path,default=Path('backend/tests/fixtures/routing/golden.json'))
    parser.add_argument('--policy',choices=['rules','hybrid','auto'],default='rules')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    data=json.loads(args.cases.read_text(encoding='utf-8'))
    cases=data['cases'] if isinstance(data,dict) else data
    rows=[]
    for index,case in enumerate(cases):
        if 'agent' in case:
            value=case['agent']
            case={'id':f'legacy-{index}','text':case['text'],'acceptable_owners':value if isinstance(value,list) else [value] if value else [],'should_ask':value is None}
        row=await run_case(case,args.policy)
        rows.append(row)
        with (args.output/'rows.jsonl').open('a',encoding='utf-8') as f: f.write(json.dumps(row,ensure_ascii=False)+'\n')
    result={'schema':'routing-evaluation/v1','timestamp':datetime.now(timezone.utc).isoformat(),
            'policy':args.policy,'dataset':str(args.cases),'dataset_sha256':hashlib.sha256(args.cases.read_bytes()).hexdigest(),
            'head':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            'dirty':bool(subprocess.check_output(['git','status','--porcelain'],text=True).strip()),
            'metrics':score_routes(rows),'limits':['Development fixtures unless separately labelled and held out.',
                'No owner execution or design generation.','Unexposed model identity/token usage remain null.']}
    (args.output/'summary.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result['metrics'],ensure_ascii=False))


if __name__ == '__main__':
    asyncio.run(main())
