"""Bind judging comparisons to the actual frozen rubric, never a round label."""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

import hashlib
import json
import re
from pathlib import Path


def rubric_id(prompt):
    # The canonical rubric follows the variable SITE INPUT DATA section in
    # both track prompts. Reject unknown boundaries rather than hash site facts.
    start = re.search(r'(?m)^You are (?:a juror|an architectural design juror)\b', prompt)
    if start is None:
        raise ValueError('Cannot identify the frozen stage rubric')
    rubric = prompt[start.start():].replace('\r\n', '\n').strip()
    return 'sha256:' + hashlib.sha256(rubric.encode('utf8')).hexdigest()


def stage_contract(stage, *, freeze=False):
    stage = Path(stage)
    path = stage / 'evaluation-contract.json'
    contract = json.loads(path.read_text(encoding='utf8')) if path.exists() else None
    if not freeze:
        return contract
    prompt = stage / 'PROMPT.txt'
    if not prompt.exists():
        if contract:
            raise ValueError('Frozen evaluation prompt is missing')
        return None  # Legacy scorer fixtures/replay have no frozen prompt.
    current = {'schema':'arr.maas.evaluation_contract.v1',
               'rubric_id':rubric_id(prompt.read_text(encoding='utf8')),
               'prompt_sha256':hashlib.sha256(prompt.read_bytes()).hexdigest()}
    if contract is not None and contract != current:
        raise ValueError('Frozen evaluation prompt changed; use a new stage and rejudge')
    if contract is None:
        path.write_text(json.dumps(current, indent=2), encoding='utf8')
    return current


def compatible(row, active):
    return bool(active) and row.get('rubric_id') == active


def active_rubrics(root):
    result = {}
    for track, filename in [('O', 'judge-prompts-overseas.json'), ('K', 'judge-prompts.json')]:
        path = Path(root) / 'inputs' / filename
        if path.exists():
            result[track] = rubric_id(json.loads(path.read_text(encoding='utf8'))['rubric'])
    return result


def jury_provenance(stage):
    path = Path(stage) / 'jury-provenance.json'
    if not path.exists():
        return {'mode':'unspecified', 'model':None}
    value = json.loads(path.read_text(encoding='utf8'))
    if not isinstance(value, dict) or value.get('mode') not in ('external', 'internal'):
        raise ValueError('Jury provenance must declare external or internal mode')
    if value['mode'] == 'internal' and not value.get('model'):
        raise ValueError('Internal jury provenance must identify its model')
    return {**value, 'model':value.get('model')}
