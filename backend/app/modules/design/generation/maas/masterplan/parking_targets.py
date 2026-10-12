"""A preliminary search count is separate from a required design promise or Law count."""


def target_mode(request):
    options = request.get('options') or {}
    mode = options.get('parking_target_mode',
                       'reference' if options.get('planning_stage') == 'placement' else 'required')
    if mode not in ('reference', 'required'):
        raise ValueError('parking_target_mode must be reference or required')
    return mode


def target_observation(request, target, provided):
    return {'mode': target_mode(request), 'stalls': target, 'provided': provided,
            'difference': provided - target if target is not None else None,
            'scope': 'Search reference unless explicitly required; Law parking count is separate.'}
