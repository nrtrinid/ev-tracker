from typing import Any, Callable


def build_settings_update_payload(settings_update) -> dict[str, Any]:
    data: dict[str, Any] = {}
    if settings_update.k_factor is not None:
        data["k_factor"] = settings_update.k_factor
    if settings_update.default_stake is not None:
        data["default_stake"] = settings_update.default_stake
    if settings_update.preferred_sportsbooks is not None:
        data["preferred_sportsbooks"] = settings_update.preferred_sportsbooks
    if settings_update.k_factor_mode is not None:
        data["k_factor_mode"] = settings_update.k_factor_mode
    if settings_update.k_factor_min_stake is not None:
        data["k_factor_min_stake"] = settings_update.k_factor_min_stake
    if settings_update.k_factor_smoothing is not None:
        data["k_factor_smoothing"] = settings_update.k_factor_smoothing
    if settings_update.k_factor_clamp_min is not None:
        data["k_factor_clamp_min"] = settings_update.k_factor_clamp_min
    if settings_update.k_factor_clamp_max is not None:
        data["k_factor_clamp_max"] = settings_update.k_factor_clamp_max
    return data


def get_settings_impl(
    *,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    build_settings_response: Callable[[Any, str, dict], Any],
):
    db = get_db()
    settings = get_user_settings(db, user["id"])
    return build_settings_response(db, user["id"], settings)


def update_settings_impl(
    *,
    settings_update,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    build_settings_response: Callable[[Any, str, dict], Any],
    build_update_payload: Callable[[Any], dict[str, Any]],
    utc_now_iso: Callable[[], str],
):
    db = get_db()

    get_user_settings(db, user["id"])
    data = build_update_payload(settings_update)

    if data:
        data["updated_at"] = utc_now_iso()
        db.table("settings").update(data).eq("user_id", user["id"]).execute()

    updated = get_user_settings(db, user["id"])
    return build_settings_response(db, user["id"], updated)