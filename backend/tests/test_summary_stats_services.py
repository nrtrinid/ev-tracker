from types import SimpleNamespace

from models import BetResult
from services.summary_stats import empty_summary_payload, summarize_bets


def test_empty_summary_payload_shape():
    payload = empty_summary_payload()
    assert payload["total_bets"] == 0
    assert payload["total_ev"] == 0.0
    assert payload["win_rate"] is None
    assert payload["ev_by_sportsbook"] == {}


def test_summarize_bets_returns_empty_payload_for_none_or_empty_list():
    assert summarize_bets(bets=None, k_factor=0.5, build_bet_response=lambda row, k: row) == empty_summary_payload()
    assert summarize_bets(bets=[], k_factor=0.5, build_bet_response=lambda row, k: row) == empty_summary_payload()


def test_summarize_bets_aggregates_totals_counts_and_breakdowns():
    rows = [{"id": "1"}, {"id": "2"}, {"id": "3"}]
    fake_responses = {
        "1": SimpleNamespace(
            ev_total=4.255,
            real_profit=10.0,
            result=BetResult.WIN,
            sportsbook="DraftKings",
            sport="basketball_nba",
        ),
        "2": SimpleNamespace(
            ev_total=1.334,
            real_profit=-5.0,
            result=BetResult.LOSS,
            sportsbook="DraftKings",
            sport="basketball_nba",
        ),
        "3": SimpleNamespace(
            ev_total=0.749,
            real_profit=None,
            result=BetResult.PENDING,
            sportsbook="FanDuel",
            sport="basketball_ncaab",
        ),
    }

    def _build_bet_response(row, _k_factor):
        return fake_responses[row["id"]]

    payload = summarize_bets(
        bets=rows,
        k_factor=0.5,
        build_bet_response=_build_bet_response,
    )

    assert payload["total_bets"] == 3
    assert payload["pending_bets"] == 1
    assert payload["total_ev"] == 6.34
    assert payload["total_real_profit"] == 5.0
    assert payload["variance"] == -1.34
    assert payload["win_count"] == 1
    assert payload["loss_count"] == 1
    assert payload["win_rate"] == 0.5

    assert payload["ev_by_sportsbook"] == {
        "DraftKings": 5.59,
        "FanDuel": 0.75,
    }
    assert payload["profit_by_sportsbook"] == {
        "DraftKings": 5.0,
    }
    assert payload["ev_by_sport"] == {
        "basketball_nba": 5.59,
        "basketball_ncaab": 0.75,
    }
