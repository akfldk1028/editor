"""Archived candidate audits bounded to the Editor-owned candidate store."""
from io import StringIO
import json
import os
from pathlib import Path
import re
from uuid import uuid4


def audit_pool(body):
    from backend.app.modules.design.generation.paths import data_root
    allowed = Path(os.environ.get('EDITOR_MASS_OUTPUT_ROOT',
                                  str(data_root() / 'massing/candidates'))).resolve()
    value = body.get('candidates_root', '')
    if not isinstance(value, str) or not value.strip():
        return {'exit': 2, 'error': 'candidates_root is required'}, 400
    candidate = Path(value)
    candidate = (candidate if candidate.is_absolute() else allowed / candidate).resolve()
    if not candidate.is_relative_to(allowed):
        return {'exit': 2, 'error': 'Candidate pool is outside the Editor candidate store'}, 400
    if not candidate.is_dir():
        return {'exit': 2, 'error': 'Candidate pool does not exist'}, 404
    limit = body.get('limit', 0)
    if isinstance(limit, bool) or not isinstance(limit, int) or not 0 <= limit <= 1000:
        return {'exit': 2, 'error': 'limit must be an integer from 0 to 1000'}, 400
    pnu = body.get('pnu', '')
    if not isinstance(pnu, str) or not re.fullmatch(r'\d{19}', pnu):
        return {'exit': 2, 'error': 'A 19-digit pnu is required'}, 400
    legal_check = body.get('legal_check', True)
    if not isinstance(legal_check, bool):
        return {'exit': 2, 'error': 'legal_check must be boolean'}, 400
    files = sorted(candidate.glob('*/candidates/*.json')) or sorted(candidate.glob('candidates/*.json'))
    if not files:
        return {'exit': 2, 'error': 'Candidate pool contains no candidate JSON'}, 400
    if any(not path.resolve().is_relative_to(allowed) for path in files):
        return {'exit': 2, 'error': 'Candidate file escapes the Editor candidate store'}, 400
    if not limit and len(files) > 1000:
        return {'exit': 2, 'error': 'Select at most 1000 candidates per audit'}, 413
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime
    ensure_design_runtime()
    from backend.app.modules.massing.commands.audit_maas_agent_collaboration import Command
    output = StringIO()
    command = Command(stdout=output)
    options = vars(command.create_parser('editor', 'audit').parse_args([
        '--candidates-root', str(candidate), '--pnu', pnu, '--limit', str(limit),
        *(['--legal-check'] if legal_check else []),
    ]))
    command.handle(**options)
    report = json.loads(output.getvalue())
    receipt = data_root() / 'law-audits' / (uuid4().hex + '.json')
    receipt.parent.mkdir(parents=True, exist_ok=True)
    receipt.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return {'exit': 0, 'stdout': '', 'report': str(receipt),
            'law_source': report.get('law_source'),
            'conditions': {name: value.get('final_status')
                           for name, value in report.get('conditions', {}).items()}}, 200
