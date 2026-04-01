from __future__ import annotations

from contextvars import ContextVar, Token


_request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
_correlation_id_var: ContextVar[str | None] = ContextVar("correlation_id", default=None)
_db_roundtrip_count_var: ContextVar[int] = ContextVar("db_roundtrip_count", default=0)
_db_roundtrip_duration_ms_var: ContextVar[float] = ContextVar("db_roundtrip_duration_ms", default=0.0)


def set_request_context(*, request_id: str | None, correlation_id: str | None) -> tuple[Token, Token]:
    return (
        _request_id_var.set(request_id),
        _correlation_id_var.set(correlation_id),
    )


def reset_request_context(*, request_token: Token, correlation_token: Token) -> None:
    _request_id_var.reset(request_token)
    _correlation_id_var.reset(correlation_token)


def get_request_id() -> str | None:
    return _request_id_var.get()


def get_correlation_id() -> str | None:
    return _correlation_id_var.get()


def reset_db_metrics() -> tuple[Token, Token]:
    return (
        _db_roundtrip_count_var.set(0),
        _db_roundtrip_duration_ms_var.set(0.0),
    )


def restore_db_metrics(*, count_token: Token, duration_token: Token) -> None:
    _db_roundtrip_count_var.reset(count_token)
    _db_roundtrip_duration_ms_var.reset(duration_token)


def record_db_roundtrip(duration_ms: float | int | None = None) -> None:
    _db_roundtrip_count_var.set(_db_roundtrip_count_var.get() + 1)
    if isinstance(duration_ms, (int, float)):
        _db_roundtrip_duration_ms_var.set(_db_roundtrip_duration_ms_var.get() + float(duration_ms))


def get_db_metrics() -> dict[str, float | int]:
    return {
        "roundtrip_count": _db_roundtrip_count_var.get(),
        "roundtrip_duration_ms": round(_db_roundtrip_duration_ms_var.get(), 2),
    }
