from datetime import datetime, UTC
from types import SimpleNamespace

import pytest

from services.transaction_records import (
    build_transaction_insert_payload,
    transaction_row_to_response_payload,
    transaction_rows_to_response_payloads,
    validate_transaction_against_balance,
)


def test_build_transaction_insert_payload_includes_optional_created_at():
    tx = SimpleNamespace(
        sportsbook="DraftKings",
        type=SimpleNamespace(value="deposit"),
        amount=100,
        notes="test",
        transaction_date=None,
        created_at=datetime(2026, 3, 19, tzinfo=UTC),
    )

    out = build_transaction_insert_payload(user_id="u1", transaction=tx)

    assert out["user_id"] == "u1"
    assert out["sportsbook"] == "DraftKings"
    assert out["type"] == "deposit"
    assert out["amount"] == 100
    assert out["notes"] == "test"
    assert out["created_at"] == "2026-03-19T00:00:00+00:00"
    assert out["transaction_date"] == "2026-03-19T00:00:00+00:00"


def test_build_transaction_insert_payload_prefers_transaction_date():
    tx = SimpleNamespace(
        sportsbook="DraftKings",
        type=SimpleNamespace(value="deposit"),
        amount=100,
        notes=None,
        transaction_date=datetime(2026, 3, 20, tzinfo=UTC),
        created_at=datetime(2026, 3, 19, tzinfo=UTC),
    )

    out = build_transaction_insert_payload(user_id="u1", transaction=tx)

    assert out["created_at"] == "2026-03-19T00:00:00+00:00"
    assert out["transaction_date"] == "2026-03-20T00:00:00+00:00"


def test_build_transaction_insert_payload_omits_created_at_when_not_set():
    tx = SimpleNamespace(
        sportsbook="FanDuel",
        type=SimpleNamespace(value="withdrawal"),
        amount=25,
        notes=None,
        transaction_date=None,
        created_at=None,
    )

    out = build_transaction_insert_payload(user_id="u2", transaction=tx)

    assert out["user_id"] == "u2"
    assert "created_at" not in out
    assert "transaction_date" not in out


def test_transaction_row_to_response_payload_and_list_mapper():
    row = {
        "id": "tx1",
        "created_at": "2026-03-19T00:00:00Z",
        "transaction_date": "2026-03-20T00:00:00Z",
        "updated_at": "2026-03-21T00:00:00Z",
        "sportsbook": "BetMGM",
        "type": "adjustment",
        "amount": -10,
        "notes": "note",
    }

    mapped = transaction_row_to_response_payload(row)
    assert mapped == row

    mapped_list = transaction_rows_to_response_payloads([row])
    assert mapped_list == [row]


def test_transaction_row_to_response_payload_backfills_new_dates_for_legacy_rows():
    row = {
        "id": "tx1",
        "created_at": "2026-03-19T00:00:00Z",
        "sportsbook": "BetMGM",
        "type": "deposit",
        "amount": 10,
        "notes": None,
    }

    mapped = transaction_row_to_response_payload(row)

    assert mapped["transaction_date"] == row["created_at"]
    assert mapped["updated_at"] == row["created_at"]


def test_validate_transaction_against_balance_rejects_negative_withdrawal_projection():
    tx = SimpleNamespace(type=SimpleNamespace(value="withdrawal"), amount=25)

    with pytest.raises(ValueError, match="negative"):
        validate_transaction_against_balance(transaction=tx, current_balance=10)


def test_validate_transaction_against_balance_allows_signed_adjustment_delta():
    validate_transaction_against_balance(
        transaction=SimpleNamespace(type=SimpleNamespace(value="adjustment"), amount=-5),
        current_balance=10,
    )

    with pytest.raises(ValueError, match="change"):
        validate_transaction_against_balance(
            transaction=SimpleNamespace(type=SimpleNamespace(value="adjustment"), amount=0),
            current_balance=10,
        )

    with pytest.raises(ValueError, match="negative"):
        validate_transaction_against_balance(
            transaction=SimpleNamespace(type=SimpleNamespace(value="adjustment"), amount=-15),
            current_balance=10,
        )
