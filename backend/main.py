"""
EV Tracker API
FastAPI backend for sports betting EV tracking.
"""

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
import os
from dotenv import load_dotenv

from models import (
    BetCreate, BetUpdate, BetResponse, BetResult, PromoType,
    SettingsUpdate, SettingsResponse, SummaryResponse,
    TransactionCreate, TransactionResponse, BalanceResponse
)
from calculations import american_to_decimal, calculate_ev, calculate_real_profit

load_dotenv()

app = FastAPI(
    title="EV Tracker API",
    description="Track sports betting Expected Value",
    version="1.0.0"
)

# CORS - allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import database after app setup to avoid circular imports
from database import get_db

# In-memory settings (in production, store in Supabase)
user_settings = {
    "k_factor": 0.78,
    "default_stake": None,
    "preferred_sportsbooks": [
        "DraftKings", "FanDuel", "BetMGM", "Caesars",
        "ESPN Bet", "Fanatics", "Hard Rock", "bet365"
    ]
}


def build_bet_response(row: dict, k_factor: float) -> BetResponse:
    """Convert database row to BetResponse with calculated fields."""
    decimal_odds = american_to_decimal(row["odds_american"])
    
    ev_result = calculate_ev(
        stake=row["stake"],
        decimal_odds=decimal_odds,
        promo_type=row["promo_type"],
        k_factor=k_factor,
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
    )
    
    # Use payout override if present
    win_payout = row.get("payout_override") or ev_result["win_payout"]
    
    real_profit = calculate_real_profit(
        stake=row["stake"],
        win_payout=win_payout,
        result=row["result"],
        promo_type=row["promo_type"],
    )
    
    return BetResponse(
        id=row["id"],
        created_at=row["created_at"],
        event_date=row["event_date"],
        settled_at=row.get("settled_at"),
        sport=row["sport"],
        event=row["event"],
        market=row["market"],
        sportsbook=row["sportsbook"],
        promo_type=row["promo_type"],
        odds_american=row["odds_american"],
        odds_decimal=decimal_odds,
        stake=row["stake"],
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
        notes=row.get("notes"),
        result=row["result"],
        win_payout=win_payout,
        ev_per_dollar=ev_result["ev_per_dollar"],
        ev_total=ev_result["ev_total"],
        real_profit=real_profit,
    )


# ============ Health Check ============

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}


# ============ Bets CRUD ============

@app.post("/bets", response_model=BetResponse)
def create_bet(bet: BetCreate):
    """Create a new bet."""
    db = get_db()
    
    data = {
        "sport": bet.sport,
        "event": bet.event,
        "market": bet.market,
        "sportsbook": bet.sportsbook,
        "promo_type": bet.promo_type.value,
        "odds_american": bet.odds_american,
        "stake": bet.stake,
        "boost_percent": bet.boost_percent,
        "winnings_cap": bet.winnings_cap,
        "notes": bet.notes,
        "payout_override": bet.payout_override,
        "result": BetResult.PENDING.value,
    }
    
    # Only include event_date if provided, otherwise let DB default to today
    if bet.event_date:
        data["event_date"] = bet.event_date.isoformat()
    
    result = db.table("bets").insert(data).execute()
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create bet")
    
    return build_bet_response(result.data[0], user_settings["k_factor"])


@app.get("/bets", response_model=list[BetResponse])
def get_bets(
    sport: str | None = None,
    sportsbook: str | None = None,
    result: BetResult | None = None,
    limit: int = 1000,
    offset: int = 0,
):
    """Get all bets with optional filters."""
    db = get_db()
    
    query = db.table("bets").select("*").order("created_at", desc=True)
    
    if sport:
        query = query.eq("sport", sport)
    if sportsbook:
        query = query.eq("sportsbook", sportsbook)
    if result:
        query = query.eq("result", result.value)
    
    query = query.range(offset, offset + limit - 1)
    
    response = query.execute()
    
    return [build_bet_response(row, user_settings["k_factor"]) for row in response.data]


@app.get("/bets/{bet_id}", response_model=BetResponse)
def get_bet(bet_id: str):
    """Get a single bet by ID."""
    db = get_db()
    
    result = db.table("bets").select("*").eq("id", bet_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    
    return build_bet_response(result.data[0], user_settings["k_factor"])


@app.patch("/bets/{bet_id}", response_model=BetResponse)
def update_bet(bet_id: str, bet: BetUpdate):
    """Update an existing bet."""
    db = get_db()
    
    # Build update data, excluding None values
    data = {}
    if bet.sport is not None:
        data["sport"] = bet.sport
    if bet.event is not None:
        data["event"] = bet.event
    if bet.market is not None:
        data["market"] = bet.market
    if bet.sportsbook is not None:
        data["sportsbook"] = bet.sportsbook
    if bet.promo_type is not None:
        data["promo_type"] = bet.promo_type.value
    if bet.odds_american is not None:
        data["odds_american"] = bet.odds_american
    if bet.stake is not None:
        data["stake"] = bet.stake
    if bet.boost_percent is not None:
        data["boost_percent"] = bet.boost_percent
    if bet.winnings_cap is not None:
        data["winnings_cap"] = bet.winnings_cap
    if bet.notes is not None:
        data["notes"] = bet.notes
    if bet.result is not None:
        data["result"] = bet.result.value
        # Auto-set settled_at when result changes from pending
        # First check if current result is pending
        current = db.table("bets").select("result").eq("id", bet_id).execute()
        if current.data and current.data[0]["result"] == "pending" and bet.result.value != "pending":
            data["settled_at"] = datetime.utcnow().isoformat()
    if bet.payout_override is not None:
        data["payout_override"] = bet.payout_override
    if bet.event_date is not None:
        data["event_date"] = bet.event_date.isoformat()
    
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    
    result = db.table("bets").update(data).eq("id", bet_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    
    return build_bet_response(result.data[0], user_settings["k_factor"])


@app.patch("/bets/{bet_id}/result")
def update_bet_result(bet_id: str, result: BetResult):
    """Quick endpoint to just update bet result (win/loss)."""
    db = get_db()
    
    # Build update data
    update_data = {"result": result.value}
    
    # Auto-set settled_at when changing from pending to settled
    current = db.table("bets").select("result").eq("id", bet_id).execute()
    if current.data and current.data[0]["result"] == "pending" and result.value != "pending":
        update_data["settled_at"] = datetime.utcnow().isoformat()
    
    response = db.table("bets").update(update_data).eq("id", bet_id).execute()
    
    if not response.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    
    return build_bet_response(response.data[0], user_settings["k_factor"])


@app.delete("/bets/{bet_id}")
def delete_bet(bet_id: str):
    """Delete a bet."""
    db = get_db()
    
    result = db.table("bets").delete().eq("id", bet_id).execute()
    
    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    
    return {"deleted": True, "id": bet_id}


# ============ Summary / Dashboard ============

@app.get("/summary", response_model=SummaryResponse)
def get_summary():
    """Get dashboard summary statistics."""
    db = get_db()
    
    result = db.table("bets").select("*").execute()
    bets = result.data
    
    if not bets:
        return SummaryResponse(
            total_bets=0,
            pending_bets=0,
            total_ev=0.0,
            total_real_profit=0.0,
            variance=0.0,
            win_count=0,
            loss_count=0,
            win_rate=None,
            ev_by_sportsbook={},
            profit_by_sportsbook={},
            ev_by_sport={},
        )
    
    k_factor = user_settings["k_factor"]
    
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
        
        # Totals
        total_ev += bet_response.ev_total
        if bet_response.real_profit is not None:
            total_real_profit += bet_response.real_profit
        
        # Counts
        if bet_response.result == BetResult.WIN:
            win_count += 1
        elif bet_response.result == BetResult.LOSS:
            loss_count += 1
        elif bet_response.result == BetResult.PENDING:
            pending_count += 1
        
        # By sportsbook
        book = bet_response.sportsbook
        ev_by_sportsbook[book] = ev_by_sportsbook.get(book, 0) + bet_response.ev_total
        if bet_response.real_profit is not None:
            profit_by_sportsbook[book] = profit_by_sportsbook.get(book, 0) + bet_response.real_profit
        
        # By sport
        sport = bet_response.sport
        ev_by_sport[sport] = ev_by_sport.get(sport, 0) + bet_response.ev_total
    
    settled_count = win_count + loss_count
    win_rate = (win_count / settled_count) if settled_count > 0 else None
    
    return SummaryResponse(
        total_bets=len(bets),
        pending_bets=pending_count,
        total_ev=round(total_ev, 2),
        total_real_profit=round(total_real_profit, 2),
        variance=round(total_real_profit - total_ev, 2),
        win_count=win_count,
        loss_count=loss_count,
        win_rate=round(win_rate, 4) if win_rate else None,
        ev_by_sportsbook={k: round(v, 2) for k, v in ev_by_sportsbook.items()},
        profit_by_sportsbook={k: round(v, 2) for k, v in profit_by_sportsbook.items()},
        ev_by_sport={k: round(v, 2) for k, v in ev_by_sport.items()},
    )


# ============ Transactions ============

@app.post("/transactions", response_model=TransactionResponse, status_code=201)
def create_transaction(transaction: TransactionCreate):
    """Create a new deposit or withdrawal."""
    db = get_db()
    
    data = {
        "sportsbook": transaction.sportsbook,
        "type": transaction.type.value,
        "amount": transaction.amount,
        "notes": transaction.notes,
    }
    
    result = db.table("transactions").insert(data).execute()
    
    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create transaction")
    
    row = result.data[0]
    return TransactionResponse(
        id=row["id"],
        created_at=row["created_at"],
        sportsbook=row["sportsbook"],
        type=row["type"],
        amount=row["amount"],
        notes=row.get("notes"),
    )


@app.get("/transactions", response_model=list[TransactionResponse])
def list_transactions(sportsbook: str | None = None):
    """List all transactions, optionally filtered by sportsbook."""
    db = get_db()
    
    query = db.table("transactions").select("*").order("created_at", desc=True)
    
    if sportsbook:
        query = query.eq("sportsbook", sportsbook)
    
    result = query.execute()
    
    return [
        TransactionResponse(
            id=row["id"],
            created_at=row["created_at"],
            sportsbook=row["sportsbook"],
            type=row["type"],
            amount=row["amount"],
            notes=row.get("notes"),
        )
        for row in result.data
    ]


@app.delete("/transactions/{transaction_id}", status_code=204)
def delete_transaction(transaction_id: str):
    """Delete a transaction."""
    db = get_db()
    result = db.table("transactions").delete().eq("id", transaction_id).execute()

    # Supabase delete returns an empty list when nothing is deleted; treat non-200 as error
    if result.status_code and result.status_code >= 400:
        raise HTTPException(status_code=500, detail="Failed to delete transaction")


@app.get("/balances", response_model=list[BalanceResponse])
def get_balances():
    """Get computed balance for each sportsbook."""
    db = get_db()
    k_factor = user_settings["k_factor"]
    
    # Get all transactions
    tx_result = db.table("transactions").select("*").execute()
    transactions = tx_result.data or []
    
    # Get all bets for profit calculation
    bets_result = db.table("bets").select("*").execute()
    bets = bets_result.data or []
    
    # Aggregate by sportsbook
    sportsbook_data = {}
    
    # Process transactions
    for tx in transactions:
        book = tx["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0, "withdrawals": 0, "profit": 0, "pending": 0}
        
        if tx["type"] == "deposit":
            sportsbook_data[book]["deposits"] += float(tx["amount"])
        else:
            sportsbook_data[book]["withdrawals"] += float(tx["amount"])
    
    # Process bets for profit and pending
    for row in bets:
        book = row["sportsbook"]
        if book not in sportsbook_data:
            sportsbook_data[book] = {"deposits": 0, "withdrawals": 0, "profit": 0, "pending": 0}
        
        bet = build_bet_response(row, k_factor)
        
        if bet.result == BetResult.PENDING:
            # For pending bets, add stake as pending exposure
            sportsbook_data[book]["pending"] += bet.stake
        elif bet.real_profit is not None:
            # For settled bets, add to profit
            sportsbook_data[book]["profit"] += bet.real_profit
    
    # Build response
    balances = []
    for book, data in sorted(sportsbook_data.items()):
        net_deposits = data["deposits"] - data["withdrawals"]
        balance = net_deposits + data["profit"] - data["pending"]
        
        balances.append(BalanceResponse(
            sportsbook=book,
            deposits=round(data["deposits"], 2),
            withdrawals=round(data["withdrawals"], 2),
            net_deposits=round(net_deposits, 2),
            profit=round(data["profit"], 2),
            pending=round(data["pending"], 2),
            balance=round(balance, 2),
        ))
    
    return balances


# ============ Settings ============

@app.get("/settings", response_model=SettingsResponse)
def get_settings():
    """Get user settings."""
    return SettingsResponse(**user_settings)


@app.patch("/settings", response_model=SettingsResponse)
def update_settings(settings: SettingsUpdate):
    """Update user settings."""
    if settings.k_factor is not None:
        user_settings["k_factor"] = settings.k_factor
    if settings.default_stake is not None:
        user_settings["default_stake"] = settings.default_stake
    if settings.preferred_sportsbooks is not None:
        user_settings["preferred_sportsbooks"] = settings.preferred_sportsbooks
    
    return SettingsResponse(**user_settings)


# ============ Utility ============

@app.get("/calculate-ev")
def calculate_ev_preview(
    odds_american: float,
    stake: float,
    promo_type: PromoType,
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
):
    """
    Preview EV calculation without saving a bet.
    Useful for real-time calculation as user types.
    """
    decimal_odds = american_to_decimal(odds_american)
    
    result = calculate_ev(
        stake=stake,
        decimal_odds=decimal_odds,
        promo_type=promo_type.value,
        k_factor=user_settings["k_factor"],
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
