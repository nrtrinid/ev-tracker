from typing import Any, Callable

from fastapi import HTTPException
from fastapi import APIRouter, Depends

from dependencies import require_current_user
from models import TransactionCreate, TransactionResponse


router = APIRouter()


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
        .order("created_at", desc=True)
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
    import main

    return main.create_transaction(transaction=transaction, user=user)


@router.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(
    sportsbook: str | None = None,
    user: dict = Depends(require_current_user),
):
    import main

    return main.list_transactions(sportsbook=sportsbook, user=user)


@router.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: str,
    user: dict = Depends(require_current_user),
):
    import main

    return main.delete_transaction(transaction_id=transaction_id, user=user)