"""Adapt public asset links without changing stored execution evidence."""


def normalize_design_urls(value):
    if isinstance(value, list):
        return [normalize_design_urls(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: '/api/v1' + item
        if (key in {'url', 'href'} or key.endswith('_url'))
        and isinstance(item, str) and item.startswith('/design/')
        else normalize_design_urls(item)
        for key, item in value.items()
    }
