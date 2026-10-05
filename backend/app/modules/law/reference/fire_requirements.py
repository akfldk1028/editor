"""Six source-bound equipment triggers from fire decree Annex 4.

This determines individual installation requirements, not installation compliance.
Caller-confirmed classification, statutory measurements, edition applicability and
exception review are project facts; absent facts are never inferred from use names.
"""

from backend.app.modules.design.generation import paths as _design_paths
from datetime import date
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path
import re

SOURCE_PATH = _design_paths.package_root('law') / 'data/facility_sources/fire_annex_4.json'
SOURCE_HASH = '4d0433e5945fe91f75adda4cf0c8d51557d63dc87d60d6acd5e0f916ee61bbc3'
EDITION = '287375'
GROSS_BASIS = 'building_decree_119_1_4_gross_floor_area'
FLOOR_BASIS = 'building_decree_119_1_3_floor_area'
ROOF_BASIS = 'fire_annex_4_1_c_3_rooftop_garage_parking_used_area'
RULES = (
    ('extinguisher_area', '소화기구', '별표4 제1호가목1)', 'whole_specific_fire_object'),
    ('residential_kitchen', '주거용 주방자동소화장치', '별표4 제1호나목1)', 'qualifying_kitchen'),
    ('commercial_kitchen', '상업용 주방자동소화장치', '별표4 제1호나목2)', 'qualifying_kitchen'),
    ('hydrant_gross_area', '옥내소화전설비', '별표4 제1호다목1)가)', 'all_floors'),
    ('hydrant_floor_area', '옥내소화전설비', '별표4 제1호다목1)나)·다)', 'all_floors'),
    ('hydrant_rooftop_parking', '옥내소화전설비', '별표4 제1호다목3)', 'qualifying_rooftop_parking_part'),
)
SUBTYPES = {'apartment_etc', 'officetel', 'gas_facility', 'underground_utility',
            'unmanned_substation', 'tunnel', 'barn', 'other_confirmed'}


def _source():
    d = json.loads(SOURCE_PATH.read_text(encoding='utf-8'))
    actual = hashlib.sha256(d['annex_text'].encode('utf-8')).hexdigest()
    if (actual != SOURCE_HASH or d['annex_text_sha256'] != actual
            or d['selected_mst'] != EDITION or d['selected_effective_date'] != '20260701'
            or d.get('selection_as_of') != '2026-09-13' or d.get('source_edition_confirmed') is not True):
        raise ValueError('Pinned fire source failed integrity or edition validation')
    return d


def _number(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() and result >= 0 else None


def _measure(facts, key, basis, missing):
    record = facts.get(key)
    if not isinstance(record, dict) or record.get('unit') != 'm2' or record.get('basis') != basis:
        missing.append(key + ': value, unit=m2, basis=' + basis)
        return None
    value = _number(record.get('value'))
    if value is None:
        missing.append(key + '.value: finite nonnegative number')
    return value


def _boolean(facts, key, missing):
    value = facts.get(key)
    if type(value) is not bool:
        missing.append(key + ': explicit boolean')
        return None
    return value


def _excerpt(text, start, end):
    return text[text.index(start):text.index(end)]


def _bind_project_evidence(facts, finding, assessment_date):
    """Retain calculation but withhold determinate findings without fact provenance.

    References identify project documents; their contents are not validated here.
    A source reference cannot substitute for a missing or wrongly typed fact.
    """
    if finding['status'] not in ('required', 'not_required_by_this_rule'):
        return
    rule_id = finding['rule_id']
    paths = ['governing_edition', 'specific_fire_object', 'classification_basis',
             'fire_subtype', 'nuclear_reactor_related_facility', 'mixed_use_scope_reviewed',
             'exception_review.' + rule_id]
    measurements = []
    # Exemptions and express exclusions resolve before predicate measurements.
    early = finding['reason'] in (
        'Project-confirmed exemption; no conclusion about other rules',
        'Express exclusion in Annex 4 1(c)',
        'Express remote-control unmanned-substation exclusion',
    )
    if (rule_id.startswith('hydrant') and facts.get('fire_subtype') == 'unmanned_substation'
            and facts['exception_review'][rule_id] != 'exempt'):
        paths.append('substation_remote_sprinkler_or_water_spray_control')
    if not early:
        if rule_id == 'extinguisher_area' or (rule_id == 'hydrant_gross_area' and facts['fire_subtype'] != 'tunnel'):
            measurements.append(('gross_floor_area', facts.get('gross_floor_area')))
        elif 'kitchen' in rule_id:
            paths.extend(['kitchen_has_hood', 'kitchen_has_duct'])
            if rule_id == 'commercial_kitchen':
                paths.extend(['general_restaurant_in_statutory_large_store', 'collective_food_service_under_food_act'])
        elif rule_id == 'hydrant_rooftop_parking':
            paths.append('has_rooftop_garage_or_parking')
            measurements.append(('rooftop_parking_used_area', facts.get('rooftop_parking_used_area')))
        elif rule_id == 'hydrant_floor_area':
            paths.extend('qualifying_floor.' + key for key in
                         ('floor_id', 'is_basement', 'is_windowless', 'floor_number', 'is_barn'))
            measurements.append(('qualifying_floor.floor_area', facts['qualifying_floor'].get('floor_area')))
    supplied = facts.get('fact_evidence')
    supplied = supplied if isinstance(supplied, dict) else {}
    references = {}
    consumed = {}
    missing = []

    def reference(path, record):
        ref = record.get('source_ref') if isinstance(record, dict) else None
        if not isinstance(ref, str) or not ref.strip():
            missing.append(path + '.source_ref')
        else:
            references[path] = ref
        if not isinstance(record, dict) or record.get('assessment_date') != assessment_date:
            missing.append(path + '.assessment_date: must match evaluation date')
        consumed[path] = deepcopy(record)

    for path in paths:
        reference('fact_evidence.' + path, supplied.get(path))
    for path, record in measurements:
        reference(path, record)
    if facts['exception_review'][rule_id] == 'exempt':
        proof = supplied.get('exception_review.' + rule_id, {})
        proof = proof if isinstance(proof, dict) else {}
        if proof.get('rule_id') != rule_id:
            missing.append('fact_evidence.exception_review.' + rule_id + '.rule_id: exact reviewed rule')
        if not isinstance(proof.get('legal_basis'), str) or not proof['legal_basis'].strip():
            missing.append('fact_evidence.exception_review.' + rule_id + '.legal_basis: specific legal provision or approval')
        if proof.get('exemption_basis_type') not in ('rule_specific_statutory_exemption', 'specific_authority_approval'):
            missing.append('fact_evidence.exception_review.' + rule_id + '.exemption_basis_type: rule-specific basis required')
        # Annex 5 expressly excludes kitchen devices from the automatic-device
        # substitution exemption. This engine has no other compiled kitchen
        # exemption, so a general statutory exemption assertion cannot clear it.
        if 'kitchen' in rule_id and proof.get('exemption_basis_type') != 'specific_authority_approval':
            missing.append('Kitchen exemption requires specific authority approval; generic Annex 5 substitution is excluded')
    values = {}
    for path in paths:
        value = facts
        for part in path.split('.'):
            value = value.get(part) if isinstance(value, dict) else None
        values[path] = deepcopy(value)
    finding['project_evidence_refs'] = references
    finding['consumed_input_values'] = values
    finding['consumed_evidence_records'] = consumed
    finding['input_sha256'] = hashlib.sha256(json.dumps(
        {'assessment_date': assessment_date, 'values': values, 'evidence': consumed},
        ensure_ascii=False, sort_keys=True, separators=(',', ':'), default=str).encode('utf-8')).hexdigest()
    finding['project_evidence_verification'] = 'references_provided_content_not_validated'
    if missing:
        finding['conditional_predicate_result'] = finding['status']
        finding['conditional_reason'] = finding['reason']
        finding.update(status='needs_evidence', reason='Project fact or measurement evidence references are missing',
                       missing_evidence=missing)


def evaluate_fire_requirements(facts: dict, assessment_date: str) -> dict:
    """Evaluate six bounded triggers using a fully explicit project fact contract.

    Common required facts: governing_edition='287375', specific_fire_object=True,
    classification_basis='fire_decree_annex_2', fire_subtype from SUBTYPES,
    nuclear_reactor_related_facility=False, mixed_use_scope_reviewed=True, and
    exception_review[rule_id]='none' or 'exempt'. The last record requires a
    project review of retroactivity, Annex 5 exemptions and alternative approvals;
    it is not a fact the engine derives from Annex 4 alone.

    Every decision-driving fact needs fact_evidence[field_path]={source_ref:...,
    assessment_date:...},
    including exception_review.<rule_id>. Areas are {value, unit:'m2', basis:...,
    source_ref:..., assessment_date:...}. Evidence review dates must match the
    evaluation date. An exempt assertion additionally needs rule_id, legal_basis,
    and exemption_basis_type. Kitchen exceptions require specific authority
    approval, because generic Annex 5 substitution excludes those devices.
    Missing references preserve only a conditional predicate.
    qualifying_floor is one identified
    floor with floor_id, floor_area, is_basement, is_windowless, floor_number,
    is_barn. A negative result covers that supplied floor only.
    """
    if not isinstance(facts, dict):
        raise ValueError('facts must be a dictionary')
    try:
        day = date.fromisoformat(assessment_date)
    except (TypeError, ValueError):
        raise ValueError('assessment_date must be an ISO date') from None
    findings = []
    result = {'assessment_date': assessment_date, 'purpose': 'individual_equipment_requirement_triggers',
              'findings': findings, 'global_compliance': 'not_evaluated',
              'coverage': {'implemented_trigger_count': len(RULES), 'all_fire_requirements_covered': False},
              'limitations': ['Equipment presence, design, quantities, performance and installation are not certified.',
                              'Other Annex 4 triggers remain applicable candidates even when a supplied predicate is false.',
                              'Project edition, mixed-use scope and exemptions require independent review.']}
    try:
        source = _source()
        text = source['annex_text']
        excerpts = {'extinguisher': _excerpt(text, '가. 화재안전기준', '나. 자동소화장치'),
                    'kitchen': _excerpt(text, '나. 자동소화장치', '다. 옥내소화전설비'),
                    'hydrant': _excerpt(text, '다. 옥내소화전설비', '라. 스프링클러설비')}
        compact = {k: re.sub(r'\s+', '', v) for k, v in excerpts.items()}
        threshold_ext = Decimal(re.search(r'연면적(\d+)㎡이상', compact['extinguisher']).group(1))
        threshold_gross = Decimal(re.search(r'연면적(\d+)천㎡이상', compact['hydrant']).group(1)) * 1000
        threshold_floor = Decimal(re.search(r'바닥면적이(\d+)㎡이상', compact['hydrant']).group(1))
        threshold_roof = Decimal(re.search(r'사용되는면적이(\d+)㎡이상', compact['hydrant']).group(1))
        result['source'] = {k: source[k] for k in ('source_id', 'source_url', 'annex_pdf_url', 'selected_mst',
                                                 'selected_effective_date', 'annex_revision_date', 'annex_text_sha256')}
        evidence_error = None
    except (OSError, ValueError, KeyError, AttributeError):
        source, excerpts = None, {}
        evidence_error = 'Current pinned source text or bound threshold could not be verified'
    for rule_id, equipment, locator, scope in RULES:
        family = 'extinguisher' if rule_id.startswith('extinguisher') else 'kitchen' if 'kitchen' in rule_id else 'hydrant'
        finding = {'rule_id': rule_id, 'equipment': equipment, 'locator': locator, 'required_scope': scope,
                   'status': 'needs_input', 'missing_inputs': [], 'evidence_text': excerpts.get(family, ''),
                   'source_sha256': SOURCE_HASH, 'assumptions': []}
        findings.append(finding)
        if evidence_error or not (date(2026, 7, 1) <= day <= date(2026, 9, 13)):
            finding.update(status='needs_evidence', reason=evidence_error or 'Assessment date outside verified edition interval')
            continue
        missing = finding['missing_inputs']
        if facts.get('governing_edition') != EDITION:
            missing.append('governing_edition: project-confirmed ' + EDITION)
        nuclear = _boolean(facts, 'nuclear_reactor_related_facility', missing)
        if nuclear is True:
            finding.update(status='needs_evidence', reason='Annex 4 note 2 routes reactor and related facilities to nuclear permit criteria')
            continue
        if facts.get('specific_fire_object') is not True:
            missing.append('specific_fire_object: confirmed true under Annex 2')
        if facts.get('classification_basis') != 'fire_decree_annex_2':
            missing.append('classification_basis: fire_decree_annex_2')
        subtype = facts.get('fire_subtype')
        if subtype not in SUBTYPES:
            missing.append('fire_subtype: confirmed supported Annex 2 subtype')
        if facts.get('mixed_use_scope_reviewed') is not True:
            missing.append('mixed_use_scope_reviewed: true (Annex 4 note 1)')
        reviews = facts.get('exception_review')
        exemption = reviews.get(rule_id) if isinstance(reviews, dict) else None
        if exemption not in ('none', 'exempt'):
            missing.append('exception_review.' + rule_id + ': none or exempt after independent review')
        if missing:
            continue
        finding['assumptions'] = ['Project supplied and confirmed legal classification, governing edition and exception review.']
        if exemption == 'exempt':
            finding.update(status='not_required_by_this_rule', reason='Project-confirmed exemption; no conclusion about other rules')
            continue
        if family == 'hydrant':
            if subtype in ('gas_facility', 'underground_utility'):
                finding.update(status='not_required_by_this_rule', reason='Express exclusion in Annex 4 1(c)')
                continue
            if subtype == 'unmanned_substation':
                remote = _boolean(facts, 'substation_remote_sprinkler_or_water_spray_control', missing)
                if remote is True:
                    finding.update(status='not_required_by_this_rule', reason='Express remote-control unmanned-substation exclusion')
                    continue
                if remote is None:
                    continue
        trigger = None
        if rule_id == 'extinguisher_area':
            area = _measure(facts, 'gross_floor_area', GROSS_BASIS, missing)
            if area is not None:
                trigger = area >= threshold_ext
                finding['comparison'] = {'actual': str(area), 'operator': '>=', 'threshold': str(threshold_ext), 'unit': 'm2'}
        elif 'kitchen' in rule_id:
            hood = _boolean(facts, 'kitchen_has_hood', missing)
            duct = _boolean(facts, 'kitchen_has_duct', missing)
            if rule_id == 'residential_kitchen':
                use = subtype in ('apartment_etc', 'officetel')
            else:
                restaurant = _boolean(facts, 'general_restaurant_in_statutory_large_store', missing)
                collective = _boolean(facts, 'collective_food_service_under_food_act', missing)
                use = restaurant or collective
            if not missing:
                trigger = hood and duct and use
        elif rule_id == 'hydrant_gross_area':
            if subtype == 'tunnel':
                trigger = False
            else:
                area = _measure(facts, 'gross_floor_area', GROSS_BASIS, missing)
                if area is not None:
                    trigger = area >= threshold_gross
                    finding['comparison'] = {'actual': str(area), 'operator': '>=', 'threshold': str(threshold_gross), 'unit': 'm2'}
        elif rule_id == 'hydrant_rooftop_parking':
            rooftop = _boolean(facts, 'has_rooftop_garage_or_parking', missing)
            area = _measure(facts, 'rooftop_parking_used_area', ROOF_BASIS, missing)
            if not missing:
                trigger = rooftop and area >= threshold_roof
                finding['comparison'] = {'actual': str(area), 'operator': '>=', 'threshold': str(threshold_roof), 'unit': 'm2'}
        elif rule_id == 'hydrant_floor_area':
            floor = facts.get('qualifying_floor')
            if not isinstance(floor, dict):
                missing.append('qualifying_floor: identified floor and statutory area facts')
                continue
            if not isinstance(floor.get('floor_id'), str) or not floor['floor_id'].strip():
                missing.append('qualifying_floor.floor_id')
            area = _measure(floor, 'floor_area', FLOOR_BASIS, missing)
            basement = _boolean(floor, 'is_basement', missing)
            windowless = _boolean(floor, 'is_windowless', missing)
            barn = _boolean(floor, 'is_barn', missing)
            floor_number = _number(floor.get('floor_number'))
            if floor_number is None or floor_number != floor_number.to_integral():
                missing.append('qualifying_floor.floor_number: nonnegative statutory floor ordinal')
            if not missing:
                trigger = area >= threshold_floor and (((basement or windowless) and not barn) or (not basement and floor_number >= 4))
                finding['evaluated_floor_id'] = floor['floor_id']
                finding['comparison'] = {'actual': str(area), 'operator': '>=', 'threshold': str(threshold_floor), 'unit': 'm2'}
                finding['negative_scope'] = 'Only this identified floor; other floors and other hydrant clauses are not cleared.'
        if missing or trigger is None:
            continue
        finding['status'] = 'required' if trigger else 'not_required_by_this_rule'
        finding['reason'] = 'Source-bound predicate satisfied' if trigger else 'This predicate is not satisfied; other legal triggers are not cleared'
    for finding in findings:
        _bind_project_evidence(facts, finding, assessment_date)
    result['coverage']['required_count'] = sum(f['status'] == 'required' for f in findings)
    result['coverage']['unresolved_count'] = sum(f['status'] in ('needs_input', 'needs_evidence') for f in findings)
    return result
