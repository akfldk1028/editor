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
from backend.app.modules.platform.run_results.agents import law, review, site
from backend.app.modules.platform.run_results.common import _dict, _str, _strings, _unique, loads_tolerant

SITE_TOOL, LAW_TOOL, REVIEW_TOOL = site.TOOL, law.TOOL, review.TOOL
law_from_response = law.law_from_response


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


def parse_run_results(run):
    """Never raises: a run that is not a dict reads as an empty result with status 'unknown'."""
    run = _dict(run)
    rows = _communications(run)
    responses = {id(row): _dict(loads_tolerant(row.get('response_text'))) for row in rows}
    site_row, law_row, review_row = (_first(rows, tool) for tool in (SITE_TOOL, LAW_TOOL, REVIEW_TOOL))
    rationale = review.parse_rationale(responses.get(id(review_row), {}))
    notes = []
    law_result = law.parse(law_row, responses.get(id(law_row), {}), rationale, notes)
    site_result = site.parse(site_row, responses.get(id(site_row), {}), rationale)
    review_result = review.parse(review_row, responses.get(id(review_row), {}), rationale)
    law_missing = [code for finding in (law_result or {}).get('findings', []) for code in finding['missing_evidence']]
    return {
        'run_id': _str(run.get('run_id')), 'status': _str(run.get('status')) or 'unknown', 'goal': _str(run.get('goal')),
        'pending_input': run.get('pending_input') is True,
        # What the run asks the person for (the door's `pending_fields`, e.g. building_type), empty when nothing.
        'pending_fields': [field for field in (run.get('pending_fields') or []) if isinstance(field, str)],
        'truncated': any(row.get('truncated') is True for row in rows) or run.get('communications_truncated') is True,
        'request': _request(rows, (law_result or {}).get('findings', []), (law_result or {}).get('ordinance')),
        'steps': [_step(row, responses[id(row)]) for row in rows],
        'site': site_result, 'law': law_result, 'review': review_result,
        'missing_evidence_all': _unique((site_result or {}).get('facts_missing', []) + law_missing + (review_result or {}).get('missing_evidence', [])),
        'notes': notes,
        'raw': {'communications': len(rows), 'keys': {row.get('tool'): len(responses[id(row)]) for row in rows if _str(row.get('tool'))}},
    }

