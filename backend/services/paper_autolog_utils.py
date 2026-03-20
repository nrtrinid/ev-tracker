from typing import Any


def _normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def cohort_for_side(
    side: dict[str, Any],
    *,
    supported_sports: set[str],
    low_edge_cohort: str,
    high_edge_cohort: str,
    low_edge_ev_min: float,
    low_edge_ev_max: float,
    low_edge_odds_min: float,
    low_edge_odds_max: float,
    high_edge_ev_min: float,
    high_edge_odds_min: float,
) -> str | None:
    sport = _normalize_text(side.get("sport"))
    if sport not in supported_sports:
        return None

    try:
        ev = float(side.get("ev_percentage"))
        odds = float(side.get("book_odds"))
    except Exception:
        return None

    if low_edge_ev_min <= ev <= low_edge_ev_max and low_edge_odds_min <= odds <= low_edge_odds_max:
        return low_edge_cohort
    if ev >= high_edge_ev_min and odds >= high_edge_odds_min:
        return high_edge_cohort
    return None


def sport_display(sport_key: str) -> str:
    mapping = {
        "basketball_nba": "NBA",
        "basketball_ncaab": "NCAAB",
    }
    return mapping.get(sport_key, sport_key)


def autolog_key_for_side(side: dict[str, Any], cohort: str) -> str:
    return "|".join([
        "v1",
        cohort,
        _normalize_text(side.get("sport")),
        str(side.get("commence_time") or "").strip(),
        _normalize_text(side.get("team")),
        _normalize_text(side.get("sportsbook")),
        "ml",
    ])