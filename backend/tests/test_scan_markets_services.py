import pytest
import httpx
from fastapi import HTTPException

from services.scan_markets import (
    manual_scan_sports_for_env,
    aggregate_manual_scan_all_sports,
    build_single_sport_manual_scan_outputs,
    build_all_sports_manual_scan_outputs,
    scanned_at_from_fetched_timestamp,
    run_single_sport_manual_scan,
    run_all_sports_manual_scan,
    apply_manual_scan_bundle,
    scan_exception_to_http_exception,
)


VALID_PROP_DIAGNOSTICS = {
    "scan_mode": "curated_sniper",
    "scoreboard_event_count": 10,
    "odds_event_count": 5,
    "curated_games": [
        {
            "event_id": "espn-1",
            "away_team": "Boston Celtics",
            "home_team": "Los Angeles Lakers",
            "selection_reason": "national_tv",
            "broadcasts": ["ESPN"],
            "odds_event_id": "odds-1",
            "commence_time": "2026-03-19T00:00:00Z",
            "matched": True,
        }
    ],
    "matched_event_count": 1,
    "unmatched_game_count": 0,
    "events_fetched": 1,
    "events_skipped_pregame": 0,
    "events_with_results": 1,
    "candidate_sides_count": 14,
    "quality_gate_filtered_count": 2,
    "quality_gate_min_reference_bookmakers": 2,
    "sides_count": 12,
    "markets_requested": ["player_points"],
}


def test_manual_scan_sports_for_env_switches_in_development():
    supported = ["basketball_nba", "basketball_ncaab"]
    assert manual_scan_sports_for_env(environment="development", supported_sports=supported) == ["basketball_nba"]
    assert manual_scan_sports_for_env(environment="production", supported_sports=supported) == supported


@pytest.mark.asyncio
async def test_aggregate_manual_scan_all_sports_skips_404_and_rolls_up_fields():
    async def _get_cached_or_scan(sport):
        if sport == "missing":
            req = httpx.Request("GET", "https://example.test")
            resp = httpx.Response(404, request=req)
            raise httpx.HTTPStatusError("not found", request=req, response=resp)
        return {
            "sides": [{"sport": sport}],
            "events_fetched": 2,
            "events_with_both_books": 1,
            "api_requests_remaining": "95" if sport == "a" else "90",
            "fetched_at": 100.0 if sport == "a" else 80.0,
        }

    out = await aggregate_manual_scan_all_sports(
        sports_to_scan=["a", "missing", "b"],
        get_cached_or_scan=_get_cached_or_scan,
    )

    assert len(out["all_sides"]) == 2
    assert out["total_events"] == 4
    assert out["total_with_both"] == 2
    assert out["min_remaining"] == "90"
    assert out["oldest_fetched"] == 80.0


@pytest.mark.asyncio
async def test_aggregate_manual_scan_all_sports_re_raises_non_404_http_errors():
    async def _get_cached_or_scan(_sport):
        req = httpx.Request("GET", "https://example.test")
        resp = httpx.Response(500, request=req)
        raise httpx.HTTPStatusError("server error", request=req, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        await aggregate_manual_scan_all_sports(
            sports_to_scan=["a"],
            get_cached_or_scan=_get_cached_or_scan,
        )


def test_build_single_sport_manual_scan_outputs_builds_response_and_persist_payloads():
    result = {
        "sides": [{"id": "a"}],
        "events_fetched": 4,
        "events_with_both_books": 3,
        "api_requests_remaining": "87",
        "diagnostics": VALID_PROP_DIAGNOSTICS,
    }

    out = build_single_sport_manual_scan_outputs(
        result=result,
        sport="basketball_nba",
        scanned_at="2026-03-19T00:00:00Z",
        annotate_sides=lambda sides: sides + [{"id": "annotated"}],
    )

    assert out["base_sides"] == [{"surface": "straight_bets", "id": "a"}]
    assert out["response_payload"]["sport"] == "basketball_nba"
    assert out["response_payload"]["sides"] == [
        {"surface": "straight_bets", "id": "a"},
        {"surface": "straight_bets", "id": "annotated"},
    ]
    assert out["persist_payload"]["sides"] == [{"surface": "straight_bets", "id": "a"}]
    assert out["ops_status_payload"]["total_sides"] == 1
    assert out["response_payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS
    assert out["persist_payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS


def test_build_all_sports_manual_scan_outputs_builds_response_and_persist_payloads():
    out = build_all_sports_manual_scan_outputs(
        all_sides=[{"id": "a"}],
        total_events=5,
        total_with_both=4,
        min_remaining="77",
        scanned_at="2026-03-19T00:00:00Z",
        diagnostics=VALID_PROP_DIAGNOSTICS,
        annotate_sides=lambda sides: sides + [{"id": "annotated"}],
    )

    assert out["response_payload"]["sport"] == "all"
    assert out["response_payload"]["sides"] == [
        {"surface": "straight_bets", "id": "a"},
        {"surface": "straight_bets", "id": "annotated"},
    ]
    assert out["persist_payload"]["sides"] == [{"surface": "straight_bets", "id": "a"}]
    assert out["ops_status_payload"]["total_sides"] == 1
    assert out["ops_status_payload"]["events_fetched"] == 5
    assert out["response_payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS


def test_scanned_at_from_fetched_timestamp_handles_none_and_value():
    assert scanned_at_from_fetched_timestamp(None) is None
    assert scanned_at_from_fetched_timestamp(0.0) == "1970-01-01T00:00:00Z"


@pytest.mark.asyncio
async def test_run_single_sport_manual_scan_builds_bundle_with_annotated_sides():
    async def _get_cached_or_scan(sport):
        assert sport == "basketball_nba"
        return {
            "sides": [{"id": "a"}],
            "events_fetched": 2,
            "events_with_both_books": 1,
            "api_requests_remaining": "99",
            "fetched_at": 0.0,
            "diagnostics": VALID_PROP_DIAGNOSTICS,
        }

    out = await run_single_sport_manual_scan(
        sport="basketball_nba",
        get_cached_or_scan=_get_cached_or_scan,
        annotate_sides=lambda sides: sides + [{"id": "annotated"}],
    )

    assert out["response_payload"]["sides"] == [
        {"surface": "straight_bets", "id": "a"},
        {"surface": "straight_bets", "id": "annotated"},
    ]
    assert out["persist_payload"]["sides"] == [{"surface": "straight_bets", "id": "a"}]
    assert out["response_payload"]["scanned_at"] == "1970-01-01T00:00:00Z"
    assert out["response_payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS


@pytest.mark.asyncio
async def test_run_all_sports_manual_scan_development_uses_only_nba():
    called = []

    async def _get_cached_or_scan(sport):
        called.append(sport)
        return {
            "sides": [{"id": sport}],
            "events_fetched": 1,
            "events_with_both_books": 1,
            "api_requests_remaining": "80",
            "fetched_at": 10.0,
            "diagnostics": VALID_PROP_DIAGNOSTICS,
        }

    out = await run_all_sports_manual_scan(
        environment="development",
        supported_sports=["basketball_nba", "basketball_ncaab"],
        get_cached_or_scan=_get_cached_or_scan,
        annotate_sides=lambda sides: sides,
    )

    assert called == ["basketball_nba"]
    assert out["ops_status_payload"]["events_fetched"] == 1
    assert out["persist_payload"]["sport"] == "all"
    assert out["response_payload"]["diagnostics"] == VALID_PROP_DIAGNOSTICS


def test_apply_manual_scan_bundle_runs_status_piggyback_and_persist():
    calls = {"status": [], "piggyback": [], "persist": []}
    bundle = {
        "ops_status_payload": {"sport": "all", "total_sides": 1},
        "persist_payload": {"sides": [{"id": "a"}], "sport": "all"},
        "response_payload": {"sport": "all", "sides": [{"id": "annotated"}]},
    }

    out = apply_manual_scan_bundle(
        bundle=bundle,
        captured_at="2026-03-19T00:00:00Z",
        set_last_manual_scan_status=lambda status: calls["status"].append(status),
        schedule_piggyback=lambda sides: calls["piggyback"].append(sides),
        persist_latest_scan=lambda payload: calls["persist"].append(payload),
    )

    assert out == bundle["response_payload"]
    assert calls["status"][0]["captured_at"] == "2026-03-19T00:00:00Z"
    assert calls["piggyback"][0] == [{"id": "a"}]
    assert calls["persist"][0] == bundle["persist_payload"]


def test_scan_exception_to_http_exception_maps_value_and_generic_errors():
    v = scan_exception_to_http_exception(ValueError("bad input"))
    assert isinstance(v, HTTPException)
    assert v.status_code == 500
    assert v.detail == "bad input"

    g = scan_exception_to_http_exception(RuntimeError("upstream boom"))
    assert isinstance(g, HTTPException)
    assert g.status_code == 502
    assert g.detail == "Odds API error: upstream boom"

    original = HTTPException(status_code=418, detail="teapot")
    same = scan_exception_to_http_exception(original)
    assert same is original
