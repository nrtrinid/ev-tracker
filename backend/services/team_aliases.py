from __future__ import annotations

import re
from dataclasses import dataclass


_NON_ALNUM_RE = re.compile(r"[^a-z0-9\s]+")
_MULTISPACE_RE = re.compile(r"\s+")
_DIRECTION_MAP = {
    "n": "north",
    "s": "south",
    "e": "east",
    "w": "west",
    "ne": "northeast",
    "nw": "northwest",
    "se": "southeast",
    "sw": "southwest",
}


@dataclass(frozen=True)
class TeamAliasEntry:
    canonical_id: str
    full_name: str
    short_name: str
    aliases: tuple[str, ...]


TEAM_ALIASES_BY_SPORT: dict[str, tuple[TeamAliasEntry, ...]] = {
    "basketball_nba": (
        TeamAliasEntry("nba_atlanta_hawks", "Atlanta Hawks", "ATL", ("hawks",)),
        TeamAliasEntry("nba_boston_celtics", "Boston Celtics", "BOS", ("celtics",)),
        TeamAliasEntry("nba_brooklyn_nets", "Brooklyn Nets", "BKN", ("nets",)),
        TeamAliasEntry("nba_charlotte_hornets", "Charlotte Hornets", "CHA", ("hornets",)),
        TeamAliasEntry("nba_chicago_bulls", "Chicago Bulls", "CHI", ("bulls",)),
        TeamAliasEntry("nba_cleveland_cavaliers", "Cleveland Cavaliers", "CLE", ("cavaliers", "cavs")),
        TeamAliasEntry("nba_dallas_mavericks", "Dallas Mavericks", "DAL", ("mavericks", "mavs")),
        TeamAliasEntry("nba_denver_nuggets", "Denver Nuggets", "DEN", ("nuggets",)),
        TeamAliasEntry("nba_detroit_pistons", "Detroit Pistons", "DET", ("pistons",)),
        TeamAliasEntry("nba_golden_state_warriors", "Golden State Warriors", "GSW", ("warriors", "golden state")),
        TeamAliasEntry("nba_houston_rockets", "Houston Rockets", "HOU", ("rockets",)),
        TeamAliasEntry("nba_indiana_pacers", "Indiana Pacers", "IND", ("pacers",)),
        TeamAliasEntry("nba_los_angeles_clippers", "Los Angeles Clippers", "LAC", ("la clippers", "clippers")),
        TeamAliasEntry("nba_los_angeles_lakers", "Los Angeles Lakers", "LAL", ("la lakers", "lakers")),
        TeamAliasEntry("nba_memphis_grizzlies", "Memphis Grizzlies", "MEM", ("grizzlies",)),
        TeamAliasEntry("nba_miami_heat", "Miami Heat", "MIA", ("heat",)),
        TeamAliasEntry("nba_milwaukee_bucks", "Milwaukee Bucks", "MIL", ("bucks",)),
        TeamAliasEntry("nba_minnesota_timberwolves", "Minnesota Timberwolves", "MIN", ("timberwolves", "wolves")),
        TeamAliasEntry("nba_new_orleans_pelicans", "New Orleans Pelicans", "NOP", ("pelicans",)),
        TeamAliasEntry("nba_new_york_knicks", "New York Knicks", "NYK", ("knicks",)),
        TeamAliasEntry("nba_oklahoma_city_thunder", "Oklahoma City Thunder", "OKC", ("thunder",)),
        TeamAliasEntry("nba_orlando_magic", "Orlando Magic", "ORL", ("magic",)),
        TeamAliasEntry("nba_philadelphia_76ers", "Philadelphia 76ers", "PHI", ("sixers", "76ers")),
        TeamAliasEntry("nba_phoenix_suns", "Phoenix Suns", "PHX", ("suns",)),
        TeamAliasEntry("nba_portland_trail_blazers", "Portland Trail Blazers", "POR", ("blazers", "trail blazers")),
        TeamAliasEntry("nba_sacramento_kings", "Sacramento Kings", "SAC", ("kings",)),
        TeamAliasEntry("nba_san_antonio_spurs", "San Antonio Spurs", "SAS", ("spurs",)),
        TeamAliasEntry("nba_toronto_raptors", "Toronto Raptors", "TOR", ("raptors",)),
        TeamAliasEntry("nba_utah_jazz", "Utah Jazz", "UTA", ("jazz",)),
        TeamAliasEntry("nba_washington_wizards", "Washington Wizards", "WAS", ("wizards",)),
    ),
    "baseball_mlb": (
        TeamAliasEntry("mlb_arizona_diamondbacks", "Arizona Diamondbacks", "ARI", ("dbacks", "diamondbacks")),
        TeamAliasEntry("mlb_atlanta_braves", "Atlanta Braves", "ATL", ("braves",)),
        TeamAliasEntry("mlb_baltimore_orioles", "Baltimore Orioles", "BAL", ("orioles",)),
        TeamAliasEntry("mlb_boston_red_sox", "Boston Red Sox", "BOS", ("red sox",)),
        TeamAliasEntry("mlb_chicago_cubs", "Chicago Cubs", "CHC", ("cubs",)),
        TeamAliasEntry("mlb_chicago_white_sox", "Chicago White Sox", "CWS", ("white sox",)),
        TeamAliasEntry("mlb_cincinnati_reds", "Cincinnati Reds", "CIN", ("reds",)),
        TeamAliasEntry("mlb_cleveland_guardians", "Cleveland Guardians", "CLE", ("guardians",)),
        TeamAliasEntry("mlb_colorado_rockies", "Colorado Rockies", "COL", ("rockies",)),
        TeamAliasEntry("mlb_detroit_tigers", "Detroit Tigers", "DET", ("tigers",)),
        TeamAliasEntry("mlb_houston_astros", "Houston Astros", "HOU", ("astros",)),
        TeamAliasEntry("mlb_kansas_city_royals", "Kansas City Royals", "KC", ("royals",)),
        TeamAliasEntry("mlb_los_angeles_angels", "Los Angeles Angels", "LAA", ("la angels", "angels")),
        TeamAliasEntry("mlb_los_angeles_dodgers", "Los Angeles Dodgers", "LAD", ("la dodgers", "dodgers")),
        TeamAliasEntry("mlb_miami_marlins", "Miami Marlins", "MIA", ("marlins",)),
        TeamAliasEntry("mlb_milwaukee_brewers", "Milwaukee Brewers", "MIL", ("brewers",)),
        TeamAliasEntry("mlb_minnesota_twins", "Minnesota Twins", "MIN", ("twins",)),
        TeamAliasEntry("mlb_new_york_mets", "New York Mets", "NYM", ("mets",)),
        TeamAliasEntry("mlb_new_york_yankees", "New York Yankees", "NYY", ("yankees",)),
        TeamAliasEntry("mlb_oakland_athletics", "Oakland Athletics", "ATH", ("athletics", "oakland a's", "as")),
        TeamAliasEntry("mlb_philadelphia_phillies", "Philadelphia Phillies", "PHI", ("phillies",)),
        TeamAliasEntry("mlb_pittsburgh_pirates", "Pittsburgh Pirates", "PIT", ("pirates",)),
        TeamAliasEntry("mlb_san_diego_padres", "San Diego Padres", "SD", ("padres",)),
        TeamAliasEntry("mlb_san_francisco_giants", "San Francisco Giants", "SF", ("giants",)),
        TeamAliasEntry("mlb_seattle_mariners", "Seattle Mariners", "SEA", ("mariners",)),
        TeamAliasEntry("mlb_st_louis_cardinals", "St. Louis Cardinals", "STL", ("st louis", "cardinals")),
        TeamAliasEntry("mlb_tampa_bay_rays", "Tampa Bay Rays", "TB", ("rays",)),
        TeamAliasEntry("mlb_texas_rangers", "Texas Rangers", "TEX", ("rangers",)),
        TeamAliasEntry("mlb_toronto_blue_jays", "Toronto Blue Jays", "TOR", ("blue jays",)),
        TeamAliasEntry("mlb_washington_nationals", "Washington Nationals", "WSH", ("nationals", "nats")),
    ),
    "basketball_ncaab": (
        TeamAliasEntry("ncaab_duke_blue_devils", "Duke Blue Devils", "DUKE", ("duke",)),
        TeamAliasEntry(
            "ncaab_north_carolina_tar_heels",
            "North Carolina Tar Heels",
            "UNC",
            ("north carolina", "n carolina", "unc", "tar heels"),
        ),
        TeamAliasEntry("ncaab_uconn_huskies", "UConn Huskies", "UCONN", ("uconn", "connecticut", "huskies")),
        TeamAliasEntry(
            "ncaab_st_johns_red_storm",
            "St. John's Red Storm",
            "STJ",
            ("st johns", "st john's", "saint johns", "saint john's"),
        ),
        TeamAliasEntry("ncaab_kansas_jayhawks", "Kansas Jayhawks", "KU", ("kansas", "jayhawks")),
        TeamAliasEntry("ncaab_high_point_panthers", "High Point Panthers", "HPU", ("high point", "panthers")),
        TeamAliasEntry("ncaab_wisconsin_badgers", "Wisconsin Badgers", "WIS", ("wisconsin", "badgers")),
    ),
}


def _normalize_direction_token(token: str) -> str:
    return _DIRECTION_MAP.get(token, token)


def normalize_team_name(value: str | None) -> str:
    if not value:
        return ""
    lowered = str(value).strip().lower()
    lowered = lowered.replace("&", " and ")
    lowered = lowered.replace("'", "")
    lowered = lowered.replace(".", " ")
    lowered = lowered.replace("-", " ")
    lowered = lowered.replace("univ ", "university ")
    lowered = lowered.replace("univ.", "university")
    lowered = lowered.replace("university of ", "")
    lowered = lowered.replace("state university", "state")
    lowered = lowered.replace("st ", "saint ")
    lowered = _NON_ALNUM_RE.sub(" ", lowered)
    lowered = _MULTISPACE_RE.sub(" ", lowered).strip()
    if not lowered:
        return ""
    parts = [_normalize_direction_token(part) for part in lowered.split(" ")]
    return "".join(parts)


def _build_lookup() -> dict[str, dict[str, TeamAliasEntry]]:
    lookup: dict[str, dict[str, TeamAliasEntry]] = {}
    for sport_key, entries in TEAM_ALIASES_BY_SPORT.items():
        sport_lookup: dict[str, TeamAliasEntry] = {}
        for entry in entries:
            all_aliases = {entry.full_name, entry.short_name, *entry.aliases}
            for alias in all_aliases:
                token = normalize_team_name(alias)
                if not token:
                    continue
                existing = sport_lookup.get(token)
                if existing is not None and existing.canonical_id != entry.canonical_id:
                    raise ValueError(
                        f"Duplicate alias '{alias}' ({token}) for sport '{sport_key}' "
                        f"maps to both '{existing.canonical_id}' and '{entry.canonical_id}'."
                    )
                sport_lookup[token] = entry
        lookup[sport_key] = sport_lookup
    return lookup


_LOOKUP_BY_SPORT = _build_lookup()
_CANONICAL_IDS_BY_SPORT: dict[str, set[str]] = {
    sport_key: {entry.canonical_id for entry in entries}
    for sport_key, entries in TEAM_ALIASES_BY_SPORT.items()
}


def resolve_team_alias(sport_key: str | None, raw_name: str | None) -> str | None:
    value = str(raw_name or "").strip().lower()
    sport = str(sport_key or "").strip()
    if sport and value and value in _CANONICAL_IDS_BY_SPORT.get(sport, set()):
        return value
    token = normalize_team_name(raw_name)
    if not token:
        return None
    sport_lookup = _LOOKUP_BY_SPORT.get(sport)
    if sport_lookup and token in sport_lookup:
        return sport_lookup[token].canonical_id
    return None


def canonical_team_token(sport_key: str | None, raw_name: str | None) -> str:
    if not raw_name:
        return ""
    resolved = resolve_team_alias(sport_key, raw_name)
    if resolved:
        return resolved
    return normalize_team_name(raw_name)


def canonical_display_name(sport_key: str | None, raw_name: str | None) -> str:
    token = normalize_team_name(raw_name)
    if not token:
        return str(raw_name or "").strip()
    sport_lookup = _LOOKUP_BY_SPORT.get(str(sport_key or "").strip())
    if not sport_lookup:
        return str(raw_name or "").strip()
    entry = sport_lookup.get(token)
    return entry.full_name if entry else str(raw_name or "").strip()


def canonical_short_name(sport_key: str | None, raw_name: str | None) -> str:
    token = normalize_team_name(raw_name)
    if not token:
        return str(raw_name or "").strip()
    sport_lookup = _LOOKUP_BY_SPORT.get(str(sport_key or "").strip())
    if not sport_lookup:
        return str(raw_name or "").strip()
    entry = sport_lookup.get(token)
    return entry.short_name if entry else str(raw_name or "").strip()


def build_short_event_label(sport_key: str | None, away_team: str | None, home_team: str | None) -> str:
    away_short = canonical_short_name(sport_key, away_team)
    home_short = canonical_short_name(sport_key, home_team)
    if not away_short or not home_short:
        return f"{str(away_team or '').strip()} @ {str(home_team or '').strip()}".strip()
    return f"{away_short} @ {home_short}"
