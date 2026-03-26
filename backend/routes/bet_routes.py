"""Bet CRUD HTTP routes.

Extracted from main.py to reduce monolith size.
All business logic lives in services/bet_crud.py.
"""

from fastapi import APIRouter, Depends

from auth import get_current_user
from database import get_db
from models import BetCreate, BetResult, BetResponse, BetUpdate
from services.bet_crud import (
    create_bet_impl,
    delete_bet_impl,
    get_bet_impl,
    get_bets_impl,
    update_bet_impl,
    update_bet_result_impl,
)

router = APIRouter()


@router.post("/bets", response_model=BetResponse, status_code=201)
def create_bet(bet: BetCreate, user: dict = Depends(get_current_user)):
    """Create a new bet."""
    return create_bet_impl(get_db(), user, bet)


@router.get("/bets", response_model=list[BetResponse])
def get_bets(
    sport: str | None = None,
    sportsbook: str | None = None,
    result: BetResult | None = None,
    limit: int = 1000,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get all bets with optional filters."""
    return get_bets_impl(get_db(), user, sport, sportsbook, result, limit, offset)


@router.get("/bets/{bet_id}", response_model=BetResponse)
def get_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Get a single bet by ID."""
    return get_bet_impl(get_db(), user, bet_id)


@router.patch("/bets/{bet_id}", response_model=BetResponse)
def update_bet(bet_id: str, bet: BetUpdate, user: dict = Depends(get_current_user)):
    """Update an existing bet."""
    return update_bet_impl(get_db(), user, bet_id, bet)


@router.patch("/bets/{bet_id}/result")
def update_bet_result(
    bet_id: str,
    result: BetResult,
    user: dict = Depends(get_current_user),
):
    """Quick endpoint to just update bet result (win/loss)."""
    return update_bet_result_impl(get_db(), user, bet_id, result)


@router.delete("/bets/{bet_id}")
def delete_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Delete a bet."""
    return delete_bet_impl(get_db(), user, bet_id)
