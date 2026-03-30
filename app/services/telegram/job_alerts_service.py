import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from zoneinfo import ZoneInfo

from app.services.mongo import mongo


def compute_next_run_utc(hour: int, minute: int, tz_name: str) -> datetime:
    tz = ZoneInfo(tz_name)
    now_local = datetime.now(tz)
    candidate = now_local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if candidate <= now_local:
        candidate += timedelta(days=1)
    return candidate.astimezone(timezone.utc)


def parse_time_hm(text: str) -> Optional[Tuple[int, int]]:
    t = text.strip().lower().replace(".", "")

    m = re.match(r"^(\d{1,2}):(\d{2})\s*(am|pm)$", t)
    if m:
        h, minute, ap = int(m.group(1)), int(m.group(2)), m.group(3)
        if not (0 <= minute <= 59) or not (1 <= h <= 12):
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return h, minute

    m2 = re.match(r"^(\d{1,2})\s*(am|pm)$", t)
    if m2:
        h, ap = int(m2.group(1)), m2.group(2)
        if not (1 <= h <= 12):
            return None
        if ap == "pm" and h != 12:
            h += 12
        if ap == "am" and h == 12:
            h = 0
        return h, 0

    m3 = re.match(r"^(\d{1,2}):(\d{2})$", text.strip())
    if m3:
        h, minute = int(m3.group(1)), int(m3.group(2))
        if 0 <= h <= 23 and 0 <= minute <= 59:
            return h, minute

    return None


async def upsert_subscription(
    chat_id: str,
    user_id: str,
    search_term: str,
    location: str,
    hour: int,
    minute: int,
    tz_name: str,
) -> Dict[str, Any]:
    next_run = compute_next_run_utc(hour, minute, tz_name)
    now = datetime.now(timezone.utc)
    doc = {
        "chat_id":       chat_id,
        "user_id":       user_id,
        "search_term":   search_term,
        "location":      location,
        "alert_hour":    hour,
        "alert_minute":  minute,
        "timezone":      tz_name,
        "is_active":     True,
        "next_run_at":   next_run,
        "updated_at":    now,
    }
    await mongo.job_alert_subscriptions.update_one(
        {"user_id": user_id},
        {"$set": doc, "$setOnInsert": {"created_at": now, "last_sent_at": None}},
        upsert=True,
    )
    return {"next_run_at": next_run.isoformat(), "timezone": tz_name}


async def deactivate_for_user(user_id: str) -> int:
    r = await mongo.job_alert_subscriptions.update_many(
        {"user_id": user_id},
        {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
    )
    return r.modified_count


async def get_active_for_user(user_id: str) -> Optional[Dict[str, Any]]:
    return await mongo.job_alert_subscriptions.find_one(
        {"user_id": user_id, "is_active": True}
    )


async def mark_dispatched(
    user_id: str,
    hour: int,
    minute: int,
    tz_name: str,
) -> None:
    next_run = compute_next_run_utc(hour, minute, tz_name)
    now = datetime.now(timezone.utc)
    await mongo.job_alert_subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "last_sent_at": now,
                "next_run_at":  next_run,
                "updated_at":   now,
            }
        },
    )


async def fetch_due_subscriptions(now_utc: datetime, limit: int = 25) -> List[Dict[str, Any]]:
    cursor = (
        mongo.job_alert_subscriptions.find(
            {"is_active": True, "next_run_at": {"$lte": now_utc}}
        )
        .sort("next_run_at", 1)
        .limit(limit)
    )
    return await cursor.to_list(length=limit)
