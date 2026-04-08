"""Onboarding state normalization and transition helpers."""

from __future__ import annotations

from typing import Any

ONBOARDING_VERSION = 2

ONBOARDING_STEP_IDS: tuple[str, ...] = (
    "tutorial_scanner_straight_bets",
    "home_scanner_review",
    "scanner_review_prompt",
    "parlay_builder",
    "parlay_one_leg_prompt",
)

ONBOARDING_EVENTS: tuple[str, ...] = (
    "complete_step",
    "dismiss_step",
    "reset",
)


def is_valid_onboarding_step(step: str) -> bool:
    return step in ONBOARDING_STEP_IDS


def is_valid_onboarding_event(event: str) -> bool:
    return event in ONBOARDING_EVENTS


def _unique_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        unique.append(value)
    return unique


def _sanitize_steps(raw: Any) -> list[str]:
    if not isinstance(raw, list):
        return []
    steps = [
        step
        for step in raw
        if isinstance(step, str) and is_valid_onboarding_step(step)
    ]
    return _unique_preserve_order(steps)


def default_onboarding_state(now_iso: str) -> dict[str, Any]:
    return {
        "version": ONBOARDING_VERSION,
        "completed": [],
        "dismissed": [],
        "last_seen_at": now_iso,
    }


def normalize_onboarding_state(
    payload: Any,
    *,
    now_iso: str,
    reset_legacy: bool = True,
) -> dict[str, Any]:
    """Normalize onboarding payload and optionally reset legacy versions.

    If reset_legacy=True, any non-v2 state is reset to the v2 default.
    """
    if not isinstance(payload, dict):
        return default_onboarding_state(now_iso)

    version = payload.get("version")
    if version != ONBOARDING_VERSION and reset_legacy:
        return default_onboarding_state(now_iso)

    completed = _sanitize_steps(payload.get("completed"))
    dismissed = _sanitize_steps(payload.get("dismissed"))
    dismissed = [step for step in dismissed if step not in completed]

    last_seen_at = payload.get("last_seen_at")
    if not isinstance(last_seen_at, str) or not last_seen_at:
        last_seen_at = now_iso

    return {
        "version": ONBOARDING_VERSION,
        "completed": completed,
        "dismissed": dismissed,
        "last_seen_at": last_seen_at,
    }


def apply_onboarding_event(
    current_state: dict[str, Any],
    *,
    event: str,
    step: str | None,
    now_iso: str,
) -> dict[str, Any]:
    """Apply a validated event to onboarding state."""
    if event == "reset":
        return default_onboarding_state(now_iso)

    completed = list(current_state.get("completed") or [])
    dismissed = list(current_state.get("dismissed") or [])

    if event == "complete_step" and step:
        if step not in completed:
            completed.append(step)
        dismissed = [item for item in dismissed if item != step]
    elif event == "dismiss_step" and step:
        if step not in completed and step not in dismissed:
            dismissed.append(step)

    return {
        "version": ONBOARDING_VERSION,
        "completed": completed,
        "dismissed": dismissed,
        "last_seen_at": now_iso,
    }
