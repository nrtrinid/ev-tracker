from datetime import datetime, timezone

from models import BetLiveSnapshotResponse


def test_bets_live_requires_auth(public_client):
    response = public_client.get("/bets/live")

    assert response.status_code == 401


def test_bets_live_returns_live_snapshot_contract(auth_client, monkeypatch):
    async def _fake_live_snapshots(db, user):
        return BetLiveSnapshotResponse(
            generated_at=datetime(2026, 4, 22, 3, 15, tzinfo=timezone.utc),
            ttl_seconds=60,
            active_bet_count=0,
            snapshots_by_bet_id={},
        )

    import services.bet_live_tracking as bet_live_tracking
    import routes.bet_routes as bet_routes

    monkeypatch.setattr(bet_live_tracking, "get_bet_live_snapshots_impl", _fake_live_snapshots)
    monkeypatch.setattr(bet_routes, "get_db", lambda: object())

    response = auth_client.get("/bets/live")

    assert response.status_code == 200
    payload = response.json()
    assert payload["ttl_seconds"] == 60
    assert payload["active_bet_count"] == 0
    assert payload["snapshots_by_bet_id"] == {}
