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


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _resolve_win_payout(row: dict[str, Any]) -> float | None:
    locked = _coerce_float(row.get("win_payout_locked"))
    if locked is not None:
        return locked

    payout_override = _coerce_float(row.get("payout_override"))
    if payout_override is not None:
        return payout_override

    stake = _coerce_float(row.get("stake"))
    odds_american = _coerce_float(row.get("odds_american"))
    promo_type = str(row.get("promo_type") or "").strip()
    if stake is None or odds_american is None or not promo_type:
        return None

    decimal_odds = american_to_decimal(odds_american)
    ev_result = calculate_ev(
        stake=stake,
        decimal_odds=decimal_odds,
        promo_type=promo_type,
        boost_percent=_coerce_float(row.get("boost_percent")),
        winnings_cap=_coerce_float(row.get("winnings_cap")),
        true_prob=_coerce_float(row.get("true_prob_at_entry")),
    )
    return _coerce_float(ev_result.get("win_payout"))


def compute_balances_by_sportsbook_fast(
    *,
    transactions: list[dict[str, Any]],
    bets: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Fast path for balances using raw bet rows instead of full BetResponse objects."""
    sportsbook_data: dict[str, dict[str, float]] = {}

    for tx in transactions:
        book = str(tx.get("sportsbook") or "").strip()
        if not book:
            continue
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        amount = _coerce_float(tx.get("amount")) or 0.0
        if tx.get("type") == "deposit":
            sportsbook_data[book]["deposits"] += amount
        else:
            sportsbook_data[book]["withdrawals"] += amount

    for row in bets:
        book = str(row.get("sportsbook") or "").strip()
        if not book:
            continue
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0.0, "withdrawals": 0.0, "profit": 0.0, "pending": 0.0}

        result = str(row.get("result") or "").strip().lower()
        promo_type = str(row.get("promo_type") or "").strip()
        stake = _coerce_float(row.get("stake")) or 0.0

        if result == BetResult.PENDING.value:
            if promo_type != "bonus_bet":
                sportsbook_data[book]["pending"] += stake
            continue

        win_payout = _resolve_win_payout(row)
        if win_payout is None:
            continue

        real_profit = calculate_real_profit(
            stake=stake,
            win_payout=win_payout,
            result=result,
            promo_type=promo_type,
        )
        if real_profit is not None:
            sportsbook_data[book]["profit"] += real_profit

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
