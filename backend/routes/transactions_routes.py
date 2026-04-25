from typing import Any, Callable

from fastapi import HTTPException
from fastapi import APIRouter, Depends

from database import get_db
from dependencies import require_current_user
from models import TransactionCreate, TransactionResponse
from services.balance_stats import compute_balances_by_sportsbook
from services.bet_crud import _retry_supabase, build_bet_response, get_user_settings
from services.transaction_records import (
    build_transaction_insert_payload,
    transaction_row_to_response_payload,
    transaction_rows_to_response_payloads,
    transaction_type_value,
    validate_transaction_against_balance,
)


router = APIRouter()


def current_sportsbook_balance(*, db, user_id: str, sportsbook: str) -> float:
    settings = get_user_settings(db, user_id)
    tx_result = _retry_supabase(
        lambda: db.table("transactions").select("*").eq("user_id", user_id).execute(),
        label="transactions.select_for_balance_validation",
    )
    bets_result = _retry_supabase(
        lambda: db.table("bets").select("*").eq("user_id", user_id).execute(),
        label="transactions.bets_for_balance_validation",
    )
    balances = compute_balances_by_sportsbook(
        transactions=tx_result.data or [],
        bets=bets_result.data or [],
        k_factor=settings["k_factor"],
        build_bet_response=build_bet_response,
    )
    for row in balances:
        if row["sportsbook"] == sportsbook:
            return float(row["balance"])
    return 0.0


def create_transaction_impl(
    *,
    transaction,
    user: dict,
    get_db: Callable[[], Any],
    build_insert_payload: Callable[..., dict],
    map_row_to_response_payload: Callable[[dict], dict],
    build_transaction_response: Callable[[dict], Any],
):
    db = get_db()
    current_balance = 0.0
    if transaction_type_value(transaction) in {"withdrawal", "adjustment"}:
        current_balance = current_sportsbook_balance(
            db=db,
            user_id=user["id"],
            sportsbook=transaction.sportsbook,
        )
    try:
        validate_transaction_against_balance(
            transaction=transaction,
            current_balance=current_balance,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    data = build_insert_payload(user_id=user["id"], transaction=transaction)
    result = db.table("transactions").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create transaction")

    return build_transaction_response(map_row_to_response_payload(result.data[0]))


def list_transactions_impl(
    *,
    sportsbook: str | None,
    user: dict,
    get_db: Callable[[], Any],
    map_rows_to_response_payloads: Callable[[list[dict]], list[dict]],
    build_transaction_response: Callable[[dict], Any],
):
    db = get_db()

    query = (
        db.table("transactions")
        .select("*")
        .eq("user_id", user["id"])
        .order("transaction_date", desc=True)
    )

    if sportsbook:
        query = query.eq("sportsbook", sportsbook)

    result = query.execute()
    payload = map_rows_to_response_payloads(result.data)
    return [build_transaction_response(row) for row in payload]


def delete_transaction_impl(
    *,
    transaction_id: str,
    user: dict,
    get_db: Callable[[], Any],
):
    db = get_db()
    result = (
        db.table("transactions")
        .delete()
        .eq("id", transaction_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if result.status_code and result.status_code >= 400:
        raise HTTPException(status_code=500, detail="Failed to delete transaction")

    if not result.data:
        raise HTTPException(status_code=404, detail="Transaction not found")

    return {"deleted": True, "id": transaction_id}


@router.post("/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(
    transaction: TransactionCreate,
    user: dict = Depends(require_current_user),
):
    return create_transaction_impl(
        transaction=transaction,
        user=user,
        get_db=get_db,
        build_insert_payload=build_transaction_insert_payload,
        map_row_to_response_payload=transaction_row_to_response_payload,
        build_transaction_response=lambda payload: TransactionResponse(**payload),
    )


@router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    sportsbook: str | None = None,
    user: dict = Depends(require_current_user),
):
    return list_transactions_impl(
        sportsbook=sportsbook,
        user=user,
        get_db=get_db,
        map_rows_to_response_payloads=lambda rows: transaction_rows_to_response_payloads(rows or []),
        build_transaction_response=lambda payload: TransactionResponse(**payload),
    )


@router.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: str,
    user: dict = Depends(require_current_user),
):
    return delete_transaction_impl(
        transaction_id=transaction_id,
        user=user,
        get_db=get_db,
    )
