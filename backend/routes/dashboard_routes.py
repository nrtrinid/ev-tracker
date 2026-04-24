"""Dashboard summary and balance HTTP routes."""

from fastapi import APIRouter, Depends

from auth import get_current_user
from database import get_db
from models import BalanceResponse, SummaryResponse
from services.balance_stats import compute_balances_by_sportsbook
from services.bet_crud import _retry_supabase, build_bet_response, get_user_settings
from services.summary_stats import summarize_bets


router = APIRouter()


@router.get("/summary", response_model=SummaryResponse)
def get_summary(user: dict = Depends(get_current_user)):
    """Get dashboard summary statistics."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    bets_result = _retry_supabase(
        lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute(),
        label="dashboard.bets.select_summary",
    )
    payload = summarize_bets(
        bets=bets_result.data or [],
        k_factor=settings["k_factor"],
        build_bet_response=build_bet_response,
    )
    return SummaryResponse(**payload)


@router.get("/balances", response_model=list[BalanceResponse])
def get_balances(user: dict = Depends(get_current_user)):
    """Get computed balance for each sportsbook."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    tx_result = _retry_supabase(
        lambda: db.table("transactions").select("*").eq("user_id", user["id"]).execute(),
        label="dashboard.transactions.select_balances",
    )
    bets_result = _retry_supabase(
        lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute(),
        label="dashboard.bets.select_balances",
    )
    payload = compute_balances_by_sportsbook(
        transactions=tx_result.data or [],
        bets=bets_result.data or [],
        k_factor=settings["k_factor"],
        build_bet_response=build_bet_response,
    )
    return [BalanceResponse(**row) for row in payload]
