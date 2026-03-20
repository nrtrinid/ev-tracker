from typing import Any, Callable

from models import BetResult


def empty_summary_payload() -> dict[str, Any]:
    return {
        "total_bets": 0,
        "pending_bets": 0,
        "total_ev": 0.0,
        "total_real_profit": 0.0,
        "variance": 0.0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate": None,
        "ev_by_sportsbook": {},
        "profit_by_sportsbook": {},
        "ev_by_sport": {},
    }


def summarize_bets(
    *,
    bets: list[dict[str, Any]] | None,
    k_factor: float,
    build_bet_response: Callable[[dict[str, Any], float], Any],
) -> dict[str, Any]:
    if not bets:
        return empty_summary_payload()

    total_ev = 0.0
    total_real_profit = 0.0
    win_count = 0
    loss_count = 0
    pending_count = 0

    ev_by_sportsbook: dict[str, float] = {}
    profit_by_sportsbook: dict[str, float] = {}
    ev_by_sport: dict[str, float] = {}

    for row in bets:
        bet_response = build_bet_response(row, k_factor)

        total_ev += bet_response.ev_total
        if bet_response.real_profit is not None:
            total_real_profit += bet_response.real_profit

        if bet_response.result == BetResult.WIN:
            win_count += 1
        elif bet_response.result == BetResult.LOSS:
            loss_count += 1
        elif bet_response.result == BetResult.PENDING:
            pending_count += 1

        book = bet_response.sportsbook
        ev_by_sportsbook[book] = ev_by_sportsbook.get(book, 0.0) + bet_response.ev_total
        if bet_response.real_profit is not None:
            profit_by_sportsbook[book] = profit_by_sportsbook.get(book, 0.0) + bet_response.real_profit

        sport = bet_response.sport
        ev_by_sport[sport] = ev_by_sport.get(sport, 0.0) + bet_response.ev_total

    settled_count = win_count + loss_count
    win_rate = (win_count / settled_count) if settled_count > 0 else None

    return {
        "total_bets": len(bets),
        "pending_bets": pending_count,
        "total_ev": round(total_ev, 2),
        "total_real_profit": round(total_real_profit, 2),
        "variance": round(total_real_profit - total_ev, 2),
        "win_count": win_count,
        "loss_count": loss_count,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "ev_by_sportsbook": {k: round(v, 2) for k, v in ev_by_sportsbook.items()},
        "profit_by_sportsbook": {k: round(v, 2) for k, v in profit_by_sportsbook.items()},
        "ev_by_sport": {k: round(v, 2) for k, v in ev_by_sport.items()},
    }