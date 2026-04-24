from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from services.shared_state import get_json, set_json

PLAYER_PROP_WEIGHT_CACHE_KEY = "player-prop-model-weights"
PLAYER_PROP_WEIGHT_CACHE_TTL_SECONDS = 60 * 60 * 6
PLAYER_PROP_WEIGHT_LOOKBACK_DAYS_ENV = "PLAYER_PROP_WEIGHT_LOOKBACK_DAYS"
PLAYER_PROP_WEIGHT_MIN_SAMPLES_ENV = "PLAYER_PROP_WEIGHT_MIN_SAMPLES"
PLAYER_PROP_WEIGHT_SUPPORTED_MODELS = {"props_v2_shadow", "props_v2_live"}
PLAYER_PROP_WEIGHT_DEFAULTS: dict[str, float] = {
    "betonlineag": 3.0,
    "bovada": 1.5,
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=timezone.utc)


def _coerce_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def get_player_prop_weight_lookback_days() -> int:
    raw = str(os.getenv(PLAYER_PROP_WEIGHT_LOOKBACK_DAYS_ENV) or "").strip()
    try:
        parsed = int(raw)
    except Exception:
        parsed = 30
    return max(7, min(parsed, 90))


def get_player_prop_weight_min_samples() -> int:
    raw = str(os.getenv(PLAYER_PROP_WEIGHT_MIN_SAMPLES_ENV) or "").strip()
    try:
        parsed = int(raw)
    except Exception:
        parsed = 25
    return max(5, min(parsed, 500))


def is_missing_player_prop_model_weights_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("player_prop_model_weights" in msg and "schema cache" in msg)


def is_missing_scan_opportunity_model_evaluations_error(error: Exception) -> bool:
    msg = str(error)
    return "PGRST205" in msg or ("scan_opportunity_model_evaluations" in msg and "schema cache" in msg)


def _normalized_weight_payload(rows: list[dict[str, Any]]) -> dict[str, dict[str, float]]:
    weights: dict[str, dict[str, float]] = {}
    for row in rows:
        market_key = str(row.get("market_key") or "").strip()
        sportsbook_key = str(row.get("sportsbook_key") or "").strip()
        weight = _coerce_float(row.get("weight"))
        if not market_key or not sportsbook_key or weight is None or weight <= 0:
            continue
        weights.setdefault(market_key, {})[sportsbook_key] = float(weight)
    return weights


def get_player_prop_weight_overrides(db=None) -> dict[str, dict[str, float]]:
    cached = get_json(PLAYER_PROP_WEIGHT_CACHE_KEY)
    if isinstance(cached, dict) and isinstance(cached.get("weights"), dict):
        return {
            str(market): {str(book): float(weight) for book, weight in (books or {}).items()}
            for market, books in cached["weights"].items()
            if isinstance(books, dict)
        }

    if db is None:
        try:
            from database import get_db

            db = get_db()
        except Exception:
            return {}
    if db is None:
        return {}

    try:
        result = db.table("player_prop_model_weights").select(
            "market_key,sportsbook_key,weight"
        ).execute()
    except Exception as exc:
        if is_missing_player_prop_model_weights_error(exc):
            return {}
        raise

    rows = list(result.data or [])
    weights = _normalized_weight_payload(rows)
    set_json(
        PLAYER_PROP_WEIGHT_CACHE_KEY,
        {"updated_at": _utc_now().isoformat(), "weights": weights},
        PLAYER_PROP_WEIGHT_CACHE_TTL_SECONDS,
    )
    return weights


def train_player_prop_model_weights(
    db,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    current = now or _utc_now()
    lookback_days = get_player_prop_weight_lookback_days()
    min_samples = get_player_prop_weight_min_samples()
    cutoff = current - timedelta(days=lookback_days)

    try:
        result = db.table("scan_opportunity_model_evaluations").select(
            "id,model_key,market,sportsbook_key,first_true_prob,close_true_prob,close_captured_at"
        ).execute()
    except Exception as exc:
        if is_missing_scan_opportunity_model_evaluations_error(exc):
            return {
                "ok": False,
                "trained_rows": 0,
                "markets": 0,
                "lookback_days": lookback_days,
                "min_samples": min_samples,
                "reason": "missing_evaluations_table",
            }
        raise

    recent_rows: list[dict[str, Any]] = []
    for row in result.data or []:
        model_key = str(row.get("model_key") or "").strip().lower()
        if model_key not in PLAYER_PROP_WEIGHT_SUPPORTED_MODELS:
            continue
        close_prob = _coerce_float(row.get("close_true_prob"))
        first_prob = _coerce_float(row.get("first_true_prob"))
        close_captured_at = _coerce_datetime(row.get("close_captured_at"))
        if close_prob is None or first_prob is None or close_captured_at is None:
            continue
        if close_captured_at < cutoff:
            continue
        recent_rows.append(dict(row))

    grouped: dict[str, dict[str, list[tuple[float, float]]]] = {}
    for row in recent_rows:
        market_key = str(row.get("market") or "").strip()
        sportsbook_key = str(row.get("sportsbook_key") or "").strip().lower()
        close_prob = float(row["close_true_prob"])
        first_prob = float(row["first_true_prob"])
        close_captured_at = _coerce_datetime(row.get("close_captured_at")) or current
        age_days = max(0.0, (current - close_captured_at).total_seconds() / 86400.0)
        recency_weight = math.exp(-age_days / 7.0)
        grouped.setdefault(market_key, {}).setdefault(sportsbook_key, []).append((abs(first_prob - close_prob), recency_weight))

    upserts: list[dict[str, Any]] = []
    for market_key, market_group in grouped.items():
        raw_weights: dict[str, float] = {}
        counts: dict[str, int] = {}
        metrics: dict[str, float] = {}
        for sportsbook_key, samples in market_group.items():
            counts[sportsbook_key] = len(samples)
            if len(samples) < min_samples:
                continue
            weighted_error_sum = sum(error * weight for error, weight in samples)
            total_weight = sum(weight for _error, weight in samples)
            if total_weight <= 0:
                continue
            weighted_mae = weighted_error_sum / total_weight
            metrics[sportsbook_key] = weighted_mae
            raw_weights[sportsbook_key] = 1.0 / max(weighted_mae, 0.015)

        if not raw_weights:
            continue

        mean_weight = sum(raw_weights.values()) / len(raw_weights)
        if mean_weight <= 0:
            continue

        for sportsbook_key, raw_weight in raw_weights.items():
            normalized = max(0.5, min(round(raw_weight / mean_weight, 4), 3.5))
            upserts.append(
                {
                    "model_family": "props_v2",
                    "market_key": market_key,
                    "sportsbook_key": sportsbook_key,
                    "weight": normalized,
                    "sample_count": counts.get(sportsbook_key, 0),
                    "weighted_mae": round(metrics.get(sportsbook_key, 0.0), 6),
                    "updated_at": current.isoformat(),
                }
            )

    if upserts:
        try:
            existing = db.table("player_prop_model_weights").select(
                "id,market_key,sportsbook_key"
            ).execute()
        except Exception as exc:
            if is_missing_player_prop_model_weights_error(exc):
                return {
                    "ok": False,
                    "trained_rows": 0,
                    "markets": 0,
                    "lookback_days": lookback_days,
                    "min_samples": min_samples,
                    "reason": "missing_weights_table",
                }
            raise

        existing_by_key = {
            (str(row.get("market_key") or ""), str(row.get("sportsbook_key") or "").lower()): row
            for row in (existing.data or [])
        }
        for payload in upserts:
            key = (str(payload.get("market_key") or ""), str(payload.get("sportsbook_key") or "").lower())
            row = existing_by_key.get(key)
            if row is None:
                db.table("player_prop_model_weights").insert(payload).execute()
            else:
                db.table("player_prop_model_weights").update(payload).eq("id", row["id"]).execute()

    weights = _normalized_weight_payload(upserts)
    if weights:
        set_json(
            PLAYER_PROP_WEIGHT_CACHE_KEY,
            {"updated_at": current.isoformat(), "weights": weights},
            PLAYER_PROP_WEIGHT_CACHE_TTL_SECONDS,
        )

    return {
        "ok": True,
        "trained_rows": len(upserts),
        "markets": len({row["market_key"] for row in upserts}),
        "lookback_days": lookback_days,
        "min_samples": min_samples,
        "source_rows": len(recent_rows),
    }
