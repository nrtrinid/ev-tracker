from typing import Any, Callable

from fastapi import APIRouter, Depends

from dependencies import require_current_user
from models import PromoType


router = APIRouter()


def calculate_ev_preview_impl(
    *,
    odds_american: float,
    stake: float,
    promo_type,
    boost_percent: float | None,
    winnings_cap: float | None,
    user: dict,
    get_db: Callable[[], Any],
    get_user_settings: Callable[[Any, str], dict],
    american_to_decimal: Callable[[float], float],
    calculate_ev: Callable[..., dict[str, Any]],
) -> dict[str, Any]:
    db = get_db()
    settings = get_user_settings(db, user["id"])

    decimal_odds = american_to_decimal(odds_american)
    result = calculate_ev(
        stake=stake,
        decimal_odds=decimal_odds,
        promo_type=promo_type.value,
        k_factor=settings["k_factor"],
        boost_percent=boost_percent,
        winnings_cap=winnings_cap,
    )

    return {
        "odds_american": odds_american,
        "odds_decimal": decimal_odds,
        "stake": stake,
        "promo_type": promo_type.value,
        **result,
    }


@router.get("/calculate-ev")
def calculate_ev_preview(
    odds_american: float,
    stake: float,
    promo_type: PromoType,
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
    user: dict = Depends(require_current_user),
):
    import main

    return main.calculate_ev_preview(
        odds_american=odds_american,
        stake=stake,
        promo_type=promo_type,
        boost_percent=boost_percent,
        winnings_cap=winnings_cap,
        user=user,
    )