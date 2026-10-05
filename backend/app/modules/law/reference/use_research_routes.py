"""Evidence-indexed research candidates, never executable compliance findings.

Operational recipes suggest possible legal families. They do not establish the
building's statutory classification. Unresearched domains remain visible.
"""

from backend.app.modules.design.generation import paths as _design_paths
import json
from pathlib import Path


SOURCE_PATH = _design_paths.package_root('law') / 'data/use_research_sources.json'
_EXPECTED_IDS = {str(n) for n in range(1, 30)} | {'23의2'}


def get_use_research_routes(family_id='', operational_type=''):
    """Return explicit candidate routes; unknown selectors produce visible gaps.

    Supplying both selectors combines their candidates without treating their
    agreement as classification evidence. Empty selectors return the full index.
    """
    if not isinstance(family_id, str) or not isinstance(operational_type, str):
        raise ValueError('family_id and operational_type must be strings')
    data = json.loads(SOURCE_PATH.read_text(encoding='utf-8'))
    # Reuse the current source owner; don't leave the research index pointing at
    # the superseded March edition after the July Annex 4 was ingested.
    if 'fire' in data['sources']:
        from backend.app.modules.law.reference.fire_requirements import _source
        source = _source()
        when = source['selected_effective_date']
        data['sources']['fire'].update(
            url=source['annex_pdf_url'], effective_date=f'{when[:4]}-{when[4:6]}-{when[6:8]}',
            current_edition_verified=True, verification_status='pinned_current_annex_4',
            verification_note='Current Annex 4 is pinned and six installation triggers are implemented separately. Other fire criteria still need compilation.',
            source_snapshot='law/data/facility_sources/fire_annex_4.json')
    if set(data['families']) != _EXPECTED_IDS:
        raise ValueError('Research route index must cover all 30 statutory families')
    for record in [*data['families'].values(), *data['operational_types'].values()]:
        if set(record['source_ids']) - data['sources'].keys():
            raise ValueError('Research route references an unknown source')
    family_id = family_id.strip().replace('23-2', '23의2')
    operation_key = operational_type.strip().casefold()
    aliases = {alias.casefold(): key
               for key, record in data['operational_types'].items()
               for alias in [key, record['name'], *record['aliases']]}
    operation_key = aliases.get(operation_key, operation_key)
    all_requested = not family_id and not operational_type.strip()
    issues = []
    family_ids = []
    operation_ids = []
    if all_requested:
        family_ids = list(data['families'])
        operation_ids = list(data['operational_types'])
    else:
        if family_id:
            if family_id in data['families']:
                family_ids.append(family_id)
            else:
                issues.append({'kind': 'unknown_family', 'value': family_id})
        if operational_type.strip():
            if operation_key in data['operational_types']:
                operation_ids.append(operation_key)
                family_ids.extend(data['operational_types'][operation_key]['candidate_family_ids'])
            else:
                issues.append({'kind': 'unresearched_operational_type', 'value': operational_type})
    family_ids = list(dict.fromkeys(family_ids))
    routes = []
    source_ids = []

    def add_route(route_id, record, kind):
        ids = list(dict.fromkeys(data['baseline_source_ids'] + record['source_ids']))
        source_ids.extend(ids)
        unresolved = list(record['unresolved_domains'])
        unresolved.extend(['site_zoning_and_local_ordinances', 'structural_energy_and_project_specific_requirements'])
        routes.append({
            'route_id': route_id, 'route_kind': kind,
            'status': 'candidate_requires_applicability_review',
            'applicability': 'not_evaluated', 'actual_check_count': 0,
            'source_ids': ids, 'unresolved_domains': list(dict.fromkeys(unresolved)),
            'required_inputs': sorted({'project_date', 'municipality', 'legal_subtype', 'mixed_uses'} |
                                      {item for key in ids for item in data['sources'][key]['required_inputs']}),
        })

    for key in family_ids:
        add_route('family:' + key, data['families'][key], 'statutory_family_candidate')
    for key in operation_ids:
        record = data['operational_types'][key]
        add_route('operation:' + key, record, 'operational_candidate')
        routes[-1]['candidate_family_ids'] = record['candidate_family_ids']
    sources = {key: data['sources'][key] for key in dict.fromkeys(source_ids)}
    return {
        'schema_version': data['schema_version'], 'verified_as_of': data['verified_as_of'],
        'purpose': data['purpose'], 'family_id': family_id, 'operational_type': operation_key,
        'status': 'unresolved_selector' if issues else 'research_candidates_only',
        'issues': issues, 'routes': routes, 'sources': sources,
        'required_inputs': sorted({item for route in routes for item in route['required_inputs']}),
        'rule_suggestions': [r for r in data['rule_suggestions'] if r['source_id'] in sources],
        'papers': data['papers'],
        'coverage': {
            'statutory_family_count': len(data['families']),
            'registered_operational_route_count': len(data['operational_types']),
            'matched_family_count': len(family_ids), 'matched_operational_type_count': len(operation_ids),
            'candidate_route_count': len(routes), 'source_count': len(sources),
            'current_edition_verified_source_count': sum(s['current_edition_verified'] for s in sources.values()),
            'sources_requiring_refresh_count': sum(not s['current_edition_verified'] for s in sources.values()),
            'unresolved_domain_count': len({d for route in routes for d in route['unresolved_domains']}),
            'actual_check_count': 0, 'legal_compliance_coverage': 'not_claimed',
        },
    }
