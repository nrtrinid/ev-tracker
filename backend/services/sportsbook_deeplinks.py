from typing import Any, Literal
from urllib.parse import urlparse


ScannerDeeplinkLevel = Literal["selection", "market", "event", "homepage"]
NormalizationReason = Literal[
    "missing_input",
    "blank_input",
    "unresolved_template",
    "invalid_scheme",
    "missing_host",
    "ok",
]

BETMGM_TEMPLATE_HOST = "sports.{state}.betmgm.com"
BETMGM_CANONICAL_HOST = "sports.betmgm.com"


SPORTSBOOK_HOMEPAGES: dict[str, str] = {
    "BetMGM": "https://sports.betmgm.com/",
    "BetOnline.ag": "https://www.betonline.ag/sportsbook",
    "Bovada": "https://www.bovada.lv/sports",
    "Caesars": "https://www.caesars.com/sportsbook",
    "DraftKings": "https://sportsbook.draftkings.com/",
    "ESPN Bet": "https://sportsbook.thescore.bet/",
    "FanDuel": "https://sportsbook.fanduel.com/",
}


def _canonicalize_betmgm_template_host(candidate: str) -> str:
    """Canonicalize only the exact BetMGM template host to a usable host."""
    try:
        parsed = urlparse(candidate)
    except Exception:
        return candidate

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return candidate

    hostname = str(parsed.hostname or "").lower()
    if hostname != BETMGM_TEMPLATE_HOST:
        return candidate

    # Keep behavior strict and aligned with frontend normalization.
    if parsed.username is not None or parsed.password is not None:
        return candidate

    try:
        port = parsed.port
    except ValueError:
        return candidate

    netloc = BETMGM_CANONICAL_HOST
    if port is not None:
        netloc += f":{port}"

    return parsed._replace(netloc=netloc).geturl()


def _normalize_sportsbook_link_with_reason(value: str | None) -> tuple[str | None, NormalizationReason]:
    if value is None:
        return None, "missing_input"

    candidate = str(value).strip()
    if not candidate:
        return None, "blank_input"

    # Odds provider responses can include BetMGM's exact template host.
    # Canonicalize that one host only; all other brace templates stay invalid.
    candidate = _canonicalize_betmgm_template_host(candidate)

    # Preserve valid links exactly as provided (including real state hosts like
    # sports.nj.betmgm.com) while rejecting unresolved template placeholders.
    if not candidate or "{" in candidate or "}" in candidate:
        return None, "unresolved_template"

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None, "invalid_scheme"

    if parsed.scheme not in {"http", "https"}:
        return None, "invalid_scheme"
    if not parsed.netloc:
        return None, "missing_host"

    return candidate, "ok"


def normalize_sportsbook_link(value: str | None) -> str | None:
    normalized, _reason = _normalize_sportsbook_link_with_reason(value)
    return normalized


def debug_resolve_sportsbook_deeplink(
    *,
    sportsbook: str,
    selection_link: str | None = None,
    market_link: str | None = None,
    event_link: str | None = None,
) -> dict[str, Any]:
    attempts: list[dict[str, str | None]] = []
    selected_url: str | None = None
    selected_level: ScannerDeeplinkLevel | None = None

    for level, candidate in (
        ("selection", selection_link),
        ("market", market_link),
        ("event", event_link),
        ("homepage", SPORTSBOOK_HOMEPAGES.get(sportsbook)),
    ):
        normalized, reason = _normalize_sportsbook_link_with_reason(candidate)
        attempts.append(
            {
                "level": level,
                "input": candidate,
                "normalized": normalized,
                "reason": reason,
            }
        )
        if normalized:
            selected_url = normalized
            selected_level = level
            break

    return {
        "sportsbook": sportsbook,
        "selected_url": selected_url,
        "selected_level": selected_level,
        "attempts": attempts,
    }


def resolve_sportsbook_deeplink(
    *,
    sportsbook: str,
    selection_link: str | None = None,
    market_link: str | None = None,
    event_link: str | None = None,
) -> tuple[str | None, ScannerDeeplinkLevel | None]:
    trace = debug_resolve_sportsbook_deeplink(
        sportsbook=sportsbook,
        selection_link=selection_link,
        market_link=market_link,
        event_link=event_link,
    )
    return trace["selected_url"], trace["selected_level"]
