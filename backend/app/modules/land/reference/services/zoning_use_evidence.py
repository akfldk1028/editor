"""Evaluate caller-supplied, source-bound zoning conditions, never permission.

No statutory rules are embedded. ``land_info.zoning_use_evidence`` accepts
``rules`` and ``facts``. Each rule needs id, exact zone_name/canonical_use,
effect (allow/prohibit), conditions_complete=True, source (URL, article,
excerpt, effective_from and optional inclusive effective_to), and conditions.
Conditions are a conjunction of {fact, operator, value}; an explicit empty
list means unconditional *within this supplied rule*. Supported operators:
eq, lt, lte, gt, gte. Values are finite numbers, strings or booleans; no coercion.

Facts are keyed by program-use id then fact name: {value, source: {url,
excerpt}}. floor_area_m2 always comes from Program intent and cannot be
overridden. Sources and condition completeness are caller assertions, not
independently verified law. Results retain this provenance and do not remove
the caller's existing municipal, district-plan or edition evidence gaps.
"""
from copy import deepcopy
from datetime import date
import math
import operator
from urllib.parse import urlsplit


_OPERATORS = {'eq': operator.eq, 'lt': operator.lt, 'lte': operator.le,
              'gt': operator.gt, 'gte': operator.ge}


def _date(value):
    try:
        return date.fromisoformat(value) if isinstance(value, str) and date.fromisoformat(value).isoformat() == value else None
    except ValueError:
        return None


def _kind(value):
    if type(value) is bool:
        return 'boolean'
    if type(value) in (int, float):
        try:
            return 'number' if math.isfinite(value) else None
        except OverflowError:
            return None
    if isinstance(value, str):
        return 'string'
    return None


def _source_valid(source):
    if not isinstance(source, dict) or not isinstance(source.get('url'), str):
        return False
    try:
        url = urlsplit(source['url'])
        return (url.scheme in ('https', 'http') and bool(url.hostname)
                and isinstance(source.get('excerpt'), str) and bool(source['excerpt'].strip()))
    except ValueError:
        return False


def _condition(condition, use, facts):
    if not isinstance(condition, dict):
        return {'status': 'unknown', 'reason': 'invalid_condition'}
    field, op, expected = condition.get('fact'), condition.get('operator'), condition.get('value')
    result = {'fact': field, 'operator': op, 'expected': deepcopy(expected), 'status': 'unknown'}
    if not isinstance(field, str) or not isinstance(op, str) or op not in _OPERATORS or not _kind(expected):
        return {**result, 'reason': 'invalid_condition'}
    if field == 'floor_area_m2':
        actual = use.get(field)
        result['fact_source'] = 'program_intent'
        if _kind(actual) != 'number' or actual <= 0:
            return {**result, 'reason': 'missing_or_invalid_fact'}
    else:
        fact = facts.get(field)
        if not isinstance(fact, dict) or not _source_valid(fact.get('source')):
            return {**result, 'reason': 'missing_source_bound_fact'}
        actual = fact.get('value')
        result['fact_source'] = deepcopy(fact['source'])
    if not _kind(actual) or _kind(actual) != _kind(expected) or (op != 'eq' and _kind(actual) != 'number'):
        return {**result, 'reason': 'invalid_fact_type'}
    return {**result, 'actual': actual,
            'status': 'met' if _OPERATORS[op](actual, expected) else 'not_met'}


def evaluate_use_evidence(use, classification, zone_names, evidence, assessment_date):
    """Return auditable partial evaluations without a legal permission claim."""
    evidence = evidence if isinstance(evidence, dict) else {}
    rules = evidence.get('rules')
    rules = rules if isinstance(rules, list) else []
    all_facts = evidence.get('facts')
    all_facts = all_facts if isinstance(all_facts, dict) else {}
    use_id = use.get('id')
    facts = all_facts.get(use_id, {}) if isinstance(use_id, str) else {}
    facts = facts if isinstance(facts, dict) else {}
    assessment = _date(assessment_date)
    evaluations, effects = [], set()
    for rule in rules:
        row = {'status': 'unknown', 'reason': 'invalid_rule',
               'evidence_origin': 'caller_supplied', 'source_verified': False}
        if not isinstance(rule, dict):
            evaluations.append(row)
            continue
        row.update({'rule_id': rule.get('id'), 'zone_name': rule.get('zone_name'),
                    'canonical_use': rule.get('canonical_use'), 'effect': rule.get('effect'),
                    'source': deepcopy(rule.get('source')), 'conditions': []})
        evaluations.append(row)
        if (classification.get('status') != 'classified' or rule.get('zone_name') not in zone_names
                or rule.get('canonical_use') != classification.get('canonical_use')):
            row['reason'] = 'scope_not_matched'
            continue
        if (not isinstance(rule.get('id'), str) or not rule['id'].strip()
                or rule.get('effect') not in ('allow', 'prohibit')
                or rule.get('conditions_complete') is not True or not isinstance(rule.get('conditions'), list)):
            continue
        source = rule.get('source')
        if (not _source_valid(source) or not isinstance(source.get('article'), str)
                or not source['article'].strip()):
            row['reason'] = 'missing_rule_source'
            continue
        start, end = _date(source.get('effective_from')), _date(source.get('effective_to'))
        if (not assessment or not start or assessment < start
                or ('effective_to' in source and (not end or assessment > end or end < start))):
            row['reason'] = 'applicable_legal_edition_unknown'
            continue
        row['conditions'] = [_condition(condition, use, facts) for condition in rule['conditions']]
        states = [condition['status'] for condition in row['conditions']]
        # Unknown wins: partial/invalid conjunctions are not completed checks.
        row['status'] = 'unknown' if 'unknown' in states else ('not_met' if 'not_met' in states else 'met')
        row['reason'] = 'conditions_need_evidence' if row['status'] == 'unknown' else 'supplied_conditions_evaluated'
        if row['status'] == 'met':
            effects.add(rule['effect'])
    return {'evidence_evaluated': any(row['status'] in ('met', 'not_met') for row in evaluations),
            'scoped_rule_result': ('conflict' if len(effects) > 1 else next(iter(effects), 'unknown')),
            'rule_evaluations': evaluations,
            'evidence_scope': 'caller_supplied_rules_only', 'source_verified': False}
