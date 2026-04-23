import asyncio
import json
import os
from typing import Any
from urllib.parse import urlencode

import httpx
from services.shared_state import is_redis_enabled, mark_alert_if_new
from services.match_keys import alert_key_from_side

ALERTED_KEYS: set[str] = set()
_warned_missing_webhook = False
_warned_alert_route_disabled = False
ALERT_DEDUPE_TTL_SECONDS = int(os.getenv("ALERT_DEDUPE_TTL_SECONDS", "21600"))

FRONTEND_BASE_URL = "https://ev-tracker-gamma.vercel.app"


class DiscordDeliveryError(RuntimeError):
    def __init__(
        self,
        *,
        message: str,
        message_type: str,
        status_code: int | None = None,
        response_text: str | None = None,
        route_kind: str | None = None,
        webhook_source: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message_type = message_type
        self.status_code = status_code
        self.response_text = response_text
        self.route_kind = route_kind
        self.webhook_source = webhook_source


def _empty_schedule_stats() -> dict[str, int]:
    return {
        "candidates_seen": 0,
        "scheduled": 0,
        "skipped_memory_dedupe": 0,
        "skipped_shared_dedupe": 0,
        "skipped_threshold": 0,
        "skipped_total": 0,
    }


_LAST_SCHEDULE_STATS: dict[str, int] = _empty_schedule_stats()


def _is_alert_route_enabled() -> bool:
    # Keep alert-path delivery enabled unless explicitly disabled.
    return (os.getenv("DISCORD_ENABLE_ALERT_ROUTE") or "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _resolve_route_config(message_type: str = "alert") -> dict[str, Any]:
    normalized = (message_type or "alert").strip().lower() or "alert"

    if normalized == "alert":
        # Default-safe behavior: alert-path Discord delivery is opt-in.
        if not _is_alert_route_enabled():
            return {
                "message_type": normalized,
                "route_kind": "alert_disabled",
                "webhook_url": None,
                "webhook_source": None,
                "mention_role_id": None,
                "role_source": None,
            }
        route_prefix = "alert"
        webhook_env = "DISCORD_ALERT_WEBHOOK_URL"
        role_env = "DISCORD_ALERT_MENTION_ROLE_ID"
        allow_primary_fallback = True
    elif normalized == "heartbeat":
        route_prefix = normalized
        webhook_env = "DISCORD_DEBUG_WEBHOOK_URL"
        role_env = "DISCORD_DEBUG_MENTION_ROLE_ID"
        allow_primary_fallback = os.getenv("DISCORD_ALLOW_DEBUG_FALLBACK_TO_PRIMARY") == "1"
    elif normalized == "test":
        route_prefix = normalized
        webhook_env = "DISCORD_DEBUG_WEBHOOK_URL"
        role_env = "DISCORD_DEBUG_MENTION_ROLE_ID"
        # Keep validation traffic isolated to the debug route.
        allow_primary_fallback = False
    else:
        route_prefix = "unknown"
        webhook_env = None
        role_env = None
        allow_primary_fallback = True

    webhook_url = None
    webhook_source = None
    if webhook_env and os.getenv(webhook_env):
        webhook_url = os.getenv(webhook_env)
        webhook_source = webhook_env
        route_kind = f"{route_prefix}_dedicated"
    elif allow_primary_fallback and os.getenv("DISCORD_WEBHOOK_URL"):
        webhook_url = os.getenv("DISCORD_WEBHOOK_URL")
        webhook_source = "DISCORD_WEBHOOK_URL"
        route_kind = f"{route_prefix}_primary_fallback"
    else:
        route_kind = f"{route_prefix}_unconfigured"

    role_id = None
    role_source = None
    if role_env and os.getenv(role_env):
        role_id = os.getenv(role_env)
        role_source = role_env
    elif allow_primary_fallback and os.getenv("DISCORD_MENTION_ROLE_ID"):
        role_id = os.getenv("DISCORD_MENTION_ROLE_ID")
        role_source = "DISCORD_MENTION_ROLE_ID"

    return {
        "message_type": normalized,
        "route_kind": route_kind,
        "webhook_url": webhook_url,
        "webhook_source": webhook_source,
        "mention_role_id": role_id,
        "role_source": role_source,
    }


def describe_discord_delivery_target(message_type: str = "alert") -> dict[str, Any]:
    config = _resolve_route_config(message_type)
    return {
        "message_type": config["message_type"],
        "route_kind": config["route_kind"],
        "webhook_configured": bool(config["webhook_url"]),
        "webhook_source": config["webhook_source"],
        "role_configured": bool(config["mention_role_id"]),
        "role_source": config["role_source"],
        "dedupe_ttl_seconds": ALERT_DEDUPE_TTL_SECONDS,
        "redis_enabled": is_redis_enabled(),
    }


def get_last_schedule_stats() -> dict[str, int]:
    return dict(_LAST_SCHEDULE_STATS)


def _get_webhook_and_role(message_type: str = "alert") -> tuple[str | None, str | None]:
    """
    Route to appropriate webhook and role mention based on message type.
    
    Args:
        message_type: "alert" (bet alerts), "heartbeat" (debug/operational), or "test" (webhook validation)
    
    Returns:
        Tuple of (webhook_url, mention_role_id) with fallback to primary webhook if secondary not set.
    """
    config = _resolve_route_config(message_type)
    webhook = config["webhook_url"]
    role = config["mention_role_id"]

    return webhook, role


def _with_role_mention(payload: dict[str, Any], role_id: str | None = None) -> dict[str, Any]:
    """
    If role_id is provided (or DISCORD_MENTION_ROLE_ID fallback is set), 
    prepend a role mention to the message content.
    This will only notify users if the role is mentionable and the channel allows role mentions.
    """
    if role_id is None:
        role_id = os.getenv("DISCORD_MENTION_ROLE_ID")
    
    if not role_id:
        return payload

    mention = f"<@&{role_id}>"
    content = str(payload.get("content") or "").strip()
    payload["content"] = f"{mention} {content}".strip()
    return payload


def should_alert(side: dict[str, Any]) -> bool:
    try:
        ev = float(side.get("ev_percentage", 0))
        odds = float(side.get("book_odds", 0))
    except Exception:
        return False
    return ev >= 1.5 and odds <= 500


def make_alert_key(side: dict[str, Any]) -> str:
    return alert_key_from_side(side)


def build_scanner_deeplink(side: dict[str, Any]) -> str:
    params = {
        "sport": side.get("sport", ""),
        "event": side.get("event", ""),
        "team": side.get("team", ""),
        "book": side.get("sportsbook", ""),
    }
    event_id = str(side.get("event_id") or "").strip()
    if event_id:
        params["event_id"] = event_id
    return f"{FRONTEND_BASE_URL}/scanner?{urlencode(params)}"


def build_discord_payload(side: dict[str, Any]) -> dict[str, Any]:
    sport = str(side.get("sport", ""))
    event = str(side.get("event", ""))
    team = str(side.get("team", ""))
    book = str(side.get("sportsbook", ""))
    odds = side.get("book_odds", "")
    ev = side.get("ev_percentage", "")


    link = build_scanner_deeplink(side)

    try:
        ev_value = float(ev)
    except Exception:
        ev_value = None

    is_high_edge = ev_value is not None and ev_value >= 3.0
    tier_label = "HIGH EDGE" if is_high_edge else "Solid Edge"
    title_prefix = "HIGH EDGE" if is_high_edge else "Solid Edge"

    return {
        "embeds": [
            {
                "title": (
                    f"{title_prefix} ({ev_value:.2f}% EV)"
                    if ev_value is not None
                    else title_prefix
                ),
                "description": f"**{team} ML** at **{book}**",
                "url": link,
                "fields": [
                    {"name": "Tier", "value": tier_label, "inline": True},
                    {"name": "Sport", "value": sport or "—", "inline": True},
                    {"name": "Matchup", "value": event or "—", "inline": False},
                    {"name": "Odds", "value": f"{odds:+}" if isinstance(odds, (int, float)) else str(odds), "inline": True},
                    {"name": "EV", "value": f"{float(ev):.2f}%" if isinstance(ev, (int, float)) else str(ev), "inline": True},
                    {"name": "Link", "value": f"[Open scanner]({link})", "inline": False},
                ],
            }
        ]
    }


def build_board_drop_alert_payload(
    *,
    window_label: str,
    anchor_time_mst: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    props_sides = int(result.get("props_sides") or 0)
    straight_sides = int(result.get("straight_sides") or 0)
    featured_games = int(result.get("featured_games_count") or 0)
    board_url = f"{FRONTEND_BASE_URL}/"
    return {
        "embeds": [
            {
                "title": "Trusted Beta Board Live",
                "description": f"{window_label} completed at {anchor_time_mst} MST.",
                "fields": [
                    {"name": "Player Props", "value": str(props_sides), "inline": True},
                    {"name": "Game Lines", "value": str(straight_sides), "inline": True},
                    {"name": "Featured Games", "value": str(featured_games), "inline": True},
                    {"name": "Open Board", "value": f"[Open EV Tracker]({board_url})", "inline": False},
                ],
            }
        ]
    }


async def send_discord_webhook(payload: dict[str, Any], message_type: str = "alert") -> dict[str, Any]:
    global _warned_alert_route_disabled, _warned_missing_webhook

    route_config = _resolve_route_config(message_type)
    target = describe_discord_delivery_target(message_type)
    webhook_url = route_config["webhook_url"]
    role_id = route_config["mention_role_id"]

    if not webhook_url:
        if route_config.get("route_kind") == "alert_disabled":
            if not _warned_alert_route_disabled:
                _warned_alert_route_disabled = True
                print(
                    "[Discord] Alert route disabled (DISCORD_ENABLE_ALERT_ROUTE=0); "
                    "alert-path notifications suppressed."
                )
        elif not _warned_missing_webhook:
            _warned_missing_webhook = True
            print("[Discord] DISCORD_WEBHOOK_URL not set; alerts disabled.")
        return {
            **target,
            "delivery_status": "disabled_no_webhook",
            "status_code": None,
            "response_text": None,
        }

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    try:
        payload = _with_role_mention(payload, role_id)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, json=payload)
            print(f"[Discord] Webhook response: {resp.status_code} {resp.text}")
            resp.raise_for_status()
            return {
                **target,
                "delivery_status": "delivered",
                "status_code": resp.status_code,
                "response_text": (resp.text or "").strip() or None,
            }
    except httpx.HTTPStatusError as exc:
        response_text = (exc.response.text or "").strip()
        message = (
            f"Discord webhook rejected {message_type} message with status "
            f"{exc.response.status_code}"
        )
        if response_text:
            message = f"{message}: {response_text}"
        print(f"[Discord] Webhook error: {message}")
        raise DiscordDeliveryError(
            message=message,
            message_type=message_type,
            status_code=exc.response.status_code,
            response_text=response_text or None,
            route_kind=target.get("route_kind"),
            webhook_source=target.get("webhook_source"),
        ) from exc
    except httpx.HTTPError as exc:
        message = f"Discord webhook request failed for {message_type}: {exc}"
        print(f"[Discord] Webhook error: {message}")
        raise DiscordDeliveryError(
            message=message,
            message_type=message_type,
            route_kind=target.get("route_kind"),
            webhook_source=target.get("webhook_source"),
        ) from exc
    except Exception as e:
        print(f"[Discord] Webhook error: {e}")
        raise


async def alert_for_side(side: dict[str, Any], message_type: str = "alert") -> None:
    payload = build_discord_payload(side)
    await send_discord_webhook(payload, message_type=message_type)


async def _alert_for_side_with_logging(side: dict[str, Any], message_type: str = "alert") -> None:
    try:
        await alert_for_side(side, message_type=message_type)
    except Exception as exc:
        key = make_alert_key(side)
        print(f"[Discord] Background {message_type} delivery failed for {key}: {exc}")


def schedule_alerts(sides: list[dict[str, Any]], message_type: str = "alert") -> int:
    """
    Fire-and-forget scheduling of Discord notifications for qualifying sides.
    Returns the number of notifications that were scheduled (not necessarily delivered).
    """
    global _LAST_SCHEDULE_STATS

    stats = _empty_schedule_stats()
    stats["candidates_seen"] = len(sides)

    for side in sides:
        key = make_alert_key(side)
        if key in ALERTED_KEYS:
            stats["skipped_memory_dedupe"] += 1
            continue
        if not mark_alert_if_new(key, ALERT_DEDUPE_TTL_SECONDS):
            stats["skipped_shared_dedupe"] += 1
            continue
        if not should_alert(side):
            stats["skipped_threshold"] += 1
            continue
        # Mark as alerted immediately to prevent duplicates within the same scan batch.
        ALERTED_KEYS.add(key)
        stats["scheduled"] += 1
        asyncio.create_task(_alert_for_side_with_logging(side, message_type=message_type))

    stats["skipped_total"] = (
        stats["skipped_memory_dedupe"]
        + stats["skipped_shared_dedupe"]
        + stats["skipped_threshold"]
    )
    _LAST_SCHEDULE_STATS = stats
    print(f"[Discord] schedule_alerts stats: {json.dumps(stats, sort_keys=True)}")
    return stats["scheduled"]
