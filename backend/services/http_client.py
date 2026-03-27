from __future__ import annotations

import asyncio
import random
import time
from typing import Any, Iterable

import httpx

_CLIENT: httpx.AsyncClient | None = None
_CLIENT_LOCK = asyncio.Lock()


def _default_timeout() -> httpx.Timeout:
    # Conservative split timeouts: fail fast on connect/pool, allow moderate reads.
    return httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


def _default_limits() -> httpx.Limits:
    # Keep small-instance footprint in mind.
    return httpx.Limits(max_connections=20, max_keepalive_connections=10, keepalive_expiry=30.0)


async def get_async_client() -> httpx.AsyncClient:
    global _CLIENT
    if _CLIENT is not None:
        return _CLIENT
    async with _CLIENT_LOCK:
        if _CLIENT is None:
            try:
                _CLIENT = httpx.AsyncClient(
                    timeout=_default_timeout(),
                    limits=_default_limits(),
                    headers={"user-agent": "ev-betting-tracker-backend"},
                )
            except TypeError:
                # Unit tests sometimes monkeypatch httpx.AsyncClient with a
                # simplified stub that doesn't accept all kwargs.
                _CLIENT = httpx.AsyncClient(timeout=_default_timeout())
        return _CLIENT


async def close_async_client() -> None:
    global _CLIENT
    client = _CLIENT
    _CLIENT = None
    if client is None:
        return
    try:
        await client.aclose()
    except Exception:
        return


def _is_retryable_httpx_error(exc: Exception) -> bool:
    return isinstance(
        exc,
        (
            httpx.ReadError,
            httpx.ConnectError,
            httpx.RemoteProtocolError,
            httpx.PoolTimeout,
            httpx.TimeoutException,
        ),
    )


async def request_with_retries(
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    json: Any | None = None,
    data: Any | None = None,
    timeout: httpx.Timeout | float | None = None,
    retries: int = 2,
    retryable_status_codes: Iterable[int] = (502, 503, 504),
) -> httpx.Response:
    """
    Make an HTTP request with small-instance-friendly retries.

    - Retries transport read/connect/pool/timeout errors.
    - Retries specific upstream status codes (default: 502/503/504).
    - Uses exponential backoff with jitter.
    """
    client = await get_async_client()
    last_exc: Exception | None = None
    attempts = max(1, retries + 1)

    for attempt in range(attempts):
        try:
            upper = method.upper()

            # If a prior test run left us with a stub client that can't do this method,
            # recreate the singleton so the current monkeypatch (if any) takes effect.
            if not hasattr(client, "request") and upper == "GET" and not hasattr(client, "get"):
                await close_async_client()
                client = await get_async_client()
            if not hasattr(client, "request") and upper == "POST" and not hasattr(client, "post"):
                await close_async_client()
                client = await get_async_client()

            if hasattr(client, "request"):
                resp = await client.request(
                    method,
                    url,
                    params=params,
                    headers=headers,
                    json=json,
                    data=data,
                    timeout=timeout,
                )
            else:
                if upper == "GET" and hasattr(client, "get"):
                    kwargs: dict[str, Any] = {}
                    if params is not None:
                        kwargs["params"] = params
                    if headers is not None:
                        kwargs["headers"] = headers
                    if timeout is not None:
                        kwargs["timeout"] = timeout
                    resp = await client.get(url, **kwargs)
                elif upper == "POST" and hasattr(client, "post"):
                    kwargs = {}
                    if params is not None:
                        kwargs["params"] = params
                    if headers is not None:
                        kwargs["headers"] = headers
                    if json is not None:
                        kwargs["json"] = json
                    if data is not None:
                        kwargs["data"] = data
                    if timeout is not None:
                        kwargs["timeout"] = timeout
                    try:
                        resp = await client.post(url, **kwargs)
                    except TypeError:
                        # Some test stubs only accept (url, json=...).
                        resp = await client.post(url, json=json)
                else:
                    raise AttributeError("http client lacks request/get/post")
            if resp.status_code in set(retryable_status_codes) and attempt < attempts - 1:
                # Drain body to release connection back to pool.
                try:
                    _ = resp.text
                except Exception:
                    pass
                sleep_s = min(2.0, 0.25 * (2**attempt)) + random.random() * 0.15
                await asyncio.sleep(sleep_s)
                continue
            return resp
        except Exception as exc:
            last_exc = exc if isinstance(exc, Exception) else Exception(str(exc))
            if attempt >= attempts - 1 or not _is_retryable_httpx_error(last_exc):
                raise
            sleep_s = min(2.0, 0.25 * (2**attempt)) + random.random() * 0.15
            await asyncio.sleep(sleep_s)

    assert last_exc is not None
    raise last_exc

