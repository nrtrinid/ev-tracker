"""
EV Tracker API
FastAPI backend for sports betting EV tracking.
"""

import asyncio
from fastapi import FastAPI, HTTPException, Depends, Header
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime, UTC
from contextlib import asynccontextmanager
import os
import time
from dotenv import load_dotenv
import httpx
from zoneinfo import ZoneInfo

from models import (
    BetCreate, BetUpdate, BetResponse, BetResult, PromoType,
    SettingsUpdate, SettingsResponse, SummaryResponse,
    TransactionCreate, TransactionResponse, BalanceResponse,
    ScanResponse, FullScanResponse,
)
from calculations import american_to_decimal, calculate_ev, calculate_real_profit, calculate_clv
from auth import get_current_user

load_dotenv()

app: FastAPI

PHOENIX_TZ = None
try:
    PHOENIX_TZ = ZoneInfo("America/Phoenix")
except Exception as e:
    # If the runtime lacks IANA tzdata, scheduled scans should not run at wrong times.
    # Install the `tzdata` package if this occurs in production.
    print(f"[Scheduler] Failed to load America/Phoenix timezone: {e}")


# ---------- CLV daily safety-net scheduler ----------
# Fires once per day at 23:30 UTC (6:30 PM ET). Makes one fetch_odds call per
# active sport and updates pinnacle_odds_at_close for all pending tracked bets.
# This is a backstop — the piggyback in scan_markets does most of the work for free.

async def _run_clv_daily_job():
    """Safety-net: fetch closing Pinnacle lines for all pending CLV-tracked bets."""
    from services.odds_api import fetch_clv_for_pending_bets
    db = get_db()
    try:
        updated = await fetch_clv_for_pending_bets(db)
        print(f"[CLV daily job] Updated {updated} bet(s) with closing lines.")
    except Exception as e:
        print(f"[CLV daily job] Error: {e}")


async def _run_jit_clv_snatcher_job():
    """JIT CLV Snatcher: capture closing Pinnacle lines for games starting in the next 20 min."""
    from services.odds_api import run_jit_clv_snatcher
    db = get_db()
    try:
        updated = await run_jit_clv_snatcher(db)
        if updated:
            print(f"[JIT CLV] Captured closing lines for {updated} bet(s).")
    except Exception as e:
        print(f"[JIT CLV] Error: {e}")


async def _run_auto_settler_job():
    """Auto-Settler: grade completed ML bets using The Odds API /scores endpoint."""
    from services.odds_api import run_auto_settler
    db = get_db()
    try:
        settled = await run_auto_settler(db)
        print(f"[Auto-Settler] Graded {settled} bet(s).")
    except Exception as e:
        print(f"[Auto-Settler] Error: {e}")


async def _run_scheduled_scan_job():
    """
    Scheduled scan job: warms the same cache used by GET /api/scan-markets by
    calling services.odds_api.get_cached_or_scan across SUPPORTED_SPORTS.
    """
    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS

    started = datetime.now(UTC).isoformat()
    print(f"[Scheduled scan] Starting scan job at {started}Z")

    for sport_key in SUPPORTED_SPORTS:
        try:
            result = await get_cached_or_scan(sport_key)
            sides_count = len(result.get("sides") or [])
            fetched = result.get("events_fetched")
            with_both = result.get("events_with_both_books")
            print(
                f"[Scheduled scan] {sport_key}: {sides_count} sides "
                f"({fetched} events, {with_both} with sharp+target)"
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"[Scheduled scan] {sport_key}: 404 (no odds). Skipping.")
                continue
            print(f"[Scheduled scan] {sport_key}: HTTP error: {e}")
        except Exception as e:
            # Never crash the server/scheduler; log and continue.
            print(f"[Scheduled scan] {sport_key}: Error: {e}")

    finished = datetime.now(UTC).isoformat()
    print(f"[Scheduled scan] Finished scan job at {finished}Z")


async def _piggyback_clv(sides: list[dict]):
    """
    Fire-and-forget task: update CLV snapshots for all pending tracked bets
    from the just-completed scan. Errors are swallowed so they never affect
    the scan response the user sees.
    """
    from services.odds_api import update_clv_snapshots
    try:
        db = get_db()
        update_clv_snapshots(sides, db)
    except Exception as e:
        print(f"[CLV piggyback] Error: {e}")


async def start_scheduler():
    if os.getenv("TESTING") == "1":
        return  # Skip scheduler in integration tests so we don't hit Odds API or cron
    if os.getenv("ENABLE_SCHEDULER") != "1":
        return  # Only one instance should run background jobs (Render scaling/workers)
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    from apscheduler.triggers.interval import IntervalTrigger
    scheduler = AsyncIOScheduler()
    # 23:30 UTC = 6:30 PM ET (accounts for EST; shift to 22:30 during EDT if needed)
    scheduler.add_job(_run_clv_daily_job, CronTrigger(hour=23, minute=30))
    # Every 15 min: capture closing Pinnacle lines for games starting within 20 min
    scheduler.add_job(_run_jit_clv_snatcher_job, IntervalTrigger(minutes=15))
    # 4:00 AM UTC daily: auto-grade completed ML bets via /scores
    scheduler.add_job(_run_auto_settler_job, CronTrigger(hour=4, minute=0))
    if PHOENIX_TZ is not None:
        scheduler.add_job(
            _run_scheduled_scan_job,
            CronTrigger(hour=16, minute=30, timezone=PHOENIX_TZ),
        )
        scheduler.add_job(
            _run_scheduled_scan_job,
            CronTrigger(hour=18, minute=30, timezone=PHOENIX_TZ),
        )
    else:
        print("[Scheduler] Phoenix timezone unavailable; skipping scheduled scan jobs.")
    scheduler.start()
    app.state.scheduler = scheduler


async def stop_scheduler():
    scheduler = getattr(app.state, "scheduler", None)
    if scheduler:
        try:
            scheduler.shutdown(wait=False)
        except Exception as e:
            print(f"[Scheduler] Error shutting down: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    await start_scheduler()
    try:
        yield
    finally:
        await stop_scheduler()


app = FastAPI(
    title="EV Tracker API",
    description="Track sports betting Expected Value",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS - allow frontend to call API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Import database after app setup to avoid circular imports
from database import get_db

# ---------- Scan rate limit (per user, in-memory) ----------
# 12 full scans per 15 minutes per user; cache makes most requests cheap.
_scan_rate_window_sec = 15 * 60
_scan_rate_max = 12
_scan_rate_times: dict[str, list[float]] = {}
_scan_rate_lock = asyncio.Lock()


async def require_scan_rate_limit(user: dict = Depends(get_current_user)) -> dict:
    """Allow at most _scan_rate_max scan requests per user per _scan_rate_window_sec."""
    async with _scan_rate_lock:
        now = time.time()
        uid = user["id"]
        if uid not in _scan_rate_times:
            _scan_rate_times[uid] = []
        times = _scan_rate_times[uid]
        times[:] = [t for t in times if (now - t) < _scan_rate_window_sec]
        if len(times) >= _scan_rate_max:
            raise HTTPException(
                status_code=429,
                detail="Too many scan requests. Please try again in a few minutes.",
            )
        times.append(now)
    return user


def _retry_supabase(f, retries=2):
    """Retry a Supabase/PostgREST request on transient 'Server disconnected' errors."""
    last_err = None
    for attempt in range(retries):
        try:
            return f()
        except httpx.RemoteProtocolError as e:
            last_err = e
            if attempt == retries - 1:
                raise
            time.sleep(0.4)
    if last_err:
        raise last_err


DEFAULT_SPORTSBOOKS = [
    "DraftKings", "FanDuel", "BetMGM", "Caesars",
    "ESPN Bet", "Fanatics", "Hard Rock", "bet365"
]


def get_user_settings(db, user_id: str) -> dict:
    """Get settings from DB, creating defaults for new users."""
    result = _retry_supabase(lambda: db.table("settings").select("*").eq("user_id", user_id).execute())
    if result.data:
        return result.data[0]

    defaults = {
        "user_id": user_id,
        "k_factor": 0.78,
        "default_stake": None,
        "preferred_sportsbooks": DEFAULT_SPORTSBOOKS,
    }
    _retry_supabase(lambda: db.table("settings").upsert(defaults).execute())
    result = _retry_supabase(lambda: db.table("settings").select("*").eq("user_id", user_id).execute())
    return result.data[0]


def build_bet_response(row: dict, k_factor: float) -> BetResponse:
    """Convert database row to BetResponse with calculated fields."""
    from calculations import calculate_hold_from_odds

    decimal_odds = american_to_decimal(row["odds_american"])
    decimal_odds_for_ev = decimal_odds

    # If payout_override is provided, keep EV math consistent with the displayed payout.
    # This is only unambiguous for markets where win_payout is stake * decimal_odds
    # (standard/no_sweat/promo_qualifier). For bonus bets and profit boosts, payout
    # semantics differ, so we do not try to back-solve odds automatically.
    payout_override = row.get("payout_override")
    promo_type = row.get("promo_type")
    stake = row.get("stake") or 0
    if (
        payout_override is not None
        and stake
        and promo_type in ("standard", "no_sweat", "promo_qualifier")
    ):
        try:
            implied_decimal = float(payout_override) / float(stake)
            if implied_decimal > 1:
                decimal_odds_for_ev = implied_decimal
        except Exception:
            pass

    vig = None
    if row.get("opposing_odds"):
        vig = calculate_hold_from_odds(row["odds_american"], row["opposing_odds"])

    ev_result = calculate_ev(
        stake=row["stake"],
        decimal_odds=decimal_odds_for_ev,
        promo_type=row["promo_type"],
        k_factor=k_factor,
        boost_percent=row.get("boost_percent"),
        winnings_cap=row.get("winnings_cap"),
        vig=vig,
        true_prob=row.get("true_prob_at_entry"),
    )

    # Use payout override if present
    win_payout = payout_override or ev_result["win_payout"]

    real_profit = calculate_real_profit(
        stake=row["stake"],
        win_payout=win_payout,
        result=row["result"],
        promo_type=row["promo_type"],
    )

    # CLV — compute only when we have both entry and close Pinnacle lines
    clv_ev_percent = None
    beat_close = None
    if row.get("pinnacle_odds_at_entry") and row.get("pinnacle_odds_at_close"):
        clv_result = calculate_clv(row["odds_american"], row["pinnacle_odds_at_close"])
        clv_ev_percent = clv_result["clv_ev_percent"]
        beat_close = clv_result["beat_close"]

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
        opposing_odds=row.get("opposing_odds"),
        result=row["result"],
        win_payout=win_payout,
        ev_per_dollar=ev_result["ev_per_dollar"],
        ev_total=ev_result["ev_total"],
        real_profit=real_profit,
        pinnacle_odds_at_entry=row.get("pinnacle_odds_at_entry"),
        pinnacle_odds_at_close=row.get("pinnacle_odds_at_close"),
        clv_updated_at=row.get("clv_updated_at"),
        commence_time=row.get("commence_time"),
        clv_team=row.get("clv_team"),
        clv_sport_key=row.get("clv_sport_key"),
        true_prob_at_entry=row.get("true_prob_at_entry"),
        clv_ev_percent=clv_ev_percent,
        beat_close=beat_close,
    )


# ============ Health Check ============

@app.get("/health")
def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now(UTC).isoformat()}


# ============ Bets CRUD ============

@app.post("/bets", response_model=BetResponse, status_code=201)
def create_bet(bet: BetCreate, user: dict = Depends(get_current_user)):
    """Create a new bet."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    data = {
        "user_id": user["id"],
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
        "opposing_odds": bet.opposing_odds,
        "result": BetResult.PENDING.value,
        # CLV tracking fields (None when betting manually, set when logging from scanner)
        "pinnacle_odds_at_entry": bet.pinnacle_odds_at_entry,
        "commence_time": bet.commence_time,
        "clv_team": bet.clv_team,
        "clv_sport_key": bet.clv_sport_key,
        "true_prob_at_entry": bet.true_prob_at_entry,
    }

    # Only include event_date if provided, otherwise let DB default to today
    if bet.event_date:
        data["event_date"] = bet.event_date.isoformat()

    result = db.table("bets").insert(data).execute()

    if not result.data:
        raise HTTPException(status_code=500, detail="Failed to create bet")

    return build_bet_response(result.data[0], settings["k_factor"])


@app.get("/bets", response_model=list[BetResponse])
def get_bets(
    sport: str | None = None,
    sportsbook: str | None = None,
    result: BetResult | None = None,
    limit: int = 1000,
    offset: int = 0,
    user: dict = Depends(get_current_user),
):
    """Get all bets with optional filters."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    query = (
        db.table("bets")
        .select("*")
        .eq("user_id", user["id"])
        .order("created_at", desc=True)
    )

    if sport:
        query = query.eq("sport", sport)
    if sportsbook:
        query = query.eq("sportsbook", sportsbook)
    if result:
        query = query.eq("result", result.value)

    query = query.range(offset, offset + limit - 1)

    response = _retry_supabase(lambda: query.execute())

    return [build_bet_response(row, settings["k_factor"]) for row in response.data]


@app.get("/bets/{bet_id}", response_model=BetResponse)
def get_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Get a single bet by ID."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    result = (
        db.table("bets")
        .select("*")
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(result.data[0], settings["k_factor"])


@app.patch("/bets/{bet_id}", response_model=BetResponse)
def update_bet(bet_id: str, bet: BetUpdate, user: dict = Depends(get_current_user)):
    """Update an existing bet."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

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
        current = (
            db.table("bets")
            .select("result")
            .eq("id", bet_id)
            .eq("user_id", user["id"])
            .execute()
        )
        if current.data and current.data[0]["result"] == "pending" and bet.result.value != "pending":
            data["settled_at"] = datetime.now(UTC).isoformat()
    if bet.payout_override is not None:
        data["payout_override"] = bet.payout_override
    if bet.opposing_odds is not None:
        data["opposing_odds"] = bet.opposing_odds
    if bet.event_date is not None:
        data["event_date"] = bet.event_date.isoformat()

    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    result = (
        db.table("bets")
        .update(data)
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(result.data[0], settings["k_factor"])


@app.patch("/bets/{bet_id}/result")
def update_bet_result(
    bet_id: str,
    result: BetResult,
    user: dict = Depends(get_current_user),
):
    """Quick endpoint to just update bet result (win/loss)."""
    db = get_db()
    settings = get_user_settings(db, user["id"])

    # Build update data
    update_data = {"result": result.value}

    # Auto-set settled_at when changing from pending to settled
    current = (
        db.table("bets")
        .select("result")
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )
    if not current.data:
        raise HTTPException(status_code=404, detail="Bet not found")
    if current.data[0]["result"] == "pending" and result.value != "pending":
        update_data["settled_at"] = datetime.now(UTC).isoformat()

    response = (
        db.table("bets")
        .update(update_data)
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not response.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return build_bet_response(response.data[0], settings["k_factor"])


@app.delete("/bets/{bet_id}")
def delete_bet(bet_id: str, user: dict = Depends(get_current_user)):
    """Delete a bet."""
    db = get_db()

    result = (
        db.table("bets")
        .delete()
        .eq("id", bet_id)
        .eq("user_id", user["id"])
        .execute()
    )

    if not result.data:
        raise HTTPException(status_code=404, detail="Bet not found")

    return {"deleted": True, "id": bet_id}


# ============ Summary / Dashboard ============

@app.get("/summary", response_model=SummaryResponse)
def get_summary(user: dict = Depends(get_current_user)):
    """Get dashboard summary statistics."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    k_factor = settings["k_factor"]

    result = _retry_supabase(lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute())
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
def create_transaction(
    transaction: TransactionCreate,
    user: dict = Depends(get_current_user),
):
    """Create a new deposit or withdrawal."""
    db = get_db()

    data = {
        "user_id": user["id"],
        "sportsbook": transaction.sportsbook,
        "type": transaction.type.value,
        "amount": transaction.amount,
        "notes": transaction.notes,
    }

    # If created_at is provided (for undo), use it; otherwise let database set it
    if transaction.created_at:
        data["created_at"] = transaction.created_at.isoformat()

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
def list_transactions(
    sportsbook: str | None = None,
    user: dict = Depends(get_current_user),
):
    """List all transactions, optionally filtered by sportsbook."""
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


@app.delete("/transactions/{transaction_id}")
def delete_transaction(
    transaction_id: str,
    user: dict = Depends(get_current_user),
):
    """Delete a transaction."""
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

    return {"deleted": True, "id": transaction_id}


@app.get("/balances", response_model=list[BalanceResponse])
def get_balances(user: dict = Depends(get_current_user)):
    """Get computed balance for each sportsbook."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    k_factor = settings["k_factor"]

    # Get all transactions for this user
    tx_result = _retry_supabase(lambda: (
        db.table("transactions")
        .select("*")
        .eq("user_id", user["id"])
        .execute()
    ))
    transactions = tx_result.data or []

    # Get all bets for profit calculation
    bets_result = _retry_supabase(lambda: db.table("bets").select("*").eq("user_id", user["id"]).execute())
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
            sportsbook_data[book]["pending"] += bet.stake
        elif bet.real_profit is not None:
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
def get_settings(user: dict = Depends(get_current_user)):
    """Get user settings."""
    db = get_db()
    settings = get_user_settings(db, user["id"])
    return SettingsResponse(
        k_factor=settings["k_factor"],
        default_stake=settings.get("default_stake"),
        preferred_sportsbooks=settings.get("preferred_sportsbooks", DEFAULT_SPORTSBOOKS),
    )


@app.patch("/settings", response_model=SettingsResponse)
def update_settings(
    settings: SettingsUpdate,
    user: dict = Depends(get_current_user),
):
    """Update user settings."""
    db = get_db()

    # Ensure settings row exists
    get_user_settings(db, user["id"])

    data = {}
    if settings.k_factor is not None:
        data["k_factor"] = settings.k_factor
    if settings.default_stake is not None:
        data["default_stake"] = settings.default_stake
    if settings.preferred_sportsbooks is not None:
        data["preferred_sportsbooks"] = settings.preferred_sportsbooks

    if data:
        data["updated_at"] = datetime.now(UTC).isoformat()
        db.table("settings").update(data).eq("user_id", user["id"]).execute()

    updated = get_user_settings(db, user["id"])
    return SettingsResponse(
        k_factor=updated["k_factor"],
        default_stake=updated.get("default_stake"),
        preferred_sportsbooks=updated.get("preferred_sportsbooks", DEFAULT_SPORTSBOOKS),
    )


# ============ Utility ============

@app.get("/calculate-ev")
def calculate_ev_preview(
    odds_american: float,
    stake: float,
    promo_type: PromoType,
    boost_percent: float | None = None,
    winnings_cap: float | None = None,
    user: dict = Depends(get_current_user),
):
    """
    Preview EV calculation without saving a bet.
    Useful for real-time calculation as user types.
    """
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


# ============ Odds Scanner ============

@app.get("/api/scan-bets", response_model=ScanResponse)
async def scan_bets(
    sport: str = "basketball_nba",
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Scan live odds: de-vig Pinnacle, compare to DraftKings,
    return any +EV moneyline opportunities.
    """
    from services.odds_api import scan_for_ev, fetch_odds, SUPPORTED_SPORTS

    if sport not in SUPPORTED_SPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(SUPPORTED_SPORTS)}",
        )

    try:
        result = await scan_for_ev(sport)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")

    return ScanResponse(
        sport=sport,
        opportunities=result["opportunities"],
        events_fetched=result["events_fetched"],
        events_with_both_books=result["events_with_both_books"],
        api_requests_remaining=result.get("api_requests_remaining"),
    )


@app.get("/api/scan-markets", response_model=FullScanResponse)
async def scan_markets(
    sport: str | None = None,
    user: dict = Depends(require_scan_rate_limit),
):
    """
    Full market scan: returns every matched side between Pinnacle and the target
    books with de-vigged true probabilities. Uses server-side 5-min TTL cache per
    sport. If sport is omitted, scans all supported sports (cached per sport; only
    stale sports hit the API).
    """
    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS
    from datetime import datetime

    if sport is not None and sport not in SUPPORTED_SPORTS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported sport. Choose from: {', '.join(SUPPORTED_SPORTS)}",
        )

    try:
        if sport is not None:
            result = await get_cached_or_scan(sport)
            scanned_at = datetime.utcfromtimestamp(result["fetched_at"]).isoformat() + "Z"
            # Piggyback CLV update — zero extra API calls
            asyncio.create_task(_piggyback_clv(result["sides"]))
            return FullScanResponse(
                sport=sport,
                sides=result["sides"],
                events_fetched=result["events_fetched"],
                events_with_both_books=result["events_with_both_books"],
                api_requests_remaining=result.get("api_requests_remaining"),
                scanned_at=scanned_at,
            )
        # Full scan: all sports (skip any that 404 — e.g. out of season)
        all_sides = []
        total_events = 0
        total_with_both = 0
        min_remaining = None
        oldest_fetched = None
        from os import getenv
        env = getenv("ENVIRONMENT", "production").lower()
        sports_to_scan = ["basketball_nba"] if env == "development" else SUPPORTED_SPORTS
        for s in sports_to_scan:
            try:
                result = await get_cached_or_scan(s)
            except httpx.HTTPStatusError as e:
                if e.response.status_code == 404:
                    continue  # sport has no odds right now (e.g. off-season)
                raise
            all_sides.extend(result["sides"])
            total_events += result["events_fetched"]
            total_with_both += result["events_with_both_books"]
            rem = result.get("api_requests_remaining")
            if rem is not None:
                try:
                    r = int(rem)
                    min_remaining = str(r) if min_remaining is None else str(min(r, int(min_remaining)))
                except ValueError:
                    min_remaining = rem
            ft = result.get("fetched_at")
            if ft is not None:
                oldest_fetched = ft if oldest_fetched is None else min(oldest_fetched, ft)
        scanned_at = (datetime.utcfromtimestamp(oldest_fetched).isoformat() + "Z") if oldest_fetched else None
        # Piggyback CLV update across all scanned sides — zero extra API calls
        asyncio.create_task(_piggyback_clv(all_sides))
        return FullScanResponse(
            sport="all",
            sides=all_sides,
            events_fetched=total_events,
            events_with_both_books=total_with_both,
            api_requests_remaining=min_remaining,
            scanned_at=scanned_at,
        )
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Odds API error: {e}")


@app.post("/api/cron/run-scan")
async def cron_run_scan(x_cron_token: str | None = Header(default=None, alias="X-Cron-Token")):
    """
    Cron-triggered scan runner (for Render free sleep). This endpoint is intended to be
    called by an external scheduler (cron-job.org, GitHub Actions, etc.) to wake the
    service and warm the scan cache.

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if not x_cron_token or x_cron_token != expected:
        raise HTTPException(status_code=401, detail="Invalid cron token")

    from services.odds_api import get_cached_or_scan, SUPPORTED_SPORTS

    started = datetime.now(UTC).isoformat() + "Z"
    scanned = []
    errors: list[dict] = []
    total_sides = 0
    alerts_scheduled = 0
    from services.discord_alerts import schedule_alerts

    for sport_key in SUPPORTED_SPORTS:
        try:
            result = await get_cached_or_scan(sport_key)
            sides = result.get("sides") or []
            scanned.append(
                {
                    "sport": sport_key,
                    "sides": len(sides),
                    "events_fetched": result.get("events_fetched"),
                    "events_with_both_books": result.get("events_with_both_books"),
                    "api_requests_remaining": result.get("api_requests_remaining"),
                }
            )
            total_sides += len(sides)
            alerts_scheduled += schedule_alerts(sides)
        except httpx.HTTPStatusError as e:
            status = e.response.status_code if e.response is not None else None
            # 404 just means out of season / no odds; treat as non-fatal.
            if status == 404:
                errors.append({"sport": sport_key, "status": 404, "error": "no odds"})
                continue
            errors.append({"sport": sport_key, "status": status, "error": str(e)})
        except Exception as e:
            errors.append({"sport": sport_key, "error": str(e)})

    finished = datetime.now(UTC).isoformat() + "Z"

    # Optional heartbeat so we can confirm the scheduled scan ran even when it finds no lines.
    # Reuse the existing heartbeat flag to avoid adding another env var.
    # Sends only when enabled and when no alerts were scheduled.
    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1" and alerts_scheduled == 0:
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Scan run complete (no alerts)",
                    "description": "The scheduled scan ran successfully but found no qualifying lines to alert on.",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                        {"name": "Total sides", "value": str(total_sides), "inline": True},
                        {"name": "Alerts scheduled", "value": str(alerts_scheduled), "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload))

    return {
        "ok": True,
        "started_at": started,
        "finished_at": finished,
        "sports_scanned": scanned,
        "errors": errors,
        "total_sides": total_sides,
        "alerts_scheduled": alerts_scheduled,
    }


@app.post("/api/cron/run-auto-settle")
async def cron_run_auto_settle(
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Cron-triggered auto-settler runner (for Render free sleep).

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if not x_cron_token or x_cron_token != expected:
        raise HTTPException(status_code=401, detail="Invalid cron token")

    db = get_db()
    started = datetime.now(UTC).isoformat() + "Z"
    try:
        from services.odds_api import run_auto_settler

        settled = await run_auto_settler(db)
    except Exception as e:
        # Never crash the server; return error for cron logs.
        raise HTTPException(status_code=502, detail=f"Auto-settler error: {e}")
    finally:
        finished = datetime.now(UTC).isoformat() + "Z"

    if os.getenv("DISCORD_AUTO_SETTLE_HEARTBEAT") == "1":
        from services.discord_alerts import send_discord_webhook

        payload = {
            "embeds": [
                {
                    "title": "Auto-settle run complete",
                    "description": f"Graded **{settled}** bet(s).",
                    "fields": [
                        {"name": "Started (UTC)", "value": started, "inline": True},
                        {"name": "Finished (UTC)", "value": finished, "inline": True},
                    ],
                }
            ]
        }
        asyncio.create_task(send_discord_webhook(payload))

    return {
        "ok": True,
        "started_at": started,
        "finished_at": finished,
        "settled": settled,
    }


@app.post("/api/cron/test-discord")
async def cron_test_discord(
    x_cron_token: str | None = Header(default=None, alias="X-Cron-Token"),
):
    """
    Send a test Discord message (no EV/odds filtering).

    Security: requires X-Cron-Token header matching the CRON_TOKEN environment variable.
    """
    expected = os.getenv("CRON_TOKEN")
    if not expected:
        raise HTTPException(status_code=503, detail="CRON_TOKEN not configured on server")
    if not x_cron_token or x_cron_token != expected:
        raise HTTPException(status_code=401, detail="Invalid cron token")

    from services.discord_alerts import send_discord_webhook

    payload = {
        "embeds": [
            {
                "title": "Webhook test",
                "description": "If you can read this, DISCORD_WEBHOOK_URL is working.",
                "fields": [
                    {"name": "Server time (UTC)", "value": datetime.now(UTC).isoformat() + "Z", "inline": False},
                ],
            }
        ]
    }

    # Awaited directly so any Discord error surfaces in logs/response.
    await send_discord_webhook(payload)
    return {"ok": True, "scheduled": True}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
