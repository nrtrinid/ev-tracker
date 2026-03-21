from services.paper_autolog_flow import (
    build_eligible_autolog_sides,
    build_pending_autolog_keys,
    build_autolog_insert_payload,
    run_autolog_insert_loop,
)


def test_build_eligible_autolog_sides_filters_and_sorts_deterministically():
    sides = [
        {
            "sport": "basketball_nba",
            "ev_percentage": 1.0,
            "book_odds": 100,
            "commence_time": "2026-03-19T20:00:00Z",
            "team": "A",
            "sportsbook": "Book1",
        },
        {
            "sport": "basketball_nba",
            "ev_percentage": 1.2,
            "book_odds": 100,
            "commence_time": "2026-03-19T19:00:00Z",
            "team": "B",
            "sportsbook": "Book1",
        },
        {
            "sport": "soccer_epl",
            "ev_percentage": 5.0,
            "book_odds": 100,
            "commence_time": "2026-03-19T18:00:00Z",
            "team": "C",
            "sportsbook": "Book1",
        },
    ]

    out = build_eligible_autolog_sides(
        sides=sides,
        supported_sports={"basketball_nba"},
        low_edge_cohort="low",
        high_edge_cohort="high",
        low_edge_ev_min=0.5,
        low_edge_ev_max=1.5,
        low_edge_odds_min=-200,
        low_edge_odds_max=300,
        high_edge_ev_min=10.0,
        high_edge_odds_min=700,
    )

    assert len(out) == 2
    assert out[0]["team"] == "B"
    assert out[0]["strategy_cohort"] == "low"
    assert out[1]["team"] == "A"


def test_build_pending_autolog_keys_normalizes_components():
    keys = build_pending_autolog_keys(
        [
            {
                "strategy_cohort": "high",
                "clv_sport_key": "Basketball_NBA",
                "commence_time": "2026-03-19T20:00:00Z",
                "clv_team": "Lakers",
                "sportsbook": "DraftKings",
                "market": "ML",
            }
        ]
    )

    assert keys == {"v1|high|basketball_nba|2026-03-19T20:00:00Z|lakers|draftkings|ml"}


def test_build_pending_autolog_keys_prefers_event_id_and_keeps_legacy():
    keys = build_pending_autolog_keys(
        [
            {
                "strategy_cohort": "high",
                "clv_sport_key": "Basketball_NBA",
                "commence_time": "2026-03-19T20:00:00Z",
                "clv_event_id": "evt_777",
                "clv_team": "Lakers",
                "sportsbook": "DraftKings",
                "market": "ML",
            }
        ]
    )

    assert "v1|high|basketball_nba|id:evt_777|lakers|draftkings|ml" in keys
    assert "v1|high|basketball_nba|2026-03-19T20:00:00Z|lakers|draftkings|ml" in keys


def test_build_autolog_insert_payload_sets_fields_and_fallback_event_date():
    side = {
        "sport": "basketball_nba",
        "team": "Lakers",
        "sportsbook": "DraftKings",
        "book_odds": 120,
        "pinnacle_odds": 110,
        "true_prob": 0.52,
        "ev_percentage": 1.2,
    }

    payload = build_autolog_insert_payload(
        user_id="u1",
        side={**side, "event_id": "evt_333"},
        cohort="low",
        run_key="run|key",
        run_at="2026-03-19T00:00:00Z",
        paper_stake=10.0,
        pending_result_value="pending",
        fallback_event_date="2026-03-19",
    )

    assert payload["user_id"] == "u1"
    assert payload["sport"] == "NBA"
    assert payload["event"] == "Lakers ML"
    assert payload["event_date"] == "2026-03-19"
    assert payload["result"] == "pending"
    assert payload["strategy_cohort"] == "low"
    assert payload["auto_log_run_key"] == "run|key"
    assert payload["clv_event_id"] == "evt_333"


def test_run_autolog_insert_loop_applies_caps_duplicate_checks_and_counts():
    eligible = [
        {"strategy_cohort": "low", "sport": "basketball_nba", "team": "A", "sportsbook": "Book", "commence_time": "2026-03-19T20:00:00Z"},
        {"strategy_cohort": "low", "sport": "basketball_nba", "team": "B", "sportsbook": "Book", "commence_time": "2026-03-19T21:00:00Z"},
        {"strategy_cohort": "high", "sport": "basketball_nba", "team": "C", "sportsbook": "Book", "commence_time": "2026-03-19T22:00:00Z"},
    ]
    inserted = []
    existing = {"run-1|v1|low|basketball_nba|2026-03-19T21:00:00Z|b|book|ml"}

    out = run_autolog_insert_loop(
        eligible_sides=eligible,
        run_id="run-1",
        pending_keys=set(),
        low_edge_cohort="low",
        high_edge_cohort="high",
        max_total=2,
        max_low=2,
        max_high=3,
        build_run_payload=lambda side, cohort, run_key: {"team": side["team"], "cohort": cohort, "run_key": run_key},
        has_existing_run_key=lambda run_key: run_key in existing,
        insert_payload=lambda payload: inserted.append(payload),
    )

    assert out["inserted_total"] == 2
    assert out["inserted_by_cohort"] == {"low": 1, "high": 1}
    assert out["selected_by_cohort"] == {"low": 2, "high": 1}
    assert out["skipped_duplicate"] == 1
    assert out["skipped_rule"] == 0
    assert [p["team"] for p in inserted] == ["A", "C"]
