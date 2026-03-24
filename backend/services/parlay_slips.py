from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any


ALLOWED_PARLAY_SURFACES = {"straight_bets", "player_props"}

SPORT_DISPLAY_MAP = {
    "americanfootball_nfl": "NFL",
    "basketball_nba": "NBA",
    "basketball_ncaab": "NCAAB",
    "baseball_mlb": "MLB",
    "icehockey_nhl": "NHL",
    "soccer_epl": "EPL",
    "mma_mixed_martial_arts": "MMA",
}


def _normalize_text(value: Any) -> str:
    return str(value or "").strip()


def _legs_from_payload(legs: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    return [dict(leg) for leg in (legs or [])]


def validate_parlay_slip_snapshot(*, sportsbook: str, legs: list[dict[str, Any]] | None) -> None:
    normalized_book = _normalize_text(sportsbook)
    if not normalized_book:
        raise ValueError("Parlay slip sportsbook is required")

    snapshot_legs = _legs_from_payload(legs)
    if not snapshot_legs:
        raise ValueError("Parlay slip must include at least one leg")

    seen_ids: set[str] = set()
    for leg in snapshot_legs:
        leg_id = _normalize_text(leg.get("id"))
        if not leg_id:
            raise ValueError("Each parlay slip leg must include an id")
        if leg_id in seen_ids:
            raise ValueError("Parlay slip cannot contain duplicate leg ids")
        seen_ids.add(leg_id)

        leg_surface = _normalize_text(leg.get("surface"))
        if leg_surface not in ALLOWED_PARLAY_SURFACES:
            raise ValueError("Parlay slip supports straight bets and player props only")

        leg_book = _normalize_text(leg.get("sportsbook"))
        if leg_book != normalized_book:
            raise ValueError("Parlay slip legs must all use the same sportsbook")


def build_parlay_slip_insert_payload(*, user_id: str, slip, utc_now_iso) -> dict[str, Any]:
    payload = slip.model_dump()
    validate_parlay_slip_snapshot(sportsbook=payload["sportsbook"], legs=payload["legs"])
    now = utc_now_iso()
    return {
        "user_id": user_id,
        "sportsbook": payload["sportsbook"],
        "stake": payload.get("stake"),
        "legs_json": payload["legs"],
        "warnings_json": payload.get("warnings") or [],
        "pricing_preview_json": payload.get("pricingPreview"),
        "updated_at": now,
    }


def build_parlay_slip_update_payload(
    *,
    slip_update,
    sportsbook: str,
    current_legs: list[dict[str, Any]] | None,
    utc_now_iso,
) -> dict[str, Any]:
    payload = slip_update.model_dump(exclude_unset=True)
    if not payload:
        return {}

    next_sportsbook = payload.get("sportsbook", sportsbook)
    next_legs = payload.get("legs")
    if next_legs is not None or "sportsbook" in payload:
        validate_parlay_slip_snapshot(
            sportsbook=next_sportsbook,
            legs=next_legs if next_legs is not None else current_legs,
        )

    update_payload: dict[str, Any] = {"updated_at": utc_now_iso()}
    if "sportsbook" in payload:
        update_payload["sportsbook"] = payload["sportsbook"]
    if "stake" in payload:
        update_payload["stake"] = payload["stake"]
    if "legs" in payload:
        update_payload["legs_json"] = payload["legs"]
    if "warnings" in payload:
        update_payload["warnings_json"] = payload["warnings"] or []
    if "pricingPreview" in payload:
        update_payload["pricing_preview_json"] = payload["pricingPreview"]
    return update_payload


def parlay_slip_row_to_response_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "sportsbook": row["sportsbook"],
        "stake": row.get("stake"),
        "legs": row.get("legs_json") or [],
        "warnings": row.get("warnings_json") or [],
        "pricingPreview": row.get("pricing_preview_json"),
        "logged_bet_id": row.get("logged_bet_id"),
    }


def parlay_slip_rows_to_response_payloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [parlay_slip_row_to_response_payload(row) for row in rows]


def derive_parlay_logged_sport(legs: list[dict[str, Any]]) -> str:
    unique_sports: list[str] = []
    for leg in legs:
        sport = _normalize_text(leg.get("sport"))
        if sport and sport not in unique_sports:
            unique_sports.append(sport)

    if len(unique_sports) == 1:
        return SPORT_DISPLAY_MAP.get(unique_sports[0], unique_sports[0])
    if len(unique_sports) > 1:
        return "Mixed"
    return "Other"


def derive_parlay_event_summary(*, sportsbook: str, legs: list[dict[str, Any]]) -> str:
    leg_count = len(legs)
    unique_events: list[str] = []
    for leg in legs:
        event = _normalize_text(leg.get("event"))
        if event and event not in unique_events:
            unique_events.append(event)

    if len(unique_events) == 1:
        return f"{leg_count}-leg {unique_events[0]} parlay"
    return f"{leg_count}-leg {sportsbook} parlay"


def derive_parlay_event_date(legs: list[dict[str, Any]]) -> date | None:
    kickoff_dates: list[date] = []
    for leg in legs:
        commence_time = _normalize_text(leg.get("commenceTime"))
        if not commence_time:
            continue
        try:
            kickoff = datetime.fromisoformat(commence_time.replace("Z", "+00:00"))
        except ValueError:
            continue
        kickoff_dates.append(kickoff.astimezone(UTC).date())

    if not kickoff_dates:
        return None
    return min(kickoff_dates)


def build_parlay_selection_meta(
    *,
    slip_id: str,
    sportsbook: str,
    legs: list[dict[str, Any]],
    warnings: list[dict[str, Any]],
    pricing_preview: dict[str, Any] | None,
    logged_at_iso: str,
) -> dict[str, Any]:
    return {
        "type": "parlay",
        "slip_id": slip_id,
        "sportsbook": sportsbook,
        "logged_at": logged_at_iso,
        "legs": legs,
        "warnings": warnings,
        "pricingPreview": pricing_preview,
    }


def build_parlay_logged_bet_payload(*, slip_row: dict[str, Any], log_request, utc_now_iso) -> dict[str, Any]:
    legs = _legs_from_payload(slip_row.get("legs_json") or slip_row.get("legs"))
    sportsbook = _normalize_text(slip_row.get("sportsbook"))
    warnings = list(slip_row.get("warnings_json") or slip_row.get("warnings") or [])
    pricing_preview = slip_row.get("pricing_preview_json") or slip_row.get("pricingPreview")
    inferred_sport = derive_parlay_logged_sport(legs)
    inferred_event = derive_parlay_event_summary(sportsbook=sportsbook, legs=legs)
    inferred_event_date = derive_parlay_event_date(legs)

    estimated_true_probability = None
    if isinstance(pricing_preview, dict) and pricing_preview.get("estimateAvailable"):
        try:
            estimated_true_probability = float(pricing_preview.get("estimatedTrueProbability"))
        except (TypeError, ValueError):
            estimated_true_probability = None

    payload = {
        "sport": _normalize_text(getattr(log_request, "sport", None)) or inferred_sport,
        "event": _normalize_text(getattr(log_request, "event", None)) or inferred_event,
        "market": "Parlay",
        "surface": "parlay",
        "sportsbook": sportsbook,
        "promo_type": log_request.promo_type.value,
        "odds_american": log_request.odds_american,
        "stake": log_request.stake,
        "boost_percent": log_request.boost_percent,
        "winnings_cap": log_request.winnings_cap,
        "notes": log_request.notes,
        "opposing_odds": log_request.opposing_odds,
        "payout_override": log_request.payout_override,
        "true_prob_at_entry": estimated_true_probability,
        "selection_meta": build_parlay_selection_meta(
            slip_id=str(slip_row["id"]),
            sportsbook=sportsbook,
            legs=legs,
            warnings=warnings,
            pricing_preview=pricing_preview if isinstance(pricing_preview, dict) else None,
            logged_at_iso=utc_now_iso(),
        ),
    }
    event_date = log_request.event_date or inferred_event_date
    if event_date is not None:
        payload["event_date"] = event_date.isoformat()
    return payload
