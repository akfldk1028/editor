"""Compile declarative legal constraints and compare version-bound design facts.

Compilation checks structure and evidence integrity; it does not verify that a
caller faithfully interpreted a law. Such findings are explicitly scoped to the
supplied constraints. Program/Law never mutate geometry or issue a permit here.
"""
from copy import deepcopy
from datetime import date
from decimal import Decimal, InvalidOperation
import hashlib
import json
from urllib.parse import urlsplit

SCOPES = {"site", "mass", "plan", "elevation", "detail", "program"}
OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _text(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} must be nonempty text")
    return value


def _date(value):
    parsed = date.fromisoformat(_text(value, "date"))
    if parsed.isoformat() != value:
        raise ValueError("date must be YYYY-MM-DD")
    return parsed


def _kind(value):
    if type(value) is bool:
        return "boolean"
    if isinstance(value, str):
        return "string"
    if type(value) in (int, float):
        try:
            return "number" if Decimal(str(value)).is_finite() else None
        except InvalidOperation:
            return None
    return None


def _predicate(item):
    if not isinstance(item, dict):
        raise ValueError("predicate must be an object")
    _text(item.get("fact"), "predicate.fact")
    op, expected = item.get("operator"), item.get("value")
    if op not in OPERATORS:
        raise ValueError("unsupported predicate operator")
    values = expected if op == "in" else [expected]
    if not isinstance(values, list) or not values or any(_kind(v) is None for v in values):
        raise ValueError("predicate values must be finite numbers, strings or booleans")
    if len({_kind(v) for v in values}) != 1:
        raise ValueError("predicate values must share a type")
    if op in {"gt", "gte", "lt", "lte"} and _kind(expected) != "number":
        raise ValueError("ordered comparison requires a number")
    for key in ("unit", "basis"):
        if key in item:
            _text(item[key], f"predicate.{key}")
    return deepcopy(item)


def compile_rules(rules):
    """Validate a finite source-bound IR; never execute Python or model output."""
    if not isinstance(rules, list) or len(rules) > 2000:
        raise ValueError("rules must be a list of at most 2000 entries")
    compiled, seen = [], set()
    for raw in rules:
        if not isinstance(raw, dict):
            raise ValueError("rule must be an object")
        rule = deepcopy(raw)
        rid = _text(rule.get("rule_id"), "rule_id")
        if rid in seen:
            raise ValueError("duplicate rule_id")
        seen.add(rid)
        if rule.get("scope") not in SCOPES:
            raise ValueError("unsupported rule scope")
        nodes = rule.get("input_nodes")
        if not isinstance(nodes, list) or not nodes:
            raise ValueError("rule.input_nodes must identify dependencies")
        for node in nodes:
            _text(node, "input node")
        source = rule.get("source")
        if not isinstance(source, dict):
            raise ValueError("rule.source required")
        url = urlsplit(_text(source.get("url"), "source.url"))
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("source requires a public HTTPS URL")
        for key in ("article", "excerpt"):
            _text(source.get(key), f"source.{key}")
        expected = hashlib.sha256(source["excerpt"].encode()).hexdigest()
        if source.get("excerpt_sha256") != expected:
            raise ValueError("source excerpt hash mismatch")
        start = _date(source.get("effective_from"))
        _date(source.get("edition_checked_on"))
        if source.get("effective_to") is not None and _date(source["effective_to"]) < start:
            raise ValueError("invalid source effective interval")
        for key in ("applies_when", "requirements"):
            items = rule.get(key)
            if not isinstance(items, list) or len(items) > 100 or (key == "requirements" and not items):
                raise ValueError(f"{key} must be an explicit list; requirements cannot be empty")
            rule[key] = [_predicate(item) for item in items]
        rule["compiled_hash"] = _hash(raw)
        rule["source_verified"] = False  # A hash proves integrity, not legal interpretation.
        compiled.append(rule)
    return compiled


def _evaluate(predicate, facts, versions, dependencies):
    name = predicate["fact"]
    result = {"fact_id": name, "predicate": deepcopy(predicate)}
    fact = facts.get(name)
    if fact is None or fact.get("value") is None:
        return {**result, "status": "needs_input", "reason": "missing_fact"}
    expected = predicate["value"]
    values = expected if predicate["operator"] == "in" else [expected]
    if _kind(fact["value"]) != _kind(values[0]):
        return {**result, "status": "needs_input", "reason": "fact_type_mismatch"}
    node = fact.get("input_node")
    if (not isinstance(fact.get("source_ref"), str) or not fact["source_ref"].strip()
            or node not in dependencies or node not in versions
            or type(fact.get("input_version")) is not type(versions[node])
            or fact["input_version"] != versions[node]):
        return {**result, "status": "needs_evidence", "reason": "missing_or_stale_fact_provenance"}
    for key in ("unit", "basis"):
        if key in predicate and predicate[key] != fact.get(key):
            return {**result, "status": "needs_evidence", "reason": f"{key}_mismatch"}
    actual = fact["value"]
    numeric = _kind(actual) == "number"
    left = Decimal(str(actual)) if numeric else actual
    right = [Decimal(str(v)) for v in values] if numeric else values
    op = predicate["operator"]
    if op == "in":
        met = left in right
    elif op == "eq":
        met = left == right[0]
    elif op == "ne":
        met = left != right[0]
    elif op == "gt":
        met = left > right[0]
    elif op == "gte":
        met = left >= right[0]
    elif op == "lt":
        met = left < right[0]
    else:
        met = left <= right[0]
    return {**result, "status": "met" if met else "not_met", "actual": actual,
            "measurement": deepcopy(fact)}


def review_design_state(design_state, rules):
    if not isinstance(design_state, dict):
        raise ValueError("design_state must be an object")
    assessment = _date(design_state.get("assessment_date"))
    versions = design_state.get("versions")
    if not isinstance(versions, dict) or any(not isinstance(k, str) or type(v) not in (int, str) or v == "" for k, v in versions.items()):
        raise ValueError("versions must map nodes to non-boolean revisions")
    scopes = design_state.get("review_scopes", sorted(SCOPES))
    if not isinstance(scopes, list) or not scopes or any(s not in SCOPES for s in scopes):
        raise ValueError("review_scopes must list supported scopes")
    raw_facts = design_state.get("facts", [])
    if not isinstance(raw_facts, list):
        raise ValueError("facts must be a list")
    facts = {}
    for fact in raw_facts:
        if not isinstance(fact, dict):
            raise ValueError("fact must be an object")
        name = _text(fact.get("fact_id"), "fact_id")
        if name in facts:
            raise ValueError("duplicate fact_id; aggregate explicitly")
        facts[name] = fact
    compiled = compile_rules(rules)
    checks = []
    for rule in compiled:
        if rule["scope"] not in scopes:
            continue
        source = rule["source"]
        check = {"rule_id": rule["rule_id"], "scope": rule["scope"], "source": deepcopy(source),
                 "source_verified": False, "compiled_hash": rule["compiled_hash"],
                 "input_nodes": rule["input_nodes"], "status": "needs_evidence",
                 "applicability": [], "comparisons": []}
        checks.append(check)
        if (_date(source["effective_from"]) > assessment or source["edition_checked_on"] != assessment.isoformat()
                or (source.get("effective_to") and _date(source["effective_to"]) < assessment)):
            check["reason"] = "source_edition_not_bound_to_assessment_date"
            continue
        check["applicability"] = [_evaluate(p, facts, versions, rule["input_nodes"]) for p in rule["applies_when"]]
        states = {p["status"] for p in check["applicability"]}
        if "needs_evidence" in states or "needs_input" in states:
            check["status"] = "needs_evidence" if "needs_evidence" in states else "needs_input"
            continue
        if "not_met" in states:
            check["status"] = "not_applicable"
            continue
        check["comparisons"] = [_evaluate(p, facts, versions, rule["input_nodes"]) for p in rule["requirements"]]
        states = {p["status"] for p in check["comparisons"]}
        # A proven violated obligation survives missing evidence for other obligations.
        check["status"] = ("violates_constraint" if "not_met" in states else "needs_evidence" if "needs_evidence" in states
                           else "needs_input" if "needs_input" in states else "meets_constraint")
    uncovered = sorted(set(scopes) - {c["scope"] for c in checks})
    violations = [deepcopy(c) for c in checks if c["status"] == "violates_constraint"]
    missing = sorted({p["fact_id"] for c in checks for p in c["applicability"] + c["comparisons"] if p["status"] == "needs_input"})
    digest = _hash({"design_state": design_state, "rules": rules})
    return {"schema_version": "law-review/1", "review_id": "design-" + digest[:24], "agent": "law", "request_hash": digest,
            "assessment_date": assessment.isoformat(), "input_versions": deepcopy(versions), "input_hash": _hash(design_state),
            "status": "conflict" if violations else "needs_evidence", "checks": checks,
            "sources": [deepcopy(c["source"]) for c in checks], "violations": violations,
            "missing_inputs": missing, "proposals": [], "permit_ready": False,
            "coverage": {"requested_scopes": scopes, "uncovered_scopes": uncovered,
                         "legal_interpretation_verified": False, "scope": "supplied_constraints_only"}}
