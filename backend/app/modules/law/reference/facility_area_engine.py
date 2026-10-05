"""Evidence-aware area arithmetic for explicitly supplied, sourced rules.

This module contains no legal coefficients and makes no whole-building or permit
decision. Callers must supply rules and confirm their edition for the assessment
date. Date intervals include both endpoints. Values are never inferred from an
unlabelled measurement or a different area basis.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, localcontext
import math


def _number(value):
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and _finite(value) and value >= 0)


def _finite(value):
    try:
        return math.isfinite(value)
    except (OverflowError, TypeError, ValueError):
        return False


def _count(value):
    return _number(value) and (isinstance(value, int) or value.is_integer())


def _date(value):
    if not isinstance(value, str) or len(value) != 10:
        return None
    try:
        parsed = date.fromisoformat(value)
        return parsed if parsed.isoformat() == value else None
    except ValueError:
        return None


def _mapping(value):
    return value if isinstance(value, dict) else {}


def _text(value):
    return isinstance(value, str) and bool(value.strip())


def _evaluate(facts, rule, assessment_date):
    rule = _mapping(rule)
    rule_id = rule.get('rule_id')
    result = {
        'rule_id': rule_id, 'status': 'needs_evidence',
        'reason_codes': [], 'source': deepcopy(rule.get('source')),
        'area_basis': rule.get('area_basis'),
        'quantity_fact': rule.get('quantity_fact'), 'area_fact': rule.get('area_fact'),
        'required_area_m2': None, 'provided_area_m2': None,
        'conditional_area_comparison': None,
        'effective_from': rule.get('effective_from'),
        'effective_to': rule.get('effective_to'),
        'source_edition_evidence': deepcopy(
            _mapping(facts.get('source_edition_evidence')).get(rule_id)
            if _text(rule_id) else None),
    }

    def finish(status, *reasons):
        result['status'] = status
        result['reason_codes'].extend(reasons)
        return result

    types = rule.get('facility_types')
    if not isinstance(types, list) or not types or not all(_text(t) for t in types):
        return finish('needs_evidence', 'invalid_rule_facility_types')
    facility_type = facts.get('facility_type')
    if not _text(facility_type):
        return finish('needs_input', 'missing_facility_type')
    if facility_type not in types:
        return finish('not_applicable', 'facility_type_mismatch')

    required = rule.get('required_conditions')
    if not isinstance(required, dict) or any(
            not _text(k) or not isinstance(v, (bool, str)) for k, v in required.items()):
        return finish('needs_evidence', 'invalid_rule_conditions')
    conditions = _mapping(facts.get('conditions'))
    unknown = []
    for key, expected in required.items():
        actual = conditions.get(key)
        if not isinstance(actual, (bool, str)):
            unknown.append(key)
        elif type(actual) is not type(expected) or actual != expected:
            return finish('not_applicable', 'condition_mismatch:' + key)
    if unknown:
        return finish('needs_input', *['missing_condition:' + key for key in unknown])

    when = _date(assessment_date)
    if when is None:
        return finish('needs_input', 'invalid_assessment_date')
    start = _date(rule.get('effective_from'))
    end_value = rule.get('effective_to')
    end = _date(end_value) if end_value is not None else None
    evidence = []
    condition_evidence = _mapping(facts.get('condition_evidence'))
    for key in required:
        if not _text(_mapping(condition_evidence.get(key)).get('source_ref')):
            evidence.append('missing_condition_evidence:' + key)
    result['condition_evidence'] = deepcopy({
        key: condition_evidence.get(key) for key in required})
    if start is None or (end_value is not None and end is None) or (
            start is not None and end is not None and end < start):
        evidence.append('invalid_rule_date_interval')
    elif when < start or (end is not None and when > end):
        evidence.append('assessment_outside_rule_interval')
    if not _text(rule_id):
        evidence.append('missing_rule_id')
    elif _mapping(facts.get('source_edition_confirmed')).get(rule_id) is not True:
        evidence.append('source_edition_unconfirmed')
    source = _mapping(rule.get('source'))
    if not all(_text(source.get(key)) for key in ('url', 'edition', 'locator')):
        evidence.append('incomplete_rule_source')

    has_terms = 'area_terms' in rule
    coefficient = rule.get('coefficient_m2_per_unit', 0 if has_terms else None)
    fixed = rule.get('fixed_minimum_m2', 0)
    additive_constant = rule.get('additive_constant_m2', 0)
    minimum_quantity = rule.get('minimum_quantity', 0)
    if (not _number(coefficient) or not _number(fixed)
            or not _number(additive_constant) or not _count(minimum_quantity)):
        return finish('needs_evidence', *evidence, 'invalid_rule_numeric_parameters')
    if not all(_text(rule.get(key)) for key in ('quantity_fact', 'area_fact', 'area_basis')):
        return finish('needs_evidence', *evidence, 'incomplete_rule_measurement_definition')

    terms = rule.get('area_terms') if has_terms else [
        {'quantity_fact': rule['quantity_fact'], 'coefficient': coefficient}]
    if (not isinstance(terms, list) or not terms or any(
            not isinstance(term, dict) or not _text(term.get('quantity_fact'))
            or not _number(term.get('coefficient')) for term in terms)):
        return finish('needs_evidence', *evidence, 'invalid_rule_area_terms')
    lower, upper = 0, None
    if 'quantity_range' in rule:
        bounds = rule['quantity_range']
        if (not isinstance(bounds, dict) or not bounds
                or any(key not in ('minimum', 'maximum') for key in bounds)):
            return finish('needs_evidence', *evidence, 'invalid_rule_quantity_range')
        lower, upper = bounds.get('minimum', 0), bounds.get('maximum')
        if (not _count(lower) or (upper is not None and not _count(upper))
                or (upper is not None and upper < lower)):
            return finish('needs_evidence', *evidence, 'invalid_rule_quantity_range')
    quantities = _mapping(facts.get('quantities'))
    quantity = quantities.get(rule['quantity_fact'])
    if not _count(quantity) or quantity < minimum_quantity:
        return finish('needs_input', *evidence, 'invalid_or_missing_quantity')
    result['quantity'] = quantity
    if quantity < lower or (upper is not None and quantity > upper):
        return finish('not_applicable', 'quantity_outside_rule_range')
    evaluated_terms = []
    decimal_term_areas = []
    for term in terms:
        term_quantity = quantities.get(term['quantity_fact'])
        if not _count(term_quantity):
            return finish('needs_input', *evidence,
                          'invalid_or_missing_quantity:' + term['quantity_fact'])
        term_area = Decimal(str(term_quantity)) * Decimal(str(term['coefficient']))
        if not _finite(term_area):
            return finish('needs_evidence', *evidence, 'required_area_overflow')
        evaluated_terms.append({'quantity_fact': term['quantity_fact'],
                                'quantity': term_quantity,
                                'coefficient': term['coefficient'],
                                'area_m2': float(term_area)})
        decimal_term_areas.append(term_area)
    try:
        required_area = max(sum(decimal_term_areas, Decimal(0))
                            + Decimal(str(additive_constant)), Decimal(str(fixed)))
    except OverflowError:
        return finish('needs_evidence', *evidence, 'required_area_overflow')
    if not _finite(required_area):
        return finish('needs_evidence', *evidence, 'required_area_overflow')
    result['evaluated_area_terms'] = evaluated_terms
    result['additive_constant_m2'] = additive_constant
    result['required_area_m2'] = float(required_area)
    area = _mapping(_mapping(facts.get('areas')).get(rule['area_fact']))
    result['provided_area'] = deepcopy(area)
    value = area.get('value')
    if not _number(value):
        return finish('needs_input', *evidence, 'invalid_or_missing_area')
    if area.get('basis') != rule['area_basis']:
        return finish('needs_input', *evidence, 'area_basis_missing_or_mismatch')
    unit = area.get('unit')
    if unit not in ('m2', 'ft2'):
        return finish('needs_input', *evidence, 'unsupported_or_missing_area_unit')
    provided_area = Decimal(str(value))
    if unit == 'ft2':
        provided_area *= Decimal('0.09290304')
    if not _finite(provided_area):
        return finish('needs_input', *evidence, 'provided_area_overflow')
    result['provided_area_m2'] = float(provided_area)
    if not _text(area.get('source_ref')):
        evidence.append('missing_measurement_source')
    comparison = ('meets_area_minimum' if provided_area >= required_area
                  else 'below_area_minimum')
    result['conditional_area_comparison'] = comparison
    if evidence:
        return finish('needs_evidence', *evidence)
    return finish(comparison)


def evaluate_facility_areas(facts: dict, rules: list, assessment_date: str) -> dict:
    """Evaluate only supplied rules; return individual area checks and coverage gaps.

    ``conditional_area_comparison`` is arithmetic, including when an edition lacks
    evidence; only a check's ``status`` says whether its inputs support a result.
    Rules omitted from the list cannot be assessed. Invalid input containers are
    represented as missing input/evidence rather than raising an API exception.
    Optional ``area_terms`` replace the primary quantity product with a sum of
    nonnegative coefficient/count products. The nonnegative additive constant is
    applied before the fixed minimum. ``quantity_range`` is inclusive and applies
    to the primary quantity, with an omitted/null maximum meaning no upper bound.
    """
    facts = _mapping(facts)
    # Inputs must fit finite binary64 values. This precision covers the full
    # decimal exponent span of their products/sums without threshold rounding.
    with localcontext() as arithmetic_context:
        arithmetic_context.prec = 1024
        checks = [_evaluate(facts, rule, assessment_date)
                  for rule in (rules if isinstance(rules, list) else [])]
    gaps = []
    if not checks or all(check['status'] == 'not_applicable' for check in checks):
        gaps.append({'code': 'no_applicable_rules', 'facility_type': facts.get('facility_type')})
    return {
        'assessment_date': assessment_date, 'checks': checks, 'coverage_gaps': gaps,
        'scope_notice': 'Area minimum checks for supplied rules only; other statutory '
                        'requirements and permit eligibility are not assessed.',
    }
