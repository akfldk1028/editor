"""Transport-independent Program intent consumed by LawAgent.

This validates a requested schedule, not legal classification or permission.
The Program Agent owns areas and intent; legal rules remain with LawAgent.
"""
from datetime import date
import math


def _area(value, field):
    if value is None or value == '':
        return None
    if isinstance(value, bool):
        raise ValueError(f'{field} must be a finite positive area')
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f'{field} must be a finite positive area') from exc
    if not math.isfinite(result) or result <= 0:
        raise ValueError(f'{field} must be a finite positive area')
    return result


def normalize_program_request(body):
    if not isinstance(body, dict):
        raise ValueError('request body must be a JSON object')
    building_type = body.get('building_type') or ''
    if not isinstance(building_type, str) or len(building_type) > 200:
        raise ValueError('building_type must be a string of at most 200 characters')
    assessment = body.get('assessment_date')
    if assessment is None:
        assessment = date.today().isoformat()
    if not isinstance(assessment, str):
        raise ValueError('assessment_date must use YYYY-MM-DD')
    try:
        if date.fromisoformat(assessment).isoformat() != assessment:
            raise ValueError()
    except ValueError as exc:
        raise ValueError('assessment_date must be a valid YYYY-MM-DD date') from exc
    schedule = body.get('program_uses')
    if schedule is not None:
        if not isinstance(schedule, list) or not 1 <= len(schedule) <= 100:
            raise ValueError('program_uses must contain between 1 and 100 use entries')
        normalized, ids = [], set()
        for index, row in enumerate(schedule):
            if not isinstance(row, dict):
                raise ValueError('each program use must be a JSON object')
            use = row.get('building_type')
            if not isinstance(use, str) or not use.strip() or len(use) > 200:
                raise ValueError('each program use needs a building_type string (max 200)')
            use_id = row.get('id', f'use-{index + 1}')
            if not isinstance(use_id, str) or not use_id.strip() or len(use_id) > 200 or use_id in ids:
                raise ValueError('program use ids must be nonempty, unique strings (max 200)')
            ids.add(use_id)
            normalized.append({'id': use_id, 'building_type': use.strip(),
                               'floor_area_m2': _area(row.get('floor_area_m2'), f'{use_id}.floor_area_m2')})
        schedule = normalized
    return {'building_type': building_type.strip(),
            'floor_area_m2': _area(body.get('floor_area_m2'), 'floor_area_m2'),
            'program_uses': schedule, 'assessment_date': assessment}
