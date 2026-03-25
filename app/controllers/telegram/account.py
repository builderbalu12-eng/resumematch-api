# app/controllers/telegram/account.py

from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder
from app.services.credits_service import CreditsService
from app.services.mongo import mongo


async def handle_credits(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    cost_per_lead = await CreditsService.get_feature_cost("find_leads")

    await telegram_service.send_message(
        chat_id,
        message_builder.credits(
            user.get("credits", 0),
            user.get("active_plan", "Free"),
            cost_per_lead=cost_per_lead,
        )
    )


async def handle_status(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return

    await telegram_service.send_message(
        chat_id,
        message_builder.status(
            user.get("email", "N/A"),
            user.get("credits", 0),
            user.get("active_plan", "Free"),
        )
    )
