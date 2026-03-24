from typing import Literal
from urllib.parse import urlparse


ScannerDeeplinkLevel = Literal["selection", "market", "event", "homepage"]


SPORTSBOOK_HOMEPAGES: dict[str, str] = {
    "BetMGM": "https://sports.betmgm.com/",
    "BetOnline.ag": "https://www.betonline.ag/sportsbook",
    "Bovada": "https://www.bovada.lv/sports",
    "Caesars": "https://www.caesars.com/sportsbook",
    "DraftKings": "https://sportsbook.draftkings.com/",
    "ESPN Bet": "https://sportsbook.thescore.bet/",
    "FanDuel": "https://sportsbook.fanduel.com/",
}


def normalize_sportsbook_link(value: str | None) -> str | None:
    if not value:
        return None

    candidate = str(value).strip()
    if not candidate or "{" in candidate or "}" in candidate:
        return None

    try:
        parsed = urlparse(candidate)
    except Exception:
        return None

    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    return candidate


def resolve_sportsbook_deeplink(
    *,
    sportsbook: str,
    selection_link: str | None = None,
    market_link: str | None = None,
    event_link: str | None = None,
) -> tuple[str | None, ScannerDeeplinkLevel | None]:
    for level, candidate in (
        ("selection", selection_link),
        ("market", market_link),
        ("event", event_link),
        ("homepage", SPORTSBOOK_HOMEPAGES.get(sportsbook)),
    ):
        normalized = normalize_sportsbook_link(candidate)
        if normalized:
            return normalized, level

    return None, None
