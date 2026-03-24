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
