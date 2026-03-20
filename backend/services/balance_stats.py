from typing import Any, Callable

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
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        if tx["type"] == "deposit":
            sportsbook_data[book]["deposits"] += float(tx["amount"])
        else:
            sportsbook_data[book]["withdrawals"] += float(tx["amount"])

    for row in bets:
        book = row["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        bet = build_bet_response(row, k_factor)

        if bet.result == BetResult.PENDING:
            if bet.promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += bet.stake
        elif bet.real_profit is not None:
            sportsbook_data[book]["profit"] += bet.real_profit

    balances: list[dict[str, Any]] = []
    for book, data in sorted(sportsbook_data.items()):
        net_deposits = data["deposits"] - data["withdrawals"]
        balance = net_deposits + data["profit"] - data["pending"]

        balances.append(
            {
                "sportsbook": book,
                "deposits": round(data["deposits"], 2),
                "withdrawals": round(data["withdrawals"], 2),
                "net_deposits": round(net_deposits, 2),
                "profit": round(data["profit"], 2),
                "pending": round(data["pending"], 2),
                "balance": round(balance, 2),
            }
        )

    return balances