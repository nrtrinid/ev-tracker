from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from auth import get_current_user_unrestricted, is_valid_beta_invite_code


router = APIRouter()


class BetaAccessGrantRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=80)


@router.post("/beta/access/grant")
def grant_beta_access(
    payload: BetaAccessGrantRequest,
    user: dict = Depends(get_current_user_unrestricted),
):
    import main

    if not is_valid_beta_invite_code(payload.invite_code):
        raise HTTPException(status_code=403, detail="That invite code is not valid.")

    db = main.get_db()
    main.get_user_settings(db, user["id"])
    now_iso = main._utc_now_iso()
    db.table("settings").update(
        {
            "beta_access_granted": True,
            "beta_access_granted_at": now_iso,
            "beta_access_method": "invite_code",
            "updated_at": now_iso,
        }
    ).eq("user_id", user["id"]).execute()

    return {
        "ok": True,
        "granted": True,
    }
