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

def _with_role_mention(payload: dict[str, Any]) -> dict[str, Any]:
    """
    If DISCORD_MENTION_ROLE_ID is set, prepend a role mention to the message content.
    This will only notify users if the role is mentionable and the channel allows role mentions.
    """
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
    kelly = side.get("base_kelly_fraction", None)

    kelly_text = "—"
    try:
        if kelly is not None:
            kelly_text = f"{float(kelly) * 100:.2f}% bankroll"
    except Exception:
        kelly_text = "—"

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
                    {"name": "Kelly", "value": kelly_text, "inline": True},
                    {"name": "Link", "value": f"[Open scanner]({link})", "inline": False},
                ],
            }
        ]
    }


async def send_discord_webhook(payload: dict[str, Any]) -> None:
    global _warned_missing_webhook
    url = os.getenv("DISCORD_WEBHOOK_URL")
    if not url:
        if not _warned_missing_webhook:
            _warned_missing_webhook = True
            print("[Discord] DISCORD_WEBHOOK_URL not set; alerts disabled.")
        return

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=10.0, pool=5.0)
    try:
        payload = _with_role_mention(payload)
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, json=payload)
            print(f"[Discord] Webhook response: {resp.status_code} {resp.text}")
            resp.raise_for_status()
    except Exception as e:
        # Never crash caller; Discord being down should not affect scans.
        print(f"[Discord] Webhook error: {e}")
        raise


async def alert_for_side(side: dict[str, Any]) -> None:
    key = make_alert_key(side)
    if key in ALERTED_KEYS:
        return
    if not mark_alert_if_new(key, ALERT_DEDUPE_TTL_SECONDS):
        return
    if not should_alert(side):
        return
    ALERTED_KEYS.add(key)
    payload = build_discord_payload(side)
    await send_discord_webhook(payload)


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
        asyncio.create_task(alert_for_side(side))
    return scheduled

