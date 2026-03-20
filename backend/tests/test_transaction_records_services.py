from datetime import datetime, UTC
from types import SimpleNamespace

from services.transaction_records import (
    build_transaction_insert_payload,
    transaction_row_to_response_payload,
    transaction_rows_to_response_payloads,
)


def test_build_transaction_insert_payload_includes_optional_created_at():
    tx = SimpleNamespace(
        sportsbook="DraftKings",
        type=SimpleNamespace(value="deposit"),
        amount=100,
        notes="test",
        created_at=datetime(2026, 3, 19, tzinfo=UTC),
    )

    out = build_transaction_insert_payload(user_id="u1", transaction=tx)

    assert out["user_id"] == "u1"
    assert out["sportsbook"] == "DraftKings"
    assert out["type"] == "deposit"
    assert out["amount"] == 100
    assert out["notes"] == "test"
    assert out["created_at"] == "2026-03-19T00:00:00+00:00"


def test_build_transaction_insert_payload_omits_created_at_when_not_set():
    tx = SimpleNamespace(
        sportsbook="FanDuel",
        type=SimpleNamespace(value="withdrawal"),
        amount=25,
        notes=None,
        created_at=None,
    )

    out = build_transaction_insert_payload(user_id="u2", transaction=tx)

    assert out["user_id"] == "u2"
    assert "created_at" not in out


def test_transaction_row_to_response_payload_and_list_mapper():
    row = {
        "id": "tx1",
        "created_at": "2026-03-19T00:00:00Z",
        "sportsbook": "BetMGM",
        "type": "deposit",
        "amount": 10,
        "notes": "note",
    }

    mapped = transaction_row_to_response_payload(row)
    assert mapped == row

    mapped_list = transaction_rows_to_response_payloads([row])
    assert mapped_list == [row]
