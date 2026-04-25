from types import SimpleNamespace

from models import BetResult
from services.balance_stats import compute_balances_by_sportsbook, compute_balances_by_sportsbook_fast


def test_compute_balances_by_sportsbook_handles_transactions_and_bets():
    transactions = [
        {"sportsbook": "DraftKings", "type": "deposit", "amount": 100.0},
        {"sportsbook": "DraftKings", "type": "withdrawal", "amount": 20.0},
        {"sportsbook": "DraftKings", "type": "adjustment", "amount": 5.0},
        {"sportsbook": "FanDuel", "type": "deposit", "amount": 50.0},
        {"sportsbook": "FanDuel", "type": "adjustment", "amount": -10.0},
    ]

    bets = [
        {"id": "b1", "sportsbook": "DraftKings"},
        {"id": "b2", "sportsbook": "DraftKings"},
        {"id": "b3", "sportsbook": "FanDuel"},
        {"id": "b4", "sportsbook": "BetMGM"},
    ]

    fake = {
        "b1": SimpleNamespace(result=BetResult.PENDING, promo_type="standard", stake=10.0, real_profit=None),
        "b2": SimpleNamespace(result=BetResult.PENDING, promo_type="bonus_bet", stake=15.0, real_profit=None),
        "b3": SimpleNamespace(result=BetResult.WIN, promo_type="standard", stake=10.0, real_profit=5.0),
        "b4": SimpleNamespace(result=BetResult.LOSS, promo_type="standard", stake=10.0, real_profit=-7.5),
    }

    def _build_bet_response(row, _k_factor):
        return fake[row["id"]]

    out = compute_balances_by_sportsbook(
        transactions=transactions,
        bets=bets,
        k_factor=0.5,
        build_bet_response=_build_bet_response,
    )

    assert out == [
        {
            "sportsbook": "BetMGM",
            "deposits": 0.0,
            "withdrawals": 0.0,
            "adjustments": 0.0,
            "net_deposits": 0.0,
            "profit": -7.5,
            "pending": 0.0,
            "balance": -7.5,
        },
        {
            "sportsbook": "DraftKings",
            "deposits": 100.0,
            "withdrawals": 20.0,
            "adjustments": 5.0,
            "net_deposits": 80.0,
            "profit": 0.0,
            "pending": 10.0,
            "balance": 75.0,
        },
        {
            "sportsbook": "FanDuel",
            "deposits": 50.0,
            "withdrawals": 0.0,
            "adjustments": -10.0,
            "net_deposits": 50.0,
            "profit": 5.0,
            "pending": 0.0,
            "balance": 45.0,
        },
    ]


def test_compute_balances_by_sportsbook_returns_empty_for_no_data():
    out = compute_balances_by_sportsbook(
        transactions=[],
        bets=[],
        k_factor=0.5,
        build_bet_response=lambda row, k_factor: row,
    )
    assert out == []


def test_compute_balances_by_sportsbook_fast_handles_pending_and_settled_rows():
    transactions = [
        {"sportsbook": "DraftKings", "type": "deposit", "amount": 100.0},
        {"sportsbook": "DraftKings", "type": "withdrawal", "amount": 20.0},
        {"sportsbook": "DraftKings", "type": "adjustment", "amount": 5.0},
        {"sportsbook": "FanDuel", "type": "deposit", "amount": 50.0},
        {"sportsbook": "FanDuel", "type": "adjustment", "amount": -10.0},
    ]

    bets = [
        {
            "sportsbook": "DraftKings",
            "result": "pending",
            "promo_type": "standard",
            "stake": 10.0,
            "odds_american": -110,
            "boost_percent": None,
            "winnings_cap": None,
            "payout_override": None,
            "win_payout_locked": None,
            "true_prob_at_entry": None,
        },
        {
            "sportsbook": "DraftKings",
            "result": "pending",
            "promo_type": "bonus_bet",
            "stake": 15.0,
            "odds_american": 100,
            "boost_percent": None,
            "winnings_cap": None,
            "payout_override": None,
            "win_payout_locked": None,
            "true_prob_at_entry": None,
        },
        {
            "sportsbook": "FanDuel",
            "result": "win",
            "promo_type": "standard",
            "stake": 10.0,
            "odds_american": -110,
            "boost_percent": None,
            "winnings_cap": None,
            "payout_override": None,
            "win_payout_locked": 15.0,
            "true_prob_at_entry": None,
        },
        {
            "sportsbook": "BetMGM",
            "result": "loss",
            "promo_type": "standard",
            "stake": 7.5,
            "odds_american": -105,
            "boost_percent": None,
            "winnings_cap": None,
            "payout_override": None,
            "win_payout_locked": None,
            "true_prob_at_entry": None,
        },
    ]

    out = compute_balances_by_sportsbook_fast(transactions=transactions, bets=bets)

    assert out == [
        {
            "sportsbook": "BetMGM",
            "deposits": 0.0,
            "withdrawals": 0.0,
            "adjustments": 0.0,
            "net_deposits": 0.0,
            "profit": -7.5,
            "pending": 0.0,
            "balance": -7.5,
        },
        {
            "sportsbook": "DraftKings",
            "deposits": 100.0,
            "withdrawals": 20.0,
            "adjustments": 5.0,
            "net_deposits": 80.0,
            "profit": 0.0,
            "pending": 10.0,
            "balance": 75.0,
        },
        {
            "sportsbook": "FanDuel",
            "deposits": 50.0,
            "withdrawals": 0.0,
            "adjustments": -10.0,
            "net_deposits": 50.0,
            "profit": 5.0,
            "pending": 0.0,
            "balance": 45.0,
        },
    ]
