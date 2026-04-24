from collections import defaultdict
from pathlib import Path

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

    removed_scan_path = "/api/ops/trigger/" + "scan"
    assert ("POST", removed_scan_path) not in routes
    assert ("POST", f"{removed_scan_path}/async") not in routes
    assert routes[("POST", "/api/ops/trigger/board-refresh")].__module__ == "routes.ops_cron"
    assert routes[("POST", "/api/ops/trigger/board-refresh/async")].__module__ == "routes.ops_cron"


def test_route_and_cron_modules_do_not_import_app_composition():
    backend_root = Path(__file__).resolve().parents[1]
    checked_roots = [backend_root / "routes"]
    offenders = []
    for root in checked_roots:
        for path in root.glob("*.py"):
            text = path.read_text(encoding="utf-8")
            if ("import " + "main") in text or ("main" + ".") in text:
                offenders.append(str(path.relative_to(backend_root)))
    assert offenders == []


def test_main_is_app_composition_only():
    backend_root = Path(__file__).resolve().parents[1]
    main_text = (backend_root / ("main" + ".py")).read_text(encoding="utf-8")
    forbidden_markers = [
        "def _retry_supabase",
        "def get_user_settings",
        "def compute_k_user",
        "def build_bet_response",
        "def _runtime_state",
        "def _run_scheduled_board_drop_job",
        "def _piggyback_clv",
    ]
    assert [marker for marker in forbidden_markers if marker in main_text] == []


def test_board_routes_have_explicit_runtime_hooks():
    import routes.board_routes as board_routes

    assert not hasattr(board_routes, "_resolve_" + "main_runtime_hooks")
    for name in [
        "_log_event",
        "_set_ops_status",
        "_persist_ops_job_run",
        "_sync_pickem_research_from_props_payload",
    ]:
        assert hasattr(board_routes, name)
