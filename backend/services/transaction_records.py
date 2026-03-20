from typing import Any


def build_transaction_insert_payload(*, user_id: str, transaction) -> dict[str, Any]:
    payload = {
        "user_id": user_id,
        "sportsbook": transaction.sportsbook,
        "type": transaction.type.value,
        "amount": transaction.amount,
        "notes": transaction.notes,
    }
    if transaction.created_at:
        payload["created_at"] = transaction.created_at.isoformat()
    return payload


def transaction_row_to_response_payload(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "sportsbook": row["sportsbook"],
        "type": row["type"],
        "amount": row["amount"],
        "notes": row.get("notes"),
    }


def transaction_rows_to_response_payloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [transaction_row_to_response_payload(row) for row in rows]