from typing import Any, Callable

from calculations import american_to_decimal, calculate_ev, calculate_real_profit
from models import BetResult


def compute_balances_by_sportsbook(
    *,
    transactions: list[dict[str, Any]],
    bets: list[dict[str, Any]],
    k_factor: float,
    build_bet_response: Callable[[dict[str, Any], float], Any],
) -> list[dict[str, Any]]:
    sportsbook_data: dict[str, dict[str, float]] = {}

    for tx in transactions:
        book = tx["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {
                "deposits": 0.0,
                "withdrawals": 0.0,
                "adjustments": 0.0,
                "profit": 0.0,
                "pending": 0.0,
            }

        if tx["type"] == "deposit":
            sportsbook_data[book]["deposits"] += float(tx["amount"])
        elif tx["type"] == "withdrawal":
            sportsbook_data[book]["withdrawals"] += float(tx["amount"])
        elif tx["type"] == "adjustment":
            sportsbook_data[book]["adjustments"] += float(tx["amount"])

    for row in bets:
        book = row["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {
                "deposits": 0.0,
                "withdrawals": 0.0,
                "adjustments": 0.0,
                "profit": 0.0,
                "pending": 0.0,
            }

        bet = build_bet_response(row, k_factor)

        if bet.result == BetResult.PENDING:
            if bet.promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += bet.stake
        elif bet.real_profit is not None:
            sportsbook_data[book]["profit"] += bet.real_profit

    balances: list[dict[str, Any]] = []
    for book, data in sorted(sportsbook_data.items()):
        net_deposits = data["deposits"] - data["withdrawals"]
        balance = net_deposits + data["adjustments"] + data["profit"] - data["pending"]

        balances.append(
            {
                "sportsbook": book,
                "deposits": round(data["deposits"], 2),
                "withdrawals": round(data["withdrawals"], 2),
                "adjustments": round(data["adjustments"], 2),
                "net_deposits": round(net_deposits, 2),
                "profit": round(data["profit"], 2),
                "pending": round(data["pending"], 2),
                "balance": round(balance, 2),
            }
        )

    return balances


def compute_balances_by_sportsbook_fast(
    *,
    transactions: list[dict[str, Any]],
    bets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compute balances directly from DB-like rows without building BetResponse objects."""
    sportsbook_data: dict[str, dict[str, float]] = {}

    for tx in transactions:
        book = tx["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {
                "deposits": 0.0,
                "withdrawals": 0.0,
                "adjustments": 0.0,
                "profit": 0.0,
                "pending": 0.0,
            }

        if tx["type"] == "deposit":
            sportsbook_data[book]["deposits"] += float(tx["amount"])
        elif tx["type"] == "withdrawal":
            sportsbook_data[book]["withdrawals"] += float(tx["amount"])
        elif tx["type"] == "adjustment":
            sportsbook_data[book]["adjustments"] += float(tx["amount"])

    for row in bets:
        book = str(row.get("sportsbook") or "")
        if not book:
            continue
        if book not in sportsbook_data:
            sportsbook_data[book] = {
                "deposits": 0.0,
                "withdrawals": 0.0,
                "adjustments": 0.0,
                "profit": 0.0,
                "pending": 0.0,
            }

        stake = float(row.get("stake") or 0.0)
        promo_type = str(row.get("promo_type") or "standard")
        result = str(row.get("result") or "").lower()

        if result == BetResult.PENDING.value:
            if promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += stake
            continue

        win_payout_raw = row.get("win_payout_locked")
        if win_payout_raw is None:
            win_payout_raw = row.get("payout_override")
        if win_payout_raw is None:
            odds = row.get("odds_american")
            if odds is not None:
                try:
                    ev_result = calculate_ev(
                        stake=stake,
                        decimal_odds=american_to_decimal(float(odds)),
                        promo_type=promo_type,
                        boost_percent=row.get("boost_percent"),
                        winnings_cap=row.get("winnings_cap"),
                        true_prob=row.get("true_prob_at_entry"),
                    )
                    win_payout_raw = ev_result.get("win_payout")
                except Exception:
                    win_payout_raw = 0.0

        win_payout = float(win_payout_raw or 0.0)
        real_profit = calculate_real_profit(
            stake=stake,
            win_payout=win_payout,
            result=result,
            promo_type=promo_type,
        )
        if real_profit is not None:
            sportsbook_data[book]["profit"] += float(real_profit)

    balances: list[dict[str, Any]] = []
    for book, data in sorted(sportsbook_data.items()):
        net_deposits = data["deposits"] - data["withdrawals"]
        balance = net_deposits + data["adjustments"] + data["profit"] - data["pending"]

        balances.append(
            {
                "sportsbook": book,
                "deposits": round(data["deposits"], 2),
                "withdrawals": round(data["withdrawals"], 2),
                "adjustments": round(data["adjustments"], 2),
                "net_deposits": round(net_deposits, 2),
                "profit": round(data["profit"], 2),
                "pending": round(data["pending"], 2),
                "balance": round(balance, 2),
            }
        )

    return balances
