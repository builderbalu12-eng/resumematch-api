from app.services.telegram_service import telegram_service
from app.services.telegram.message_builder import message_builder
from app.services.mongo import mongo

async def handle_credits(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return
    await telegram_service.send_message(
        chat_id,
        message_builder.credits(user.get("credits", 0), user.get("active_plan", "Free"))
    )

async def handle_status(chat_id: str):
    user = await mongo.users.find_one({"telegram_chat_id": chat_id})
    if not user:
        await telegram_service.send_message(chat_id, message_builder.not_linked())
        return
    await telegram_service.send_message(
        chat_id,
        message_builder.status(user.get("email", "N/A"), user.get("credits", 0), user.get("active_plan", "Free"))
    )
