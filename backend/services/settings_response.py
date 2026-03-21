from typing import Any, Callable


def build_settings_response(
    *,
    db,
    user_id: str,
    settings: dict[str, Any],
    default_sportsbooks: list[str],
    compute_k_user: Callable[[Any, str], dict[str, Any]],
    build_effective_k: Callable[[dict[str, Any], float, float], dict[str, Any]],
    settings_response_cls,
):
    k_data = compute_k_user(db, user_id)
    k_derived = build_effective_k(settings, k_data["k_obs"], k_data["bonus_stake_settled"])
    return settings_response_cls(
        k_factor=settings["k_factor"],
        default_stake=settings.get("default_stake"),
        preferred_sportsbooks=settings.get("preferred_sportsbooks") or default_sportsbooks,
        k_factor_mode=settings.get("k_factor_mode") or "baseline",
        k_factor_min_stake=float(settings.get("k_factor_min_stake") or 300.0),
        k_factor_smoothing=float(settings.get("k_factor_smoothing") or 700.0),
        k_factor_clamp_min=float(settings.get("k_factor_clamp_min") or 0.50),
        k_factor_clamp_max=float(settings.get("k_factor_clamp_max") or 0.95),
        onboarding_state=settings.get("onboarding_state"),
        **k_derived,
    )
