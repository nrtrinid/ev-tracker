from services.team_aliases import (
    build_short_event_label,
    canonical_display_name,
    canonical_short_name,
    canonical_team_token,
    normalize_team_name,
    resolve_team_alias,
)


def test_normalize_team_name_handles_punctuation_and_directionals():
    assert normalize_team_name("N. Carolina") == "northcarolina"
    assert normalize_team_name("St. John's") == "saintjohns"


def test_resolve_team_alias_maps_common_nba_variants():
    assert resolve_team_alias("basketball_nba", "Los Angeles Lakers") == "nba_los_angeles_lakers"
    assert resolve_team_alias("basketball_nba", "LA Lakers") == "nba_los_angeles_lakers"
    assert canonical_short_name("basketball_nba", "Los Angeles Lakers") == "LAL"


def test_resolve_team_alias_maps_common_college_variants():
    assert resolve_team_alias("basketball_ncaab", "UNC") == "ncaab_north_carolina_tar_heels"
    assert resolve_team_alias("basketball_ncaab", "N. Carolina") == "ncaab_north_carolina_tar_heels"
    assert canonical_display_name("basketball_ncaab", "st johns") == "St. John's Red Storm"
    assert canonical_short_name("basketball_ncaab", "st johns") == "STJ"


def test_canonical_team_token_falls_back_for_unknown_teams():
    assert canonical_team_token("basketball_ncaab", "Some New Team") == "somenewteam"


def test_build_short_event_label_uses_team_short_names():
    short_label = build_short_event_label("basketball_nba", "Los Angeles Lakers", "Boston Celtics")
    assert short_label == "LAL @ BOS"
