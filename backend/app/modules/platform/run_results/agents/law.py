"""The Law Agent's answer (`law_parcel_limits`), read into the contract's `law` shape — the ordinance receipt
(articles, edition, law.go.kr source, limitations), the caps and capacities, Law's premises; district findings from
Revision's rationale."""
from backend.app.modules.platform.run_results.common import _dict, _int, _num, _str, _strings

TOOL = 'law_parcel_limits'
AGENT = 'law'


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


def parse(row, response, rationale, notes):
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
            # Why the Orchestrator did not adopt Law's caps (its check of the answer against Site's zoning reading), when it did not.
            'code': _str(row.get('code')),
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
            'findings': findings, 'truncated': row.get('truncated') is True,
            # Where the caps came from (ordinance | district_plan), and whether the parcel sits in a 지구단위계획구역 whose lot
            # rules were not applied: then these are ordinance ceilings and the lot's own values come from the district review.
            'limits_from': _str(response.get('limits_from')),
            'district_plan_applied': response.get('district_plan_applied') is True,
            'district_plan_review_needed': response.get('district_plan_review_needed') is True,
            'disclosures': _strings(response.get('disclosures')),
            'missing_evidence': _strings(response.get('missing_evidence')),
            # The 용도지역 split behind the caps: excluded boundary strips, disclosed (null for a single zone).
            'zone_split': _dict(response.get('zone_split')) or None}


def law_from_response(payload, *, truncated=False):
    """The `law` shape of the contract from one `law_parcel_limits` answer (the Law Agent asked directly)."""
    return parse({'state': 'succeeded', 'truncated': truncated}, _dict(payload), [], [])

