import json
import os
import threading
import time

try:
    import redis  # type: ignore
except Exception:
    redis = None

_REDIS_URL = os.getenv("REDIS_URL")
_WARNED_REDIS_IMPORT = False
_REDIS_CLIENT = None

_LOCK = threading.Lock()
_MEMORY_TTL_STORE: dict[str, tuple[float, str]] = {}


def _get_redis_client():
    global _WARNED_REDIS_IMPORT, _REDIS_CLIENT

    if not _REDIS_URL:
        return None
    if redis is None:
        if not _WARNED_REDIS_IMPORT:
            _WARNED_REDIS_IMPORT = True
            print("[SharedState] REDIS_URL set but redis package is not installed. Falling back to in-memory state.")
        return None
    if _REDIS_CLIENT is None:
        _REDIS_CLIENT = redis.from_url(_REDIS_URL, decode_responses=True)
    return _REDIS_CLIENT


def _memory_get(key: str) -> str | None:
    now = time.time()
    with _LOCK:
        item = _MEMORY_TTL_STORE.get(key)
        if not item:
            return None
        expires_at, value = item
        if expires_at <= now:
            _MEMORY_TTL_STORE.pop(key, None)
            return None
        return value


def _memory_set(key: str, value: str, ttl_seconds: int) -> None:
    expires_at = time.time() + ttl_seconds
    with _LOCK:
        _MEMORY_TTL_STORE[key] = (expires_at, value)


def get_json(key: str) -> dict | list | None:
    client = _get_redis_client()
    if client is not None:
        try:
            raw = client.get(key)
            return json.loads(raw) if raw else None
        except Exception as e:
            print(f"[SharedState] Redis GET failed for {key}: {e}")

    raw_local = _memory_get(key)
    if not raw_local:
        return None
    try:
        return json.loads(raw_local)
    except Exception:
        return None


def set_json(key: str, value: dict | list, ttl_seconds: int) -> None:
    payload = json.dumps(value, default=str)
    client = _get_redis_client()
    if client is not None:
        try:
            client.set(key, payload, ex=ttl_seconds)
            return
        except Exception as e:
            print(f"[SharedState] Redis SET failed for {key}: {e}")
    _memory_set(key, payload, ttl_seconds)


def mark_once(key: str, ttl_seconds: int) -> bool:
    """Return True if key was newly marked, False if already present in the TTL window."""
    client = _get_redis_client()
    if client is not None:
        try:
            created = client.set(key, "1", nx=True, ex=ttl_seconds)
            return bool(created)
        except Exception as e:
            print(f"[SharedState] Redis mark_once failed for {key}: {e}")

    now = time.time()
    with _LOCK:
        existing = _MEMORY_TTL_STORE.get(key)
        if existing:
            expires_at, _value = existing
            if expires_at > now:
                return False
        _MEMORY_TTL_STORE[key] = (now + ttl_seconds, "1")
        return True


def allow_fixed_window_rate_limit(bucket_key: str, max_requests: int, window_seconds: int) -> bool:
    """Distributed-friendly fixed-window rate limiter. Returns True when request is allowed."""
    window_id = int(time.time() // window_seconds)
    key = f"rl:{bucket_key}:{window_id}"

    client = _get_redis_client()
    if client is not None:
        try:
            count = client.incr(key)
            if count == 1:
                client.expire(key, window_seconds)
            return count <= max_requests
        except Exception as e:
            print(f"[SharedState] Redis rate-limit failed for {bucket_key}: {e}")

    now = time.time()
    with _LOCK:
        existing = _MEMORY_TTL_STORE.get(key)
        if existing:
            expires_at, value = existing
            if expires_at > now:
                count = int(value)
            else:
                count = 0
        else:
            count = 0

        count += 1
        _MEMORY_TTL_STORE[key] = (now + window_seconds, str(count))
        return count <= max_requests


def scan_cache_key(sport: str) -> str:
    return f"scan-cache:{sport}"


def get_scan_cache(sport: str) -> dict | None:
    data = get_json(scan_cache_key(sport))
    return data if isinstance(data, dict) else None


def set_scan_cache(sport: str, payload: dict, ttl_seconds: int) -> None:
    set_json(scan_cache_key(sport), payload, ttl_seconds)


def dedupe_alert_key(key: str) -> str:
    return f"alert-dedupe:{key}"


def mark_alert_if_new(alert_key: str, ttl_seconds: int) -> bool:
    return mark_once(dedupe_alert_key(alert_key), ttl_seconds)


def is_redis_enabled() -> bool:
    return bool(_REDIS_URL)
