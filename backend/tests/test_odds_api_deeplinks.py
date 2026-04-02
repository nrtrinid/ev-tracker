import httpx
import pytest


@pytest.mark.asyncio
async def test_scan_all_sides_includes_selection_level_sportsbook_deeplink_when_available(monkeypatch):
    from services import odds_api

    event = {
        "id": "evt_123",
        "sport_key": "basketball_nba",
        "home_team": "Warriors",
        "away_team": "Lakers",
        "commence_time": "2099-03-20T20:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Warriors", "price": -110},
                            {"name": "Lakers", "price": 100},
                        ],
                    }
                ],
            },
            {
                "key": "draftkings",
                "link": "https://sportsbook.example/dk/event/evt_123",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {
                                "name": "Warriors",
                                "price": -105,
                                "link": "https://sportsbook.example/dk/betslip/warriors",
                            },
                            {
                                "name": "Lakers",
                                "price": 115,
                                "link": "https://sportsbook.example/dk/betslip/lakers",
                            },
                        ],
                    }
                ],
            },
        ],
    }

    async def _fake_fetch_odds(_sport: str, source: str = "unknown"):
        assert source == "unit_test"
        req = httpx.Request("GET", "https://example.test")
        resp = httpx.Response(200, request=req, headers={"x-requests-remaining": "499"})
        return [event], resp

    monkeypatch.setattr(odds_api, "TARGET_BOOKS", {"draftkings": "DraftKings"}, raising=True)
    monkeypatch.setattr(odds_api, "fetch_odds", _fake_fetch_odds, raising=True)

    out = await odds_api.scan_all_sides("basketball_nba", source="unit_test")

    assert out["events_fetched"] == 1
    assert out["events_with_both_books"] == 1
    assert out["api_requests_remaining"] == "499"
    assert len(out["sides"]) == 2
    assert all(side["sportsbook"] == "DraftKings" for side in out["sides"])
    lakers_side = next(side for side in out["sides"] if side["team"] == "Lakers")
    warriors_side = next(side for side in out["sides"] if side["team"] == "Warriors")
    assert lakers_side["sportsbook_deeplink_url"] == "https://sportsbook.example/dk/betslip/lakers"
    assert lakers_side["sportsbook_deeplink_level"] == "selection"
    assert warriors_side["sportsbook_deeplink_url"] == "https://sportsbook.example/dk/betslip/warriors"
    assert warriors_side["sportsbook_deeplink_level"] == "selection"


@pytest.mark.asyncio
async def test_scan_all_sides_includes_spreads_and_totals_when_exact_lines_match(monkeypatch):
    from services import odds_api

    event = {
        "id": "evt_456",
        "sport_key": "basketball_nba",
        "home_team": "Bulls",
        "away_team": "Knicks",
        "commence_time": "2099-03-20T20:00:00Z",
        "bookmakers": [
            {
                "key": "pinnacle",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Bulls", "price": -110},
                            {"name": "Knicks", "price": 100},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {"name": "Bulls", "price": -110, "point": -4.5},
                            {"name": "Knicks", "price": -110, "point": 4.5},
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {"name": "Over", "price": -108, "point": 220.5},
                            {"name": "Under", "price": -112, "point": 220.5},
                        ],
                    },
                ],
            },
            {
                "key": "draftkings",
                "link": "https://sportsbook.example/dk/event/evt_456",
                "markets": [
                    {
                        "key": "h2h",
                        "outcomes": [
                            {"name": "Bulls", "price": -105},
                            {"name": "Knicks", "price": 115},
                        ],
                    },
                    {
                        "key": "spreads",
                        "outcomes": [
                            {
                                "name": "Bulls",
                                "price": -115,
                                "point": -4.5,
                                "link": "https://sportsbook.example/dk/spreads/bulls",
                            },
                            {
                                "name": "Knicks",
                                "price": -105,
                                "point": 4.5,
                                "link": "https://sportsbook.example/dk/spreads/knicks",
                            },
                        ],
                    },
                    {
                        "key": "totals",
                        "outcomes": [
                            {
                                "name": "Over",
                                "price": 100,
                                "point": 220.5,
                                "link": "https://sportsbook.example/dk/totals/over",
                            },
                            {
                                "name": "Under",
                                "price": -120,
                                "point": 220.5,
                                "link": "https://sportsbook.example/dk/totals/under",
                            },
                        ],
                    },
                ],
            },
        ],
    }

    async def _fake_fetch_odds(_sport: str, source: str = "unknown", **_kwargs):
        assert source == "unit_test"
        req = httpx.Request("GET", "https://example.test")
        resp = httpx.Response(200, request=req, headers={"x-requests-remaining": "498"})
        return [event], resp

    monkeypatch.setattr(odds_api, "TARGET_BOOKS", {"draftkings": "DraftKings"}, raising=True)
    monkeypatch.setattr(odds_api, "fetch_odds", _fake_fetch_odds, raising=True)

    out = await odds_api.scan_all_sides("basketball_nba", source="unit_test")

    assert out["events_fetched"] == 1
    assert out["events_with_both_books"] == 1
    assert len(out["sides"]) == 6

    bulls_spread = next(side for side in out["sides"] if side["market_key"] == "spreads" and side["team"] == "Bulls")
    over_total = next(side for side in out["sides"] if side["market_key"] == "totals" and side["selection_side"] == "over")

    assert bulls_spread["line_value"] == -4.5
    assert bulls_spread["selection_key"] == "evt_456|spreads|bulls|-4.5"
    assert bulls_spread["sportsbook_deeplink_url"] == "https://sportsbook.example/dk/spreads/bulls"
    assert bulls_spread["sportsbook_deeplink_level"] == "selection"

    assert over_total["line_value"] == 220.5
    assert over_total["selection_key"] == "evt_456|totals|over|220.5"
    assert over_total["sportsbook_deeplink_url"] == "https://sportsbook.example/dk/totals/over"
    assert over_total["sportsbook_deeplink_level"] == "selection"
