from typing import Any


def normalize_text(value: str | None) -> str:
    return (value or "").strip().lower()


def team_from_bet_row(row: dict[str, Any]) -> str:
    team = normalize_text(row.get("clv_team"))
    if team:
        return team
    event = str(row.get("event") or "").strip()
    if event.upper().endswith(" ML"):
        return normalize_text(event[:-3])
    return ""


def scanner_match_key_from_side(side: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        normalize_text(side.get("sport")),
        str(side.get("commence_time") or "").strip(),
        "ml",
        normalize_text(side.get("team")),
        normalize_text(side.get("sportsbook")),
    )


def scanner_match_key_from_bet(row: dict[str, Any]) -> tuple[str, str, str, str, str]:
    return (
        normalize_text(row.get("clv_sport_key") or row.get("sport")),
        str(row.get("commence_time") or "").strip(),
        normalize_text(row.get("market")),
        team_from_bet_row(row),
        normalize_text(row.get("sportsbook")),
    )


def alert_key_from_side(side: dict[str, Any]) -> str:
    sport = str(side.get("sport", ""))
    commence = str(side.get("commence_time", ""))
    event = str(side.get("event", ""))
    sportsbook = str(side.get("sportsbook", ""))
    team = str(side.get("team", ""))
    return "|".join([sport, commence, event, sportsbook, team])
