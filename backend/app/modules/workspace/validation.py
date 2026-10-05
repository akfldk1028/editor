def validate_template_shape(component, expected=None, depth=0):
    if depth > 32 or not isinstance(component, dict):
        raise ValueError('Invalid component structure')
    kind = component.get('component_type')
    if kind not in ('team', 'agent', 'model', 'tool', 'termination', 'workbench') or (expected and kind not in expected):
        raise ValueError('Invalid component type')
    if not isinstance(component.get('provider'), str) or not component['provider'].strip():
        raise ValueError('Provider is required')
    config = component.get('config')
    if not isinstance(config, dict):
        raise ValueError('Component config must be an object')
    for key in ('label', 'description'):
        if component.get(key) is not None and not isinstance(component[key], str):
            raise ValueError(f'{key} must be text')
    if config.get('name') is not None and not isinstance(config['name'], str):
        raise ValueError('Component name must be text')
    for key, child_types in (('participants', ('agent', 'team')), ('tools', ('tool',)), ('conditions', ('termination',))):
        if key not in config:
            continue
        if not isinstance(config[key], list):
            raise ValueError(f'{key} must be a list')
        for child in config[key]:
            validate_template_shape(child, child_types, depth + 1)
    for key, child_types in (('model_client', ('model',)), ('termination_condition', ('termination',))):
        if config.get(key) is not None:
            validate_template_shape(config[key], child_types, depth + 1)
