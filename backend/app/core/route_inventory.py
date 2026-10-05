"""The HTTP surface the backend serves, as one committed list.

OpenAPI alone cannot describe it: design operations sit behind one catch-all
that resolves Django URL patterns. The frontend's api-surface test reads the
committed file, and test_route_inventory.py keeps the file equal to the code.

    python -m backend.app.core.route_inventory --write
"""
import json
import re
import sys
from pathlib import Path

INVENTORY_PATH = Path(__file__).resolve().parents[2] / 'route-inventory.json'
SCHEMA = 'editor-route-inventory/v1'
METHODS = ('GET', 'POST', 'PUT', 'DELETE')
DESIGN_CATCH_ALL = '/api/v1/design/{path}'
_DJANGO_PARAM = re.compile(r'<(?:[a-z]+:)?([A-Za-z_][A-Za-z0-9_]*)>')


def _design_routes():
    from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime

    ensure_design_runtime()
    from backend.app.api.design_runtime.urls import urlpatterns

    # The catch-all forwards GET and POST alike; each view rejects the other itself.
    for pattern in urlpatterns:
        path = '/api/v1/design/' + _DJANGO_PARAM.sub(r'{\1}', str(pattern.pattern)).rstrip('/')
        for method in ('GET', 'POST'):
            yield {'method': method, 'path': path, 'owner': 'design-runtime'}


def compute_inventory():
    from backend.app.main import create_app

    routes = []
    # The OpenAPI document is the one view that already flattens nested routers.
    for path, operations in create_app().openapi()['paths'].items():
        if path == DESIGN_CATCH_ALL:
            continue
        for method in sorted(operations):
            if method.upper() in METHODS:
                routes.append({'method': method.upper(), 'path': path.rstrip('/') or '/', 'owner': 'fastapi'})
    routes.extend(_design_routes())
    routes.sort(key=lambda row: (row['path'], row['method']))
    return {'schema': SCHEMA, 'routes': routes}


def render(inventory):
    return json.dumps(inventory, indent=1, ensure_ascii=False, sort_keys=True) + '\n'


if __name__ == '__main__':
    text = render(compute_inventory())
    if '--write' in sys.argv:
        INVENTORY_PATH.write_text(text, encoding='utf-8')
        print(f'wrote {INVENTORY_PATH}')
    else:
        sys.stdout.write(text)
