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
