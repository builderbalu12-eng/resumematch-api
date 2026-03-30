import asyncio
import html
from typing import Any, Dict

from app.config import settings
from app.models.job.listed_job import JobRecommendRequest
from app.services.job_recommendation_service import job_recommendation_service
from app.services.mongo import mongo
from app.services.telegram import conversation_state
from app.services.telegram import job_alerts_service
from app.services.telegram.message_builder import message_builder
from app.services.telegram_service import telegram_service

FIND_JOBS_BTN = "🔍 Find Jobs"
DAILY_ALERTS_BTN = "🔔 Daily Alerts"


async def _ensure_linked(chat_id: str):
    return await mongo.users.find_one({"telegram_chat_id": chat_id})


async def handle_menu_or_conversation(chat_id: str, text: str, name: str) -> bool:
    raw = (text or "").strip()
    if not raw:
        return False

    if raw in (FIND_JOBS_BTN, DAILY_ALERTS_BTN):
        user = await _ensure_linked(chat_id)
        if not user:
            await telegram_service.send_message(chat_id, message_builder.not_linked())
            return True
        user_id = str(user["_id"])
        if raw == FIND_JOBS_BTN:
            await _start_find_jobs(chat_id, user_id)
        else:
            await _start_daily_alerts(chat_id, user_id)
        return True

    user = await _ensure_linked(chat_id)
    if not user:
        return False

    user_id = str(user["_id"])
    st = await conversation_state.get_state(chat_id)
    if not st:
        return False

    flow = st.get("flow")
    if flow == "find_jobs":
        await _step_find_jobs(chat_id, user_id, st, raw)
        return True
    if flow == "daily_alerts":
        await _step_daily_alerts(chat_id, user_id, st, raw)
        return True

    return False


async def _start_find_jobs(chat_id: str, user_id: str) -> None:
    await conversation_state.set_state(chat_id, user_id, "find_jobs", "title", {})
    await telegram_service.send_message(
        chat_id,
        "🔍 <b>Find jobs</b>\n\nEnter <b>job title</b> (e.g. Frontend Engineer):",
    )


async def _start_daily_alerts(chat_id: str, user_id: str) -> None:
    await conversation_state.set_state(chat_id, user_id, "daily_alerts", "title", {})
    tz = settings.telegram_alert_default_timezone
    await telegram_service.send_message(
        chat_id,
        "🔔 <b>Daily job alerts</b>\n\n"
        f"Timezone: <code>{html.escape(tz)}</code> (default)\n\n"
        "Enter your preferred <b>job title</b>:",
    )


async def _step_find_jobs(
    chat_id: str, user_id: str, st: Dict[str, Any], text: str
) -> None:
    step = st.get("step")
    draft = dict(st.get("draft") or {})

    if step == "title":
        draft["search_term"] = text
        await conversation_state.set_state(
            chat_id, user_id, "find_jobs", "location", draft
        )
        await telegram_service.send_message(
            chat_id,
            "Enter <b>location</b> (e.g. Bangalore, Remote, Delhi):",
        )
        return

    if step == "location":
        search_term = (draft.get("search_term") or "").strip()
        location = text.strip()
        await conversation_state.clear_state(chat_id)
        await telegram_service.send_message(
            chat_id,
            "⏳ <b>Searching…</b> This can take 1–3 minutes. "
            "Results are ranked using your uploaded resume.",
        )
        asyncio.create_task(
            run_recommend_and_reply(chat_id, user_id, search_term, location)
        )


async def _step_daily_alerts(
    chat_id: str, user_id: str, st: Dict[str, Any], text: str
) -> None:
    step = st.get("step")
    draft = dict(st.get("draft") or {})
    tz_name = settings.telegram_alert_default_timezone

    if step == "title":
        draft["search_term"] = text
        await conversation_state.set_state(
            chat_id, user_id, "daily_alerts", "location", draft
        )
        await telegram_service.send_message(
            chat_id,
            "Enter preferred <b>location</b>:",
        )
        return

    if step == "location":
        draft["location"] = text
        await conversation_state.set_state(
            chat_id, user_id, "daily_alerts", "time", draft
        )
        await telegram_service.send_message(
            chat_id,
            "Enter <b>daily alert time</b> (local), e.g. "
            "<code>9:00</code>, <code>09:30</code>, or <code>6:30 pm</code>:",
        )
        return

    if step == "time":
        parsed = job_alerts_service.parse_time_hm(text)
        if not parsed:
            await telegram_service.send_message(
                chat_id,
                "⚠️ Could not parse time. Try e.g. <code>9:00</code> or <code>6:30 pm</code>.",
            )
            return
        hour, minute = parsed
        search_term = (draft.get("search_term") or "").strip()
        location = (draft.get("location") or "").strip()
        await conversation_state.clear_state(chat_id)
        result = await job_alerts_service.upsert_subscription(
            chat_id=chat_id,
            user_id=user_id,
            search_term=search_term,
            location=location,
            hour=hour,
            minute=minute,
            tz_name=tz_name,
        )
        await telegram_service.send_message(
            chat_id,
            message_builder.daily_alert_confirmed(
                search_term,
                location,
                hour,
                minute,
                tz_name,
                str(result.get("next_run_at", "")),
            ),
        )


async def run_recommend_and_reply(
    chat_id: str,
    user_id: str,
    search_term: str,
    location: str,
    header_prefix: str = "",
) -> None:
    if not search_term or not location:
        await telegram_service.send_message(chat_id, "⚠️ Missing job title or location.")
        return

    try:
        resume_id = await job_recommendation_service.get_resume_id_for_user(user_id)
    except ValueError:
        await telegram_service.send_message(chat_id, message_builder.resume_required())
        return
    except Exception as e:
        await telegram_service.send_message(
            chat_id,
            f"❌ Could not load resume: {html.escape(str(e))}",
        )
        return

    payload = JobRecommendRequest(
        search_term=search_term,
        location=location,
        top_n=settings.telegram_job_search_top_n,
    )
    try:
        result = await job_recommendation_service.recommend_jobs(
            user_id=user_id,
            resume_id=resume_id,
            payload=payload,
        )
    except Exception as e:
        await telegram_service.send_message(
            chat_id,
            f"❌ Job search failed: {html.escape(str(e))}",
        )
        return

    if not result.get("success") or not result.get("jobs"):
        await telegram_service.send_message(
            chat_id,
            "😕 No jobs found. Try different keywords or location.",
        )
        return

    chunks = message_builder.format_job_results_telegram(
        result.get("jobs", []),
        result.get("list_id", ""),
        search_term,
        location,
        header_prefix=header_prefix,
    )
    await telegram_service.send_html_chunks(chat_id, chunks)


async def handle_cancel(chat_id: str) -> None:
    await conversation_state.clear_state(chat_id)
    await telegram_service.send_message(chat_id, "✅ Cancelled.")


async def handle_findjobs_command(chat_id: str, rest: str) -> None:
    user = await _ensure_linked(chat_id)
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return
    user_id = str(user["_id"])
    rest = (rest or "").strip()
    if "|" not in rest:
        await telegram_service.send_message(
            chat_id,
            "Usage: <code>/findjobs Job Title | Location</code>\n"
            "Example: <code>/findjobs React Developer | Bangalore</code>",
        )
        return
    a, b = rest.split("|", 1)
    await telegram_service.send_message(
        chat_id,
        "⏳ <b>Searching…</b> This can take 1–3 minutes.",
    )
    asyncio.create_task(
        run_recommend_and_reply(chat_id, user_id, a.strip(), b.strip())
    )


async def handle_stop_alerts(chat_id: str) -> None:
    user = await _ensure_linked(chat_id)
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return
    n = await job_alerts_service.deactivate_for_user(str(user["_id"]))
    if n:
        await telegram_service.send_message(chat_id, "🔕 Daily alerts turned off.")
    else:
        await telegram_service.send_message(
            chat_id,
            "No active alert subscription found.",
        )


async def handle_my_alerts(chat_id: str) -> None:
    user = await _ensure_linked(chat_id)
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return
    sub = await job_alerts_service.get_active_for_user(str(user["_id"]))
    await telegram_service.send_message(
        chat_id,
        message_builder.my_alert_status(sub),
    )
