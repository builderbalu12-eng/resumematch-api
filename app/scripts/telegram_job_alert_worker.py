"""
Poll Mongo for due job-alert subscriptions and send Telegram digests.

Run (same venv / env as the API):
  python -m app.scripts.telegram_job_alert_worker

Requires TELEGRAM_BOT_TOKEN, MONGODB_*, and users with linked Telegram + resume.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from bson import ObjectId

from app.config import settings
from app.controllers.telegram.jobs_flow import run_recommend_and_reply
from app.services.mongo import mongo
from app.services.telegram import job_alerts_service


async def _process_subscription(sub: dict) -> None:
    chat_id = str(sub.get("chat_id") or "")
    user_id = str(sub.get("user_id") or "")
    if not chat_id or not user_id:
        return

    user = await mongo.users.find_one({"_id": ObjectId(user_id)})
    if (
        not user
        or not user.get("telegram_linked")
        or str(user.get("telegram_chat_id") or "") != chat_id
    ):
        await mongo.job_alert_subscriptions.update_one(
            {"user_id": user_id},
            {"$set": {"is_active": False, "updated_at": datetime.now(timezone.utc)}},
        )
        return

    header = "🔔 <b>Daily job alert</b>\n\n"
    await run_recommend_and_reply(
        chat_id=chat_id,
        user_id=user_id,
        search_term=str(sub.get("search_term") or ""),
        location=str(sub.get("location") or ""),
        header_prefix=header,
    )

    await job_alerts_service.mark_dispatched(
        user_id,
        int(sub.get("alert_hour", 0)),
        int(sub.get("alert_minute", 0)),
        str(sub.get("timezone") or settings.telegram_alert_default_timezone),
    )


async def main_loop() -> None:
    await mongo.connect()
    try:
        while True:
            now = datetime.now(timezone.utc)
            subs = await job_alerts_service.fetch_due_subscriptions(
                now, limit=40
            )
            for sub in subs:
                try:
                    await _process_subscription(sub)
                except Exception as e:
                    print(f"[telegram_job_alert_worker] user={sub.get('user_id')}: {e}")
            await asyncio.sleep(max(15, settings.telegram_job_alert_poll_seconds))
    finally:
        await mongo.close()


if __name__ == "__main__":
    asyncio.run(main_loop())
