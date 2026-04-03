import asyncio
import os
from typing import Any
from urllib.parse import urlencode

import httpx
from services.shared_state import mark_alert_if_new
from services.match_keys import alert_key_from_side

ALERTED_KEYS: set[str] = set()
_warned_missing_webhook = False
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


def _resolve_webhook_target(message_type: str = "alert") -> dict[str, str | None]:
    webhook = None
    role = None
    webhook_source = None
    route_kind = None

    if message_type == "alert":
        # Bet alerts route to dedicated alert webhook (beta server)
        if os.getenv("DISCORD_ALERT_WEBHOOK_URL"):
            webhook = os.getenv("DISCORD_ALERT_WEBHOOK_URL")
            role = os.getenv("DISCORD_ALERT_MENTION_ROLE_ID") or os.getenv("DISCORD_MENTION_ROLE_ID")
            webhook_source = "DISCORD_ALERT_WEBHOOK_URL"
            route_kind = "alert_dedicated"
        else:
            webhook = os.getenv("DISCORD_WEBHOOK_URL")
            role = os.getenv("DISCORD_MENTION_ROLE_ID")
            webhook_source = "DISCORD_WEBHOOK_URL" if webhook else None
            route_kind = "alert_primary_fallback" if webhook else "alert_unconfigured"
    elif message_type in ("heartbeat", "test"):
        # Heartbeat and test messages route to debug webhook (current/debug channel)
        if os.getenv("DISCORD_DEBUG_WEBHOOK_URL"):
            webhook = os.getenv("DISCORD_DEBUG_WEBHOOK_URL")
            role = os.getenv("DISCORD_DEBUG_MENTION_ROLE_ID") or os.getenv("DISCORD_MENTION_ROLE_ID")
            webhook_source = "DISCORD_DEBUG_WEBHOOK_URL"
            route_kind = "debug_dedicated"
        else:
            webhook = os.getenv("DISCORD_WEBHOOK_URL")
            role = os.getenv("DISCORD_MENTION_ROLE_ID")
            webhook_source = "DISCORD_WEBHOOK_URL" if webhook else None
            route_kind = "debug_primary_fallback" if webhook else "debug_unconfigured"
    else:
        # Unknown message type; fall back to primary webhook
        webhook = os.getenv("DISCORD_WEBHOOK_URL")
        role = os.getenv("DISCORD_MENTION_ROLE_ID")
        webhook_source = "DISCORD_WEBHOOK_URL" if webhook else None
        route_kind = "primary" if webhook else "primary_unconfigured"

    return {
        "webhook_url": webhook,
        "role_id": role,
        "webhook_source": webhook_source,
        "route_kind": route_kind,
    }


def _get_webhook_and_role(message_type: str = "alert") -> tuple[str | None, str | None]:
    """
    Route to appropriate webhook and role mention based on message type.
    
    Args:
        message_type: "alert" (bet alerts), "heartbeat" (debug/operational), or "test" (webhook validation)
    
    Returns:
        Tuple of (webhook_url, mention_role_id) with fallback to primary webhook if secondary not set.
    """
    target = _resolve_webhook_target(message_type)
    webhook = target["webhook_url"]
    role = target["role_id"]
    return webhook, role


def describe_discord_delivery_target(message_type: str = "alert") -> dict[str, Any]:
    target = _resolve_webhook_target(message_type)
    return {
        "message_type": message_type,
        "route_kind": target["route_kind"],
        "webhook_source": target["webhook_source"],
        "webhook_configured": bool(target["webhook_url"]),
        "role_configured": bool(target["role_id"]),
    }


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


def build_board_deeplink() -> str:
    return FRONTEND_BASE_URL.rstrip("/") + "/"


def build_board_drop_alert_payload(
    *,
    window_label: str,
    anchor_time_mst: str | None,
    result: dict[str, Any] | None,
) -> dict[str, Any]:
    snapshot = result if isinstance(result, dict) else {}
    link = build_board_deeplink()

    props_sides = int(snapshot.get("props_sides") or 0)
    straight_sides = int(snapshot.get("straight_sides") or 0)
    featured_games = int(snapshot.get("featured_games_count") or 0)

    anchor_suffix = f" ({anchor_time_mst} MST)" if anchor_time_mst else ""
    description = f"{window_label}{anchor_suffix} just published."

    return {
        "embeds": [
            {
                "title": "Trusted Beta Board Live",
                "description": description,
                "url": link,
                "fields": [
                    {"name": "Player Props", "value": str(props_sides), "inline": True},
                    {"name": "Game Lines", "value": str(straight_sides), "inline": True},
                    {"name": "Featured Games", "value": str(featured_games), "inline": True},
                    {"name": "Open Board", "value": f"[Open EV Tracker]({link})", "inline": False},
                ],
            }
        ]
    }


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


async def send_discord_webhook(payload: dict[str, Any], message_type: str = "alert") -> dict[str, Any]:
    global _warned_missing_webhook

    target = _resolve_webhook_target(message_type)
    webhook_url = target["webhook_url"]
    role_id = target["role_id"]
    route_kind = target["route_kind"]
    webhook_source = target["webhook_source"]

    if not webhook_url:
        if not _warned_missing_webhook:
            _warned_missing_webhook = True
            print("[Discord] DISCORD_WEBHOOK_URL not set; alerts disabled.")
        print(
            "[Discord] Webhook disabled: "
            f"message_type={message_type} route_kind={route_kind} webhook_source={webhook_source}"
        )
        return {
            "ok": False,
            "message_type": message_type,
            "route_kind": route_kind,
            "webhook_source": webhook_source,
            "delivery_status": "disabled_no_webhook",
            "status_code": None,
            "response_text": None,
        }

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    try:
        payload = _with_role_mention(payload, role_id)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(webhook_url, json=payload)
            response_text = (resp.text or "").strip() or None
            print(
                "[Discord] Webhook response: "
                f"message_type={message_type} route_kind={route_kind} "
                f"webhook_source={webhook_source} status={resp.status_code} "
                f"response_text={response_text}"
            )
            resp.raise_for_status()
            return {
                "ok": True,
                "message_type": message_type,
                "route_kind": route_kind,
                "webhook_source": webhook_source,
                "delivery_status": "delivered",
                "status_code": resp.status_code,
                "response_text": response_text,
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
            route_kind=route_kind,
            webhook_source=webhook_source,
        ) from exc
    except httpx.HTTPError as exc:
        message = f"Discord webhook request failed for {message_type}: {exc}"
        print(f"[Discord] Webhook error: {message}")
        raise DiscordDeliveryError(
            message=message,
            message_type=message_type,
            route_kind=route_kind,
            webhook_source=webhook_source,
        ) from exc
    except Exception as e:
        print(f"[Discord] Webhook error: {e}")
        raise


async def alert_for_side(side: dict[str, Any]) -> None:
    payload = build_discord_payload(side)
    await send_discord_webhook(payload)


async def _alert_for_side_with_logging(side: dict[str, Any]) -> None:
    try:
        await alert_for_side(side)
    except Exception as exc:
        key = make_alert_key(side)
        print(f"[Discord] Background alert delivery failed for {key}: {exc}")


def schedule_alerts(sides: list[dict[str, Any]]) -> int:
    """
    Fire-and-forget scheduling of Discord alerts for qualifying sides.
    Returns the number of alerts that were scheduled (not necessarily delivered).
    """
    scheduled = 0
    for side in sides:
        key = make_alert_key(side)
        if key in ALERTED_KEYS:
            continue
        if not mark_alert_if_new(key, ALERT_DEDUPE_TTL_SECONDS):
            continue
        if not should_alert(side):
            continue
        # Mark as alerted immediately to prevent duplicates within the same scan batch.
        ALERTED_KEYS.add(key)
        scheduled += 1
        asyncio.create_task(_alert_for_side_with_logging(side))
    return scheduled

