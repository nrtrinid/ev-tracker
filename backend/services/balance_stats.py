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


def compute_balances_by_sportsbook_fast(
    *,
    transactions: list[dict[str, Any]],
    bets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Compute balances without constructing full BetResponse objects.

    This is intended for the `/balances` endpoint to reduce CPU + memory
    pressure on small instances.
    """
    from calculations import american_to_decimal, calculate_ev, calculate_real_profit

    sportsbook_data: dict[str, dict[str, float]] = {}

    for tx in transactions:
        book = tx.get("sportsbook")
        if not book:
            continue
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        if tx.get("type") == "deposit":
            sportsbook_data[book]["deposits"] += float(tx.get("amount") or 0)
        else:
            sportsbook_data[book]["withdrawals"] += float(tx.get("amount") or 0)

    for row in bets:
        book = row.get("sportsbook")
        if not book:
            continue
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        promo_type = str(row.get("promo_type") or "standard")
        result = str(row.get("result") or "")
        stake = float(row.get("stake") or 0)

        if result == BetResult.PENDING.value:
            if promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += stake
            continue

        win_payout = row.get("payout_override") or row.get("win_payout_locked")
        if win_payout is None:
            try:
                odds_american = float(row.get("odds_american") or 0)
                decimal_odds = american_to_decimal(odds_american)
                ev_out = calculate_ev(
                    stake=stake,
                    decimal_odds=decimal_odds,
                    promo_type=promo_type,
                    boost_percent=row.get("boost_percent"),
                    winnings_cap=row.get("winnings_cap"),
                    true_prob=row.get("true_prob_at_entry"),
                )
                win_payout = ev_out.get("win_payout")
            except Exception:
                win_payout = 0.0

        profit = calculate_real_profit(
            stake=stake,
            win_payout=float(win_payout or 0),
            result=result,
            promo_type=promo_type,
        )
        if profit is not None:
            sportsbook_data[book]["profit"] += float(profit)

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