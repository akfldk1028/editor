from backend.app.route_inventory import INVENTORY_PATH, compute_inventory, render


def test_committed_route_inventory_matches_the_served_routes():
    expected = render(compute_inventory())
    assert INVENTORY_PATH.read_text(encoding='utf-8') == expected, (
        'backend/route-inventory.json is stale; run `python -m backend.app.route_inventory --write`')


def test_inventory_lists_both_owners_without_the_catch_all():
    routes = compute_inventory()['routes']
    paths = {row['path'] for row in routes}
    assert '/api/v1/design/{path}' not in paths
    assert {'method': 'GET', 'path': '/api/v1/design/jobs/{job_id}/stream', 'owner': 'design-runtime'} in routes
    assert {'method': 'POST', 'path': '/api/v1/design/site-boundary', 'owner': 'fastapi'} in routes
    assert {'method': 'GET', 'path': '/api/v1/land/agent-analyze/stream', 'owner': 'fastapi'} in routes
