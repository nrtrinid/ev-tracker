from typing import Any


def transaction_type_value(transaction) -> str:
    raw_type = getattr(transaction, "type", None)
    return str(getattr(raw_type, "value", raw_type) or "")


def validate_transaction_against_balance(*, transaction, current_balance: float) -> None:
    tx_type = transaction_type_value(transaction)
    amount = float(getattr(transaction, "amount", 0.0) or 0.0)

    if tx_type in {"deposit", "withdrawal"} and amount <= 0:
        raise ValueError("Amount must be positive.")

    if tx_type == "adjustment" and amount == 0:
        raise ValueError("Adjustment must change the tracked balance.")

    if tx_type == "withdrawal" and current_balance - amount < -0.005:
        raise ValueError("Withdrawal would make the tracked balance negative.")

    if tx_type == "adjustment" and current_balance + amount < -0.005:
        raise ValueError("Adjustment would make the tracked balance negative.")


def build_transaction_insert_payload(*, user_id: str, transaction) -> dict[str, Any]:
    transaction_date = (
        getattr(transaction, "transaction_date", None)
        or getattr(transaction, "created_at", None)
    )
    payload = {
        "user_id": user_id,
        "sportsbook": transaction.sportsbook,
        "type": transaction_type_value(transaction),
        "amount": transaction.amount,
        "notes": transaction.notes,
    }
    if transaction_date:
        payload["transaction_date"] = transaction_date.isoformat()
    created_at = getattr(transaction, "created_at", None)
    if created_at:
        payload["created_at"] = created_at.isoformat()
    return payload


def transaction_row_to_response_payload(row: dict[str, Any]) -> dict[str, Any]:
    created_at = row["created_at"]
    return {
        "id": row["id"],
        "created_at": created_at,
        "transaction_date": row.get("transaction_date") or created_at,
        "updated_at": row.get("updated_at") or created_at,
        "sportsbook": row["sportsbook"],
        "type": row["type"],
        "amount": row["amount"],
        "notes": row.get("notes"),
    }


def transaction_rows_to_response_payloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [transaction_row_to_response_payload(row) for row in rows]
