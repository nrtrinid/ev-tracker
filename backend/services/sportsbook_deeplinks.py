from typing import Literal
from urllib.parse import urlparse, urlunparse


ScannerDeeplinkLevel = Literal["selection", "market", "event", "homepage"]

BETMGM_STATE_TEMPLATE_HOST = "sports.{state}.betmgm.com"
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
    try:
        parsed = urlparse(candidate)
    except Exception:
        return candidate

    netloc = parsed.netloc
    if not netloc:
        return candidate

    userinfo = ""
    hostport = netloc
    if "@" in hostport:
        userinfo, hostport = hostport.rsplit("@", 1)

    host = hostport
    port = ""
    if hostport.startswith("["):
        # IPv6 literals are not expected here, but keep parsing safe.
        closing = hostport.find("]")
        if closing >= 0:
            host = hostport[: closing + 1]
            port = hostport[closing + 1 :]
    elif ":" in hostport:
        maybe_host, maybe_port = hostport.rsplit(":", 1)
        if maybe_port.isdigit():
            host = maybe_host
            port = f":{maybe_port}"

    if host.lower() != BETMGM_STATE_TEMPLATE_HOST:
        return candidate

    canonical_netloc = f"{userinfo + '@' if userinfo else ''}{BETMGM_CANONICAL_HOST}{port}"
    return urlunparse(
        (parsed.scheme, canonical_netloc, parsed.path, parsed.params, parsed.query, parsed.fragment)
    )


def normalize_sportsbook_link(value: str | None) -> str | None:
    if not value:
        return None

    candidate = _canonicalize_betmgm_template_host(str(value).strip())
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
