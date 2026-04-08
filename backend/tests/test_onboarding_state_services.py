from services.onboarding_state import apply_onboarding_event, normalize_onboarding_state


def test_normalize_onboarding_state_resets_legacy_versions():
    out = normalize_onboarding_state(
        {
            "version": 1,
            "completed": ["tutorial_scanner_straight_bets"],
            "dismissed": ["parlay_builder"],
            "last_seen_at": None,
        },
        now_iso="2026-03-19T00:00:00Z",
        reset_legacy=True,
    )

    assert out == {
        "version": 2,
        "completed": [],
        "dismissed": [],
        "last_seen_at": "2026-03-19T00:00:00Z",
    }


def test_normalize_onboarding_state_filters_invalid_and_dedupes():
    out = normalize_onboarding_state(
        {
            "version": 2,
            "completed": [
                "tutorial_scanner_straight_bets",
                "tutorial_scanner_straight_bets",
                "unknown_step",
            ],
            "dismissed": [
                "tutorial_scanner_straight_bets",
                "scanner_review_prompt",
                "scanner_review_prompt",
                "unknown_step",
            ],
            "last_seen_at": "2026-03-18T00:00:00Z",
        },
        now_iso="2026-03-19T00:00:00Z",
        reset_legacy=True,
    )

    assert out == {
        "version": 2,
        "completed": ["tutorial_scanner_straight_bets"],
        "dismissed": ["scanner_review_prompt"],
        "last_seen_at": "2026-03-18T00:00:00Z",
    }


def test_apply_onboarding_event_transitions_complete_dismiss_and_reset():
    state = {
        "version": 2,
        "completed": [],
        "dismissed": [],
        "last_seen_at": "2026-03-18T00:00:00Z",
    }

    completed = apply_onboarding_event(
        state,
        event="complete_step",
        step="parlay_builder",
        now_iso="2026-03-19T00:00:00Z",
    )
    assert completed["completed"] == ["parlay_builder"]
    assert completed["dismissed"] == []

    dismissed = apply_onboarding_event(
        completed,
        event="dismiss_step",
        step="scanner_review_prompt",
        now_iso="2026-03-20T00:00:00Z",
    )
    assert dismissed["completed"] == ["parlay_builder"]
    assert dismissed["dismissed"] == ["scanner_review_prompt"]

    reset = apply_onboarding_event(
        dismissed,
        event="reset",
        step=None,
        now_iso="2026-03-21T00:00:00Z",
    )
    assert reset == {
        "version": 2,
        "completed": [],
        "dismissed": [],
        "last_seen_at": "2026-03-21T00:00:00Z",
    }
