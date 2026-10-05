"""Bind algorithm-local candidates to stable IDs in one job's public journal."""


def canonicalize_result_event(event, ids_by_uid):
    def candidate(value):
        if not isinstance(value, dict):
            return value
        uid = value['uid']
        if uid not in ids_by_uid:
            ids_by_uid[uid] = len(ids_by_uid)
        return {**value, 'source_design_id': value['id'], 'id': ids_by_uid[uid]}

    result = {**event, 'pareto_front': [candidate(value) for value in event.get('pareto_front', [])]}
    if 'best' in event:
        result['best'] = candidate(event['best'])
    return result


class ResultIdentityError(ValueError):
    def __init__(self, message, status, code):
        super().__init__(message)
        self.status = status
        self.code = code


def requested_design_uid(query_values, body=None):
    if len(query_values) > 1:
        raise ResultIdentityError('Supply design_uid once', 400, 'invalid_design_uid')
    values = list(query_values)
    if body is not None and 'design_uid' in body:
        values.append(body['design_uid'])
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise ResultIdentityError('design_uid must be a non-empty string', 400, 'invalid_design_uid')
    if len(set(values)) > 1:
        raise ResultIdentityError('Query and body design_uid disagree', 400, 'conflicting_design_uid')
    return values[0] if values else None


def recorded_design_uid(design):
    outputs = design.outputs if isinstance(design.outputs, dict) else {}
    identity = outputs.get('result_identity')
    identity = identity if isinstance(identity, dict) else {}
    feature = design.mass_geojson if isinstance(design.mass_geojson, dict) else {}
    properties = feature.get('properties')
    properties = properties if isinstance(properties, dict) else {}
    uids = {value for value in (identity.get('uid'), properties.get('design_uid'))
            if isinstance(value, str) and value}
    if len(uids) > 1:
        raise ResultIdentityError('Stored design UID metadata disagrees', 409, 'conflicting_design_identity')
    return next(iter(uids), None)


def resolve_design_result(job_id, design_id, design_uid=None):
    from django.db.models import Q
    from backend.app.adapters.design_storage.models import DesignResult

    results = DesignResult.objects.select_related('job').filter(job_id=job_id, design_id=design_id)
    if design_uid is not None:
        results = results.filter(Q(outputs__result_identity__uid=design_uid)
                                 | Q(mass_geojson__properties__design_uid=design_uid))
    rows = list(results[:2])
    if not rows:
        raise ResultIdentityError('Design not found for requested identity', 404, 'design_not_found')
    if len(rows) > 1:
        raise ResultIdentityError('Ambiguous legacy design ID', 409, 'ambiguous_design_id')
    if design_uid is not None and recorded_design_uid(rows[0]) != design_uid:
        raise ResultIdentityError('Design UID does not match', 404, 'design_not_found')
    return rows[0]
