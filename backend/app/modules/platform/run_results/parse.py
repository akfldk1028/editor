"""Turn an Orchestrator run (`GET /runs/{id}`: status + `communications`) into one UI-stable shape.

The Orchestrator caps every `request_text`/`response_text` at 8000 characters, so a tool's JSON may
arrive cut off (`truncated: true`). Reading is therefore tolerant: a cut JSON text is closed at its
last complete value, an unknown or missing field is null, and nothing here raises — the UI shows
what could be read and says what could not.

Contract (every key always present):
  run_id, status, goal, pending_input, truncated
  request: {pnu, parcels[], building_type, assessment_date} | null
  steps:   [{task_id, agent, tool, state, summary, truncated}]           (communication order)
  site:    {status, code, facts_known, facts_total, facts_missing[],
            facts: [{key, confidence, source, as_of, summary}]} | null       (the readable `state_patch` facts)
  law:     {status, site_area_m2, bcr_pct, far_pct, max_floors, ground_capacity_m2, far_capacity_m2, zones[],
            national_bcr_ceiling_pct, national_far_ceiling_pct, articles: {bcr, far, height},
            height: {status, limit_m}, policy_id, parcel_label, building_type,
            ordinance: {articles[], edition_id, effective_date, assessment_date,
                        sources: [{name, ordinance_id, edition_id, effective_date, url}], limitations[]} | null,
            evidence: {floor_height_m, datum_measured, frontage_grade, legal_floor_section_count},
            sources: [{title, date}], findings: [{finding, recommended_action, missing_evidence[]}],
            truncated} | null
  review:  {status, code, missing_evidence[], actions: [{finding, raised_by, category,
            recommended_action, recommended_agents[], evidence}]} | null
  missing_evidence_all: [str]   notes: [str]   raw: {communications, keys: {tool: n}}
"""
import json
import re

SITE_TOOL, LAW_TOOL, REVIEW_TOOL = 'site_resolve', 'law_parcel_limits', 'revision_triage'
_FACTS = re.compile(r'(\d+)\s*/\s*(\d+)\s*site facts')
_MAX_REPAIR_ATTEMPTS = 400


def loads_tolerant(text):
    """JSON of `text`; a text cut mid-way is closed at its last complete value. None when unreadable."""
    if not isinstance(text, str) or not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return _close_truncated(text)


def _close_truncated(text):
    stack, cuts, in_string, escaped = [], [], False, False
    for index, char in enumerate(text):
        if in_string:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if stack:
                stack.pop()
        elif char == ',':
            cuts.append((index, ''.join(stack)))
    for index, open_brackets in reversed(cuts[-_MAX_REPAIR_ATTEMPTS:]):
        closers = ''.join('}' if char == '{' else ']' for char in reversed(open_brackets))
        try:
            return json.loads(text[:index] + closers)
        except ValueError:
            continue
    return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) and value else None


def _num(value):
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _int(value):
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _strings(value):
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


def _unique(items):
    seen, out = set(), []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _communications(run):
    rows = run.get('communications') if isinstance(run, dict) else None
    return [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []


def _first(rows, tool):
    return next((row for row in rows if row.get('tool') == tool), None)


def request_pnu(run):
    """The parcel a run was asked about: `site_resolve`'s request, else any request naming a `pnu`."""
    rows = _communications(run)
    for row in [_first(rows, SITE_TOOL)] + rows:
        pnu = _str(_dict(loads_tolerant(_dict(row).get('request_text'))).get('pnu'))
        if pnu:
            return pnu
    return None


def _request(rows, law_findings, ordinance):
    site_request = _dict(loads_tolerant(_dict(_first(rows, SITE_TOOL)).get('request_text')))
    law_request = _dict(loads_tolerant(_dict(_first(rows, LAW_TOOL)).get('request_text')))
    pnu = _str(site_request.get('pnu')) or _str(law_request.get('pnu'))
    if not pnu and not law_request:
        return None
    assessment_date = _str(_dict(ordinance).get('assessment_date'))
    for finding in law_findings:
        assessment_date = assessment_date or _str(finding.get('assessment_date'))
    return {'pnu': pnu, 'parcels': _strings(site_request.get('parcels')) or ([pnu] if pnu else []),
            'building_type': _str(law_request.get('building_type')), 'assessment_date': assessment_date}


def _step(row, response):
    summary = _str(response.get('summary')) or _str(response.get('error')) or _str(response.get('code'))
    return {'task_id': _str(row.get('task_id')), 'agent': _str(row.get('agent')), 'tool': _str(row.get('tool')),
            'state': _str(row.get('state')) or 'unknown', 'summary': summary, 'truncated': row.get('truncated') is True}


def _fact_summary(key, value):
    """One short line per site fact the Site Agent stores (`sitecontextagent/facts.py` SITE_KEYS)."""
    value = _dict(value)
    if key == 'site.boundary':
        area = _num(value.get('area_m2'))
        return f'면적 {area:,.2f}㎡' if area is not None else None
    if key == 'site.roads':
        roads = [_dict(f).get('properties') for f in value.get('centrelines') or [] if isinstance(f, dict)]
        widths = _unique(f'{_num(_dict(p).get("width_m")):g}m' for p in roads if _num(_dict(p).get('width_m')) is not None)
        return f'접도 {len(roads)}건' + (f' · 폭 {", ".join(widths)}' if widths else '') if roads else None
    if key == 'site.north':
        bearing = _num(value.get('true_north_deg')) if _num(value.get('true_north_deg')) is not None else _num(value.get('bearing_deg'))
        return f'진북 {bearing:g}°' if bearing is not None else None
    if key == 'site.terrain':
        levels = [_num(v) for v in (value.get('min_m'), value.get('max_m')) if _num(v) is not None]
        return f'표고 {levels[0]:g}~{levels[1]:g} m' if len(levels) == 2 else None
    return None


def _site_facts(response):
    """The facts readable in `state_patch` (a cut response keeps the first ones): key, confidence, provenance, summary."""
    facts = []
    for key, fact in _dict(response.get('state_patch')).items():
        if not isinstance(key, str) or not key.startswith('site.') or not isinstance(fact, dict):
            continue
        facts.append({'key': key, 'confidence': _str(fact.get('confidence')), 'source': _str(fact.get('source')),
                      'as_of': _str(fact.get('as_of')), 'summary': _fact_summary(key, fact.get('value'))})
    return facts


def _site(row, response, rationale):
    if row is None:
        return None
    match = _FACTS.search(_str(response.get('summary')) or '')
    missing = [item['finding'] for item in rationale
               if item['raised_by'] == 'site_context' and item['category'] == 'site_fact_missing' and item['finding']]
    missing += _strings(response.get('missing')) + _strings(response.get('missing_facts'))
    return {'status': _str(response.get('status')) or _str(row.get('state')) or 'unknown', 'code': _str(response.get('code')),
            'facts_known': int(match.group(1)) if match else None, 'facts_total': int(match.group(2)) if match else None,
            'facts_missing': _unique(missing), 'facts': _site_facts(response)}


def _ordinance(response):
    receipt = response.get('ordinance')
    if not isinstance(receipt, dict):
        return None
    coverage = _dict(receipt.get('municipal_coverage'))
    sources = [_dict(s) for s in coverage.get('sources') or [] if isinstance(s, dict)]
    first = sources[0] if sources else {}
    return {'articles': [a for a in (receipt.get('bcr_article'), receipt.get('far_article'), receipt.get('height_article')) if _str(a)],
            'edition_id': _str(first.get('edition_id')) or _str(first.get('edition')) or _str(first.get('name')),
            'effective_date': _str(first.get('effective_date')), 'assessment_date': _str(receipt.get('assessment_date')),
            'sources': [{'name': _str(s.get('name')), 'ordinance_id': _str(s.get('ordinance_id')), 'edition_id': _str(s.get('edition_id')),
                         'effective_date': _str(s.get('effective_date')), 'url': _str(s.get('url'))} for s in sources],
            'limitations': _strings(coverage.get('limitations'))}


def _law(row, response, rationale, notes):
    if row is None:
        return None
    policy = _dict(response.get('policy'))
    ordinance = _ordinance(response)
    if ordinance is None and row.get('truncated') is True:
        notes.append('law_response_truncated: the ordinance receipt was cut off by the 8000-character communication cap')
    findings = [{'finding': item['finding'], 'recommended_action': item['recommended_action'],
                 'missing_evidence': _strings(_dict(item['evidence']).get('missing_evidence')),
                 'assessment_date': _str(_dict(item['evidence']).get('assessment_date'))}
                for item in rationale if item['raised_by'] == 'law']
    receipt = _dict(response.get('ordinance'))
    evidence = _dict(response.get('evidence'))
    return {'status': _str(row.get('state')) or 'unknown',
            'site_area_m2': _num(response.get('parcel_area_m2')), 'bcr_pct': _num(response.get('bcr_pct')),
            'far_pct': _num(response.get('far_pct')), 'max_floors': _int(response.get('max_storeys')) or _int(policy.get('max_storeys')),
            'ground_capacity_m2': _num(response.get('ground_capacity_m2')), 'far_capacity_m2': _num(response.get('far_capacity_m2')),
            'zones': _strings(response.get('zones')),
            'national_bcr_ceiling_pct': _num(receipt.get('national_bcr_ceiling_pct')),
            'national_far_ceiling_pct': _num(receipt.get('national_far_ceiling_pct')),
            'articles': {'bcr': _str(receipt.get('bcr_article')), 'far': _str(receipt.get('far_article')), 'height': _str(receipt.get('height_article'))},
            'height': {'status': _str(receipt.get('height_status')), 'limit_m': _num(receipt.get('height_limit_m'))},
            'policy_id': _str(policy.get('policy_id')), 'parcel_label': _str(policy.get('parcel_label')),
            'building_type': _str(response.get('building_type')), 'ordinance': ordinance,
            'evidence': {'floor_height_m': _num(evidence.get('floor_height_m')),
                         'datum_measured': evidence.get('datum_measured') if isinstance(evidence.get('datum_measured'), bool) else None,
                         'frontage_grade': _str(_dict(evidence.get('authoring_frontage')).get('evidence_grade')),
                         'legal_floor_section_count': _int(evidence.get('legal_floor_section_count'))},
            'sources': [{'title': _str(_dict(s).get('title')), 'date': _str(_dict(s).get('date'))}
                        for s in policy.get('sources') or [] if isinstance(s, dict)],
            'findings': findings, 'truncated': row.get('truncated') is True}


def _rationale(response):
    out = []
    for item in response.get('rationale') or []:
        item = _dict(item)
        out.append({'finding': _str(item.get('finding')), 'raised_by': _str(item.get('raised_by')),
                    'category': _str(item.get('category')), 'recommended_action': _str(item.get('recommended_action')),
                    'recommended_agents': _strings(item.get('recommended_agents')),
                    'evidence': item.get('evidence') if isinstance(item.get('evidence'), (list, dict)) else None})
    return out


def _review(row, response, rationale):
    if row is None:
        return None
    return {'status': _str(response.get('status')) or _str(row.get('state')) or 'unknown', 'code': _str(response.get('code')),
            'missing_evidence': _strings(response.get('missing_evidence')), 'actions': rationale}


def parse_run_results(run):
    """Never raises: a run that is not a dict reads as an empty result with status 'unknown'."""
    run = _dict(run)
    rows = _communications(run)
    responses = {id(row): _dict(loads_tolerant(row.get('response_text'))) for row in rows}
    site_row, law_row, review_row = (_first(rows, tool) for tool in (SITE_TOOL, LAW_TOOL, REVIEW_TOOL))
    rationale = _rationale(responses.get(id(review_row), {}))
    notes = []
    law = _law(law_row, responses.get(id(law_row), {}), rationale, notes)
    site = _site(site_row, responses.get(id(site_row), {}), rationale)
    review = _review(review_row, responses.get(id(review_row), {}), rationale)
    law_missing = [code for finding in (law or {}).get('findings', []) for code in finding['missing_evidence']]
    return {
        'run_id': _str(run.get('run_id')), 'status': _str(run.get('status')) or 'unknown', 'goal': _str(run.get('goal')),
        'pending_input': run.get('pending_input') is True,
        'truncated': any(row.get('truncated') is True for row in rows) or run.get('communications_truncated') is True,
        'request': _request(rows, (law or {}).get('findings', []), (law or {}).get('ordinance')),
        'steps': [_step(row, responses[id(row)]) for row in rows],
        'site': site, 'law': law, 'review': review,
        'missing_evidence_all': _unique((site or {}).get('facts_missing', []) + law_missing + (review or {}).get('missing_evidence', [])),
        'notes': notes,
        'raw': {'communications': len(rows), 'keys': {row.get('tool'): len(responses[id(row)]) for row in rows if _str(row.get('tool'))}},
    }
