"""
Route-level integration tests for the FastAPI app.
Require a test Supabase (same or TEST_SUPABASE_* when TESTING=1) and a test user in auth.users.

Run from backend/ with the same venv and deps as the app (pip install -r requirements.txt).
  Windows PowerShell: $env:TESTING="1"; pytest tests/test_api.py -v
  macOS/Linux:        TESTING=1 pytest tests/test_api.py -v
  By marker:         $env:TESTING="1"; pytest -m integration -v
"""
import os

# Load .env before skip checks so SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY are available
from dotenv import load_dotenv
load_dotenv()

import pytest
from models import BetResult, TransactionType

# Skip entire module if integration env not configured
if os.getenv("TESTING") != "1":
    pytest.skip("Integration tests require TESTING=1", allow_module_level=True)
if not (os.getenv("SUPABASE_URL") or os.getenv("TEST_SUPABASE_URL")):
    pytest.skip("Integration tests require SUPABASE_URL or TEST_SUPABASE_URL", allow_module_level=True)
if not os.getenv("TEST_USER_ID"):
    pytest.skip("Integration tests require TEST_USER_ID", allow_module_level=True)
try:
    import supabase  # noqa: F401
except ModuleNotFoundError:
    pytest.skip("Install backend deps: pip install -r requirements.txt", allow_module_level=True)


@pytest.fixture
def auth_headers():
    return {"Authorization": "Bearer dummy"}


@pytest.mark.integration
def test_health(public_client):
    """GET /health returns 200 without auth."""
    r = public_client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data.get("status") == "healthy"
    assert "timestamp" in data


@pytest.mark.integration
def test_unauthorized(public_client):
    """GET /bets without auth returns 401."""
    r = public_client.get("/bets")
    assert r.status_code == 401


@pytest.mark.integration
def test_create_bet(auth_client, auth_headers, run_id, tracker):
    """POST /bets with valid payload returns 201 and bet with id."""
    payload = {
        "sport": "NFL",
        "event": f"Integration test {run_id}",
        "market": "ML",
        "sportsbook": "DraftKings",
        "promo_type": "standard",
        "odds_american": -110,
        "stake": 100,
    }
    r = auth_client.post("/bets", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    tracker.bet_ids.append(data["id"])
    assert data["sport"] == "NFL"
    assert data["event"] == payload["event"]
    assert data["result"] == BetResult.PENDING.value
    assert "ev_total" in data
    assert "win_payout" in data


@pytest.mark.integration
def test_list_bets(auth_client, auth_headers, run_id, tracker):
    """After creating a bet, GET /bets returns it."""
    payload = {
        "sport": "NBA",
        "event": f"List test {run_id}",
        "market": "ML",
        "sportsbook": "FanDuel",
        "promo_type": "standard",
        "odds_american": 150,
        "stake": 50,
    }
    create_r = auth_client.post("/bets", json=payload, headers=auth_headers)
    assert create_r.status_code == 201
    bet_id = create_r.json()["id"]
    tracker.bet_ids.append(bet_id)

    list_r = auth_client.get("/bets", headers=auth_headers)
    assert list_r.status_code == 200
    bets = list_r.json()
    assert isinstance(bets, list)
    ids = [b["id"] for b in bets]
    assert bet_id in ids


@pytest.mark.integration
def test_update_bet_result(auth_client, auth_headers, run_id, tracker):
    """Create bet, PATCH result to win, then GET confirms result."""
    payload = {
        "sport": "MLB",
        "event": f"Update result {run_id}",
        "market": "ML",
        "sportsbook": "BetMGM",
        "promo_type": "standard",
        "odds_american": 200,
        "stake": 25,
    }
    create_r = auth_client.post("/bets", json=payload, headers=auth_headers)
    assert create_r.status_code == 201
    bet_id = create_r.json()["id"]
    tracker.bet_ids.append(bet_id)

    patch_r = auth_client.patch(
        f"/bets/{bet_id}/result",
        params={"result": BetResult.WIN.value},
        headers=auth_headers,
    )
    assert patch_r.status_code == 200
    assert patch_r.json()["result"] == BetResult.WIN.value

    get_r = auth_client.get(f"/bets/{bet_id}", headers=auth_headers)
    assert get_r.status_code == 200
    assert get_r.json()["result"] == BetResult.WIN.value
    assert get_r.json().get("real_profit") is not None


@pytest.mark.integration
def test_summary_reflects_bet_and_result(auth_client, auth_headers, run_id, tracker):
    """Create bet, settle as win, GET /summary reflects totals (before/after deltas)."""
    summary_before = auth_client.get("/summary", headers=auth_headers).json()
    total_bets_before = summary_before["total_bets"]
    win_count_before = summary_before["win_count"]
    total_real_profit_before = summary_before["total_real_profit"]

    payload = {
        "sport": "NHL",
        "event": f"Summary test {run_id}",
        "market": "ML",
        "sportsbook": "Caesars",
        "promo_type": "standard",
        "odds_american": 100,
        "stake": 10,
    }
    create_r = auth_client.post("/bets", json=payload, headers=auth_headers)
    assert create_r.status_code == 201
    bet_id = create_r.json()["id"]
    tracker.bet_ids.append(bet_id)

    auth_client.patch(
        f"/bets/{bet_id}/result",
        params={"result": BetResult.WIN.value},
        headers=auth_headers,
    )

    summary_after = auth_client.get("/summary", headers=auth_headers).json()
    assert summary_after["total_bets"] == total_bets_before + 1
    assert summary_after["win_count"] == win_count_before + 1
    # Standard $10 at +100 (2.0 decimal) win -> profit $10
    assert summary_after["total_real_profit"] == total_real_profit_before + 10.0


@pytest.mark.integration
def test_create_transaction(auth_client, auth_headers, run_id, tracker):
    """POST /transactions (deposit) returns 201 and id."""
    payload = {
        "sportsbook": "DraftKings",
        "type": TransactionType.DEPOSIT.value,
        "amount": 100,
        "notes": run_id,
    }
    r = auth_client.post("/transactions", json=payload, headers=auth_headers)
    assert r.status_code == 201
    data = r.json()
    assert "id" in data
    tracker.tx_ids.append(data["id"])
    assert data["sportsbook"] == "DraftKings"
    assert data["type"] == TransactionType.DEPOSIT.value
    assert data["amount"] == 100


@pytest.mark.integration
def test_list_transactions(auth_client, auth_headers, run_id, tracker):
    """After creating a transaction, GET /transactions returns it."""
    payload = {
        "sportsbook": "FanDuel",
        "type": TransactionType.DEPOSIT.value,
        "amount": 50,
        "notes": run_id,
    }
    create_r = auth_client.post("/transactions", json=payload, headers=auth_headers)
    assert create_r.status_code == 201
    tx_id = create_r.json()["id"]
    tracker.tx_ids.append(tx_id)

    list_r = auth_client.get("/transactions", headers=auth_headers)
    assert list_r.status_code == 200
    txs = list_r.json()
    assert isinstance(txs, list)
    ids = [t["id"] for t in txs]
    assert tx_id in ids


@pytest.mark.integration
def test_balances_smoke(auth_client, auth_headers):
    """GET /balances returns 200 and a list (structure smoke)."""
    r = auth_client.get("/balances", headers=auth_headers)
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    for item in data:
        assert "sportsbook" in item
        assert "balance" in item
        assert "net_deposits" in item


def _book_balance(balances: list[dict], sportsbook: str) -> float:
    """Return balance for a book or 0 when the book has no row yet."""
    for row in balances:
        if row.get("sportsbook") == sportsbook:
            return float(row.get("balance", 0.0))
    return 0.0


@pytest.mark.integration
def test_delete_pending_cash_bet_returns_stake_to_balance(auth_client, auth_headers, run_id, tracker):
    """Deleting a pending cash bet should refund stake to available balance."""
    sportsbook = f"DeleteCash-{run_id}"

    deposit_r = auth_client.post(
        "/transactions",
        json={
            "sportsbook": sportsbook,
            "type": TransactionType.DEPOSIT.value,
            "amount": 250,
            "notes": run_id,
        },
        headers=auth_headers,
    )
    assert deposit_r.status_code == 201
    tracker.tx_ids.append(deposit_r.json()["id"])

    before_r = auth_client.get("/balances", headers=auth_headers)
    assert before_r.status_code == 200
    balance_before = _book_balance(before_r.json(), sportsbook)

    stake = 40.0
    create_r = auth_client.post(
        "/bets",
        json={
            "sport": "NBA",
            "event": f"Delete pending cash {run_id}",
            "market": "ML",
            "sportsbook": sportsbook,
            "promo_type": "standard",
            "odds_american": -110,
            "stake": stake,
        },
        headers=auth_headers,
    )
    assert create_r.status_code == 201
    bet_id = create_r.json()["id"]
    tracker.bet_ids.append(bet_id)

    during_r = auth_client.get("/balances", headers=auth_headers)
    assert during_r.status_code == 200
    balance_during = _book_balance(during_r.json(), sportsbook)
    assert round(balance_before - balance_during, 2) == round(stake, 2)

    delete_r = auth_client.delete(f"/bets/{bet_id}", headers=auth_headers)
    assert delete_r.status_code == 200

    after_r = auth_client.get("/balances", headers=auth_headers)
    assert after_r.status_code == 200
    balance_after = _book_balance(after_r.json(), sportsbook)
    assert round(balance_after, 2) == round(balance_before, 2)


@pytest.mark.integration
def test_delete_pending_bonus_bet_does_not_change_balance(auth_client, auth_headers, run_id, tracker):
    """Deleting a pending bonus bet should not refund cash stake."""
    sportsbook = f"DeleteBonus-{run_id}"

    deposit_r = auth_client.post(
        "/transactions",
        json={
            "sportsbook": sportsbook,
            "type": TransactionType.DEPOSIT.value,
            "amount": 250,
            "notes": run_id,
        },
        headers=auth_headers,
    )
    assert deposit_r.status_code == 201
    tracker.tx_ids.append(deposit_r.json()["id"])

    before_r = auth_client.get("/balances", headers=auth_headers)
    assert before_r.status_code == 200
    balance_before = _book_balance(before_r.json(), sportsbook)

    create_r = auth_client.post(
        "/bets",
        json={
            "sport": "NBA",
            "event": f"Delete pending bonus {run_id}",
            "market": "ML",
            "sportsbook": sportsbook,
            "promo_type": "bonus_bet",
            "odds_american": -110,
            "stake": 40,
        },
        headers=auth_headers,
    )
    assert create_r.status_code == 201
    bet_id = create_r.json()["id"]
    tracker.bet_ids.append(bet_id)

    during_r = auth_client.get("/balances", headers=auth_headers)
    assert during_r.status_code == 200
    balance_during = _book_balance(during_r.json(), sportsbook)
    assert round(balance_during, 2) == round(balance_before, 2)

    delete_r = auth_client.delete(f"/bets/{bet_id}", headers=auth_headers)
    assert delete_r.status_code == 200

    after_r = auth_client.get("/balances", headers=auth_headers)
    assert after_r.status_code == 200
    balance_after = _book_balance(after_r.json(), sportsbook)
    assert round(balance_after, 2) == round(balance_before, 2)
