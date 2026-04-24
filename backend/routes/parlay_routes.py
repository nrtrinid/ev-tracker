from typing import Any, Callable

from fastapi import APIRouter, Depends, HTTPException

from dependencies import require_current_user
from models import BetCreate, BetResponse, ParlaySlipCreate, ParlaySlipLogRequest, ParlaySlipResponse, ParlaySlipUpdate
from services.parlay_slips import (
    build_parlay_logged_bet_payload,
    build_parlay_slip_insert_payload,
    build_parlay_slip_update_payload,
    parlay_slip_row_to_response_payload,
    parlay_slip_rows_to_response_payloads,
)


router = APIRouter()


def _get_parlay_slip_row(*, slip_id: str, user_id: str, get_db: Callable[[], Any]) -> dict[str, Any]:
    db = get_db()
    result = (
        db.table("parlay_slips")
        .select("*")
        .eq("id", slip_id)
        .eq("user_id", user_id)
        .limit(1)
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=404, detail="Parlay slip not found")
    return result.data[0]


def list_parlay_slips_impl(
    *,
    user: dict,
    get_db: Callable[[], Any],
    build_response: Callable[[dict[str, Any]], Any],
):
    db = get_db()
    result = (
        db.table("parlay_slips")
        .select("*")
        .eq("user_id", user["id"])
        .order("updated_at", desc=True)
        .execute()
    )
    return [build_response(payload) for payload in parlay_slip_rows_to_response_payloads(result.data or [])]


def create_parlay_slip_impl(
    *,
    slip: ParlaySlipCreate,
    user: dict,
    get_db: Callable[[], Any],
    build_insert_payload: Callable[..., dict[str, Any]],
    build_response: Callable[[dict[str, Any]], Any],
    utc_now_iso: Callable[[], str],
):
    db = get_db()
    try:
        payload = build_insert_payload(user_id=user["id"], slip=slip, utc_now_iso=utc_now_iso)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    result = db.table("parlay_slips").insert(payload).execute()
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create parlay slip")
    return build_response(parlay_slip_row_to_response_payload(result.data[0]))


def update_parlay_slip_impl(
    *,
    slip_id: str,
    slip_update: ParlaySlipUpdate,
    user: dict,
    get_db: Callable[[], Any],
    build_update_payload: Callable[..., dict[str, Any]],
    build_response: Callable[[dict[str, Any]], Any],
    utc_now_iso: Callable[[], str],
):
    db = get_db()
    current_row = _get_parlay_slip_row(slip_id=slip_id, user_id=user["id"], get_db=get_db)
    if current_row.get("logged_bet_id"):
        raise HTTPException(status_code=409, detail="Logged parlay slips cannot be edited")

    try:
        payload = build_update_payload(
            slip_update=slip_update,
            sportsbook=current_row["sportsbook"],
            current_legs=current_row.get("legs_json") or [],
            utc_now_iso=utc_now_iso,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if not payload:
        return build_response(parlay_slip_row_to_response_payload(current_row))

    result = (
        db.table("parlay_slips")
        .update(payload)
        .eq("id", slip_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to update parlay slip")
    return build_response(parlay_slip_row_to_response_payload(result.data[0]))


def delete_parlay_slip_impl(
    *,
    slip_id: str,
    user: dict,
    get_db: Callable[[], Any],
):
    db = get_db()
    current_row = _get_parlay_slip_row(slip_id=slip_id, user_id=user["id"], get_db=get_db)
    if current_row.get("logged_bet_id"):
        raise HTTPException(status_code=409, detail="Logged parlay slips cannot be deleted")

    result = (
        db.table("parlay_slips")
        .delete()
        .eq("id", slip_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if result.status_code and result.status_code >= 400:
        raise HTTPException(status_code=500, detail="Failed to delete parlay slip")
    return {"deleted": True, "id": slip_id}


def log_parlay_slip_impl(
    *,
    slip_id: str,
    log_request: ParlaySlipLogRequest,
    user: dict,
    get_db: Callable[[], Any],
    build_logged_bet_payload_fn: Callable[..., dict[str, Any]],
    create_bet_fn: Callable[[BetCreate, dict], BetResponse],
    utc_now_iso: Callable[[], str],
):
    db = get_db()
    current_row = _get_parlay_slip_row(slip_id=slip_id, user_id=user["id"], get_db=get_db)
    if current_row.get("logged_bet_id"):
        raise HTTPException(status_code=409, detail="Parlay slip has already been logged")

    bet_payload = build_logged_bet_payload_fn(
        slip_row=current_row,
        log_request=log_request,
        utc_now_iso=utc_now_iso,
    )
    created_bet = create_bet_fn(BetCreate(**bet_payload), user)

    update_result = (
        db.table("parlay_slips")
        .update({
            "logged_bet_id": created_bet.id,
            "updated_at": utc_now_iso(),
        })
        .eq("id", slip_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if update_result.status_code and update_result.status_code >= 400:
        raise HTTPException(status_code=500, detail="Failed to link logged parlay slip")

    return created_bet


@router.get("/parlay-slips", response_model=list[ParlaySlipResponse])
def list_parlay_slips(user: dict = Depends(require_current_user)):
    import main

    return list_parlay_slips_impl(
        user=user,
        get_db=main.get_db,
        build_response=lambda payload: ParlaySlipResponse(**payload),
    )


@router.post("/parlay-slips", response_model=ParlaySlipResponse, status_code=201)
def create_parlay_slip(
    slip: ParlaySlipCreate,
    user: dict = Depends(require_current_user),
):
    import main

    return create_parlay_slip_impl(
        slip=slip,
        user=user,
        get_db=main.get_db,
        build_insert_payload=build_parlay_slip_insert_payload,
        build_response=lambda payload: ParlaySlipResponse(**payload),
        utc_now_iso=main._utc_now_iso,
    )


@router.patch("/parlay-slips/{slip_id}", response_model=ParlaySlipResponse)
def update_parlay_slip(
    slip_id: str,
    slip_update: ParlaySlipUpdate,
    user: dict = Depends(require_current_user),
):
    import main

    return update_parlay_slip_impl(
        slip_id=slip_id,
        slip_update=slip_update,
        user=user,
        get_db=main.get_db,
        build_update_payload=build_parlay_slip_update_payload,
        build_response=lambda payload: ParlaySlipResponse(**payload),
        utc_now_iso=main._utc_now_iso,
    )


@router.delete("/parlay-slips/{slip_id}")
def delete_parlay_slip(
    slip_id: str,
    user: dict = Depends(require_current_user),
):
    import main

    return delete_parlay_slip_impl(
        slip_id=slip_id,
        user=user,
        get_db=main.get_db,
    )


@router.post("/parlay-slips/{slip_id}/log", response_model=BetResponse)
def log_parlay_slip(
    slip_id: str,
    log_request: ParlaySlipLogRequest,
    user: dict = Depends(require_current_user),
):
    import main
    from services.bet_crud import create_bet_impl

    return log_parlay_slip_impl(
        slip_id=slip_id,
        log_request=log_request,
        user=user,
        get_db=main.get_db,
        build_logged_bet_payload_fn=build_parlay_logged_bet_payload,
        create_bet_fn=lambda bet, logged_user: create_bet_impl(main.get_db(), logged_user, bet),
        utc_now_iso=main._utc_now_iso,
    )
