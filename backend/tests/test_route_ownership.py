from collections import defaultdict

from .test_utils import ensure_supabase_stub


def _route_index(app):
    index = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        endpoint = getattr(route, "endpoint", None)
        if not path or not methods or endpoint is None:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            index[(method, path)] = endpoint
    return index


def test_active_routes_have_no_duplicate_method_path_pairs():
    ensure_supabase_stub()
    from main import app

    seen = defaultdict(list)
    for route in app.routes:
        path = getattr(route, "path", None)
        methods = getattr(route, "methods", None)
        if not path or not methods:
            continue
        for method in methods:
            if method in {"HEAD", "OPTIONS"}:
                continue
            seen[(method, path)].append(route)

    duplicates = {key: routes for key, routes in seen.items() if len(routes) > 1}
    assert duplicates == {}


def test_core_tracker_routes_are_owned_by_routers():
    ensure_supabase_stub()
    from main import app

    routes = _route_index(app)

    expected_modules = {
        ("POST", "/bets"): "routes.bet_routes",
        ("GET", "/bets"): "routes.bet_routes",
        ("GET", "/bets/live"): "routes.bet_routes",
        ("GET", "/bets/{bet_id}"): "routes.bet_routes",
        ("PATCH", "/bets/{bet_id}"): "routes.bet_routes",
        ("PATCH", "/bets/{bet_id}/result"): "routes.bet_routes",
        ("DELETE", "/bets/{bet_id}"): "routes.bet_routes",
        ("GET", "/summary"): "routes.dashboard_routes",
        ("GET", "/balances"): "routes.dashboard_routes",
    }
    for key, module in expected_modules.items():
        assert key in routes
        assert routes[key].__module__ == module


def test_deprecated_ops_scan_aliases_are_not_registered():
    ensure_supabase_stub()
    from main import app

    routes = _route_index(app)

    assert ("POST", "/api/ops/trigger/scan") not in routes
    assert ("POST", "/api/ops/trigger/scan/async") not in routes
    assert routes[("POST", "/api/ops/trigger/board-refresh")].__module__ == "routes.ops_cron"
    assert routes[("POST", "/api/ops/trigger/board-refresh/async")].__module__ == "routes.ops_cron"
